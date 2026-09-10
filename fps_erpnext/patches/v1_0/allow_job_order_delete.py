"""Let managers delete a Job Order.

Same bug, same shape as the tracker case (allow_tracker_delete), on the doctype
everything else in the app links to. Job Order carries three Custom DocPerm
rows -- one for `All`, one for FPS Operations, and one for System Manager -- and
a Custom DocPerm set REPLACES the standard set entirely rather than merging
with it, so the standard row that would have granted Sales Manager delete was
never consulted.

WORSE THAN THE TRACKERS: the existing System Manager row is at PERMLEVEL 1, not
0. Document-level actions -- read, write, create, delete, submit, cancel, amend
-- are decided from permlevel-0 rows only; permlevel 1+ rows govern access to
fields marked with that permlevel, and Job Order has none. So that row governs
nothing at all, and System Manager had ZERO standing permission on Job Order --
not even read -- from any row of its own.

This was invisible day to day only because both people who hold System Manager
on this site (agam@ and abhishek@) also hold FPS Operations, which does carry
read/write/create/submit/cancel at permlevel 0. Delete and amend were the two
actions FPS Operations does not grant, and delete is what surfaced it.

THE FIX adds a correct permlevel-0 row for System Manager and a new one for
Sales Manager, each with the full set the standard DocPerm intended: read,
write, create, delete, submit, cancel, amend, plus report, export, print, email,
share. The existing `All`, FPS Operations, and the orphaned permlevel-1 System
Manager rows are left exactly as they are -- the last one governs nothing today,
but removing it is out of scope for a delete fix and is not this patch's call to
make.

DELIBERATELY NOT FPS Operations. Job Order is the master operational record --
every Job Tracker, Customs Tracker, Proof of Delivery and Sales Invoice on a job
links back to it. Handing delete to the working role that touches it daily is a
materially bigger risk than the same call on a tracker. ops@ holds only FPS
Operations and does not get delete here; add the role to ROLES below if that
judgement should change.

FRAPPE'S OWN LINK PROTECTION STILL APPLIES, permission aside. Deleting a
document that another document still links to raises LinkExistsError, and every
Job Order gets a Job Tracker the moment it is created (JO Emit Opened, After
Insert) -- so in practice almost every existing Job Order will refuse to delete
until its tracker, and anything else pointing at it, is removed first. A
submitted Job Order (docstatus 1) also has to be cancelled before it can be
deleted at all; that is standard Frappe behaviour for any submittable doctype,
not something this patch adds or could turn off.

Safe to re-run: a row that already exists is left alone, and one missing delete
is corrected rather than duplicated.
"""

import frappe

DOCTYPE = "Job Order"

# Deliberately not FPS Operations. See the note above.
ROLES = ("System Manager", "Sales Manager")

PERMS = {
	"read": 1, "write": 1, "create": 1, "delete": 1,
	"submit": 1, "cancel": 1, "amend": 1,
	"report": 1, "export": 1, "print": 1, "email": 1, "share": 1,
}


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	added = corrected = 0

	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.log_error(title="FPS: role %s missing, no delete on %s"
			                 % (role, DOCTYPE))
			continue

		existing = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": DOCTYPE, "role": role, "permlevel": 0},
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
				parent=DOCTYPE,
				parenttype="DocType",
				parentfield="permissions",
				role=role,
				permlevel=0,
			)).insert(ignore_permissions=True)
			added += 1
		except Exception:
			frappe.log_error(title="FPS: could not grant %s delete on %s"
			                 % (role, DOCTYPE))

	if added or corrected:
		frappe.db.commit()

	frappe.clear_cache(doctype=DOCTYPE)
	frappe.logger().info(
		"FPS: Job Order delete -- %d permission rows added, %d corrected"
		% (added, corrected)
	)
