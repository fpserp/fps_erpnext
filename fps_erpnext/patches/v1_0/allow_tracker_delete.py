"""Let managers delete a Job Tracker or a Customs Tracker.

Delete was missing from both trackers' menus for EVERYONE, including the two
System Managers. The doctypes do ship a standard permission set that grants it:

    Job Tracker / Customs Tracker   System Manager  delete 1
                                    Sales Manager   delete 1
                                    Sales User      delete 0

None of it applied. Both doctypes carry CUSTOM DocPerm rows -- one for `All`,
one for FPS Operations -- and a Custom DocPerm set REPLACES the standard set
entirely rather than merging with it. So the only permissions in force were the
two custom rows, neither of which grants delete, and the System Manager and
Sales Manager rows were never consulted.

This is the same trap that once left nobody able to save a Payment Entry on this
site. It bites in both directions: adding one custom row silently discards every
standard row, and deleting the last custom row silently restores them.

THE FIX adds the two missing roles to the CUSTOM set, which is the set that is
actually read. The existing `All` and FPS Operations rows are left exactly as
they are.

WHO GETS IT. agam@ and abhishek@ hold System Manager and Sales Manager, so both
can now delete. ops@ holds only FPS Operations and deliberately does NOT -- a
tracker is one per job now and carries that job's whole history in its child
table, so deleting one is not the small act it was when a tracker was a single
event. Add FPS Operations to ROLES below if that judgement should change.

Deletion still goes through frappe.delete_doc, so a removed tracker is archived
to Deleted Document and can be restored, and a job that loses its tracker gets a
fresh one the next time anything logs against it -- the history is what is gone,
not the structure.

Safe to re-run: a row that already exists is left alone, and one that exists
without delete is corrected rather than duplicated.
"""

import frappe

TRACKERS = ("Job Tracker", "Customs Tracker")

# Deliberately not FPS Operations. See the note above.
ROLES = ("System Manager", "Sales Manager")

PERMS = {
	"read": 1, "write": 1, "create": 1, "delete": 1,
	"report": 1, "export": 1, "print": 1, "email": 1, "share": 1,
}


def execute():
	added = corrected = 0

	for doctype in TRACKERS:
		if not frappe.db.exists("DocType", doctype):
			continue

		for role in ROLES:
			if not frappe.db.exists("Role", role):
				frappe.log_error(title="FPS: role %s missing, no delete on %s"
				                 % (role, doctype))
				continue

			existing = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": doctype, "role": role, "permlevel": 0},
				"name",
			)

			if existing:
				if not frappe.db.get_value("Custom DocPerm", existing, "delete"):
					frappe.db.set_value("Custom DocPerm", existing, "delete", 1)
					corrected += 1
				continue

			try:
				frappe.get_doc(dict(
					PERMS,
					doctype="Custom DocPerm",
					parent=doctype,
					parenttype="DocType",
					parentfield="permissions",
					role=role,
					permlevel=0,
				)).insert(ignore_permissions=True)
				added += 1
			except Exception:
				frappe.log_error(title="FPS: could not grant %s delete on %s"
				                 % (role, doctype))

	if added or corrected:
		frappe.db.commit()

	for doctype in TRACKERS:
		frappe.clear_cache(doctype=doctype)

	frappe.logger().info(
		"FPS: tracker delete -- %d permission rows added, %d corrected"
		% (added, corrected)
	)
