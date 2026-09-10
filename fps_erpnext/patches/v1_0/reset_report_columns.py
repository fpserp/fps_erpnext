"""Drop the saved Report-view column lists that are hiding the new columns.

THE SYMPTOM. Quotation opens on Report view showing two columns -- ID and
Movement Type -- despite its meta now carrying seven: customer_name,
transaction_date, fps_movement_type, fps_pol, fps_pod, grand_total and status.
Every Property Setter is in place and correct. The columns are simply not being
asked for.

WHY. in_list_view only supplies the DEFAULT column set. The first time anyone
opens a Report view, Frappe saves that user's column choice into the
`__UserSettings` table under {"Report": {"fields": [...]}}, and from then on the
saved list wins -- for that user, on that doctype, forever. Adding a field to
in_list_view afterwards changes nothing they can see, because their layout was
frozen before the field existed.

So this is not a second bug on top of the first. The Property Setters fixed the
default; this clears the stale override that was standing in front of it.

WHAT IS REMOVED, AND WHAT IS NOT. Only the `fields` key, and only for the
doctypes whose in_list_view actually changed. Saved FILTERS, sort order, group
by and page length are all left exactly as they are -- someone who has set up a
filter they rely on keeps it, and only the column list falls back to the new
default. `__UserSettings` is not a DocType, so this is necessarily raw SQL
against that table.

THE CACHE HAS TO GO TOO. get_user_settings reads frappe.cache first and only
falls back to the table, so clearing the rows without clearing the cache would
leave the workers serving the old list until something else evicted it.

Safe to re-run: once the key is gone there is nothing to strip, and any layout
a user builds AFTER this runs is their own and is never touched again.
"""

import json

import frappe

# Exactly the doctypes whose in_list_view this project changed.
DOCTYPES = (
	"Attendance", "Bank Transaction", "Customer", "Expense Claim", "Item",
	"Job Order", "Journal Entry", "Lead", "Leave Application", "Material Request",
	"Opportunity", "Payment Entry", "Purchase Invoice", "Purchase Order",
	"Quotation", "Sales Invoice", "Sales Order", "Supplier",
	"Customs Tracker", "Job Tracker", "Proof of Delivery", "FPS Enquiry",
)

VIEWS = ("Report", "List")


def execute():
	if not frappe.db.table_exists("__UserSettings"):
		return

	try:
		rows = frappe.db.sql(
			"""select `user`, `doctype`, `data` from `__UserSettings`
			   where `doctype` in %(doctypes)s""",
			{"doctypes": tuple(DOCTYPES)},
			as_dict=True,
		)
	except Exception:
		frappe.log_error(title="FPS: could not read __UserSettings")
		return

	cleared = 0
	for row in rows:
		if not row.get("data"):
			continue
		try:
			settings = json.loads(row["data"])
		except Exception:
			continue
		if not isinstance(settings, dict):
			continue

		touched = False
		for view in VIEWS:
			block = settings.get(view)
			if isinstance(block, dict) and "fields" in block:
				# Only the column list. Filters, sort and group by stay.
				block.pop("fields", None)
				touched = True

		if not touched:
			continue

		try:
			frappe.db.sql(
				"""update `__UserSettings` set `data` = %(data)s
				   where `user` = %(user)s and `doctype` = %(doctype)s""",
				{"data": json.dumps(settings), "user": row["user"],
				 "doctype": row["doctype"]},
			)
			cleared += 1
		except Exception:
			frappe.log_error(
				title="FPS: could not reset columns for %s / %s"
				% (row["doctype"], row["user"])
			)

	if cleared:
		frappe.db.commit()

	# get_user_settings reads the cache before the table.
	try:
		frappe.cache.delete_key("_user_settings")
	except Exception:
		try:
			frappe.cache().delete_key("_user_settings")
		except Exception:
			frappe.log_error(title="FPS: could not clear the _user_settings cache")

	frappe.clear_cache()
	frappe.logger().info("FPS: reset saved report columns on %d user/doctype rows" % cleared)
