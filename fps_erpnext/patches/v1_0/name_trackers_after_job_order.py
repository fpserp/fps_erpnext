"""Rename every tracker to its job order's number, dropping the FPS/JT and FPS/CT series.

    Job Order        FPS/JO/2607/018
    Job Tracker      FPS/JT/2609/117  ->  FPS/JO/2607/018
    Customs Tracker  FPS/CT/2607/018  ->  FPS/JO/2607/018

Frappe requires a name to be unique only WITHIN a doctype, and these are three
separate tables, so all three can share one string. That was the point of the
change: the job order number is the only number anyone at FPS says out loud.

MUST RUN AFTER consolidate_job_trackers. Before the consolidation a job had up
to ten trackers, so this would hand out -2 .. -10 suffixes that the very next
patch deletes again. Afterwards Job Tracker is 1:1 and needs no suffix at all.

CUSTOMS TRACKER IS NOT 1:1 AND NEVER WILL BE. It is per customs leg, and four
jobs clear in two legs -- 2607/020, 2607/025, 2607/027 and 2608/065. Those keep
a -2. That is honest: they really are two declarations.

rename_doc repoints every Link field, comment, version and attachment that
referenced the old name, and deletes nothing.

KEEP THE rename_doc CALL MINIMAL. The deployed Frappe (16.24.1) does not accept
ignore_permissions on rename_doc -- passing it raised
"TypeError: rename_doc() got an unexpected keyword argument 'ignore_permissions'"
and took a whole migration down. The version-16 branch does accept it, so the
branch source is NOT a safe guide to what is running here. Only `force` is
passed; patches run as Administrator, so there is no permission to bypass.

Safe to re-run: anything already at its target name is skipped.
"""

import frappe

TRACKERS = ("Job Tracker", "Customs Tracker")


def execute():
	_disable_naming_rules()
	for doctype in TRACKERS:
		if not frappe.db.exists("DocType", doctype):
			continue
		_rename(doctype)
	frappe.clear_cache()


def _disable_naming_rules():
	"""Get the Document Naming Rules out of the way, or the rename is cosmetic.

	Frappe applies Document Naming Rules BEFORE the autoname doc_event. In
	set_new_name(): set_naming_from_document_naming_rule(doc) runs first, and
	doc.run_method("autoname") is only reached `if not doc.name`. So an enabled
	rule that matches pre-empts fps_erpnext.api.trackers.name_from_job_order
	entirely -- it never sees the document.

	This is not a theory. The hook shipped on 2026-09-10 and has NEVER fired:
	Job Tracker FPS/JT/2609/631 was created that day at 12:04 for job order
	FPS/JO/2609/083, and rule aeeprd3stu's counter moved to 631 seven
	milliseconds later. The hook would have produced FPS/JO/2609/083.

	The rules match on a condition of naming_series = "FPS/JT/.YY..MM./.###",
	and Document.insert() runs _set_defaults() before set_new_name(), so the
	DocField's own default fills that field in even though nothing passes it any
	more. Clearing the default would not be enough either; the rule has to go.

	Only the two TRACKER rules are touched. Job Order, FPS Enquiry and Proof of
	Delivery keep theirs -- those doctypes are still numbered from a series, and
	the whole continuous-numbering scheme depends on them.

	Disabled rather than deleted, so the counters stay auditable.
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
		# Leg order first so a two-leg job's first declaration takes the bare
		# name and the second takes -2, rather than the other way round.
		order_by="job_order asc, fps_leg asc, creation asc",
	)

	renamed = 0
	for row in rows:
		if not row.job_order or row.name == row.job_order:
			continue
		if not frappe.db.exists("Job Order", row.job_order):
			frappe.log_error(
				title="FPS: %s %s points at a missing job order" % (doctype, row.name)
			)
			continue

		target = row.job_order
		n = 1
		# A name held by THIS row is already correct; only a name held by a
		# DIFFERENT record forces the next suffix. Without the `!= row.name`
		# test, a re-run walks straight past a leg-2 tracker's own -2 and
		# renames it to -3, then -4 on the run after that. The four two-leg
		# jobs -- 2607/020, 2607/025, 2607/027, 2608/065 -- are the ones that
		# would drift.
		while frappe.db.exists(doctype, target) and target != row.name:
			n += 1
			target = "%s-%d" % (row.job_order, n)

		if target == row.name:
			continue

		try:
			frappe.rename_doc(doctype, row.name, target, force=True)
			renamed += 1
		except Exception:
			frappe.log_error(title="FPS: rename %s %s" % (doctype, row.name))

	if renamed:
		frappe.db.commit()
	frappe.logger().info("FPS: renamed %d %s records" % (renamed, doctype))
