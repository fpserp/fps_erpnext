"""Anchor Port of Discharge on Origin/POL, and give Declarations its own section.

PORT OF DISCHARGE. The field was created anchored on the DESTINATION field and
landed nowhere near it -- 15 fields further down on Quotation, under Profit
Summary, and 14 further down on Sales Invoice, under Cargo Details. Two earlier
attempts to fix it by reasoning about Frappe's field sorter both failed:

  1st  set idx = anchor idx + 1 and shift the rest. The data came out exactly
       right -- fps_pod 32, fps_port_of_discharge 33, fps_carrier 34 -- and the
       merged meta still put the field at position 48. So idx is not what
       decides it.
  2nd  a local simulation of Meta.sort_fields() to predict the outcome. Its
       prediction disagreed with the live meta, so the model was wrong and any
       fix derived from it would have been a guess. It was thrown away.

What settled it was changing the anchor on the live site and re-reading the
merged meta: anchored on fps_pod the field sits at 48, anchored on fps_pol it
sits at 32 -- directly beneath Origin/POL, inside FPS Shipment Details. Measured
on all three affected doctypes, not inferred.

That is also exactly where it was asked to be, so this is not a workaround
around the symptom: Origin/POL and Port of Discharge belong together, and
Destination is the other column.

DECLARATIONS. The table was created anchored on boe_number and rendered inside a
COLUMN break, which sizes it to about a fifth of the page -- unusable for a grid
with five columns of its own. It now gets its own Section Break, which is
full width.

Both changes were applied to the live site the moment they were verified. This
patch exists so any other copy of the site reaches the same place, and is a
no-op where it is already correct.

Safe to re-run.
"""

import frappe

# doctype -> {fieldname: the field it should follow}
PLACEMENTS = {
	"Quotation": {"fps_port_of_discharge": "fps_pol"},
	"Sales Invoice": {"fps_port_of_discharge": "fps_pol"},
	"Proof of Delivery": {"port_of_discharge": "pol"},
	"Job Order": {"port_of_discharge": "pol"},
	"FPS Enquiry": {"port_of_discharge": "origin"},
	"Customs Tracker": {
		"fps_declarations_sec": "boe_number",
		"fps_declarations": "fps_declarations_sec",
	},
}

SECTION = {
	"dt": "Customs Tracker",
	"fieldname": "fps_declarations_sec",
	"fieldtype": "Section Break",
	"label": "Declarations",
	"insert_after": "boe_number",
	"description": "One row per BOE. A job that clears on two declarations has two rows.",
}


def execute():
	_ensure_declarations_section()

	changed = 0
	for doctype, wanted in PLACEMENTS.items():
		for fieldname, anchor in wanted.items():
			name = frappe.db.get_value(
				"Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
			)
			if not name:
				continue
			if not _has_field(doctype, anchor):
				frappe.log_error(
					title="FPS: %s has no %s, %s not moved" % (doctype, anchor, fieldname)
				)
				continue
			if frappe.db.get_value("Custom Field", name, "insert_after") == anchor:
				continue
			frappe.db.set_value("Custom Field", name, "insert_after", anchor)
			changed += 1

	if changed:
		frappe.db.commit()
	frappe.clear_cache()
	frappe.logger().info("FPS: repositioned %d custom fields" % changed)


def _has_field(doctype, fieldname):
	if not frappe.db.exists("DocType", doctype):
		return False
	return any(f.fieldname == fieldname for f in frappe.get_meta(doctype).fields)


def _ensure_declarations_section():
	"""The section the Declarations table lives in, if it is not there yet."""
	if not frappe.db.exists("DocType", SECTION["dt"]):
		return
	if frappe.db.exists("Custom Field",
	                    {"dt": SECTION["dt"], "fieldname": SECTION["fieldname"]}):
		return
	if not _has_field(SECTION["dt"], SECTION["insert_after"]):
		frappe.log_error(title="FPS: cannot add the Declarations section")
		return
	try:
		frappe.get_doc(dict(SECTION, doctype="Custom Field")).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=SECTION["dt"])
	except Exception:
		frappe.log_error(title="FPS: could not add the Declarations section")
