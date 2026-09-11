"""Give Job Order its own update log -- the one thing Job Tracker had that it did not.

Every field on Job Tracker OTHER than `fps_updates` was checked against the live
merged meta before this was written, and every one of them is a fetch_from
mirror of a field already on Job Order under its own name (movement_type,
client_reference_no, awb_bl_no, eta, origin_pol, and so on). The single genuine
difference is the update log: a child table of dated entries (FPS Job Update)
that the derivation engine reads to work out the stage, the checklist and
"what's next". That is what moves here.

REUSES THE EXISTING CHILD DOCTYPE. FPS Job Update is not new and is not
changed -- it already lived on Job Tracker, and a child doctype has no
inherent single-parent constraint; `parenttype` is just a string column
distinguishing whose row is whose. The same doctype now serves two parents.

OWN SECTION BREAK, same reasoning as the Customs Tracker declarations table: a
Table field anchored inside a Column Break renders at that column's width --
roughly a fifth of the page -- which is unusable for a grid. Placed directly
after the existing "Milestone checklist" section (fps_checklist_html), which is
the read-only rendering of exactly this data; the raw log sits right below the
summary it drives.

Data migration is a SEPARATE patch (migrate_updates_to_job_order), which runs
after this one and after the six tracker-facing scripts have been retargeted.

Safe to re-run: create_custom_field is a no-op when the field exists.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

DOCTYPE = "Job Order"
CHILD = "FPS Job Update"

SECTION_FIELD = {
	"fieldname": "fps_updates_sec",
	"fieldtype": "Section Break",
	"label": "Updates",
	"insert_after": "fps_checklist_html",
	"description": ("Every dated entry behind the checklist above. \"Log update\" "
	                "is the normal way in; add a row here directly for anything "
	                "that needs backdating or a bulk correction."),
}

TABLE_FIELD = {
	"fieldname": "fps_updates",
	"fieldtype": "Table",
	"label": "Update log",
	"options": CHILD,
	"insert_after": "fps_updates_sec",
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
			frappe.clear_cache(doctype=DOCTYPE)
		except Exception:
			frappe.log_error(title="FPS: could not add %s" % spec["fieldname"])

	frappe.clear_cache(doctype=DOCTYPE)
