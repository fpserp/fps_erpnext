"""Copy every Job Tracker's update log onto its Job Order, in place.

Job Tracker is already exactly one per job (the 2026-09-10 consolidation), so
this is a plain 1:1 copy, not a merge -- 90 job orders, 90 trackers, checked
live before writing this: zero orphan trackers, zero job orders without one,
zero job orders with more than one (a stray empty duplicate on 2607/039, dated
this session and holding no rows, was removed as pre-migration cleanup, not by
this patch).

WHAT MOVES: every FPS Job Update row, field for field, onto a NEW FPS Job
Update row of the same shape but parented to the Job Order instead of the Job
Tracker. Nothing is summarised or dropped -- there is no merge decision to make
here, unlike the earlier Customs Tracker declarations work, because each job
only ever had the one tracker to begin with.

NOTHING IS DELETED. The source Job Trackers and their original update rows are
left exactly as they are -- a frozen, still-readable historical record. This
patch only adds a second copy in the new location; it does not touch the old
one. If Job Tracker is ever fully retired, that is a separate, later decision.

ROLLUP IS SUPPRESSED DURING THE COPY. Left to fire naturally, the after_insert
hook on FPS Job Update (see hooks.py + fps_erpnext/api/jobs.py) would recompute
the full derivation once per ROW -- 383 times for 383 rows, each one correct
but 293 of them wasted. frappe.flags.fps_skip_rollup turns that off for the
duration of this patch, and rollup() is called explicitly once per job
afterwards instead.

Safe to re-run: a Job Order that already has fps_updates rows is skipped
entirely, so a second run touches nothing.
"""

import frappe

CHILD = "FPS Job Update"

CARRY = (
	"update_date", "milestone", "status_line", "evidence_ref",
	"notes", "issues", "next_action", "follow_up_date", "responsible",
	"event_type", "source", "customer_visible", "leg",
)


def execute():
	if not (frappe.db.exists("DocType", "Job Order") and frappe.db.exists("DocType", CHILD)):
		return

	fieldnames = [f.fieldname for f in frappe.get_meta("Job Order").fields]
	if "fps_updates" not in fieldnames:
		frappe.log_error(title="FPS: Job Order has no fps_updates, migration skipped")
		return

	trackers = frappe.get_all(
		"Job Tracker", fields=["name", "job_order"], limit_page_length=0
	)

	frappe.flags.fps_skip_rollup = True
	try:
		copied_jobs = copied_rows = skipped = 0
		for tracker in trackers:
			if not tracker.job_order:
				continue
			if not frappe.db.exists("Job Order", tracker.job_order):
				frappe.log_error(
					title="FPS: %s points at a missing job order" % tracker.name
				)
				continue
			if frappe.db.exists(CHILD, {"parenttype": "Job Order", "parent": tracker.job_order}):
				skipped += 1
				continue

			rows = frappe.get_all(
				CHILD,
				filters={"parenttype": "Job Tracker", "parent": tracker.name},
				fields=["name"] + list(CARRY),
				order_by="idx asc",
			)
			if not rows:
				continue

			try:
				for idx, row in enumerate(rows, start=1):
					child = {
						"doctype": CHILD,
						"parent": tracker.job_order,
						"parenttype": "Job Order",
						"parentfield": "fps_updates",
						"idx": idx,
					}
					for field in CARRY:
						child[field] = row.get(field)
					frappe.get_doc(child).insert(ignore_permissions=True)
					copied_rows += 1
				copied_jobs += 1
			except Exception:
				frappe.log_error(
					title="FPS: could not copy updates for %s" % tracker.job_order
				)
	finally:
		frappe.flags.fps_skip_rollup = False

	frappe.db.commit()

	from fps_erpnext.api.jobs import rollup

	rolled = 0
	for tracker in trackers:
		if not tracker.job_order:
			continue
		try:
			rollup(tracker.job_order)
			rolled += 1
		except Exception:
			frappe.log_error(title="FPS: post-migration rollup failed for %s" % tracker.job_order)

	frappe.db.commit()
	frappe.clear_cache(doctype="Job Order")
	frappe.logger().info(
		"FPS: copied %d update rows onto %d job orders (%d already had them), rolled up %d"
		% (copied_rows, copied_jobs, skipped, rolled)
	)
