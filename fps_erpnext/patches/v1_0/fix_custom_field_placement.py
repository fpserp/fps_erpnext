"""Put Port of Discharge back beside Destination on the forms where it drifted.

THE BUG. add_port_of_discharge created the field with create_custom_field and
did not set `idx`, so it defaulted to 0. Frappe's Meta.sort_fields() reads the
doctype's custom fields ORDERED BY idx and then places each one after the field
named in its insert_after -- in a small fixed number of passes. A field with
idx 0 is therefore processed FIRST, before the custom field it wants to sit
after has been placed, so its anchor is not there to find and it ends up at the
end of the custom-field block instead.

Measured on the live site, distance between the anchor and the new field:

    Job Order          pod -> port_of_discharge          adjacent    OK
    FPS Enquiry        destination -> port_of_discharge  adjacent    OK
    Proof of Delivery  destination -> port_of_discharge  7 fields further on
    Quotation          fps_pod -> fps_port_of_discharge  15 fields further on
    Sales Invoice      fps_pod -> fps_port_of_discharge  13 fields further on

The pattern is exact: it worked wherever the anchor is a STANDARD field, which
is already placed before any custom field is considered, and failed wherever the
anchor is itself a CUSTOM field. On Quotation the field was sitting past
Internal Remarks, nowhere near FPS Shipment Details -- which is why it read as
missing on a new quotation. It was always on the form, just not where anyone
would look.

THE FIX is the smallest possible change away from a state that demonstrably
works: give the field idx = anchor idx + 1, shifting anything already at or
after that number up by one so no two fields collide. Every correctly-placed FPS
custom field already has an idx ascending along its insert_after chain, so this
restores the invariant rather than inventing a new scheme.

insert_after is NOT touched. Only idx moves.

Safe to re-run: a field already sitting at anchor + 1 is left alone, so a second
run shifts nothing.
"""

import frappe

# (doctype, fieldname, the field it must follow)
PLACEMENTS = (
	("Quotation", "fps_port_of_discharge", "fps_pod"),
	("Sales Invoice", "fps_port_of_discharge", "fps_pod"),
	("Proof of Delivery", "port_of_discharge", "destination"),
	("Job Order", "port_of_discharge", "pod"),
	("FPS Enquiry", "port_of_discharge", "destination"),
)


def execute():
	for doctype, fieldname, anchor in PLACEMENTS:
		try:
			_place_after(doctype, fieldname, anchor)
		except Exception:
			frappe.log_error(title="FPS: could not place %s on %s" % (fieldname, doctype))

	frappe.clear_cache()


def _place_after(doctype, fieldname, anchor):
	field = frappe.db.get_value(
		"Custom Field", {"dt": doctype, "fieldname": fieldname}, ["name", "idx"], as_dict=True
	)
	if not field:
		return

	anchor_row = frappe.db.get_value(
		"Custom Field", {"dt": doctype, "fieldname": anchor}, ["name", "idx"], as_dict=True
	)
	if not anchor_row:
		# The anchor is a standard DocField. Those are placed before any custom
		# field is considered, so insert_after already resolves on the first
		# pass and there is nothing to fix -- Job Order and FPS Enquiry are both
		# in this category and are correct today.
		return

	wanted = (anchor_row.idx or 0) + 1
	if field.idx == wanted:
		return

	# Make room. Anything at or after the target slot moves up one, so the
	# relative order of every other field is preserved exactly.
	for row in frappe.get_all(
		"Custom Field",
		filters={"dt": doctype, "idx": [">=", wanted]},
		fields=["name", "idx"],
	):
		if row.name == field.name:
			continue
		frappe.db.set_value("Custom Field", row.name, "idx", (row.idx or 0) + 1,
		                    update_modified=False)

	frappe.db.set_value("Custom Field", field.name, "idx", wanted,
	                    update_modified=False)
	frappe.db.commit()
	frappe.logger().info(
		"FPS: %s.%s moved to idx %d, after %s" % (doctype, fieldname, wanted, anchor)
	)
