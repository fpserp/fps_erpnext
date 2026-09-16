"""Document submission deadline follows Dubai Customs: declaration date + 30.

Agam, 16 Sep 2026, asked whether ERPNext should keep counting the originals
deadline from the clearance date while Dubai Customs counts from the declaration
date (the day the AED 5/day fines are measured from): "Change ERPNext to match".

    fps_doc_deadline    was  clearance_date + 30
                        now  ct_date (declaration date) + 30 = Fine Start Date
                             (clearance_date + 30 if a cleared row has no ct_date)
    fps_mofa_deadline   unchanged, clearance_date + 14

The rule itself lives in fps_erpnext/api/customs_clock.py and the validate hook
already applies it on every save. This patch re-stamps what is ALREADY stored:
every FPS Customs Declaration row, then every Customs Tracker parent (the
nearest outstanding row's date, or its own when it has no rows). Only
fps_doc_deadline is touched -- the MOFA clock was not part of the decision.

NO PARENT IS SAVED. Values are written with db.set_value, so the "CT BOE to Job
Order" script -- which fires on Customs Tracker save and writes back onto the
Job Order -- does not run once per tracker for a derived date.

Dry run of this code against a read-only snapshot of the live site on 16 Sep
2026 (fps-agents/runs/cofficer/deadline-change-preview.json): 45 trackers, 40
declaration rows; 38 rows carry ct_date == clearance_date, so they do not move.
Three values change:

    FPS/CT/2607/039  row + parent   10-10 -> 30-09   declared 31-08, cleared 10-09
    FPS/CT/2609/082  parent (no rows)  blank -> 04-10   declared 04-09, cleared 10-09

Nothing becomes overdue or due within 7 days; 2607/039 turns amber (day 16).

It also rewrites the description on the tracker's Doc submission deadline field,
which still said "30 days from clearance".

Safe to re-run: only values that differ are written.
"""

import frappe

from fps_erpnext.api.customs import TRACKER, backfill_deadlines
from fps_erpnext.patches.v1_0.customs_tracker_deadlines import DOC_DEADLINE_DESCRIPTION

FIELD = "fps_doc_deadline"


def execute():
	if not frappe.db.exists("DocType", TRACKER):
		return

	_describe()

	try:
		result = backfill_deadlines(keys=("doc",))
	except Exception:
		frappe.db.rollback()
		# A derived date must not fail the deploy: the validate hook re-stamps a
		# tracker the next time it is saved.
		frappe.log_error(title="FPS: could not re-stamp customs doc deadlines")
		return

	frappe.db.commit()

	for parent, row, field, before, after in result["changes"]:
		frappe.logger().info(
			"FPS: %s %s %s %s -> %s" % (parent, row or "(parent)", field, before, after))

	summary = (
		"FPS: doc deadline now counts from the declaration date -- "
		"%d declaration rows and %d trackers changed"
		% (result["rows"], result["parents"])
	)
	frappe.logger().info(summary)
	print(summary)
	return result


def _describe():
	name = frappe.db.get_value("Custom Field", {"dt": TRACKER, "fieldname": FIELD})
	if not name:
		return
	if frappe.db.get_value("Custom Field", name, "description") == DOC_DEADLINE_DESCRIPTION:
		return
	frappe.db.set_value("Custom Field", name, "description", DOC_DEADLINE_DESCRIPTION)
	frappe.clear_cache(doctype=TRACKER)
