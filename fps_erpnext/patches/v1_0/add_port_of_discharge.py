"""Split "Destination / POD" into two fields: Destination, and Port of Discharge.

One field was doing two jobs. On a sea import "Jebel Ali" is the port and the
customer's warehouse is the destination; on a road job there is no port at all.

WHERE IT LIVES. Five doctypes, not the three that were named -- the
"FPS Shipment Details" group is on Sales Invoice too, and Proof of Delivery
carries the same combined label:

    Job Order         pod          "Destination / POD"  -> "Destination"
    Quotation         fps_pod      "Destination / POD"  -> "Destination"
    Sales Invoice     fps_pod      "Destination / POD"  -> "Destination"
    Proof of Delivery destination  "Destination / POD"  -> "Destination"
    FPS Enquiry       destination  already "Destination", untouched

The relabelling ships as Property Setters (declarative, in git). THIS patch adds
the second field to all five.

THE EXISTING FIELD IS KEPT AND RELABELLED RATHER THAN RENAMED. Two reasons.

First, the data. 85 job orders, 69 invoices, the quotations and the PODs all
carry a value in that one field, and there is no rule that can split "Jebel Ali"
or "DUBAI" into a destination and a port after the fact. Keeping the field means
every existing value stays exactly where it is and stays correct under the
narrower label; Port of Discharge simply starts empty and is filled in going
forward. Nothing is guessed on anyone's behalf.

Second, the dependencies. Job Order.pod is read by the JT Rollup and FPS Tracker
Sweep server scripts, by the route line on the job tracker board
(fps_erpnext.api.pipeline._route), and by Job Order - Create Buttons, which
copies it onto a new Proof of Delivery and Sales Invoice. Renaming the fieldname
for a label change would mean touching all of those to gain nothing a user can
see -- users read labels, not fieldnames.

ONE DEPENDENCY DID HAVE TO CHANGE, and it is not obvious: the
"Job Order - SOW Tracker UI" client script calls set_df_property('pod', 'label',
...) on every refresh, so it would have painted "Destination / POD" straight back
over the Property Setter. repoint_tracker_lookups ships the corrected body.

Safe to re-run: create_custom_field is a no-op when the field already exists.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

LABEL = "Port of Discharge"
DESCRIPTION = "The port the cargo is discharged at. Leave blank when there is no sea or air leg."

# doctype -> (fieldname, insert_after)
#
# The fps_ prefix is kept on the two STOCK doctypes, matching the convention
# already used there and keeping the field clear of anything ERPNext may add
# later. The three custom doctypes take the plain name.
# ANCHORED ON THE ORIGIN FIELD, NOT THE DESTINATION ONE, and that is not a
# style choice -- it is where the field actually lands. Anchoring on the
# Destination field put it 15 fields further down, in Profit Summary; anchoring
# on Origin/POL puts it directly beneath Origin/POL inside FPS Shipment Details,
# which is also where it was asked for. Verified against the live merged meta
# for all five doctypes rather than reasoned about. See place_port_of_discharge
# for why the first attempt failed and how this was measured.
FIELDS = {
	"Job Order": ("port_of_discharge", "pol"),
	"Proof of Delivery": ("port_of_discharge", "pol"),
	"FPS Enquiry": ("port_of_discharge", "origin"),
	"Quotation": ("fps_port_of_discharge", "fps_pol"),
	"Sales Invoice": ("fps_port_of_discharge", "fps_pol"),
}


def execute():
	for doctype, (fieldname, insert_after) in FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			frappe.log_error(title="FPS: %s missing, no %s added" % (doctype, fieldname))
			continue

		fieldnames = [f.fieldname for f in frappe.get_meta(doctype).fields]
		if fieldname in fieldnames:
			continue
		if insert_after not in fieldnames:
			# Do not guess a position. A field dropped at the end of a form is
			# worse than one that is reported and placed by hand.
			frappe.log_error(
				title="FPS: %s has no %s, %s not added" % (doctype, insert_after, fieldname)
			)
			continue

		try:
			create_custom_field(doctype, {
				"fieldname": fieldname,
				"label": LABEL,
				"fieldtype": "Data",
				"insert_after": insert_after,
				"description": DESCRIPTION,
				"translatable": 0,
			}, ignore_validate=True)
		except Exception:
			frappe.log_error(title="FPS: could not add %s to %s" % (fieldname, doctype))

	frappe.clear_cache()
