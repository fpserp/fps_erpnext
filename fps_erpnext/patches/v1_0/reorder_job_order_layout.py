"""Move the Scope of Work / Tracking / Milestone checklist / Updates block to
sit after Cargo Details instead of after the hidden legacy Status field.

WHAT THIS ACTUALLY TOUCHES, AND WHY THE FIRST VERSION OF THIS PATCH DID
NOTHING. Job Order carries two different kinds of field:

  - The ORIGINAL fields (Order Information, Shipment Details, Cargo Details,
    AR Charges, Cost - AP, Summary, Notes & Terms, Internal Remarks, Linked
    Invoices) are native DocField rows on the Job Order DocType document
    itself -- Job Order is a fully custom doctype (custom=1), so these live
    directly in ITS OWN `fields` table, ordered by position, with no
    insert_after at all.

  - Everything FPS-prefixed from the 2026-09-09 hybrid tracker build
    (fps_sow_sec, fps_track_sec, fps_checklist_sec, fps_updates_sec and every
    field inside each) plus port_of_discharge and shipper were added LATER as
    Custom Field records, each with its own insert_after, layered on top of
    the native list by Meta.sort_fields() at read time.

The first version of this patch walked doc.fields looking for all 14
sections and aborted (logged "FPS: Job Order section mismatch", see Error
Log eai670v03b, 2026-09-11) the moment it found only 10 -- the 4 FPS
sections were never going to be there; they are Custom Field records, not
DocField rows, so the whole premise of reordering Job Order by rewriting its
native fields table was wrong for this part of the move. Confirmed by
listing `Custom Field` with dt=Job Order directly: fps_sow_sec's own record
carries insert_after="status".

THE ACTUAL FIX is one field on one record. fps_track_sec, fps_checklist_sec
and fps_updates_sec already chain off fields INSIDE this same custom block
(fps_subcategory, fps_customer_note, fps_checklist_html) rather than
anything native, so retargeting fps_sow_sec's own insert_after is enough to
carry the whole four-section block wherever it points -- moving it from
"status" (the hidden legacy field the block used to trail) to
"cargo_remarks" (the last field of Cargo Details) is the entire change.

AR Charges and Summary are no longer touched here at all -- hiding those two
sections turned out to need nothing more than a Property Setter each (they
ARE native DocField rows, and "hidden" is a normal overridable property
regardless of that), so they moved to build_workspaces.py's PROPERTY_SETTERS
list instead, next to the same fps_route_pattern hidden setter this doctype
already carried.

Applied directly to the live site the moment this was diagnosed, the same
day as the failed first attempt. This patch exists so any other copy of the
site reaches the same place, and is a no-op where it already is.

Safe to re-run.
"""

import frappe

DOCTYPE = "Job Order"
FIELDNAME = "fps_sow_sec"
ANCHOR = "cargo_remarks"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	name = frappe.db.get_value("Custom Field", {"dt": DOCTYPE, "fieldname": FIELDNAME}, "name")
	if not name:
		return

	if not any(f.fieldname == ANCHOR for f in frappe.get_meta(DOCTYPE).fields):
		frappe.log_error(title="FPS: Job Order has no %s, %s not moved" % (ANCHOR, FIELDNAME))
		return

	if frappe.db.get_value("Custom Field", name, "insert_after") == ANCHOR:
		return

	frappe.db.set_value("Custom Field", name, "insert_after", ANCHOR)
	frappe.db.commit()
	frappe.clear_cache(doctype=DOCTYPE)
	frappe.logger().info("FPS: moved %s to follow %s" % (FIELDNAME, ANCHOR))
