"""Put the FPS/JT and FPS/CT prefixes back on the tracker names.

    Job Tracker      FPS/JO/2607/018  ->  FPS/JT/2607/018
    Customs Tracker  FPS/JO/2607/018  ->  FPS/CT/2607/018

ONLY THE PREFIX CHANGES. The year-month and the serial stay exactly as they are,
so a tracker and its job order still share a tail, and the -2 that four two-leg
Customs Trackers carry stays a -2.

WHY THIS UNDOES A PATCH FROM THE SAME DAY. name_trackers_after_job_order renamed
the trackers to their job order outright, on the reasoning that the job number is
the only number anyone at FPS says out loud. That shipped, and seeing it live the
prefix was wanted back: with Job Order, Job Tracker and Customs Tracker all
answering to "2607/018", the string alone stopped saying WHICH record was meant
in an email or over the phone. The prefix does that for free and costs nothing,
because the tail still matches.

Nothing else depends on the shape of the name. Every script and client helper
looks a tracker up by its job_order field (repoint_tracker_lookups makes that
uniform), so this is a pure relabelling of the primary key.

rename_doc repoints every Link field, comment, version and attachment, and
deletes nothing.

KEEP THE rename_doc CALL MINIMAL. The deployed Frappe (16.24.1) rejects
ignore_permissions on rename_doc -- passing it once took a whole migration down.
Only `force` is passed; patches run as Administrator, so there is nothing to
bypass.

Safe to re-run: a tracker already at its target name is skipped, and the suffix
search stops on the row's own name so a second run cannot walk -2 up to -3.
"""

import frappe

from fps_erpnext.api.trackers import TRACKERS, tracker_name_for


def execute():
	_disable_naming_rules()
	for doctype in TRACKERS:
		if not frappe.db.exists("DocType", doctype):
			continue
		_rename(doctype)
	frappe.clear_cache()


def _disable_naming_rules():
	"""Belt and braces -- name_trackers_after_job_order already did this.

	Frappe applies Document Naming Rules BEFORE the autoname doc_event and only
	reaches the hook `if not doc.name`, so an enabled rule silently takes naming
	away from fps_erpnext.api.trackers.name_from_job_order. If one has been
	switched back on since, this turns it off again rather than letting new
	trackers quietly drift back to counter-based names.
	"""
	if not frappe.db.exists("DocType", "Document Naming Rule"):
		return

	rules = frappe.get_all(
		"Document Naming Rule",
		filters={"document_type": ["in", list(TRACKERS)], "disabled": 0},
		pluck="name",
	)
	for rule in rules:
		frappe.db.set_value("Document Naming Rule", rule, "disabled", 1)

	if rules:
		frappe.db.commit()
		for doctype in TRACKERS:
			frappe.clear_cache(doctype=doctype)


def _rename(doctype):
	rows = frappe.get_all(
		doctype,
		fields=["name", "job_order"],
		# Leg order first, so a two-leg job's first declaration takes the bare
		# name and the second takes -2, rather than the other way round.
		order_by="job_order asc, fps_leg asc, creation asc",
	)

	renamed = 0
	for row in rows:
		if not row.job_order:
			continue

		base = tracker_name_for(doctype, row.job_order)
		if not base:
			frappe.log_error(
				title="FPS: cannot derive a name for %s %s" % (doctype, row.name)
			)
			continue

		target = base
		n = 1
		# A name held by THIS row is already correct; only a name held by a
		# DIFFERENT record forces the next suffix. Without the `!= row.name`
		# test a re-run walks straight past a leg-2 tracker's own -2 and
		# renames it to -3.
		while frappe.db.exists(doctype, target) and target != row.name:
			n += 1
			target = "%s-%d" % (base, n)

		if target == row.name:
			continue

		try:
			frappe.rename_doc(doctype, row.name, target, force=True)
			renamed += 1
		except Exception:
			frappe.log_error(title="FPS: rename %s %s" % (doctype, row.name))

	if renamed:
		frappe.db.commit()
	frappe.logger().info("FPS: re-prefixed %d %s records" % (renamed, doctype))
