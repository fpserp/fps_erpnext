"""Repoint the tracker scripts at a lookup that does not care what a tracker is NAMED.

The prefixes came back. On 2026-09-10 the trackers were renamed to their job
order outright (FPS/JO/2607/018) and the scripts were given a fast path that
asked for that exact name. Seeing it live, the prefix was wanted back --
FPS/JT/2607/018 and FPS/CT/2607/018 -- because with three doctypes sharing one
string a bare "2607/018" no longer said which record was meant.

Rather than teach nine scripts to rebuild "FPS/JT/" + the job order tail, every
one of them now looks the tracker up BY job_order, which is true whatever the
naming convention is this month:

    frappe.db.get_value("Job Tracker", {"job_order": jo}, "name", order_by="creation asc")

order_by is the race guard, not decoration. If two events ever open a tracker at
the same instant the second is named "<name>-2", and every later call has to
converge on the same one or the job history splits across two records. Oldest
wins, deterministically.

All eleven bodies are otherwise identical to the ones retarget_tracker_scripts
installed. They are produced the same way: the live pre-migration script,
transformed by a script, parsed (ast.parse for Python, `node --check` for
JavaScript), then round-tripped through this generated module and compared byte
for byte. Nothing here was retyped by hand.

A script that is missing, or whose body is already correct, is skipped rather
than overwritten.

Safe to re-run.
"""

import frappe


SERVER_SCRIPTS = {
	'JO Emit Opened': """\
# JO Emit Opened - Job Order After Insert: creates THE tracker for the job and its first update.
# One Job Tracker per Job Order. Before this, every event was its own tracker document.
try:
    ref = "JO:%s:opened" % doc.name
    tr = frappe.db.get_value("Job Tracker", {"job_order": doc.name}, "name", order_by="creation asc")
    if not tr:
        tr = frappe.get_doc({
            "doctype": "Job Tracker", "job_order": doc.name, "customer": doc.customer,
            "track_date": doc.jo_date or frappe.utils.today(),
        }).insert(ignore_permissions=True).name
    t = frappe.get_doc("Job Tracker", tr)
    if not [u for u in t.fps_updates if (u.evidence_ref or "") == ref]:
        text = "Job opened - %s" % (doc.fps_category or "")
        t.append("fps_updates", {
            "update_date": doc.jo_date or frappe.utils.today(), "event_type": "System",
            "milestone": "OPENED", "status_line": "Job opened", "notes": text,
            "evidence_ref": ref, "source": "System", "customer_visible": 1, "leg": 1,
            "responsible": frappe.session.user,
        })
        t.track_date = doc.jo_date or frappe.utils.today()
        t.fps_event_type = "System"
        t.fps_milestone = "OPENED"
        t.current_status = "Job opened"
        t.fps_evidence_ref = ref
        t.fps_source = "System"
        t.fps_customer_visible = 1
        t.save(ignore_permissions=True)
except Exception:
    frappe.log_error(title="JO Emit Opened")
""",
	'JT Rollup': """\
# FPS Hybrid Job Tracker - derivation engine (safe_exec Server Script body).
# rollup(jo_name): rebuilds the per-job milestone checklist, stage, progress, next action and SOW label
# from the documents on the job (Customs Trackers, PODs, Sales Invoices) and the Job Tracker event log.
# Writes only with frappe.db.set_value on the Job Order - never doc.save(), so it can never recurse or block a save.

def rollup(jo_name):
    def todate(v):
        return frappe.utils.getdate(v) if v else None
    def dstr(v):
        return str(v)[:10] if v else ""
    jo = frappe.db.get_value("Job Order", jo_name, ["name", "jo_date", "docstatus", "movement_type", "direction", "awb_bl_no", "carrier", "vessel_flight", "etd", "eta", "boe_no", "pol", "pod", "fps_svc_freight", "fps_svc_clearance", "fps_svc_transport", "fps_svc_crossborder", "fps_svc_general", "fps_category", "fps_route_pattern", "fps_stage", "fps_stage_since", "fps_clearance_location", "fps_vehicle_type", "fps_general_job_type", "fps_owner"], as_dict=True)
    if not jo or jo.docstatus == 2:
        return
    today = frappe.utils.getdate(frappe.utils.today())
    cts = frappe.get_all("Customs Tracker", filters={"job_order": jo_name}, fields=["name", "status", "boe_number", "fps_leg", "fps_clearance_type", "fps_clearance_location", "fps_mofa_status", "fps_do_status", "fps_duty_paid_on", "clearance_date", "ct_date", "modified", "remarks"], order_by="ct_date asc, creation asc")
    pods = frappe.get_all("Proof of Delivery", filters={"job_order": jo_name, "docstatus": ["<", 2]}, fields=["name", "docstatus", "delivery_status", "pod_date", "vehicle_no", "fps_pickup_datetime", "fps_final_delivery", "received_by", "delivery_location", "creation"], order_by="creation asc")
    sis = frappe.get_all("Sales Invoice", filters={"fps_job_order": jo_name, "docstatus": 1, "fps_is_payment_request": 0}, fields=["name", "posting_date"], order_by="posting_date asc")
    # ONE tracker per job now; its updates are child rows, not sibling documents.
    # Read through the parent document rather than querying the child table, so
    # no child-table query rule can change under us between Frappe versions.
    #
    # Sorted explicitly rather than trusting grid order: a back-dated update
    # appends at the END of the grid, and everything below assumes evs[-1] is
    # the newest. sorted() and lambda were both PROVED to work in this site's
    # safe_exec sandbox before this was written -- no script here had ever
    # used either, so it was not safe to assume they were available.
    tr_name = frappe.db.get_value("Job Tracker", {"job_order": jo_name}, "name", order_by="creation asc")
    evs = frappe.get_doc("Job Tracker", tr_name).fps_updates if tr_name else []
    evs = sorted(evs, key=lambda x: (str(x.update_date or "9999-12-31"), x.idx))

    FZ = ("Transfer within FZ", "FZ Transit")
    OM = ("Port Sultan Qaboos (Oman)", "Sohar Port (Oman)")
    fz_names = [c.name for c in cts if (c.fps_clearance_type or "") in FZ]
    om_names = [c.name for c in cts if (c.fps_clearance_location or "") in OM and c.name not in fz_names]
    fz_cts = [c for c in cts if c.name in fz_names]
    om_cts = [c for c in cts if c.name in om_names]
    fin_cts = [c for c in cts if c.name not in fz_names and c.name not in om_names] or om_cts

    ev_done = {}
    hold = None
    for e in evs:
        code = e.milestone
        if code == "HOLD":
            hold = e
        elif code == "RESUME":
            hold = None
        elif code and code not in ev_done:
            ev_done[code] = e.update_date

    F = jo.fps_svc_freight
    C = jo.fps_svc_clearance
    T = jo.fps_svc_transport
    X = jo.fps_svc_crossborder
    G = jo.fps_svc_general
    upd = {}
    if cts and not C:
        C = 1
        upd["fps_svc_clearance"] = 1
    if [p for p in pods if p.vehicle_no] and not T and not X:
        T = 1
        upd["fps_svc_transport"] = 1
    has_fz = len(fz_cts) > 0
    has_om = len(om_cts) > 0
    route = jo.fps_route_pattern or "Direct"
    if has_fz and route == "Direct":
        route = "FZ transfer then import"
        upd["fps_route_pattern"] = route
    if has_om and route == "Direct":
        route = "Oman corridor"
        upd["fps_route_pattern"] = route

    ms = [("OPENED", "Job opened")]
    if F:
        ms += [("BOOKED", "Booking confirmed"), ("DOCS", "Shipping docs checked"), ("DEPARTED", "Departed origin"), ("ARRIVED", "Arrived at destination")]
    elif C or (jo.movement_type in ("SEA", "AIR")):
        ms += [("DOCS", "Shipping docs checked"), ("ARRIVED", "Cargo arrived")]
    if C:
        if has_fz:
            ms += [("FZ_BOE", "FZ transfer BOE filed"), ("FZ_CLEARED", "FZ transfer approved")]
        if has_om:
            ms += [("OMAN_BOE", "Oman declaration filed"), ("OMAN_CLEARED", "Cleared at Oman port"), ("TRUCKS_DEPARTED", "Trucks departed Oman"), ("BORDER", "Border crossed")]
        ms += [("MOFA", "MOFA attestation"), ("BOE", "Declaration filed (BOE)"), ("DO", "Delivery order collected"), ("DUTY", "Duty / deposit paid"), ("CLEARED", "Customs released")]
    if T or X:
        ms += [("VEHICLE", "Vehicle assigned"), ("PICKED_UP", "Picked up / loaded")]
        if X and not has_om:
            ms += [("BORDER", "Border crossed")]
    if T or X or F:
        ms += [("DELIVERED", "Delivered")]
    if G:
        ms += [("DOCS_IN", "Documents collected"), ("SUBMITTED", "Application submitted / service scheduled"), ("COMPLETED", "Service completed")]
    ms += [("INVOICED", "Invoiced"), ("CLOSED", "Job closed")]
    seen = set()
    order = []
    for code, label in ms:
        if code not in seen:
            seen.add(code)
            order.append((code, label))
    codes = [c for c, l in order]
    labels = dict(order)

    st = {}
    def done(code, d, note=""):
        st[code] = ["done", dstr(d), note or ""]
    def na(code, note=""):
        st[code] = ["na", "", note or ""]

    done("OPENED", jo.jo_date)
    if jo.carrier and jo.vessel_flight:
        done("BOOKED", ev_done.get("BOOKED") or jo.jo_date, jo.vessel_flight)
    if jo.awb_bl_no:
        done("DOCS", ev_done.get("DOCS") or jo.jo_date, (jo.awb_bl_no or "")[:40])
    if jo.awb_bl_no and jo.etd and todate(jo.etd) <= today:
        done("DEPARTED", jo.etd, "ETD")
    if cts:
        done("ARRIVED", cts[0].ct_date, "customs entry opened")
    elif pods:
        done("ARRIVED", pods[0].creation, "delivery record exists")
    for c in fz_cts:
        if c.boe_number and "FZ_BOE" not in st:
            done("FZ_BOE", c.ct_date, c.boe_number)
        if c.status == "Cleared":
            done("FZ_CLEARED", c.clearance_date or c.modified, c.boe_number or "")
    for c in om_cts:
        if c.boe_number and "OMAN_BOE" not in st:
            done("OMAN_BOE", c.ct_date, c.boe_number)
        if c.status == "Cleared":
            done("OMAN_CLEARED", c.clearance_date or c.modified, c.boe_number or "")
    mofa_vals = [(c.fps_mofa_status or "") for c in cts]
    if "Completed" in mofa_vals:
        done("MOFA", ev_done.get("MOFA") or [c.modified for c in cts if c.fps_mofa_status == "Completed"][0])
    elif cts and mofa_vals and all(v == "N/A" for v in mofa_vals):
        na("MOFA", "not required")
    boe_cts = [c for c in fin_cts if c.boe_number]
    if boe_cts:
        done("BOE", boe_cts[0].ct_date, ", ".join([c.boe_number for c in boe_cts]))
    do_vals = [(c.fps_do_status or "") for c in cts]
    if "Collected" in do_vals:
        done("DO", ev_done.get("DO") or [c.modified for c in cts if c.fps_do_status == "Collected"][0])
    elif cts and do_vals and all(v == "N/A" for v in do_vals):
        na("DO", "not required")
    duty = [c for c in cts if c.fps_duty_paid_on]
    if duty:
        done("DUTY", duty[0].fps_duty_paid_on)
    elif fin_cts and all((c.fps_clearance_type or "") in ("Import into Free Zone", "Export from Free Zone", "Export", "Re-Export", "Transfer within FZ", "FZ Transit") for c in fin_cts):
        na("DUTY", "no duty on this type")
    if fin_cts and all(c.status == "Cleared" for c in fin_cts):
        d = max([dstr(c.clearance_date or c.modified) for c in fin_cts])
        done("CLEARED", d, "BOE " + ", ".join([c.boe_number or "?" for c in fin_cts]))
    veh = [p for p in pods if p.vehicle_no]
    if veh:
        done("VEHICLE", veh[0].creation, veh[0].vehicle_no)
    pk = [p for p in pods if p.fps_pickup_datetime]
    if pk:
        done("PICKED_UP", pk[0].fps_pickup_datetime)
    dl = [p for p in pods if p.docstatus == 1 and p.delivery_status == "Delivered"]
    fin = [p for p in dl if p.fps_final_delivery in (1, None)]
    if fin:
        done("DELIVERED", fin[-1].pod_date, (fin[-1].received_by or fin[-1].delivery_location or "")[:40])
    elif dl:
        st["DELIVERED"] = ["pending", "", "%d partial delivery" % len(dl)]
    elif [p for p in pods if p.docstatus == 0 and p.delivery_status == "Delivered"]:
        st["DELIVERED"] = ["unconfirmed", dstr(pods[-1].pod_date), "POD still in draft"]
    if sis:
        done("INVOICED", sis[0].posting_date, sis[0].name)
    if ev_done.get("CLOSED") or jo.fps_stage == "Closed":
        done("CLOSED", ev_done.get("CLOSED") or today)
    for code, d in ev_done.items():
        if code in ("HOLD", "RESUME"):
            continue
        if code not in st:
            done(code, d, "logged")

    last_done = -1
    for i, code in enumerate(codes):
        if st.get(code, [""])[0] == "done":
            last_done = i
    for i, code in enumerate(codes):
        if i < last_done and code not in st:
            if code in ("BOOKED", "DOCS", "DEPARTED", "ARRIVED", "TRUCKS_DEPARTED", "BORDER", "PICKED_UP", "VEHICLE", "DOCS_IN", "SUBMITTED", "FZ_BOE", "FZ_CLEARED", "OMAN_BOE", "OMAN_CLEARED", "BOE"):
                st[code] = ["done", "", "implied"]
            elif code in ("MOFA", "DO", "DUTY"):
                st[code] = ["na", "", "not recorded"]

    def isdone(c):
        return st.get(c, [""])[0] == "done"

    hold_reason = None
    ct_hold = [c for c in cts if c.status in ("On Hold", "Delayed")]
    pod_fail = [p for p in pods if p.docstatus == 1 and p.delivery_status in ("Failed", "Returned")]
    if hold:
        hold_reason = (hold.status_line or hold.notes or "On hold")[:140]
    elif ct_hold and not isdone("CLEARED"):
        hold_reason = ("Customs %s: %s" % (ct_hold[0].status, (ct_hold[0].remarks or "")))[:140]
    elif pod_fail and not isdone("DELIVERED"):
        hold_reason = "Delivery %s" % pod_fail[-1].delivery_status
    if hold_reason:
        stage = "On Hold"
    elif isdone("CLOSED"):
        stage = "Closed"
    elif isdone("INVOICED"):
        stage = "Invoiced"
    elif isdone("DELIVERED") or (G and isdone("COMPLETED") and not (T or X or F)):
        stage = "Delivered"
    elif (C and isdone("CLEARED")) or (F and not C and isdone("ARRIVED")):
        stage = "Cleared - Ready"
    elif cts or pods or isdone("DEPARTED") or isdone("BOOKED") or isdone("SUBMITTED") or isdone("PICKED_UP") or isdone("VEHICLE"):
        stage = "In Progress"
    elif "DOCS" in codes and not isdone("DOCS"):
        stage = "Docs received"
    else:
        stage = "New"

    applicable = [c for c in codes if st.get(c, ["pending"])[0] != "na"]
    n_done = len([c for c in applicable if st.get(c, [""])[0] == "done"])
    progress = "%d / %d" % (n_done, len(applicable))
    pending = [c for c in applicable if st.get(c, ["pending"])[0] != "done"]
    next_action = None
    next_due = None
    real_evs = [e for e in evs if not ((e.evidence_ref or "").endswith(":tracker-enabled") or ":rebuild:" in (e.evidence_ref or ""))]
    last_ev = real_evs[-1] if real_evs else None
    if last_ev and last_ev.next_action and stage not in ("Closed",):
        next_action = last_ev.next_action
        next_due = last_ev.follow_up_date
    elif pending and stage != "Closed":
        next_action = labels[pending[0]]
    last_update = None
    last_on = None
    if last_ev:
        who = (last_ev.responsible or last_ev.owner or "").split("@")[0]
        last_update = ("%s - %s: %s" % (dstr(last_ev.update_date), who, (last_ev.status_line or last_ev.notes or "")[:160]))
        last_on = last_ev.creation

    cat = jo.fps_category
    if not cat:
        if F:
            cat = "FF - Freight Forwarding"
        elif C:
            cat = "CC - Customs Clearance"
        elif X:
            cat = "XB - Cross-Border Land Transport"
        elif T:
            cat = "LT - Local Land Transport"
        elif G:
            cat = "GJ - General Job"
        if cat:
            upd["fps_category"] = cat
    code2 = (cat or "")[:2]
    parts = [code2 or "?"]
    md = " ".join([x for x in [jo.movement_type, jo.direction] if x])
    if md and code2 in ("CC", "FF"):
        parts.append(md)
    if code2 == "CC" and jo.fps_clearance_location:
        parts.append(jo.fps_clearance_location.split(" (")[0])
    if code2 in ("LT", "XB") and jo.fps_vehicle_type:
        parts.append(jo.fps_vehicle_type)
    if code2 == "GJ" and jo.fps_general_job_type:
        parts.append(jo.fps_general_job_type)
    extras = []
    if C and code2 == "FF":
        extras.append("clearance")
    if (T or X) and code2 in ("CC", "FF", "GJ"):
        extras.append("delivery")
    if route != "Direct":
        extras.append(route.lower())
    label = " - ".join(parts) + (" + " + ", ".join(extras) if extras else "")

    state = [[c, labels[c]] + st.get(c, ["pending", "", ""]) for c in codes]
    upd.update({"fps_stage": stage, "fps_progress": progress, "fps_next_action": next_action, "fps_next_due": next_due, "fps_last_update": last_update, "fps_last_update_on": last_on, "fps_hold_reason": hold_reason, "fps_milestone_state": json.dumps(state), "fps_subcategory": label})
    if stage != jo.fps_stage or not jo.fps_stage_since:
        upd["fps_stage_since"] = today
    frappe.db.set_value("Job Order", jo_name, upd)


try:
    if doc.job_order:
        rollup(doc.job_order)
except Exception:
    frappe.log_error(title='JT Rollup')
""",
	'FPS Tracker Sweep': """\
# FPS Hybrid Job Tracker - derivation engine (safe_exec Server Script body).
# rollup(jo_name): rebuilds the per-job milestone checklist, stage, progress, next action and SOW label
# from the documents on the job (Customs Trackers, PODs, Sales Invoices) and the Job Tracker event log.
# Writes only with frappe.db.set_value on the Job Order - never doc.save(), so it can never recurse or block a save.

def rollup(jo_name):
    def todate(v):
        return frappe.utils.getdate(v) if v else None
    def dstr(v):
        return str(v)[:10] if v else ""
    jo = frappe.db.get_value("Job Order", jo_name, ["name", "jo_date", "docstatus", "movement_type", "direction", "awb_bl_no", "carrier", "vessel_flight", "etd", "eta", "boe_no", "pol", "pod", "fps_svc_freight", "fps_svc_clearance", "fps_svc_transport", "fps_svc_crossborder", "fps_svc_general", "fps_category", "fps_route_pattern", "fps_stage", "fps_stage_since", "fps_clearance_location", "fps_vehicle_type", "fps_general_job_type", "fps_owner"], as_dict=True)
    if not jo or jo.docstatus == 2:
        return
    today = frappe.utils.getdate(frappe.utils.today())
    cts = frappe.get_all("Customs Tracker", filters={"job_order": jo_name}, fields=["name", "status", "boe_number", "fps_leg", "fps_clearance_type", "fps_clearance_location", "fps_mofa_status", "fps_do_status", "fps_duty_paid_on", "clearance_date", "ct_date", "modified", "remarks"], order_by="ct_date asc, creation asc")
    pods = frappe.get_all("Proof of Delivery", filters={"job_order": jo_name, "docstatus": ["<", 2]}, fields=["name", "docstatus", "delivery_status", "pod_date", "vehicle_no", "fps_pickup_datetime", "fps_final_delivery", "received_by", "delivery_location", "creation"], order_by="creation asc")
    sis = frappe.get_all("Sales Invoice", filters={"fps_job_order": jo_name, "docstatus": 1, "fps_is_payment_request": 0}, fields=["name", "posting_date"], order_by="posting_date asc")
    # ONE tracker per job now; its updates are child rows, not sibling documents.
    # Read through the parent document rather than querying the child table, so
    # no child-table query rule can change under us between Frappe versions.
    #
    # Sorted explicitly rather than trusting grid order: a back-dated update
    # appends at the END of the grid, and everything below assumes evs[-1] is
    # the newest. sorted() and lambda were both PROVED to work in this site's
    # safe_exec sandbox before this was written -- no script here had ever
    # used either, so it was not safe to assume they were available.
    tr_name = frappe.db.get_value("Job Tracker", {"job_order": jo_name}, "name", order_by="creation asc")
    evs = frappe.get_doc("Job Tracker", tr_name).fps_updates if tr_name else []
    evs = sorted(evs, key=lambda x: (str(x.update_date or "9999-12-31"), x.idx))

    FZ = ("Transfer within FZ", "FZ Transit")
    OM = ("Port Sultan Qaboos (Oman)", "Sohar Port (Oman)")
    fz_names = [c.name for c in cts if (c.fps_clearance_type or "") in FZ]
    om_names = [c.name for c in cts if (c.fps_clearance_location or "") in OM and c.name not in fz_names]
    fz_cts = [c for c in cts if c.name in fz_names]
    om_cts = [c for c in cts if c.name in om_names]
    fin_cts = [c for c in cts if c.name not in fz_names and c.name not in om_names] or om_cts

    ev_done = {}
    hold = None
    for e in evs:
        code = e.milestone
        if code == "HOLD":
            hold = e
        elif code == "RESUME":
            hold = None
        elif code and code not in ev_done:
            ev_done[code] = e.update_date

    F = jo.fps_svc_freight
    C = jo.fps_svc_clearance
    T = jo.fps_svc_transport
    X = jo.fps_svc_crossborder
    G = jo.fps_svc_general
    upd = {}
    if cts and not C:
        C = 1
        upd["fps_svc_clearance"] = 1
    if [p for p in pods if p.vehicle_no] and not T and not X:
        T = 1
        upd["fps_svc_transport"] = 1
    has_fz = len(fz_cts) > 0
    has_om = len(om_cts) > 0
    route = jo.fps_route_pattern or "Direct"
    if has_fz and route == "Direct":
        route = "FZ transfer then import"
        upd["fps_route_pattern"] = route
    if has_om and route == "Direct":
        route = "Oman corridor"
        upd["fps_route_pattern"] = route

    ms = [("OPENED", "Job opened")]
    if F:
        ms += [("BOOKED", "Booking confirmed"), ("DOCS", "Shipping docs checked"), ("DEPARTED", "Departed origin"), ("ARRIVED", "Arrived at destination")]
    elif C or (jo.movement_type in ("SEA", "AIR")):
        ms += [("DOCS", "Shipping docs checked"), ("ARRIVED", "Cargo arrived")]
    if C:
        if has_fz:
            ms += [("FZ_BOE", "FZ transfer BOE filed"), ("FZ_CLEARED", "FZ transfer approved")]
        if has_om:
            ms += [("OMAN_BOE", "Oman declaration filed"), ("OMAN_CLEARED", "Cleared at Oman port"), ("TRUCKS_DEPARTED", "Trucks departed Oman"), ("BORDER", "Border crossed")]
        ms += [("MOFA", "MOFA attestation"), ("BOE", "Declaration filed (BOE)"), ("DO", "Delivery order collected"), ("DUTY", "Duty / deposit paid"), ("CLEARED", "Customs released")]
    if T or X:
        ms += [("VEHICLE", "Vehicle assigned"), ("PICKED_UP", "Picked up / loaded")]
        if X and not has_om:
            ms += [("BORDER", "Border crossed")]
    if T or X or F:
        ms += [("DELIVERED", "Delivered")]
    if G:
        ms += [("DOCS_IN", "Documents collected"), ("SUBMITTED", "Application submitted / service scheduled"), ("COMPLETED", "Service completed")]
    ms += [("INVOICED", "Invoiced"), ("CLOSED", "Job closed")]
    seen = set()
    order = []
    for code, label in ms:
        if code not in seen:
            seen.add(code)
            order.append((code, label))
    codes = [c for c, l in order]
    labels = dict(order)

    st = {}
    def done(code, d, note=""):
        st[code] = ["done", dstr(d), note or ""]
    def na(code, note=""):
        st[code] = ["na", "", note or ""]

    done("OPENED", jo.jo_date)
    if jo.carrier and jo.vessel_flight:
        done("BOOKED", ev_done.get("BOOKED") or jo.jo_date, jo.vessel_flight)
    if jo.awb_bl_no:
        done("DOCS", ev_done.get("DOCS") or jo.jo_date, (jo.awb_bl_no or "")[:40])
    if jo.awb_bl_no and jo.etd and todate(jo.etd) <= today:
        done("DEPARTED", jo.etd, "ETD")
    if cts:
        done("ARRIVED", cts[0].ct_date, "customs entry opened")
    elif pods:
        done("ARRIVED", pods[0].creation, "delivery record exists")
    for c in fz_cts:
        if c.boe_number and "FZ_BOE" not in st:
            done("FZ_BOE", c.ct_date, c.boe_number)
        if c.status == "Cleared":
            done("FZ_CLEARED", c.clearance_date or c.modified, c.boe_number or "")
    for c in om_cts:
        if c.boe_number and "OMAN_BOE" not in st:
            done("OMAN_BOE", c.ct_date, c.boe_number)
        if c.status == "Cleared":
            done("OMAN_CLEARED", c.clearance_date or c.modified, c.boe_number or "")
    mofa_vals = [(c.fps_mofa_status or "") for c in cts]
    if "Completed" in mofa_vals:
        done("MOFA", ev_done.get("MOFA") or [c.modified for c in cts if c.fps_mofa_status == "Completed"][0])
    elif cts and mofa_vals and all(v == "N/A" for v in mofa_vals):
        na("MOFA", "not required")
    boe_cts = [c for c in fin_cts if c.boe_number]
    if boe_cts:
        done("BOE", boe_cts[0].ct_date, ", ".join([c.boe_number for c in boe_cts]))
    do_vals = [(c.fps_do_status or "") for c in cts]
    if "Collected" in do_vals:
        done("DO", ev_done.get("DO") or [c.modified for c in cts if c.fps_do_status == "Collected"][0])
    elif cts and do_vals and all(v == "N/A" for v in do_vals):
        na("DO", "not required")
    duty = [c for c in cts if c.fps_duty_paid_on]
    if duty:
        done("DUTY", duty[0].fps_duty_paid_on)
    elif fin_cts and all((c.fps_clearance_type or "") in ("Import into Free Zone", "Export from Free Zone", "Export", "Re-Export", "Transfer within FZ", "FZ Transit") for c in fin_cts):
        na("DUTY", "no duty on this type")
    if fin_cts and all(c.status == "Cleared" for c in fin_cts):
        d = max([dstr(c.clearance_date or c.modified) for c in fin_cts])
        done("CLEARED", d, "BOE " + ", ".join([c.boe_number or "?" for c in fin_cts]))
    veh = [p for p in pods if p.vehicle_no]
    if veh:
        done("VEHICLE", veh[0].creation, veh[0].vehicle_no)
    pk = [p for p in pods if p.fps_pickup_datetime]
    if pk:
        done("PICKED_UP", pk[0].fps_pickup_datetime)
    dl = [p for p in pods if p.docstatus == 1 and p.delivery_status == "Delivered"]
    fin = [p for p in dl if p.fps_final_delivery in (1, None)]
    if fin:
        done("DELIVERED", fin[-1].pod_date, (fin[-1].received_by or fin[-1].delivery_location or "")[:40])
    elif dl:
        st["DELIVERED"] = ["pending", "", "%d partial delivery" % len(dl)]
    elif [p for p in pods if p.docstatus == 0 and p.delivery_status == "Delivered"]:
        st["DELIVERED"] = ["unconfirmed", dstr(pods[-1].pod_date), "POD still in draft"]
    if sis:
        done("INVOICED", sis[0].posting_date, sis[0].name)
    if ev_done.get("CLOSED") or jo.fps_stage == "Closed":
        done("CLOSED", ev_done.get("CLOSED") or today)
    for code, d in ev_done.items():
        if code in ("HOLD", "RESUME"):
            continue
        if code not in st:
            done(code, d, "logged")

    last_done = -1
    for i, code in enumerate(codes):
        if st.get(code, [""])[0] == "done":
            last_done = i
    for i, code in enumerate(codes):
        if i < last_done and code not in st:
            if code in ("BOOKED", "DOCS", "DEPARTED", "ARRIVED", "TRUCKS_DEPARTED", "BORDER", "PICKED_UP", "VEHICLE", "DOCS_IN", "SUBMITTED", "FZ_BOE", "FZ_CLEARED", "OMAN_BOE", "OMAN_CLEARED", "BOE"):
                st[code] = ["done", "", "implied"]
            elif code in ("MOFA", "DO", "DUTY"):
                st[code] = ["na", "", "not recorded"]

    def isdone(c):
        return st.get(c, [""])[0] == "done"

    hold_reason = None
    ct_hold = [c for c in cts if c.status in ("On Hold", "Delayed")]
    pod_fail = [p for p in pods if p.docstatus == 1 and p.delivery_status in ("Failed", "Returned")]
    if hold:
        hold_reason = (hold.status_line or hold.notes or "On hold")[:140]
    elif ct_hold and not isdone("CLEARED"):
        hold_reason = ("Customs %s: %s" % (ct_hold[0].status, (ct_hold[0].remarks or "")))[:140]
    elif pod_fail and not isdone("DELIVERED"):
        hold_reason = "Delivery %s" % pod_fail[-1].delivery_status
    if hold_reason:
        stage = "On Hold"
    elif isdone("CLOSED"):
        stage = "Closed"
    elif isdone("INVOICED"):
        stage = "Invoiced"
    elif isdone("DELIVERED") or (G and isdone("COMPLETED") and not (T or X or F)):
        stage = "Delivered"
    elif (C and isdone("CLEARED")) or (F and not C and isdone("ARRIVED")):
        stage = "Cleared - Ready"
    elif cts or pods or isdone("DEPARTED") or isdone("BOOKED") or isdone("SUBMITTED") or isdone("PICKED_UP") or isdone("VEHICLE"):
        stage = "In Progress"
    elif "DOCS" in codes and not isdone("DOCS"):
        stage = "Docs received"
    else:
        stage = "New"

    applicable = [c for c in codes if st.get(c, ["pending"])[0] != "na"]
    n_done = len([c for c in applicable if st.get(c, [""])[0] == "done"])
    progress = "%d / %d" % (n_done, len(applicable))
    pending = [c for c in applicable if st.get(c, ["pending"])[0] != "done"]
    next_action = None
    next_due = None
    real_evs = [e for e in evs if not ((e.evidence_ref or "").endswith(":tracker-enabled") or ":rebuild:" in (e.evidence_ref or ""))]
    last_ev = real_evs[-1] if real_evs else None
    if last_ev and last_ev.next_action and stage not in ("Closed",):
        next_action = last_ev.next_action
        next_due = last_ev.follow_up_date
    elif pending and stage != "Closed":
        next_action = labels[pending[0]]
    last_update = None
    last_on = None
    if last_ev:
        who = (last_ev.responsible or last_ev.owner or "").split("@")[0]
        last_update = ("%s - %s: %s" % (dstr(last_ev.update_date), who, (last_ev.status_line or last_ev.notes or "")[:160]))
        last_on = last_ev.creation

    cat = jo.fps_category
    if not cat:
        if F:
            cat = "FF - Freight Forwarding"
        elif C:
            cat = "CC - Customs Clearance"
        elif X:
            cat = "XB - Cross-Border Land Transport"
        elif T:
            cat = "LT - Local Land Transport"
        elif G:
            cat = "GJ - General Job"
        if cat:
            upd["fps_category"] = cat
    code2 = (cat or "")[:2]
    parts = [code2 or "?"]
    md = " ".join([x for x in [jo.movement_type, jo.direction] if x])
    if md and code2 in ("CC", "FF"):
        parts.append(md)
    if code2 == "CC" and jo.fps_clearance_location:
        parts.append(jo.fps_clearance_location.split(" (")[0])
    if code2 in ("LT", "XB") and jo.fps_vehicle_type:
        parts.append(jo.fps_vehicle_type)
    if code2 == "GJ" and jo.fps_general_job_type:
        parts.append(jo.fps_general_job_type)
    extras = []
    if C and code2 == "FF":
        extras.append("clearance")
    if (T or X) and code2 in ("CC", "FF", "GJ"):
        extras.append("delivery")
    if route != "Direct":
        extras.append(route.lower())
    label = " - ".join(parts) + (" + " + ", ".join(extras) if extras else "")

    state = [[c, labels[c]] + st.get(c, ["pending", "", ""]) for c in codes]
    upd.update({"fps_stage": stage, "fps_progress": progress, "fps_next_action": next_action, "fps_next_due": next_due, "fps_last_update": last_update, "fps_last_update_on": last_on, "fps_hold_reason": hold_reason, "fps_milestone_state": json.dumps(state), "fps_subcategory": label})
    if stage != jo.fps_stage or not jo.fps_stage_since:
        upd["fps_stage_since"] = today
    frappe.db.set_value("Job Order", jo_name, upd)


for jrow in frappe.get_all('Job Order', filters={'docstatus': ['<', 2], 'fps_stage': ['not in', ['Closed']]}, fields=['name'], limit=2000):
    try:
        rollup(jrow.name)
    except Exception:
        frappe.log_error(title='FPS Tracker Sweep ' + jrow.name)
""",
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

        def emit(code, ref, text, visible=1, etype="System"):
            # order_by is the race guard, not decoration. If two events ever open
            # a tracker at once the second is named '<name>-2', and every later call
            # has to converge on the SAME one or the job's history splits in two.
            # Looked up by job_order rather than by name, so it does not care that
            # the prefix went back to FPS/JT.
            tr = frappe.db.get_value("Job Tracker", {"job_order": jo}, "name", order_by="creation asc")
            if not tr:
                tr = frappe.get_doc({
                    "doctype": "Job Tracker", "job_order": jo, "customer": doc.customer,
                    "track_date": frappe.utils.today(),
                }).insert(ignore_permissions=True).name
            t = frappe.get_doc("Job Tracker", tr)
            if [u for u in t.fps_updates if (u.evidence_ref or "") == ref]:
                return
            t.append("fps_updates", {
                "update_date": frappe.utils.today(), "event_type": etype, "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": doc.fps_leg or 1,
                "responsible": frappe.session.user,
            })
            t.track_date = frappe.utils.today()
            t.fps_event_type = etype
            t.fps_milestone = code
            t.current_status = text[:140]
            t.fps_evidence_ref = ref
            t.fps_source = "System"
            t.fps_customer_visible = visible
            t.save(ignore_permissions=True)
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
        def emit(code, ref, text, visible=1, etype="System"):
            # order_by is the race guard, not decoration. If two events ever open
            # a tracker at once the second is named '<name>-2', and every later call
            # has to converge on the SAME one or the job's history splits in two.
            # Looked up by job_order rather than by name, so it does not care that
            # the prefix went back to FPS/JT.
            tr = frappe.db.get_value("Job Tracker", {"job_order": jo}, "name", order_by="creation asc")
            if not tr:
                tr = frappe.get_doc({
                    "doctype": "Job Tracker", "job_order": jo, "customer": doc.customer,
                    "track_date": doc.pod_date or frappe.utils.today(),
                }).insert(ignore_permissions=True).name
            t = frappe.get_doc("Job Tracker", tr)
            if [u for u in t.fps_updates if (u.evidence_ref or "") == ref]:
                return
            t.append("fps_updates", {
                "update_date": doc.pod_date or frappe.utils.today(), "event_type": etype, "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": doc.fps_leg or 1,
                "responsible": frappe.session.user,
            })
            t.track_date = doc.pod_date or frappe.utils.today()
            t.fps_event_type = etype
            t.fps_milestone = code
            t.current_status = text[:140]
            t.fps_evidence_ref = ref
            t.fps_source = "System"
            t.fps_customer_visible = visible
            t.save(ignore_permissions=True)
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
        def emit(code, ref, text, visible=1, etype="System"):
            # order_by is the race guard, not decoration. If two events ever open
            # a tracker at once the second is named '<name>-2', and every later call
            # has to converge on the SAME one or the job's history splits in two.
            # Looked up by job_order rather than by name, so it does not care that
            # the prefix went back to FPS/JT.
            tr = frappe.db.get_value("Job Tracker", {"job_order": jo}, "name", order_by="creation asc")
            if not tr:
                tr = frappe.get_doc({
                    "doctype": "Job Tracker", "job_order": jo, "customer": doc.customer,
                    "track_date": doc.pod_date or frappe.utils.today(),
                }).insert(ignore_permissions=True).name
            t = frappe.get_doc("Job Tracker", tr)
            if [u for u in t.fps_updates if (u.evidence_ref or "") == ref]:
                return
            t.append("fps_updates", {
                "update_date": doc.pod_date or frappe.utils.today(), "event_type": etype, "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": doc.fps_leg or 1,
                "responsible": frappe.session.user,
            })
            t.track_date = doc.pod_date or frappe.utils.today()
            t.fps_event_type = etype
            t.fps_milestone = code
            t.current_status = text[:140]
            t.fps_evidence_ref = ref
            t.fps_source = "System"
            t.fps_customer_visible = visible
            t.save(ignore_permissions=True)
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
        def emit(code, ref, text, visible=1, etype="System"):
            # order_by is the race guard, not decoration. If two events ever open
            # a tracker at once the second is named '<name>-2', and every later call
            # has to converge on the SAME one or the job's history splits in two.
            # Looked up by job_order rather than by name, so it does not care that
            # the prefix went back to FPS/JT.
            tr = frappe.db.get_value("Job Tracker", {"job_order": jo}, "name", order_by="creation asc")
            if not tr:
                tr = frappe.get_doc({
                    "doctype": "Job Tracker", "job_order": jo, "customer": doc.customer,
                    "track_date": doc.pod_date or frappe.utils.today(),
                }).insert(ignore_permissions=True).name
            t = frappe.get_doc("Job Tracker", tr)
            if [u for u in t.fps_updates if (u.evidence_ref or "") == ref]:
                return
            t.append("fps_updates", {
                "update_date": doc.pod_date or frappe.utils.today(), "event_type": etype, "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": doc.fps_leg or 1,
                "responsible": frappe.session.user,
            })
            t.track_date = doc.pod_date or frappe.utils.today()
            t.fps_event_type = etype
            t.fps_milestone = code
            t.current_status = text[:140]
            t.fps_evidence_ref = ref
            t.fps_source = "System"
            t.fps_customer_visible = visible
            t.save(ignore_permissions=True)
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
        def emit(code, ref, text, visible=0):
            # order_by is the race guard, not decoration. If two events ever open
            # a tracker at once the second is named '<name>-2', and every later call
            # has to converge on the SAME one or the job's history splits in two.
            # Looked up by job_order rather than by name, so it does not care that
            # the prefix went back to FPS/JT.
            tr = frappe.db.get_value("Job Tracker", {"job_order": jo}, "name", order_by="creation asc")
            if not tr:
                tr = frappe.get_doc({
                    "doctype": "Job Tracker", "job_order": jo, "customer": doc.customer,
                    "track_date": doc.posting_date or frappe.utils.today(),
                }).insert(ignore_permissions=True).name
            t = frappe.get_doc("Job Tracker", tr)
            if [u for u in t.fps_updates if (u.evidence_ref or "") == ref]:
                return
            t.append("fps_updates", {
                "update_date": doc.posting_date or frappe.utils.today(), "event_type": "System", "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": 1,
                "responsible": frappe.session.user,
            })
            t.track_date = doc.posting_date or frappe.utils.today()
            t.fps_event_type = "System"
            t.fps_milestone = code
            t.current_status = text[:140]
            t.fps_evidence_ref = ref
            t.fps_source = "System"
            t.fps_customer_visible = visible
            t.save(ignore_permissions=True)
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
        def emit(code, ref, text, visible=0):
            # order_by is the race guard, not decoration. If two events ever open
            # a tracker at once the second is named '<name>-2', and every later call
            # has to converge on the SAME one or the job's history splits in two.
            # Looked up by job_order rather than by name, so it does not care that
            # the prefix went back to FPS/JT.
            tr = frappe.db.get_value("Job Tracker", {"job_order": jo}, "name", order_by="creation asc")
            if not tr:
                tr = frappe.get_doc({
                    "doctype": "Job Tracker", "job_order": jo, "customer": doc.customer,
                    "track_date": doc.posting_date or frappe.utils.today(),
                }).insert(ignore_permissions=True).name
            t = frappe.get_doc("Job Tracker", tr)
            if [u for u in t.fps_updates if (u.evidence_ref or "") == ref]:
                return
            t.append("fps_updates", {
                "update_date": doc.posting_date or frappe.utils.today(), "event_type": "System", "milestone": code,
                "status_line": text[:140], "notes": text, "evidence_ref": ref,
                "source": "System", "customer_visible": visible, "leg": 1,
                "responsible": frappe.session.user,
            })
            t.track_date = doc.posting_date or frappe.utils.today()
            t.fps_event_type = "System"
            t.fps_milestone = code
            t.current_status = text[:140]
            t.fps_evidence_ref = ref
            t.fps_source = "System"
            t.fps_customer_visible = visible
            t.save(ignore_permissions=True)
        if doc.docstatus == 2:
            emit(None, "SI:%s:cancel" % doc.name, "Invoice %s cancelled" % doc.name)
        elif doc.fps_is_payment_request:
            emit(None, "SI:%s:pr" % doc.name, "Payment request %s raised" % doc.name)
        else:
            emit("INVOICED", "SI:%s:submit" % doc.name, "Invoice %s issued" % doc.name)
except Exception:
    frappe.log_error(title="SI Events")
""",
}

CLIENT_SCRIPTS = {
	'Job Order - SOW Tracker UI': """\
// Job Order - SOW Tracker UI (Form). Status header + stepper at the top of the form, detailed checklist, "Log update" dialog.
frappe.ui.form.on('Job Order', {
  refresh(frm) {
    render_header(frm);
    render_checklist(frm);
    relabel(frm);
    if (frm.doc.__islocal) return;
    frm.add_custom_button(__('Log update'), () => log_update_dialog(frm)).addClass('btn-primary');
    frm.add_custom_button(__('Rebuild checklist'), () => {
      // Was: insert a throwaway Job Tracker document purely to trigger the
      // rollup. 174 of those had to be deleted afterwards. This re-derives
      // from the documents and records nothing.
      frappe.call({ method: 'fps_erpnext.api.trackers.rebuild', args: { job_order: frm.doc.name } }).then(() => frm.reload_doc());
    }, __('Tracker'));
    frm.add_custom_button(__('Update history'), () => fps_open_tracker(frm.doc.name), __('Tracker'));
    frm.add_custom_button(__('Job board'), () => frappe.set_route('job-order', 'view', 'kanban', 'FPS Job Tracker'), __('Tracker'));
    if (frm.doc.fps_stage) {
      frm.page.set_indicator(__(frm.doc.fps_stage) + (frm.doc.fps_progress ? ' · ' + frm.doc.fps_progress : ''), stage_color(frm.doc.fps_stage));
    }
  },
  fps_svc_freight(frm) { relabel(frm); }, fps_svc_transport(frm) { relabel(frm); }, fps_svc_crossborder(frm) { relabel(frm); }, fps_svc_clearance(frm) { relabel(frm); },
});

const ACTIVITY = {
  docs: { name: 'Documents & freight', bg: '#E4EEFB', fg: '#1B4FA8', border: '#B9D0F2' },
  customs: { name: 'Customs', bg: '#FCF1DA', fg: '#7D5200', border: '#F0D49A' },
  transport: { name: 'Transport & delivery', bg: '#DDF4EE', fg: '#0F6B5C', border: '#A9DFD1' },
  general: { name: 'General job', bg: '#ECE8F8', fg: '#4A3A9A', border: '#CFC5EF' },
  billing: { name: 'Billing & closure', bg: '#EBEEF2', fg: '#3B4453', border: '#CAD1DB' },
};
function activity_group(code) {
  if (['BOOKED', 'DOCS', 'DEPARTED', 'ARRIVED'].includes(code)) return ACTIVITY.docs;
  if (['FZ_BOE', 'FZ_CLEARED', 'OMAN_BOE', 'OMAN_CLEARED', 'MOFA', 'BOE', 'DO', 'DUTY', 'CLEARED'].includes(code)) return ACTIVITY.customs;
  if (['VEHICLE', 'PICKED_UP', 'TRUCKS_DEPARTED', 'BORDER', 'DELIVERED'].includes(code)) return ACTIVITY.transport;
  if (['DOCS_IN', 'SUBMITTED', 'COMPLETED'].includes(code)) return ACTIVITY.general;
  return ACTIVITY.billing;
}
function stage_color(stage) {
  return { 'New': 'gray', 'Docs': 'orange', 'In Progress': 'blue', 'Cleared - Ready': 'cyan', 'Delivered': 'green', 'Invoiced': 'darkgrey', 'Closed': 'light-gray', 'On Hold': 'red' }[stage] || 'gray';
}
function stage_words(stage) {
  return { 'New': 'New job, nothing filed yet', 'Docs': 'Waiting for shipping documents', 'In Progress': 'In progress', 'Cleared - Ready': 'Customs released, delivery pending', 'Delivered': 'Delivered, to be invoiced', 'Invoiced': 'Invoiced, awaiting closure', 'Closed': 'Closed', 'On Hold': 'On hold' }[stage] || stage;
}
function parse_state(frm) { try { return JSON.parse(frm.doc.fps_milestone_state || '[]'); } catch (e) { return []; } }
function relabel(frm) {
  const transport_only = (frm.doc.fps_svc_transport || frm.doc.fps_svc_crossborder) && !frm.doc.fps_svc_freight && !frm.doc.fps_svc_clearance;
  frm.set_df_property('pol', 'label', transport_only ? 'Pickup from' : 'Origin / POL');
  frm.set_df_property('pod', 'label', transport_only ? 'Deliver to' : 'Destination');
}

function render_header(frm) {
  if (!frm.dashboard || !frm.dashboard.wrapper) return;
  frm.dashboard.wrapper.find('.fps-status').remove();
  if (frm.doc.__islocal) return;
  const esc = frappe.utils.escape_html;
  const rows = parse_state(frm);
  const total = rows.filter(r => r[2] !== 'na').length, done = rows.filter(r => r[2] === 'done').length;
  const pct = total ? Math.round(done / total * 100) : 0;
  const stage = frm.doc.fps_stage || 'New';
  const pill = '<span class="indicator-pill ' + stage_color(stage) + '" style="font-size:13px;padding:4px 12px">' + esc(stage) + '</span>';
  let html = '<div class="fps-status" style="padding:6px 0 4px">';
  if (frm.doc.fps_hold_reason) html += '<div class="alert alert-danger" style="padding:6px 10px;margin:0 0 10px"><b>On hold:</b> ' + esc(frm.doc.fps_hold_reason) + '</div>';
  html += '<div style="display:flex;flex-wrap:wrap;gap:18px 28px;align-items:center;margin-bottom:10px">'
    + '<div>' + pill + ' <span class="text-muted" style="margin-left:6px">' + esc(stage_words(stage)) + '</span></div>'
    + '<div style="min-width:220px"><div style="display:flex;justify-content:space-between;font-size:12px;color:#6c757d"><span>' + esc(frm.doc.fps_subcategory || '') + '</span><span>' + done + ' / ' + total + '</span></div><div style="height:8px;background:#e6e9f0;border-radius:4px;overflow:hidden"><div style="height:100%;width:' + pct + '%;background:#0B4FE0"></div></div></div>'
    + '<div><div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6c757d">Next action</div><div style="font-weight:600">' + esc(frm.doc.fps_next_action || '—') + (frm.doc.fps_next_due ? ' <span class="text-muted">· due ' + frappe.datetime.str_to_user(frm.doc.fps_next_due) + '</span>' : '') + '</div></div>'
    + '<div><div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6c757d">Owner</div><div>' + esc((frm.doc.fps_owner || '').split('@')[0] || '—') + '</div></div>'
    + '<div style="flex:1;min-width:240px"><div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6c757d">Last update</div><div>' + esc(frm.doc.fps_last_update || '—') + '</div></div>'
    + '</div>';
  if (rows.length) {
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px">';
    rows.filter(r => r[0] !== 'OPENED').forEach(r => {
      const [code, label, status, date, note] = r;
      const g = activity_group(code);
      const bg = status === 'done' ? g.bg : status === 'na' ? '#F3F4F7' : '#FFFFFF';
      const fg = status === 'na' ? '#9AA3B5' : g.fg;
      const mark = status === 'done' ? '&#10003; ' : status === 'unconfirmed' ? '? ' : status === 'na' ? '&ndash; ' : '&#9675; ';
      const title = (status === 'done' ? 'Done' : status === 'unconfirmed' ? 'Unconfirmed' : status === 'na' ? 'Not applicable' : 'Pending') + (date ? ' · ' + frappe.datetime.str_to_user(date) : '') + (note ? ' · ' + note : '');
      html += '<span title="' + esc(title) + '" style="font-size:12px;padding:3px 9px;border-radius:12px;border:1px solid ' + (status === 'na' ? '#d8deea' : g.border) + ';background:' + bg + ';color:' + fg + (status === 'na' ? ';text-decoration:line-through' : '') + (status === 'unconfirmed' ? ';border-style:dashed' : '') + '">' + mark + esc(label) + (date && status === 'done' ? ' <span style="opacity:.7">' + frappe.datetime.str_to_user(date).slice(0, 5) + '</span>' : '') + '</span>';
    });
    html += '</div>';
    html += '<div style="margin-top:8px;font-size:11.5px;color:#6c757d;display:flex;flex-wrap:wrap;gap:12px">' + Object.values(ACTIVITY).map(a => '<span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:' + a.bg + ';border:1px solid ' + a.border + ';margin-right:4px;vertical-align:-1px"></i>' + a.name + '</span>').join('') + '<span>&#10003; done &nbsp; &#9675; pending &nbsp; ? unconfirmed &nbsp; &ndash; not needed</span></div>';
  }
  html += '</div>';
  const section = frm.dashboard.add_section(html, __('Job status'));
  if (section && section.addClass) section.addClass('fps-status');
  frm.dashboard.show();
}

function render_checklist(frm) {
  const wrapper = frm.get_field('fps_checklist_html') && frm.get_field('fps_checklist_html').$wrapper;
  if (!wrapper) return;
  const rows = parse_state(frm);
  if (!rows.length) { wrapper.html('<div class="text-muted small">The checklist appears after the first save. It is built from the service lines ticked above and from the customs entries, PODs and invoices on this job.</div>'); return; }
  const icon = { done: '<span style="color:#1A8F5C;font-weight:600">&#10003;</span>', na: '<span style="color:#98A3B8">&ndash;</span>', unconfirmed: '<span style="color:#B86E00;font-weight:600">?</span>', pending: '<span style="color:#B9C3D6">&#9675;</span>' };
  let html = '<table class="table table-sm" style="margin:0;font-size:12.5px"><thead><tr><th style="width:26px"></th><th>Milestone</th><th style="width:110px">Date</th><th>Proof / note</th></tr></thead><tbody>';
  rows.forEach(r => {
    const [code, label, status, date, note] = r;
    const dim = status === 'na' ? ' style="color:#98A3B8"' : '';
    const g = activity_group(code);
    html += '<tr' + dim + '><td>' + (icon[status] || icon.pending) + '</td><td><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + g.bg + ';border:1px solid ' + g.border + ';margin-right:7px;vertical-align:0"></span>' + frappe.utils.escape_html(label) + (status === 'unconfirmed' ? ' <span class="text-muted">(unconfirmed)</span>' : '') + '</td><td>' + (date ? frappe.datetime.str_to_user(date) : '') + '</td><td class="text-muted">' + frappe.utils.escape_html(note || '') + '</td></tr>';
  });
  html += '</tbody></table><div class="text-muted small" style="margin-top:6px">&#10003; proven by a document or logged update · ? a draft POD exists · &ndash; not needed on this job · &#9675; still pending</div>';
  wrapper.html(html);
}

function log_update_dialog(frm) {
  const rows = parse_state(frm);
  const pending = rows.filter(r => r[2] !== 'done' && r[2] !== 'na' && r[0] !== 'CLOSED');
  const options = [{ label: __('Just a note (no milestone)'), value: '' }]
    .concat(pending.map(r => ({ label: r[1], value: r[0] })))
    .concat([{ label: __('Put job on hold (issue)'), value: 'HOLD' }, { label: __('Lift hold / resume'), value: 'RESUME' }, { label: __('Close job'), value: 'CLOSED' }]);
  const d = new frappe.ui.Dialog({
    title: __('Log update - {0}', [frm.doc.client_reference_no || frm.doc.name]),
    fields: [
      { fieldname: 'milestone', label: __('This update proves'), fieldtype: 'Select', options: options, default: pending.length ? pending[0][0] : '' },
      { fieldname: 'track_date', label: __('Date'), fieldtype: 'Date', default: frappe.datetime.get_today(), reqd: 1 },
      { fieldname: 'note', label: __('What happened (customer will read this if visible)'), fieldtype: 'Small Text', reqd: 1 },
      { fieldname: 'evidence', label: __('Reference (BOE / DO / vehicle / document no.)'), fieldtype: 'Data' },
      { fieldname: 'cb', fieldtype: 'Column Break' },
      { fieldname: 'next_action', label: __('Next action'), fieldtype: 'Data' },
      { fieldname: 'follow_up', label: __('Next action due'), fieldtype: 'Date' },
      { fieldname: 'visible', label: __('Show on customer status sheet'), fieldtype: 'Check', default: 1 },
      { fieldname: 'internal', label: __('Internal note (never shown to customer)'), fieldtype: 'Small Text' },
    ],
    primary_action_label: __('Save update'),
    primary_action(values) {
      const is_issue = values.milestone === 'HOLD';
      frappe.call({
        method: 'fps_erpnext.api.trackers.log_update',
        args: {
          job_order: frm.doc.name, track_date: values.track_date,
          milestone: values.milestone || null, note: values.note,
          evidence: values.evidence || null, next_action: values.next_action || null,
          follow_up_date: values.follow_up || null,
          customer_visible: is_issue ? 0 : (values.visible ? 1 : 0),
          internal: values.internal || null,
        },
      }).then(() => { d.hide(); frappe.show_alert({ message: __('Update logged'), indicator: 'green' }); frm.reload_doc(); });
    },
  });
  d.show();
}

function fps_open_tracker(job_order) {
  // The tracker's name IS the job order number now, but look it up rather
  // than assuming -- a job whose tracker has not been opened yet must say so
  // instead of routing to a 404.
  frappe.db.get_value('Job Tracker', { job_order: job_order }, 'name').then(r => {
    const n = r && r.message && r.message.name;
    if (n) frappe.set_route('Form', 'Job Tracker', n);
    else frappe.msgprint(__('No tracker has been opened for this job yet.'));
  });
}
""",
	'Job Order - Create Buttons': """\
frappe.ui.form.on('Job Order', {
  refresh: function(frm) {
    if (frm.doc.docstatus === 0) {
      frm.add_custom_button(__('Save as Draft'), function() {
        frm.save().then(() => frappe.show_alert({message: __('Saved as draft - review then click Submit when ready'), indicator: 'blue'}, 6));
      });
    }
    if (frm.doc.__islocal || frm.doc.docstatus === 2) return;
    frm.add_custom_button(__('Customs Tracker'), function() { create_ct_from_jo(frm); }, __('Create'));
    // 'Job tracker note' removed: it created a SECOND Job Tracker document for
    // the job, which is exactly what the one-tracker-per-job change undoes. The
    // 'Log update' button on this same form is the way in.
    frm.add_custom_button(__('Proof of Delivery'), function() { create_pod_from_jo(frm); }, __('Create'));
    frm.add_custom_button(__('Sales Invoice'), function() { create_si_from_jo(frm); }, __('Create'));
    if (frm.doc.quotation_ref) {
      frm.add_custom_button(__('Source Quotation'), function() { frappe.set_route('Form', 'Quotation', frm.doc.quotation_ref); }, __('View'));
    }
    frm.add_custom_button(__('Linked POD'), function() { frappe.set_route('List', 'Proof of Delivery', {'job_order': frm.doc.name}); }, __('View'));
    frm.add_custom_button(__('Linked Customs Tracker'), function() { frappe.set_route('List', 'Customs Tracker', {'job_order': frm.doc.name}); }, __('View'));
    frm.add_custom_button(__('Job Tracker'), function() { fps_open_tracker(frm.doc.name); }, __('View'));
    frm.add_custom_button(__('Linked Invoices'), function() { frappe.set_route('List', 'Sales Invoice', {'fps_job_order': frm.doc.name}); }, __('View'));
  }
});
function create_doc_from_jo(frm, doctype, extra) {
  frappe.model.with_doctype(doctype, function() {
    const d = frappe.model.get_new_doc(doctype);
    d.job_order = frm.doc.name; d.customer = frm.doc.customer;
    if (extra) Object.keys(extra).forEach(k => d[k] = extra[k]);
    frappe.set_route('Form', doctype, d.name);
  });
}
function create_ct_from_jo(frm) {
  frappe.db.count('Customs Tracker', {filters: {job_order: frm.doc.name}}).then(n => {
    create_doc_from_jo(frm, 'Customs Tracker', {ct_date: frappe.datetime.get_today(), status: 'Pending', fps_leg: (n || 0) + 1, fps_clearance_location: frm.doc.fps_clearance_location, fps_clearance_type: (n || 0) === 0 ? frm.doc.fps_clearance_type : null});
  });
}
function create_pod_from_jo(frm) {
  frappe.db.count('Proof of Delivery', {filters: {job_order: frm.doc.name, docstatus: ['<', 2]}}).then(n => {
    frappe.model.with_doctype('Proof of Delivery', function() {
      const d = frappe.model.get_new_doc('Proof of Delivery');
      d.job_order = frm.doc.name; d.customer = frm.doc.customer;
      d.pod_date = frappe.datetime.get_today(); d.delivery_status = 'Pending';
      d.client_reference_no = frm.doc.client_reference_no;
      d.movement_type = frm.doc.movement_type; d.pol = frm.doc.pol; d.destination = frm.doc.pod;
      d.carrier = frm.doc.carrier; d.awb_bl_no = frm.doc.awb_bl_no; d.container_nos = frm.doc.container_nos;
      d.cargo_description = frm.doc.cargo_description; d.no_of_packages = frm.doc.no_of_packages;
      d.gross_weight = frm.doc.gross_weight; d.load = frm.doc.load;
      d.fps_leg = (n || 0) + 1; d.fps_final_delivery = 1; d.fps_vehicle_type = frm.doc.fps_vehicle_type;
      frappe.set_route('Form', 'Proof of Delivery', d.name);
    });
  });
}
function create_si_from_jo(frm) {
  frappe.model.with_doctype('Sales Invoice', function() {
    const d = frappe.model.get_new_doc('Sales Invoice');
    d.fps_job_order = frm.doc.name; d.customer = frm.doc.customer; d.customer_name = frm.doc.customer_name;
    d.posting_date = frappe.datetime.get_today(); d.due_date = frappe.datetime.add_days(frappe.datetime.get_today(), 30);
    d.fps_client_reference_no = frm.doc.client_reference_no;
    d.fps_movement_type = frm.doc.movement_type; d.fps_pol = frm.doc.pol; d.fps_pod = frm.doc.pod;
    d.fps_carrier = frm.doc.carrier; d.fps_awb_bl_no = frm.doc.awb_bl_no;
    d.fps_cargo_description = frm.doc.cargo_description; d.fps_no_of_packages = frm.doc.no_of_packages;
    d.fps_gross_weight = frm.doc.gross_weight; d.fps_load = frm.doc.load;
    if (frm.doc.ar_charges && frm.doc.ar_charges.length) {
      frm.doc.ar_charges.forEach(row => {
        const item = frappe.model.add_child(d, 'items');
        item.item_code = row.service_item; item.description = row.description;
        item.qty = row.qty || 1; item.rate = row.rate; item.amount = row.amount; item.uom = row.unit;
      });
    }
    frappe.set_route('Form', 'Sales Invoice', d.name);
  });
}
function fps_open_tracker(job_order) {
  // The tracker's name IS the job order number now, but look it up rather
  // than assuming -- a job whose tracker has not been opened yet must say so
  // instead of routing to a 404.
  frappe.db.get_value('Job Tracker', { job_order: job_order }, 'name').then(r => {
    const n = r && r.message && r.message.name;
    if (n) frappe.set_route('Form', 'Job Tracker', n);
    else frappe.msgprint(__('No tracker has been opened for this job yet.'));
  });
}
""",
}


def execute():
	_apply("Server Script", SERVER_SCRIPTS)
	_apply("Client Script", CLIENT_SCRIPTS)
	frappe.clear_cache()


def _apply(doctype, bodies):
	for name, script in bodies.items():
		if not frappe.db.exists(doctype, name):
			frappe.log_error(title="FPS: %s %s missing, not retargeted" % (doctype, name))
			continue
		current = frappe.db.get_value(doctype, name, "script") or ""
		if current == script:
			continue
		frappe.db.set_value(doctype, name, "script", script, update_modified=False)

