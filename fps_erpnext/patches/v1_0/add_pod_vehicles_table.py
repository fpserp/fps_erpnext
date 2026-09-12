"""Let one Proof of Delivery list several vehicles, for a delivery that
genuinely used more than one at once.

ADDITIVE, ON REQUEST (2026-09-12) -- confirmed with the user before writing
this. Proof of Delivery already has a way to handle multiple vehicles on one
job: create a separate POD per vehicle/leg (fps_leg, fps_final_delivery --
"Untick on interim trucks of a multi-trailer job"), and the rollup engine
already reads vehicle_no / fps_pickup_datetime per POD document across every
POD on a job. That pattern is for genuinely separate delivery events (its
own date, its own receiver, its own signature) and is completely untouched
here. This is for the simpler, different case: one delivery, several
vehicles, recorded together instead of forcing a full extra document per
truck.

New child doctype FPS POD Vehicle (fps_erpnext/fps/doctype/fps_pod_vehicle/)
carries exactly what was asked for: Vehicle No., Vehicle Type, Remarks -- one
row per vehicle. Nothing derives from these rows today (no controller logic,
no rollup reads them), so adding the table changes nothing about how a POD's
own single-vehicle fields or the existing multi-leg pattern behave.

Placed right after the existing single-vehicle fields in "Delivery
Information" (insert_after="proof_attachment"), ahead of "Remarks" -- reading
top to bottom: the one-vehicle fields most PODs still only need, then the
grid for the ones that need more than one, then remarks.

Safe to re-run: create_custom_field is a no-op when the field exists.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

DOCTYPE = "Proof of Delivery"
CHILD = "FPS POD Vehicle"

SECTION_FIELD = {
	"fieldname": "fps_vehicles_sec",
	"fieldtype": "Section Break",
	"label": "Vehicles",
	"insert_after": "proof_attachment",
	"description": ("Only needed when one delivery used more than one vehicle. For a "
	                "single truck, the Vehicle No. / Vehicle Type fields above are enough."),
}

TABLE_FIELD = {
	"fieldname": "fps_vehicles",
	"fieldtype": "Table",
	"label": "Vehicles",
	"options": CHILD,
	"insert_after": "fps_vehicles_sec",
}


def execute():
	if not (frappe.db.exists("DocType", DOCTYPE) and frappe.db.exists("DocType", CHILD)):
		return

	for spec in (SECTION_FIELD, TABLE_FIELD):
		fieldnames = [f.fieldname for f in frappe.get_meta(DOCTYPE).fields]
		if spec["fieldname"] in fieldnames:
			continue
		if spec["insert_after"] not in fieldnames:
			frappe.log_error(
				title="FPS: %s has no %s, %s not added"
				% (DOCTYPE, spec["insert_after"], spec["fieldname"])
			)
			continue
		try:
			create_custom_field(DOCTYPE, dict(spec), ignore_validate=True)
		except Exception:
			frappe.log_error(title="FPS: could not add %s" % spec["fieldname"])

	frappe.clear_cache(doctype=DOCTYPE)
