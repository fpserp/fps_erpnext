"""AP cost automation: copy at invoice creation (convenience), then a hard
Before Submit check + lock at invoice submission (enforcement).

On request (2026-09-12), corrected the same day from an earlier version of
this patch that does NOT ship: that version silently replaced the invoice's
own AP Charges with a fresh copy from the Job Order at submit time. On
review this was rejected -- a mismatch between what is on the invoice and
what is on the Job Order should stop the submission and be seen by whoever
is invoicing, not be quietly overwritten out from under them.

COPY AT CREATION (Job Order - Create Buttons, create_si_from_jo) is
unchanged from the rejected version and still ships: if AP Charges already
exist on the Job Order when "Create > Sales Invoice" is clicked, they are
copied onto the new draft's own AP Charges (fps_ap_charges -- already
existed on Sales Invoice under "Direct AP Charges (Manual Entry)", the same
child doctype, FPS AP Charge, as Job Order.ap_charges). This is pure
convenience, saving retyping; it is not what enforces anything.

THE ENFORCEMENT IS A NEW Before Submit SERVER SCRIPT, SI AP Cost Check.
Every AP cost on the Job Order must be accounted for -- by total amount, not
matched row by row -- somewhere across the invoice being submitted AND any
other already-submitted, non-payment-request invoice on the same job.
Entering MORE cost on the invoice than the Job Order has is fine (extra is
never an error, only a shortfall is). A Job Order with no AP cost at all
raises no issue either way, for either invoice count. If the total falls
short, frappe.throw blocks the submission outright with the shortfall
spelled out in AED, naming the Job Order.

The shared SI Events (Submit) / SI Events (Cancel) body no longer touches
fps_ap_charges at all -- by the time it runs (After Submit), the Before
Submit check has already passed, so all that is left to do is set (or, on
cancel, potentially lift) Job Order.fps_ap_locked, enforced by the
already-existing read_only_depends_on Property Setter and the JO AP Charges
Lock Before Save script (both unchanged from the rejected version, and
still exactly right: "visible for reference, but no further edits" was
confirmed correct on review, only the invoice-side replacement was not).

Payment requests never trigger any of this -- an advance payment ask is not
"the invoice" this was scoped to.

KNOWN CONSEQUENCE, FLAGGED NOT SILENTLY FIXED: the lock is unconditional on
any real invoice submission, exactly as asked for, including when the Job
Order had zero AP cost at that moment -- so if a supplier invoice for this
job only arrives after the customer has already been invoiced (routine in
freight forwarding), there is no way to record it on the Job Order
afterward. Raised to the user as a known tradeoff of the explicit
instruction, not changed unilaterally.

Everything here was applied directly to the live site the moment it was
written, then verified by re-reading every piece back afterward. This patch
is so any other copy of the site reaches the same place.

Safe to re-run: every piece is a no-op once already in place, and the
script-body updates simply overwrite with the same text if run again.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

SI_EVENTS_BODY = '# SI Events - Sales Invoice After Submit / After Cancel (same body). No amounts are ever written to the tracker.\ntry:\n    jo = doc.fps_job_order\n    if jo:\n        def emit(code, ref, text, visible=0, jo=jo, doc=doc):\n            # See CT BOE to Job Order for why this is a standalone insert, not a\n            # Job Order save.\n            if frappe.db.exists("FPS Job Update", {"parenttype": "Job Order", "parent": jo, "evidence_ref": ref}):\n                return\n            n = frappe.db.count("FPS Job Update", {"parenttype": "Job Order", "parent": jo})\n            frappe.get_doc({\n                "doctype": "FPS Job Update", "parenttype": "Job Order", "parent": jo,\n                "parentfield": "fps_updates", "idx": n + 1,\n                "update_date": doc.posting_date or frappe.utils.today(), "event_type": "System", "milestone": code,\n                "status_line": text[:140], "notes": text, "evidence_ref": ref,\n                "source": "System", "customer_visible": visible, "leg": 1,\n                "responsible": frappe.session.user,\n            }).insert(ignore_permissions=True)\n        if doc.docstatus == 2:\n            emit(None, "SI:%s:cancel" % doc.name, "Invoice %s cancelled" % doc.name)\n        elif doc.fps_is_payment_request:\n            emit(None, "SI:%s:pr" % doc.name, "Payment request %s raised" % doc.name)\n        else:\n            emit("INVOICED", "SI:%s:submit" % doc.name, "Invoice %s issued" % doc.name)\n\n        # AP cost lock (2026-09-12). Real invoices only, never a payment\n        # request. Coverage itself is checked earlier, in "SI AP Cost Check"\n        # (Before Submit) -- an invoice only reaches here, After Submit, once\n        # that check has already passed, so this just sets (or, on cancel,\n        # potentially lifts) the lock. Nothing here ever copies or overwrites\n        # the invoice\'s own AP Charges -- a mismatch is something the person\n        # submitting sees and fixes themselves, not something silently patched\n        # over.\n        if not doc.fps_is_payment_request:\n            if doc.docstatus == 1:\n                frappe.db.set_value("Job Order", jo, "fps_ap_locked", 1, update_modified=False)\n            elif doc.docstatus == 2:\n                still_submitted = frappe.db.exists("Sales Invoice", {\n                    "fps_job_order": jo, "docstatus": 1, "fps_is_payment_request": 0,\n                    "name": ["!=", doc.name],\n                })\n                if not still_submitted:\n                    frappe.db.set_value("Job Order", jo, "fps_ap_locked", 0, update_modified=False)\nexcept Exception:\n    frappe.log_error(title="SI Events")\n'

JO_LOCK_SCRIPT_BODY = '# JO AP Charges Lock - Job Order Before Save. Rejects further changes to AP\n# Charges once fps_ap_locked is set (2026-09-12, by SI Events at invoice\n# submission) -- costs already transferred to a submitted invoice should not\n# silently change afterward.\nif doc.fps_ap_locked and doc.has_value_changed("ap_charges"):\n    frappe.throw(frappe._(\n        "Costs are locked for this job: they were transferred to a submitted "\n        "invoice. Cancel that invoice first if these figures need to change."\n    ))\n'

AP_COST_CHECK_BODY = '# SI AP Cost Check - Sales Invoice Before Submit (2026-09-12). Every AP cost\n# on the Job Order must be accounted for somewhere across this invoice and\n# any other already-submitted, non-payment-request invoice on the same job\n# before this one may submit. Entering MORE cost on the invoice than the Job\n# Order has is fine; a Job Order with no AP cost at all raises no issue\n# either way -- only a shortfall blocks the submit. This is a check, not a\n# copy: a mismatch is something the person submitting sees and fixes\n# themselves, never something silently patched over.\ntry:\n    jo = doc.fps_job_order\n    if jo and not doc.fps_is_payment_request:\n        def ap_total(parenttype, parent):\n            rows = frappe.get_all("FPS AP Charge",\n                filters={"parenttype": parenttype, "parent": parent}, fields=["amount"])\n            return sum(frappe.utils.flt(r.amount) for r in rows)\n\n        jo_total = ap_total("Job Order", jo)\n        if jo_total > 0:\n            covered = ap_total("Sales Invoice", doc.name)\n            other_invoices = frappe.get_all("Sales Invoice", filters={\n                "fps_job_order": jo, "docstatus": 1, "fps_is_payment_request": 0,\n                "name": ["!=", doc.name],\n            }, pluck="name")\n            for other in other_invoices:\n                covered += ap_total("Sales Invoice", other)\n            if covered + 0.01 < jo_total:\n                frappe.throw(frappe._(\n                    "This invoice cannot be submitted: its AP cost does not match the "\n                    "Job Order\'s AP cost. Job Order {0} has AED {1} in AP Charges, but "\n                    "only AED {2} is covered across this invoice and any other submitted "\n                    "invoice for this job. Add the missing amount to this invoice\'s AP "\n                    "Charges, or to another invoice for the same job, then try again."\n                ).format(jo, jo_total, covered))\nexcept frappe.ValidationError:\n    raise\nexcept Exception:\n    frappe.log_error(title="SI AP Cost Check")\n'

CLIENT_SCRIPT_BODY = "frappe.ui.form.on('Job Order', {\n  refresh: function(frm) {\n    if (frm.doc.docstatus === 0) {\n      frm.add_custom_button(__('Save as Draft'), function() {\n        frm.save().then(() => frappe.show_alert({message: __('Saved as draft - review then click Submit when ready'), indicator: 'blue'}, 6));\n      });\n    }\n    if (frm.doc.__islocal || frm.doc.docstatus === 2) return;\n    frm.add_custom_button(__('Customs Tracker'), function() { create_ct_from_jo(frm); }, __('Create'));\n    // 'Job tracker note' removed: it created a SECOND Job Tracker document for\n    // the job, which is exactly what the one-tracker-per-job change undoes. The\n    // 'Log update' button on this same form is the way in.\n    frm.add_custom_button(__('Proof of Delivery'), function() { create_pod_from_jo(frm); }, __('Create'));\n    frm.add_custom_button(__('Sales Invoice'), function() { create_si_from_jo(frm); }, __('Create'));\n    if (frm.doc.quotation_ref) {\n      frm.add_custom_button(__('Source Quotation'), function() { frappe.set_route('Form', 'Quotation', frm.doc.quotation_ref); }, __('View'));\n    }\n    frm.add_custom_button(__('Linked POD'), function() { frappe.set_route('List', 'Proof of Delivery', {'job_order': frm.doc.name}); }, __('View'));\n    frm.add_custom_button(__('Linked Customs Tracker'), function() { frappe.set_route('List', 'Customs Tracker', {'job_order': frm.doc.name}); }, __('View'));\n    // 'Job Tracker' view button removed: there is no separate tracker to\n    // open any more -- its update log lives directly on this form's own\n    // Updates grid, below the checklist.\n    frm.add_custom_button(__('Linked Invoices'), function() { frappe.set_route('List', 'Sales Invoice', {'fps_job_order': frm.doc.name}); }, __('View'));\n  }\n});\nfunction create_doc_from_jo(frm, doctype, extra) {\n  frappe.model.with_doctype(doctype, function() {\n    const d = frappe.model.get_new_doc(doctype);\n    d.job_order = frm.doc.name; d.customer = frm.doc.customer;\n    if (extra) Object.keys(extra).forEach(k => d[k] = extra[k]);\n    frappe.set_route('Form', doctype, d.name);\n  });\n}\nfunction create_ct_from_jo(frm) {\n  // ONE Customs Tracker per job. A second BOE is a row inside it, not a second\n  // document -- so this opens the existing tracker rather than making another.\n  frappe.db.get_value('Customs Tracker', { job_order: frm.doc.name }, 'name').then(r => {\n    const existing = r && r.message && r.message.name;\n    if (existing) {\n      frappe.set_route('Form', 'Customs Tracker', existing);\n      frappe.show_alert({ message: __('Add the next BOE as a row under Declarations.'), indicator: 'blue' }, 7);\n      return;\n    }\n    create_doc_from_jo(frm, 'Customs Tracker', {ct_date: frappe.datetime.get_today(), status: 'Pending', fps_leg: 1, fps_clearance_location: frm.doc.fps_clearance_location, fps_clearance_type: frm.doc.fps_clearance_type});\n  });\n}\nfunction create_pod_from_jo(frm) {\n  frappe.db.count('Proof of Delivery', {filters: {job_order: frm.doc.name, docstatus: ['<', 2]}}).then(n => {\n    frappe.model.with_doctype('Proof of Delivery', function() {\n      const d = frappe.model.get_new_doc('Proof of Delivery');\n      d.job_order = frm.doc.name; d.customer = frm.doc.customer;\n      d.pod_date = frappe.datetime.get_today(); d.delivery_status = 'Pending';\n      d.client_reference_no = frm.doc.client_reference_no;\n      d.movement_type = frm.doc.movement_type; d.pol = frm.doc.pol; d.destination = frm.doc.pod;\n      d.carrier = frm.doc.carrier; d.awb_bl_no = frm.doc.awb_bl_no; d.container_nos = frm.doc.container_nos;\n      d.cargo_description = frm.doc.cargo_description; d.no_of_packages = frm.doc.no_of_packages;\n      d.gross_weight = frm.doc.gross_weight; d.load = frm.doc.load;\n      d.fps_leg = (n || 0) + 1; d.fps_final_delivery = 1; d.fps_vehicle_type = frm.doc.fps_vehicle_type;\n      frappe.set_route('Form', 'Proof of Delivery', d.name);\n    });\n  });\n}\nfunction create_si_from_jo(frm) {\n  frappe.model.with_doctype('Sales Invoice', function() {\n    const d = frappe.model.get_new_doc('Sales Invoice');\n    d.fps_job_order = frm.doc.name; d.customer = frm.doc.customer; d.customer_name = frm.doc.customer_name;\n    d.posting_date = frappe.datetime.get_today(); d.due_date = frappe.datetime.add_days(frappe.datetime.get_today(), 30);\n    d.fps_client_reference_no = frm.doc.client_reference_no;\n    d.fps_movement_type = frm.doc.movement_type; d.fps_pol = frm.doc.pol; d.fps_pod = frm.doc.pod;\n    d.fps_carrier = frm.doc.carrier; d.fps_awb_bl_no = frm.doc.awb_bl_no;\n    d.fps_cargo_description = frm.doc.cargo_description; d.fps_no_of_packages = frm.doc.no_of_packages;\n    d.fps_gross_weight = frm.doc.gross_weight; d.fps_load = frm.doc.load;\n    if (frm.doc.ar_charges && frm.doc.ar_charges.length) {\n      frm.doc.ar_charges.forEach(row => {\n        const item = frappe.model.add_child(d, 'items');\n        item.item_code = row.service_item; item.description = row.description;\n        item.qty = row.qty || 1; item.rate = row.rate; item.amount = row.amount; item.uom = row.unit;\n      });\n    }\n    // AP cost, copied over at creation time if already entered on the Job\n    // Order (2026-09-12) -- a one-time copy, same as ar_charges above. This\n    // is convenience only, not enforcement -- see SI AP Cost Check for the\n    // Before Submit validation that actually matters.\n    if (frm.doc.ap_charges && frm.doc.ap_charges.length) {\n      frm.doc.ap_charges.forEach(row => {\n        const c = frappe.model.add_child(d, 'fps_ap_charges');\n        c.service_item = row.service_item; c.description = row.description;\n        c.supplier = row.supplier; c.unit = row.unit; c.qty = row.qty; c.rate = row.rate;\n        c.amount = row.amount; c.currency = row.currency; c.tax_group = row.tax_group;\n        c.taxable_amount = row.taxable_amount; c.tax_amount = row.tax_amount;\n        c.supplier_invoice = row.supplier_invoice; c.reconciliation_no = row.reconciliation_no;\n        c.reference_number = row.reference_number; c.remarks = row.remarks;\n      });\n    }\n    frappe.set_route('Form', 'Sales Invoice', d.name);\n  });\n}\n"


def execute():
	_add_lock_field()
	_add_lock_property_setter()
	_add_lock_server_script()
	_add_ap_cost_check_script()
	_extend_si_events()
	_extend_client_script()


def _add_lock_field():
	if not frappe.db.exists("DocType", "Job Order"):
		return
	if frappe.db.exists("Custom Field", {"dt": "Job Order", "fieldname": "fps_ap_locked"}):
		return
	fieldnames = [f.fieldname for f in frappe.get_meta("Job Order").fields]
	if "ap_charges" not in fieldnames:
		frappe.log_error(title="FPS: Job Order has no ap_charges, fps_ap_locked not added")
		return
	create_custom_field("Job Order", {
		"fieldname": "fps_ap_locked",
		"label": "AP Costs Locked",
		"fieldtype": "Check",
		"hidden": 1,
		"default": "0",
		"insert_after": "ap_charges",
		"description": ("Set automatically once a submitted invoice has taken a copy of "
		                "these costs. Not meant to be ticked by hand."),
	}, ignore_validate=True)


def _add_lock_property_setter():
	name = "Job Order-ap_charges-read_only_depends_on"
	if frappe.db.exists("Property Setter", name):
		return
	if not frappe.db.exists("DocType", "Job Order"):
		return
	frappe.get_doc({
		"doctype": "Property Setter",
		"name": name,
		"doc_type": "Job Order",
		"doctype_or_field": "DocField",
		"field_name": "ap_charges",
		"module": "FPS",
		"property": "read_only_depends_on",
		"property_type": "Small Text",
		"value": "eval:doc.fps_ap_locked",
	}).insert(ignore_permissions=True)


def _add_lock_server_script():
	name = "JO AP Charges Lock"
	if frappe.db.exists("Server Script", name):
		current = frappe.db.get_value("Server Script", name, "script") or ""
		if current != JO_LOCK_SCRIPT_BODY:
			frappe.db.set_value("Server Script", name, "script", JO_LOCK_SCRIPT_BODY, update_modified=False)
		return
	frappe.get_doc({
		"doctype": "Server Script",
		"name": name,
		"script_type": "DocType Event",
		"reference_doctype": "Job Order",
		"doctype_event": "Before Save",
		"disabled": 0,
		"script": JO_LOCK_SCRIPT_BODY,
	}).insert(ignore_permissions=True)


def _add_ap_cost_check_script():
	name = "SI AP Cost Check"
	if frappe.db.exists("Server Script", name):
		current = frappe.db.get_value("Server Script", name, "script") or ""
		if current != AP_COST_CHECK_BODY:
			frappe.db.set_value("Server Script", name, "script", AP_COST_CHECK_BODY, update_modified=False)
		return
	frappe.get_doc({
		"doctype": "Server Script",
		"name": name,
		"script_type": "DocType Event",
		"reference_doctype": "Sales Invoice",
		"doctype_event": "Before Submit",
		"disabled": 0,
		"script": AP_COST_CHECK_BODY,
	}).insert(ignore_permissions=True)


def _extend_si_events():
	for name in ("SI Events (Submit)", "SI Events (Cancel)"):
		if not frappe.db.exists("Server Script", name):
			frappe.log_error(title="FPS: Server Script %s missing, AP lock not added" % name)
			continue
		current = frappe.db.get_value("Server Script", name, "script") or ""
		if current == SI_EVENTS_BODY:
			continue
		frappe.db.set_value("Server Script", name, "script", SI_EVENTS_BODY, update_modified=False)


def _extend_client_script():
	name = "Job Order - Create Buttons"
	if not frappe.db.exists("Client Script", name):
		frappe.log_error(title="FPS: Client Script %s missing, AP copy-at-creation not added" % name)
		return
	current = frappe.db.get_value("Client Script", name, "script") or ""
	if current == CLIENT_SCRIPT_BODY:
		return
	frappe.db.set_value("Client Script", name, "script", CLIENT_SCRIPT_BODY, update_modified=False)
