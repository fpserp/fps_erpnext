"""Reorder the Job Order form's sections and retire AR Charges / Summary from view.

New top-to-bottom order (requested 2026-09-11):

    Order Information -> Shipment Details -> Cargo Details -> Scope of Work
    -> Tracking -> Milestone checklist -> Updates -> Cost - Account Payable
    -> Notes & Terms -> Internal Remarks -> (Linked Invoices, unmentioned,
    kept at the tail) -> Comments (the standard activity panel Frappe always
    renders after the last field, not a field here at all).

WHY THIS IS A PATCH, NOT A LIVE MCP DOCUMENT EDIT. Job Order is a fully
custom DocType (custom=1), so unlike Quotation/Sales Invoice/etc in this app
its fields are native DocField rows living directly on the DocType document,
not Custom Field records reachable by insert_after -- confirmed live: no
field on this doctype carries an insert_after value, so DocField order is
purely the position of each row in the DocType's own `fields` table. The only
way to reorder it is to rewrite that table. Doing that with ~90 fields' full
definitions hand-typed through the API is exactly the kind of large,
unverifiable payload this project avoids; a patch that re-slices the SAME
live `doc.fields` list in Python carries every attribute across untouched --
nothing is retyped, so nothing can be mistyped.

AR CHARGES AND SUMMARY: hidden, not deleted, on explicit instruction --
same "archive, don't destroy" choice already made for Job Tracker this
session. ar_charges in particular still feeds the "Create Sales Invoice"
button's line-item prefill (see the Job Order client scripts); hiding the
section only stops new rows being entered by hand through the form, it does
not touch the field, the table doctype, or any value already saved.

Idempotent: does nothing if the field order already matches.
"""

import frappe

DOCTYPE = "Job Order"

# Every section-break fieldname, in the NEW order. Any field not itself a
# section break travels with the section break that precedes it, so listing
# section names here is enough to carry their member fields along unchanged.
NEW_SECTION_ORDER = [
	"order_info_sec",
	"shipment_sec",
	"cargo_sec",
	"fps_sow_sec",
	"fps_track_sec",
	"fps_checklist_sec",
	"fps_updates_sec",
	"ap_sec",
	"notes_sec",
	"internal_sec",
	"linked_sec",   # not named in the request; kept, pushed to the tail
	"status_sec",   # already hidden (legacy status field); tail, out of the way
	"ar_sec",       # hidden below, not deleted
	"summary_sec",  # hidden below, not deleted
]

HIDE_SECTIONS = ("ar_sec", "summary_sec")


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	doc = frappe.get_doc("DocType", DOCTYPE)

	groups = {}
	order_seen = []
	current = None
	for f in doc.fields:
		if f.fieldtype == "Section Break":
			current = f.fieldname
			order_seen.append(current)
			groups[current] = []
		if current is None:
			# Fields before the first section break, if any -- keep them exactly
			# where they are, ahead of everything else.
			groups.setdefault("__lead__", []).append(f)
			continue
		groups[current].append(f)

	lead = groups.pop("__lead__", [])

	if set(order_seen) != set(NEW_SECTION_ORDER):
		frappe.log_error(
			title="FPS: Job Order section mismatch, layout not reordered",
			message="live sections: %s\nexpected: %s" % (sorted(order_seen), sorted(NEW_SECTION_ORDER)),
		)
		return

	new_fields = list(lead)
	for section in NEW_SECTION_ORDER:
		new_fields.extend(groups[section])

	if [f.fieldname for f in new_fields] == [f.fieldname for f in doc.fields]:
		already_hidden = all(
			f.hidden for name in HIDE_SECTIONS for f in groups[name]
		)
		if already_hidden:
			return  # already in the target shape; nothing to do

	for name in HIDE_SECTIONS:
		for f in groups[name]:
			f.hidden = 1

	for i, f in enumerate(new_fields, start=1):
		f.idx = i
	doc.fields = new_fields

	doc.save(ignore_permissions=True)
	frappe.clear_cache(doctype=DOCTYPE)
	frappe.db.commit()
	frappe.logger().info("FPS: reordered Job Order layout, hid AR Charges + Summary")
