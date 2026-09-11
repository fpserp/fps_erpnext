"""Point the six job-event emitters at Job Order.fps_updates, not a separate tracker.

Job Tracker is no longer where a job's update log lives -- Job Order carries
its own fps_updates table now (add_job_order_updates_table). Every script that
used to find-or-create a Job Tracker, append a row, and save it is rewritten to
insert the row directly onto the Job Order instead.

WHAT DID NOT CHANGE: the event-detection logic in each script -- what counts as
a BOE filed, a MOFA completion, a delivery, an invoice -- is untouched, byte
for byte. Only the nested emit() helper's INTERNALS changed, from
"get/create tracker, append, save" to a single standalone child insert. That
insert fires FPS Job Update's own after_insert hook (see hooks.py), which reruns
fps_erpnext.api.jobs.rollup() for the job -- proved live, before this was
written, that a standalone child insert fires its own doc_events independently
of any parent save.

WHY NOT A JOB ORDER SAVE. Job Order already has a Before Save script,
"JO SOW Classify", that explicitly reverts fps_stage to its previous value
whenever it changes to anything but "Closed". Routing these six emitters
through a Job Order save would put that guard in the way of the very field the
derivation needs to set. See fps_erpnext/api/jobs.py for the full reasoning.

HOW THESE BODIES WERE PRODUCED. Not by hand. Each is the script that was live
on the site (pulled fresh this session, after the 2026-09-10 closure fix),
transformed by a script that asserts the exact block it expects is present
before replacing it, then ast.parse-verified. This generated patch module is
imported back and every embedded string compared byte for byte against its
source file -- a quoting slip cannot ship through this path.

A script that is missing, or whose body already matches, is skipped rather
than overwritten.

Safe to re-run.
"""

import frappe

SCRIPTS = {
	'CT BOE to Job Order': """\
# CT BOE to Job Order (extended) - Customs Tracker After Save. Keeps the BOE copy, derives clearance type,
# stamps clearance_date, copies location/type up to the Job Order, and logs each fact as a Job Tracker event
# (deduplicated by evidence reference) so the tracker rollup runs.
try:
    jo = doc.job_order
    prev = doc.get_doc_before_save()
    if jo:
        if doc.boe_number:
            current = frappe.db.get_value("Job Order", jo, "boe_no")
            if current != doc.boe_number and not (current and doc.boe_number in current):
                frappe.db.set_value("Job Order", jo, "boe_no", doc.boe_number if not current else (current + " / " + doc.boe_number), update_modified=False)
        b = (doc.boe_number or "").strip()
        ctype = doc.fps_clearance_type
        if b and not ctype:
            if b.startswith("1010"):
                ctype = "Import to Local from ROW"
            elif b.startswith("1020"):
                ctype = "Import to Local from FZ"
            elif b.startswith("5020"):
                ctype = "Transfer within FZ"
            elif b.startswith("3060"):
                ctype = "FZ Transit"
            elif len(b) == 12 and b.startswith("20"):
                ctype = "Import to Local from ROW"
            elif doc.declaration_type == "Export":
                ctype = "Export"
            if ctype:
                frappe.db.set_value("Customs Tracker", doc.name, "fps_clearance_type", ctype, update_modified=False)
        if doc.status == "Cleared" and not doc.clearance_date:
            frappe.db.set_value("Customs Tracker", doc.name, "clearance_date", frappe.utils.today(), update_modified=False)
        jod = frappe.db.get_value("Job Order", jo, ["fps_svc_clearance", "fps_clearance_location", "fps_clearance_type"], as_dict=True) or {}
        vals = {}
        if not jod.get("fps_svc_clearance"):
            vals["fps_svc_clearance"] = 1
        if not jod.get("fps_clearance_location") and doc.fps_clearance_location:
            vals["fps_clearance_location"] = doc.fps_clearance_location
        if not jod.get("fps_clearance_type") and ctype and ctype not in ("Transfer within FZ", "FZ Transit"):
            vals["fps_clearance_type"] = ctype
        if vals:
            frappe.db.set_value("Job Order", jo, vals, update_modified=False)

        def emit(code, ref, text, visible=1, etype="System", jo=jo, doc=doc):
            # ONE tracker per job is gone -- the update log is a child table on
            # the Job Order itself now. Standalone insert (not append+parent
            # save) fires FPS Job Update's own after_insert hook, which reruns
            # fps_erpnext.api.jobs.rollup(jo) for us. See that module for why
            # this is NOT a Job Order save: JO SOW Classify reverts fps_stage
            # changes it did not expect, so the write has to stay a raw insert
            # here and a raw db.set_value inside rollup(), never a doc.save()
            # on Job Order.
            if frappe.db.exists("FPS Job Update", {"parenttype": "Job Order", "parent": jo, "evidence_ref": ref}):
                return
            n = frappe.db.count("FPS Job Update", {"parenttype": "Job Order", "parent": jo})
            frappe.get_doc({
                "doctype": "FPS Job Update", "parenttype": "Job Order", "parent": jo,
                "parentfield": "fps_updates", "idx": n + 1,
                "update_date": frappe.utils.today(), "event_type": etype, "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": doc.fps_leg or 1,
                "responsible": frappe.session.user,
            }).insert(ignore_permissions=True)
        is_fz = ctype in ("Transfer within FZ", "FZ Transit")
        is_om = (doc.fps_clearance_location or "") in ("Port Sultan Qaboos (Oman)", "Sohar Port (Oman)") and not is_fz
        loc = doc.fps_clearance_location or ""
        if prev is None:
            emit(None, "CT:%s:new" % doc.name, "Customs entry opened%s" % ((" at " + loc) if loc else ""))
        if b and (prev is None or (prev.boe_number or "").strip() != b):
            emit("FZ_BOE" if is_fz else ("OMAN_BOE" if is_om else "BOE"), "CT:%s:boe:%s" % (doc.name, b), "BOE %s filed (%s)" % (b, ctype or doc.declaration_type or ""))
        if doc.fps_mofa_status == "Completed" and (prev is None or prev.fps_mofa_status != "Completed"):
            emit("MOFA", "CT:%s:mofa" % doc.name, "MOFA attestation completed")
        if doc.fps_do_status == "Collected" and (prev is None or prev.fps_do_status != "Collected"):
            emit("DO", "CT:%s:do" % doc.name, "Delivery order collected")
        if doc.fps_duty_paid_on and (prev is None or not prev.fps_duty_paid_on):
            emit("DUTY", "CT:%s:duty" % doc.name, "Duty / deposit paid on %s" % doc.fps_duty_paid_on)
        if doc.status == "Cleared" and (prev is None or prev.status != "Cleared"):
            emit("FZ_CLEARED" if is_fz else ("OMAN_CLEARED" if is_om else "CLEARED"), "CT:%s:Cleared" % doc.name, "Customs released%s%s" % ((" - BOE " + b) if b else "", (" at " + loc) if loc else ""))
        if doc.status in ("On Hold", "Delayed") and (prev is None or prev.status != doc.status):
            emit("HOLD", "CT:%s:hold:%s" % (doc.name, doc.status), "Customs %s: %s" % (doc.status, (doc.remarks or "")[:120]), 0, "Issue")
        if prev is not None and prev.status in ("On Hold", "Delayed") and doc.status in ("In Process", "Cleared", "Pending"):
            emit("RESUME", "CT:%s:resume:%s" % (doc.name, doc.status), "Customs hold lifted, now %s" % doc.status, 0)
        if doc.fps_deposit_claim == "Refunded" and (prev is None or prev.fps_deposit_claim != "Refunded"):
            emit(None, "CT:%s:refund" % doc.name, "Customs deposit refunded", 0)
except Exception:
    frappe.log_error(title="CT BOE to Job Order")
""",
	'POD Events (Save)': """\
# POD Events - Proof of Delivery After Save (draft) / After Submit / After Cancel share this body; the event decides what is logged.
try:
    jo = doc.job_order
    prev = doc.get_doc_before_save()
    if jo:
        def emit(code, ref, text, visible=1, etype="System", jo=jo, doc=doc):
            # ONE tracker per job is gone -- the update log is a child table on
            # the Job Order itself now. Standalone insert (not append+parent
            # save) fires FPS Job Update's own after_insert hook, which reruns
            # fps_erpnext.api.jobs.rollup(jo) for us. See that module for why
            # this is NOT a Job Order save: JO SOW Classify reverts fps_stage
            # changes it did not expect, so the write has to stay a raw insert
            # here and a raw db.set_value inside rollup(), never a doc.save()
            # on Job Order.
            if frappe.db.exists("FPS Job Update", {"parenttype": "Job Order", "parent": jo, "evidence_ref": ref}):
                return
            n = frappe.db.count("FPS Job Update", {"parenttype": "Job Order", "parent": jo})
            frappe.get_doc({
                "doctype": "FPS Job Update", "parenttype": "Job Order", "parent": jo,
                "parentfield": "fps_updates", "idx": n + 1,
                "update_date": doc.pod_date or frappe.utils.today(), "event_type": etype, "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": doc.fps_leg or 1,
                "responsible": frappe.session.user,
            }).insert(ignore_permissions=True)
        leg = doc.fps_leg or 1
        if doc.docstatus == 2:
            emit(None, "POD:%s:cancel" % doc.name, "Delivery record %s cancelled" % doc.name, 0)
        elif doc.docstatus == 1:
            if doc.delivery_status == "Delivered":
                if doc.fps_final_delivery in (1, None):
                    emit("DELIVERED", "POD:%s:submit" % doc.name, "Delivered%s%s" % ((" to " + doc.delivery_location) if doc.delivery_location else "", (", received by " + doc.received_by) if doc.received_by else ""))
                else:
                    emit(None, "POD:%s:submit" % doc.name, "Delivery leg %s completed%s" % (leg, (" - " + doc.delivery_location) if doc.delivery_location else ""))
            elif doc.delivery_status in ("Failed", "Returned"):
                emit("HOLD", "POD:%s:%s" % (doc.name, doc.delivery_status), "Delivery %s: %s" % (doc.delivery_status, (doc.remarks or "")[:120]), 0, "Issue")
        else:
            if doc.vehicle_no and (prev is None or not prev.vehicle_no):
                jod = frappe.db.get_value("Job Order", jo, ["fps_svc_transport", "fps_svc_crossborder"], as_dict=True) or {}
                if not jod.get("fps_svc_transport") and not jod.get("fps_svc_crossborder"):
                    frappe.db.set_value("Job Order", jo, "fps_svc_transport", 1, update_modified=False)
                emit("VEHICLE", "POD:%s:vehicle" % doc.name, "Vehicle %s assigned%s" % (doc.vehicle_no, (" (" + doc.fps_vehicle_type + ")") if doc.fps_vehicle_type else ""))
            if doc.fps_pickup_datetime and (prev is None or not prev.fps_pickup_datetime):
                emit("PICKED_UP", "POD:%s:pickup" % doc.name, "Picked up / loaded at %s" % doc.fps_pickup_datetime)
except Exception:
    frappe.log_error(title="POD Events")
""",
	'POD Events (Submit)': """\
# POD Events - Proof of Delivery After Save (draft) / After Submit / After Cancel share this body; the event decides what is logged.
try:
    jo = doc.job_order
    prev = doc.get_doc_before_save()
    if jo:
        def emit(code, ref, text, visible=1, etype="System", jo=jo, doc=doc):
            # ONE tracker per job is gone -- the update log is a child table on
            # the Job Order itself now. Standalone insert (not append+parent
            # save) fires FPS Job Update's own after_insert hook, which reruns
            # fps_erpnext.api.jobs.rollup(jo) for us. See that module for why
            # this is NOT a Job Order save: JO SOW Classify reverts fps_stage
            # changes it did not expect, so the write has to stay a raw insert
            # here and a raw db.set_value inside rollup(), never a doc.save()
            # on Job Order.
            if frappe.db.exists("FPS Job Update", {"parenttype": "Job Order", "parent": jo, "evidence_ref": ref}):
                return
            n = frappe.db.count("FPS Job Update", {"parenttype": "Job Order", "parent": jo})
            frappe.get_doc({
                "doctype": "FPS Job Update", "parenttype": "Job Order", "parent": jo,
                "parentfield": "fps_updates", "idx": n + 1,
                "update_date": doc.pod_date or frappe.utils.today(), "event_type": etype, "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": doc.fps_leg or 1,
                "responsible": frappe.session.user,
            }).insert(ignore_permissions=True)
        leg = doc.fps_leg or 1
        if doc.docstatus == 2:
            emit(None, "POD:%s:cancel" % doc.name, "Delivery record %s cancelled" % doc.name, 0)
        elif doc.docstatus == 1:
            if doc.delivery_status == "Delivered":
                if doc.fps_final_delivery in (1, None):
                    emit("DELIVERED", "POD:%s:submit" % doc.name, "Delivered%s%s" % ((" to " + doc.delivery_location) if doc.delivery_location else "", (", received by " + doc.received_by) if doc.received_by else ""))
                else:
                    emit(None, "POD:%s:submit" % doc.name, "Delivery leg %s completed%s" % (leg, (" - " + doc.delivery_location) if doc.delivery_location else ""))
            elif doc.delivery_status in ("Failed", "Returned"):
                emit("HOLD", "POD:%s:%s" % (doc.name, doc.delivery_status), "Delivery %s: %s" % (doc.delivery_status, (doc.remarks or "")[:120]), 0, "Issue")
        else:
            if doc.vehicle_no and (prev is None or not prev.vehicle_no):
                jod = frappe.db.get_value("Job Order", jo, ["fps_svc_transport", "fps_svc_crossborder"], as_dict=True) or {}
                if not jod.get("fps_svc_transport") and not jod.get("fps_svc_crossborder"):
                    frappe.db.set_value("Job Order", jo, "fps_svc_transport", 1, update_modified=False)
                emit("VEHICLE", "POD:%s:vehicle" % doc.name, "Vehicle %s assigned%s" % (doc.vehicle_no, (" (" + doc.fps_vehicle_type + ")") if doc.fps_vehicle_type else ""))
            if doc.fps_pickup_datetime and (prev is None or not prev.fps_pickup_datetime):
                emit("PICKED_UP", "POD:%s:pickup" % doc.name, "Picked up / loaded at %s" % doc.fps_pickup_datetime)
except Exception:
    frappe.log_error(title="POD Events")
""",
	'POD Events (Cancel)': """\
# POD Events - Proof of Delivery After Save (draft) / After Submit / After Cancel share this body; the event decides what is logged.
try:
    jo = doc.job_order
    prev = doc.get_doc_before_save()
    if jo:
        def emit(code, ref, text, visible=1, etype="System", jo=jo, doc=doc):
            # ONE tracker per job is gone -- the update log is a child table on
            # the Job Order itself now. Standalone insert (not append+parent
            # save) fires FPS Job Update's own after_insert hook, which reruns
            # fps_erpnext.api.jobs.rollup(jo) for us. See that module for why
            # this is NOT a Job Order save: JO SOW Classify reverts fps_stage
            # changes it did not expect, so the write has to stay a raw insert
            # here and a raw db.set_value inside rollup(), never a doc.save()
            # on Job Order.
            if frappe.db.exists("FPS Job Update", {"parenttype": "Job Order", "parent": jo, "evidence_ref": ref}):
                return
            n = frappe.db.count("FPS Job Update", {"parenttype": "Job Order", "parent": jo})
            frappe.get_doc({
                "doctype": "FPS Job Update", "parenttype": "Job Order", "parent": jo,
                "parentfield": "fps_updates", "idx": n + 1,
                "update_date": doc.pod_date or frappe.utils.today(), "event_type": etype, "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": doc.fps_leg or 1,
                "responsible": frappe.session.user,
            }).insert(ignore_permissions=True)
        leg = doc.fps_leg or 1
        if doc.docstatus == 2:
            emit(None, "POD:%s:cancel" % doc.name, "Delivery record %s cancelled" % doc.name, 0)
        elif doc.docstatus == 1:
            if doc.delivery_status == "Delivered":
                if doc.fps_final_delivery in (1, None):
                    emit("DELIVERED", "POD:%s:submit" % doc.name, "Delivered%s%s" % ((" to " + doc.delivery_location) if doc.delivery_location else "", (", received by " + doc.received_by) if doc.received_by else ""))
                else:
                    emit(None, "POD:%s:submit" % doc.name, "Delivery leg %s completed%s" % (leg, (" - " + doc.delivery_location) if doc.delivery_location else ""))
            elif doc.delivery_status in ("Failed", "Returned"):
                emit("HOLD", "POD:%s:%s" % (doc.name, doc.delivery_status), "Delivery %s: %s" % (doc.delivery_status, (doc.remarks or "")[:120]), 0, "Issue")
        else:
            if doc.vehicle_no and (prev is None or not prev.vehicle_no):
                jod = frappe.db.get_value("Job Order", jo, ["fps_svc_transport", "fps_svc_crossborder"], as_dict=True) or {}
                if not jod.get("fps_svc_transport") and not jod.get("fps_svc_crossborder"):
                    frappe.db.set_value("Job Order", jo, "fps_svc_transport", 1, update_modified=False)
                emit("VEHICLE", "POD:%s:vehicle" % doc.name, "Vehicle %s assigned%s" % (doc.vehicle_no, (" (" + doc.fps_vehicle_type + ")") if doc.fps_vehicle_type else ""))
            if doc.fps_pickup_datetime and (prev is None or not prev.fps_pickup_datetime):
                emit("PICKED_UP", "POD:%s:pickup" % doc.name, "Picked up / loaded at %s" % doc.fps_pickup_datetime)
except Exception:
    frappe.log_error(title="POD Events")
""",
	'SI Events (Submit)': """\
# SI Events - Sales Invoice After Submit / After Cancel (same body). No amounts are ever written to the tracker.
try:
    jo = doc.fps_job_order
    if jo:
        def emit(code, ref, text, visible=0, jo=jo, doc=doc):
            # See CT BOE to Job Order for why this is a standalone insert, not a
            # Job Order save.
            if frappe.db.exists("FPS Job Update", {"parenttype": "Job Order", "parent": jo, "evidence_ref": ref}):
                return
            n = frappe.db.count("FPS Job Update", {"parenttype": "Job Order", "parent": jo})
            frappe.get_doc({
                "doctype": "FPS Job Update", "parenttype": "Job Order", "parent": jo,
                "parentfield": "fps_updates", "idx": n + 1,
                "update_date": doc.posting_date or frappe.utils.today(), "event_type": "System", "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": 1,
                "responsible": frappe.session.user,
            }).insert(ignore_permissions=True)
        if doc.docstatus == 2:
            emit(None, "SI:%s:cancel" % doc.name, "Invoice %s cancelled" % doc.name)
        elif doc.fps_is_payment_request:
            emit(None, "SI:%s:pr" % doc.name, "Payment request %s raised" % doc.name)
        else:
            emit("INVOICED", "SI:%s:submit" % doc.name, "Invoice %s issued" % doc.name)
except Exception:
    frappe.log_error(title="SI Events")
""",
	'SI Events (Cancel)': """\
# SI Events - Sales Invoice After Submit / After Cancel (same body). No amounts are ever written to the tracker.
try:
    jo = doc.fps_job_order
    if jo:
        def emit(code, ref, text, visible=0, jo=jo, doc=doc):
            # See CT BOE to Job Order for why this is a standalone insert, not a
            # Job Order save.
            if frappe.db.exists("FPS Job Update", {"parenttype": "Job Order", "parent": jo, "evidence_ref": ref}):
                return
            n = frappe.db.count("FPS Job Update", {"parenttype": "Job Order", "parent": jo})
            frappe.get_doc({
                "doctype": "FPS Job Update", "parenttype": "Job Order", "parent": jo,
                "parentfield": "fps_updates", "idx": n + 1,
                "update_date": doc.posting_date or frappe.utils.today(), "event_type": "System", "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": 1,
                "responsible": frappe.session.user,
            }).insert(ignore_permissions=True)
        if doc.docstatus == 2:
            emit(None, "SI:%s:cancel" % doc.name, "Invoice %s cancelled" % doc.name)
        elif doc.fps_is_payment_request:
            emit(None, "SI:%s:pr" % doc.name, "Payment request %s raised" % doc.name)
        else:
            emit("INVOICED", "SI:%s:submit" % doc.name, "Invoice %s issued" % doc.name)
except Exception:
    frappe.log_error(title="SI Events")
""",
	'JO Emit Opened': """\
# JO Emit Opened - Job Order After Insert: appends the OPENED entry directly
# onto this job's own update log (fps_updates). No separate tracker document --
# see fps_erpnext/api/jobs.py for the derivation this feeds.
try:
    ref = "JO:%s:opened" % doc.name
    if not frappe.db.exists("FPS Job Update", {"parenttype": "Job Order", "parent": doc.name, "evidence_ref": ref}):
        text = "Job opened - %s" % (doc.fps_category or "")
        frappe.get_doc({
            "doctype": "FPS Job Update", "parenttype": "Job Order", "parent": doc.name,
            "parentfield": "fps_updates", "idx": 1,
            "update_date": doc.jo_date or frappe.utils.today(), "event_type": "System",
            "milestone": "OPENED", "status_line": "Job opened", "notes": text,
            "evidence_ref": ref, "source": "System", "customer_visible": 1, "leg": 1,
            "responsible": frappe.session.user,
        }).insert(ignore_permissions=True)
except Exception:
    frappe.log_error(title="JO Emit Opened")
""",
}


def execute():
	changed = 0
	for name, script in SCRIPTS.items():
		if not frappe.db.exists("Server Script", name):
			frappe.log_error(title="FPS: Server Script %s missing, not retargeted" % name)
			continue
		current = frappe.db.get_value("Server Script", name, "script") or ""
		if current == script:
			continue
		frappe.db.set_value("Server Script", name, "script", script, update_modified=False)
		changed += 1

	if changed:
		frappe.db.commit()
	frappe.clear_cache()
	frappe.logger().info("FPS: retargeted %d job-emitter scripts onto Job Order.fps_updates" % changed)

