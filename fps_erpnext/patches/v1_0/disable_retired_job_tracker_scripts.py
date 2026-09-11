"""Disable the three Server Scripts the update-log-on-Job-Order change supersedes.

    JT Rollup               Job Tracker After Save   -- the derivation, now
                                                         fps_erpnext.api.jobs.rollup(),
                                                         triggered by FPS Job Update's
                                                         own after_insert (hooks.py)
    FPS Tracker Sweep       Scheduler Event          -- the same derivation on a
                                                         cron, now fps_erpnext.api.
                                                         jobs.sweep() via hooks.py
                                                         scheduler_events, same
                                                         "*/30 * * * *" cadence
    JT Fetch from Job Order Job Tracker Before Save  -- filled customer /
                                                         declaration_type on a new
                                                         Job Tracker row; nothing
                                                         creates new Job Tracker
                                                         rows any more

DISABLED, NOT DELETED. Job Tracker itself is left exactly as it is -- 90
documents, still readable, still holding the update rows they always held, just
no longer where new activity is recorded or where the derivation runs from. If
someone opens an old Job Tracker directly (a saved link, an export, the
awesomebar) it still opens; it just does not do anything on save any more,
because nothing should be saving one. Config objects are cheap to disable and
just as cheap to re-enable; deleting them would be a needless one-way step for
no benefit over turning them off.

Safe to re-run: a script already disabled is left alone.
"""

import frappe

SCRIPTS = ("JT Rollup", "FPS Tracker Sweep", "JT Fetch from Job Order")


def execute():
	disabled = 0
	for name in SCRIPTS:
		if not frappe.db.exists("Server Script", name):
			continue
		if frappe.db.get_value("Server Script", name, "disabled"):
			continue
		frappe.db.set_value("Server Script", name, "disabled", 1, update_modified=False)
		disabled += 1

	if disabled:
		frappe.db.commit()
	frappe.clear_cache()
	frappe.logger().info("FPS: disabled %d retired job-tracker scripts" % disabled)
