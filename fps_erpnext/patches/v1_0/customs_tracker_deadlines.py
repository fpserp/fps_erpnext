"""Add the two customs chase clocks, and settle on one word for "done".

TWO NEW DATE FIELDS on Customs Tracker, both derived from the clearance date:

    fps_doc_deadline    Doc submission deadline   clearance + 30 days
    fps_mofa_deadline   MOFA deadline             clearance + 14 days

They are READ ONLY. Both are a fixed offset from a date already on the record,
so a typed-over value would only ever mean "this one is wrong". Change the
clearance date and both move; the validate hook in fps_erpnext.api.customs
recalculates them on every save.

Existing rows are backfilled here. 46 of the 48 live trackers have a clearance
date and get both deadlines; the two that have not cleared yet get neither,
because there is nothing to count from and a deadline invented from the entry
date would be a fake alarm.

SUBMITTED BECOMES COMPLETED. Document submission offered Pending / Submitted,
while MOFA, Deposit and Claim all offer Completed -- and the deadline rule is
written in terms of selecting "Completed". One word per state, chosen to match
the other three columns and the operations workbook, so the 17 rows reading
"Submitted" are migrated to "Completed".

THE OPTION LIST ITSELF IS NOT SET HERE. It ships as a Property Setter from
build_workspaces.py, so there is ONE definition of it in the repository -- had
this patch also written it, the next generator run would quietly revert it. The
property setter is applied during model sync, a few seconds before this patch
runs, so there is a brief moment inside the migration where 17 rows hold a value
their dropdown no longer offers. That window is inside `bench migrate` with no
user saving, and this patch closes it immediately.

Safe to re-run: create_custom_field is a no-op when the field exists, the
migration matches nothing once done, and the backfill only writes a date that
differs from what is already there.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

from fps_erpnext.api.customs import DEADLINES, backfill_deadlines

TRACKER = "Customs Tracker"

NEW_FIELDS = (
	{
		"fieldname": "fps_doc_deadline",
		"label": "Doc submission deadline",
		"fieldtype": "Date",
		"insert_after": "fps_doc_submission",
		"read_only": 1,
		"allow_on_submit": 0,
		"description": "30 days from clearance. Amber from day 15, red from day 25.",
	},
	{
		"fieldname": "fps_mofa_deadline",
		"label": "MOFA deadline",
		"fieldtype": "Date",
		"insert_after": "fps_mofa_status",
		"read_only": 1,
		"allow_on_submit": 0,
		"description": "14 days from clearance. Amber from day 9, red from day 12.",
	},
)

DOC_STATUS = "fps_doc_submission"
OLD_DONE = "Submitted"
NEW_DONE = "Completed"


def execute():
	if not frappe.db.exists("DocType", TRACKER):
		return

	_add_fields()
	frappe.clear_cache(doctype=TRACKER)

	_migrate_submitted()
	frappe.clear_cache(doctype=TRACKER)

	filled = backfill_deadlines()
	if filled:
		frappe.db.commit()
	frappe.logger().info("FPS: wrote customs deadlines onto %d trackers" % filled)


def _add_fields():
	fieldnames = [f.fieldname for f in frappe.get_meta(TRACKER).fields]
	for spec in NEW_FIELDS:
		if spec["fieldname"] in fieldnames:
			continue
		if spec["insert_after"] not in fieldnames:
			frappe.log_error(
				title="FPS: %s has no %s, %s not added"
				% (TRACKER, spec["insert_after"], spec["fieldname"])
			)
			continue
		try:
			create_custom_field(TRACKER, dict(spec), ignore_validate=True)
		except Exception:
			frappe.log_error(title="FPS: could not add %s" % spec["fieldname"])


def _migrate_submitted():
	rows = frappe.get_all(
		TRACKER, filters={DOC_STATUS: OLD_DONE}, pluck="name"
	)
	for name in rows:
		frappe.db.set_value(TRACKER, name, DOC_STATUS, NEW_DONE,
		                    update_modified=False)
	if rows:
		frappe.db.commit()
		frappe.logger().info(
			"FPS: Document submission Submitted -> Completed on %d trackers" % len(rows)
		)


def deadline_fieldnames():
	"""Convenience for anything that needs the pair. Keeps one source."""
	return [spec["date_field"] for spec in DEADLINES]
