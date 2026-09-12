"""Give Customs Tracker a way to record HOW a declaration was cleared.

Nothing on Customs Tracker previously distinguished duty paid outright from a
refundable deposit, a MOIAT exemption, or any other exemption -- fps_duty_paid_on
is only a date, and fps_deposit_status only tracks whether a deposit's OWN
process (payment/refund) is pending or done, not which of the four applies in
the first place. Nor was there anywhere to record how much was actually paid,
which matters most for a deposit since those are refundable and someone has
to know the figure to chase later.

Two fields, added in the same spot on both copies of the duty/deposit block --
Customs Tracker itself (one declaration, or the first/primary one) and FPS
Customs Declaration (one row per BOE, for jobs that clear on more than one) --
mirroring how fps_duty_paid_on / fps_deposit_status / fps_deposit_claim already
exist on both:

    fps_duty_mode   Select: Duty / Deposit / MOIAT Exemption / Other Exemption
    fps_amount_paid Currency: what was actually paid, blank for an exemption

Both inserted right after fps_duty_paid_on. FPS Customs Declaration is a real
module doctype (fps_erpnext/fps/doctype/fps_customs_declaration/), so its copy
ships as an ordinary field on that doctype's own JSON, not a Custom Field --
this patch only has Customs Tracker to do, since Customs Tracker is fully
custom (custom=1) and everything FPS-prefixed on it is already a Custom Field
for exactly the same reason fps_sow_sec is on Job Order.

Applied directly to the live site the moment this was written, verified by
re-reading the resolved field order (landed exactly as intended: right after
"Duty / deposit paid on", before "Claim"). This patch is so any other copy of
the site reaches the same place.

Safe to re-run: create_custom_field is a no-op when the field exists.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

DOCTYPE = "Customs Tracker"

FIELDS = [
	{
		"fieldname": "fps_duty_mode",
		"fieldtype": "Select",
		"label": "Processed via",
		"options": "\nDuty\nDeposit\nMOIAT Exemption\nOther Exemption",
		"insert_after": "fps_duty_paid_on",
		"description": ("How this declaration was cleared -- duty paid outright, "
		                "a refundable deposit, or an exemption."),
	},
	{
		"fieldname": "fps_amount_paid",
		"fieldtype": "Currency",
		"label": "Amount paid",
		"insert_after": "fps_duty_mode",
		"description": ("Amount paid for duty or a refundable deposit, per "
		                "\"Processed via\". Leave blank for an exemption."),
	},
]


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	for spec in FIELDS:
		if frappe.db.exists("Custom Field", {"dt": DOCTYPE, "fieldname": spec["fieldname"]}):
			continue
		fieldnames = [f.fieldname for f in frappe.get_meta(DOCTYPE).fields]
		if spec["insert_after"] not in fieldnames:
			frappe.log_error(
				title="FPS: %s has no %s, %s not added"
				% (DOCTYPE, spec["insert_after"], spec["fieldname"])
			)
			continue
		try:
			create_custom_field(DOCTYPE, dict(spec), ignore_validate=True)
		except Exception:
			frappe.log_error(title="FPS: could not add %s" % spec["fieldname"])

	frappe.clear_cache(doctype=DOCTYPE)
