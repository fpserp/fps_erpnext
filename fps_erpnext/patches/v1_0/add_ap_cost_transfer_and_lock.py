"""AP cost automation: copy at invoice creation, final transfer + lock at
invoice submission.

On request (2026-09-12), with the trigger deliberately narrowed to
SUBMISSION, not creation or save -- a draft invoice can still change, so
locking the Job Order's own costs against it would be premature.

COPY AT CREATION (Job Order - Create Buttons, create_si_from_jo): if AP
Charges already exist on the Job Order at the moment "Create > Sales
Invoice" is clicked, they are copied onto the new draft's OWN AP Charges
field, fps_ap_charges -- which already existed on Sales Invoice under
"Direct AP Charges (Manual Entry)", feeding the also-already-existing (if
until now unpopulated by anything but hand entry) Total Purchases / Gross
Profit / GP% summary further down the form. Both Job Order.ap_charges and
Sales Invoice.fps_ap_charges use the exact same child doctype, FPS AP
Charge, so the copy is a straight field-for-field row copy, the same way
Job Order.ar_charges already becomes the invoice's own `items`.

FINAL TRANSFER + LOCK AT SUBMISSION (SI Events (Submit) / SI Events
(Cancel), the existing shared body for Sales Invoice After Submit / After
Cancel): on submit, the invoice's fps_ap_charges is replaced -- not merged
-- with a fresh copy of the Job Order's ap_charges as they stand at that
exact moment, so anything added to the Job Order after the draft was first
opened is still caught. Immediately after, Job Order.fps_ap_locked is set,
which the Job Order's own new Before Save script (JO AP Charges Lock) and a
new read_only_depends_on Property Setter on ap_charges together enforce:
the grid renders read-only on the form, and any attempt to save a change to
it anyway is rejected server-side. The field stays visible -- this is a
lock, not a hide -- because the point is exactly that this data must now be
inspectable but not editable, not that it should disappear once it no
longer needs revisiting; the AR/Summary sections earlier this project were
hidden because they are unused, which is not true of AP costs at all.

On cancel, the lock lifts UNLESS another still-submitted, non-payment-request
invoice on the same job holds it -- the plain case is exactly one invoice per
job, but a job invoiced more than once should not fall back open just
because ONE of its invoices got cancelled while another stays submitted.

Payment requests (Sales Invoice with fps_is_payment_request=1) never trigger
any of this -- an advance payment ask is not "the invoice" this was scoped
to, and locking real costs against a mere request would be premature.

Everything here was applied directly to the live site the moment it was
written and confirmed by re-reading every piece back afterward: the new
Custom Field, the new Property Setter, the new Server Script, and the
extended body on both existing SI Events scripts and the Job Order client
script all landed exactly as intended. This patch is so any other copy of
the site reaches the same place.

Safe to re-run: every piece is a no-op once already in place, and the two
script-body updates simply overwrite with the same text if run again.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

SI_EVENTS_BODY = '# SI Events - Sales Invoice After Submit / After Cancel (same body). No amounts are ever written to the tracker.\ntry:\n    jo = doc.fps_job_order\n    if jo:\n        def emit(code, ref, text, visible=0, jo=jo, doc=doc):\n            # See CT BOE to Job Order for why this is a standalone insert, not a\n            # Job Order save.\n            if frappe.db.exists("FPS Job Update", {"parenttype": "Job Order", "parent": jo, "evidence_ref": ref}):\n                return\n            n = frappe.db.count("FPS Job Update", {"parenttype": "Job Order", "parent": jo})\n            frappe.get_doc({\n                "doctype": "FPS Job Update", "parenttype": "Job Order", "parent": jo,\n                "parentfield": "fps_updates", "idx": n + 1,\n                "update_date": doc.posting_date or frappe.utils.today(), "event_type": "System", "milestone": code,\n                "status_line": text[:140], "notes": text, "evidence_ref": ref,\n                "source": "System", "customer_visible": visible, "leg": 1,\n                "responsible": frappe.session.user,\n            }).insert(ignore_permissions=True)\n        if doc.docstatus == 2:\n            emit(None, "SI:%s:cancel" % doc.name, "Invoice %s cancelled" % doc.name)\n        elif doc.fps_is_payment_request:\n            emit(None, "SI:%s:pr" % doc.name, "Payment request %s raised" % doc.name)\n        else:\n            emit("INVOICED", "SI:%s:submit" % doc.name, "Invoice %s issued" % doc.name)\n\n        # AP cost transfer + lock (2026-09-12). Real invoices only, never a\n        # payment request -- that is not the "invoice submission" this was\n        # scoped to. On submit: replace this invoice\'s own AP Charges with a\n        # fresh, final copy of the Job Order\'s, catching anything added to the\n        # Job Order after the draft was first created, then lock the Job\n        # Order\'s AP Charges against further input. On cancel: lift the lock,\n        # unless another submitted invoice on the same job still holds it.\n        if not doc.fps_is_payment_request:\n            if doc.docstatus == 1:\n                jo_doc = frappe.get_doc("Job Order", jo)\n                rows = jo_doc.get("ap_charges") or []\n                for name in frappe.get_all("FPS AP Charge",\n                        filters={"parenttype": "Sales Invoice", "parent": doc.name, "parentfield": "fps_ap_charges"},\n                        pluck="name"):\n                    frappe.delete_doc("FPS AP Charge", name, ignore_permissions=True, force=True)\n                for i, row in enumerate(rows, start=1):\n                    frappe.get_doc({\n                        "doctype": "FPS AP Charge", "parenttype": "Sales Invoice", "parent": doc.name,\n                        "parentfield": "fps_ap_charges", "idx": i,\n                        "service_item": row.service_item, "description": row.description,\n                        "supplier": row.supplier, "unit": row.unit, "qty": row.qty, "rate": row.rate,\n                        "amount": row.amount, "currency": row.currency, "tax_group": row.tax_group,\n                        "taxable_amount": row.taxable_amount, "tax_amount": row.tax_amount,\n                        "supplier_invoice": row.supplier_invoice, "reconciliation_no": row.reconciliation_no,\n                        "reference_number": row.reference_number, "remarks": row.remarks,\n                    }).insert(ignore_permissions=True)\n                frappe.db.set_value("Job Order", jo, "fps_ap_locked", 1, update_modified=False)\n            elif doc.docstatus == 2:\n                still_submitted = frappe.db.exists("Sales Invoice", {\n                    "fps_job_order": jo, "docstatus": 1, "fps_is_payment_request": 0,\n                    "name": ["!=", doc.name],\n                })\n                if not still_submitted:\n                    frappe.db.set_value("Job Order", jo, "fps_ap_locked", 0, update_modified=False)\nexcept Exception:\n    frappe.log_error(title="SI Events")\n'

JO_LOCK_SCRIPT_BODY = '# JO AP Charges Lock - Job Order Before Save. Rejects further changes to AP\n# Charges once fps_ap_locked is set (2026-09-12, by SI Events at invoice\n# submission) -- costs already transferred to a submitted invoice should not\n# silently change afterward.\nif doc.fps_ap_locked and doc.has_value_changed("ap_charges"):\n    frappe.throw(frappe._(\n        "Costs are locked for this job: they were transferred to a submitted "\n        "invoice. Cancel that invoice first if these figures need to change."\n    ))\n'

CLIENT_SCRIPT_BODY = "frappe.ui.form.on('Job Order', {\n  refresh: function(frm) {\n    if (frm.doc.docstatus === 0) {\n      frm.add_custom_button(__('Save as Draft'), function() {\n        frm.save().then(() => frappe.show_alert({message: __('Saved as draft - review then click Submit when ready'), indicator: 'blue'}, 6));\n      });\n    }\n    if (frm.doc.__islocal || frm.doc.docstatus === 2) return;\n    frm.add_custom_button(__('Customs Tracker'), function() { create_ct_from_jo(frm); }, __('Create'));\n    // 'Job tracker note' removed: it created a SECOND Job Tracker document for\n    // the job, which is exactly what the one-tracker-per-job change undoes. The\n    // 'Log update' button on this same form is the way in.\n    frm.add_custom_button(__('Proof of Delivery'), function() { create_pod_from_jo(frm); }, __('Create'));\n    frm.add_custom_button(__('Sales Invoice'), function() { create_si_from_jo(frm); }, __('Create'));\n    if (frm.doc.quotation_ref) {\n      frm.add_custom_button(__('Source Quotation'), function() { frappe.set_route('Form', 'Quotation', frm.doc.quotation_ref); }, __('View'));\n    }\n    frm.add_custom_button(__('Linked POD'), function() { frappe.set_route('List', 'Proof of Delivery', {'job_order': frm.doc.name}); }, __('View'));\n    frm.add_custom_button(__('Linked Customs Tracker'), function() { frappe.set_route('List', 'Customs Tracker', {'job_order': frm.doc.name}); }, __('View'));\n    // 'Job Tracker' view button removed: there is no separate tracker to\n    // open any more -- its update log lives directly on this form's own\n    // Updates grid, below the checklist.\n    frm.add_custom_button(__('Linked Invoices'), function() { frappe.set_route('List', 'Sales Invoice', {'fps_job_order': frm.doc.name}); }, __('View'));\n  }\n});\nfunction create_doc_from_jo(frm, doctype, extra) {\n  frappe.model.with_doctype(doctype, function() {\n    const d = frappe.model.get_new_doc(doctype);\n    d.job_order = frm.doc.name; d.customer = frm.doc.customer;\n    if (extra) Object.keys(extra).forEach(k => d[k] = extra[k]);\n    frappe.set_route('Form', doctype, d.name);\n  });\n}\nfunction create_ct_from_jo(frm) {\n  // ONE Customs Tracker per job. A second BOE is a row inside it, not a second\n  // document -- so this opens the existing tracker rather than making another.\n  frappe.db.get_value('Customs Tracker', { job_order: frm.doc.name }, 'name').then(r => {\n    const existing = r && r.message && r.message.name;\n    if (existing) {\n      frappe.set_route('Form', 'Customs Tracker', existing);\n      frappe.show_alert({ message: __('Add the next BOE as a row under Declarations.'), indicator: 'blue' }, 7);\n      return;\n    }\n    create_doc_from_jo(frm, 'Customs Tracker', {ct_date: frappe.datetime.get_today(), status: 'Pending', fps_leg: 1, fps_clearance_location: frm.doc.fps_clearance_location, fps_clearance_type: frm.doc.fps_clearance_type});\n  });\n}\nfunction create_pod_from_jo(frm) {\n  frappe.db.count('Proof of Delivery', {filters: {job_order: frm.doc.name, docstatus: ['<', 2]}}).then(n => {\n    frappe.model.with_doctype('Proof of Delivery', function() {\n      const d = frappe.model.get_new_doc('Proof of Delivery');\n      d.job_order = frm.doc.name; d.customer = frm.doc.customer;\n      d.pod_date = frappe.datetime.get_today(); d.delivery_status = 'Pending';\n      d.client_reference_no = frm.doc.client_reference_no;\n      d.movement_type = frm.doc.movement_type; d.pol = frm.doc.pol; d.destination = frm.doc.pod;\n      d.carrier = frm.doc.carrier; d.awb_bl_no = frm.doc.awb_bl_no; d.container_nos = frm.doc.container_nos;\n      d.cargo_description = frm.doc.cargo_description; d.no_of_packages = frm.doc.no_of_packages;\n      d.gross_weight = frm.doc.gross_weight; d.load = frm.doc.load;\n      d.fps_leg = (n || 0) + 1; d.fps_final_delivery = 1; d.fps_vehicle_type = frm.doc.fps_vehicle_type;\n      frappe.set_route('Form', 'Proof of Delivery', d.name);\n    });\n  });\n}\nfunction create_si_from_jo(frm) {\n  frappe.model.with_doctype('Sales Invoice', function() {\n    const d = frappe.model.get_new_doc('Sales Invoice');\n    d.fps_job_order = frm.doc.name; d.customer = frm.doc.customer; d.customer_name = frm.doc.customer_name;\n    d.posting_date = frappe.datetime.get_today(); d.due_date = frappe.datetime.add_days(frappe.datetime.get_today(), 30);\n    d.fps_client_reference_no = frm.doc.client_reference_no;\n    d.fps_movement_type = frm.doc.movement_type; d.fps_pol = frm.doc.pol; d.fps_pod = frm.doc.pod;\n    d.fps_carrier = frm.doc.carrier; d.fps_awb_bl_no = frm.doc.awb_bl_no;\n    d.fps_cargo_description = frm.doc.cargo_description; d.fps_no_of_packages = frm.doc.no_of_packages;\n    d.fps_gross_weight = frm.doc.gross_weight; d.fps_load = frm.doc.load;\n    if (frm.doc.ar_charges && frm.doc.ar_charges.length) {\n      frm.doc.ar_charges.forEach(row => {\n        const item = frappe.model.add_child(d, 'items');\n        item.item_code = row.service_item; item.description = row.description;\n        item.qty = row.qty || 1; item.rate = row.rate; item.amount = row.amount; item.uom = row.unit;\n      });\n    }\n    // AP cost, copied over at creation time if already entered on the Job\n    // Order (2026-09-12) -- a one-time copy, same as ar_charges above. SI\n    // Events does a final, authoritative re-copy at submission to catch\n    // anything added to the Job Order after this draft was created, then\n    // locks the Job Order's own AP Charges -- see that script.\n    if (frm.doc.ap_charges && frm.doc.ap_charges.length) {\n      frm.doc.ap_charges.forEach(row => {\n        const c = frappe.model.add_child(d, 'fps_ap_charges');\n        c.service_item = row.service_item; c.description = row.description;\n        c.supplier = row.supplier; c.unit = row.unit; c.qty = row.qty; c.rate = row.rate;\n        c.amount = row.amount; c.currency = row.currency; c.tax_group = row.tax_group;\n        c.taxable_amount = row.taxable_amount; c.tax_amount = row.tax_amount;\n        c.supplier_invoice = row.supplier_invoice; c.reconciliation_no = row.reconciliation_no;\n        c.reference_number = row.reference_number; c.remarks = row.remarks;\n      });\n    }\n    frappe.set_route('Form', 'Sales Invoice', d.name);\n  });\n}\n"


def execute():
	_add_lock_field()
	_add_lock_property_setter()
	_add_lock_server_script()
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


def _extend_si_events():
	for name in ("SI Events (Submit)", "SI Events (Cancel)"):
		if not frappe.db.exists("Server Script", name):
			frappe.log_error(title="FPS: Server Script %s missing, AP transfer not added" % name)
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
