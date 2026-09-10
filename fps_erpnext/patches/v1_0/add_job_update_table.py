"""Give Job Tracker the child table its updates will live in.

Job Tracker is a CUSTOM doctype -- it lives in the site database, not in this
app -- so the table field has to be added as a Custom Field rather than shipped
in a doctype JSON. The child doctype itself (FPS Job Update) IS app-shipped and
is created by the model sync that runs before this patch.

Created here rather than as a module JSON fixture on purpose: a patch runs
strictly after the model sync, so "FPS Job Update" is guaranteed to exist when
the Table field points at it. A fixture would be racing that ordering.

Safe to re-run.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

FIELD = {
	"fieldname": "fps_updates",
	"fieldtype": "Table",
	"label": "Updates",
	"options": "FPS Job Update",
	"insert_after": "issues",
	"description": (
		"Every dated update on this job, oldest first. This used to be a separate "
		"Job Tracker document per update."
	),
	"allow_on_submit": 0,
	"permlevel": 0,
}


def execute():
	if not frappe.db.exists("DocType", "Job Tracker"):
		return
	if not frappe.db.exists("DocType", "FPS Job Update"):
		# Model sync did not run or the child doctype was removed. Do NOT create a
		# Table field pointing at a doctype that does not exist -- it makes the
		# whole Job Tracker form fail to render.
		frappe.log_error(title="FPS: FPS Job Update missing, skipped fps_updates")
		return

	create_custom_field("Job Tracker", FIELD, ignore_validate=True)
	frappe.clear_cache(doctype="Job Tracker")
