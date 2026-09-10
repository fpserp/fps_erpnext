"""Add the two Customs Tracker columns the operations workbook has and ERPNext did not.

SOURCE OF TRUTH: "Daily Operation's & Quotes MAY 2026.xlsx", sheet "Customs
Tracker" -- the sheet operations actually keep. Its eleven columns map onto the
doctype like this:

    Job No.               job_order
    Client                customer
    BOE                   boe_number
    Type                  fps_clearance_type
    Date                  ct_date
    MOFA                  fps_mofa_status
    Doc Sub               fps_doc_submission
    Deposit               fps_deposit_status      <- ADDED HERE
    Claim                 fps_deposit_claim       (relabelled "Claim")
    Approval if Required  fps_approval_required   <- ADDED HERE
    Remarks               remarks

Only two were genuinely missing. "Deposit" had no status field at all -- just
fps_duty_paid_on, a date, which answers a different question -- and there was
nowhere to record an approval.

THE DATA IS ALREADY ON THE SITE, STRANDED IN A TEXT FIELD. When these 46 rows
were imported from the workbook, the columns that had no home were flattened into
`remarks` as plain text and left there:

    Original Type: IMPORT TO LOCAL FROM ROW
    MOFA: Completed
    Doc Submission: Pending
    Deposit: Not Applicable
    Claim: Not Applicable
    Approval if Required: N/A

So this patch reads those lines back out and puts them in the new fields. All 46
rows agree -- Deposit and Claim are "Not Applicable" on every one, Approval is
"N/A" on every one -- but the values are parsed per row rather than assumed, so
the day one of them says something else it is carried across correctly.

MOFA AND DOC SUBMISSION ARE DELIBERATELY NOT BACKFILLED. They already migrated
into their own fields (28 and 38 of 46). Checked before writing this: of the 18
rows with no MOFA and the 8 with no Doc Submission, remarks supplies a value for
ZERO of them -- those are blank in the workbook too. Re-parsing would only risk
overwriting good structured values with the workbook's messier casing
("COMPLETED", "completed", "PENDING").

REMARKS IS NOT TOUCHED. It is the only copy of the original import and costs
nothing to keep.

A value is only written if it is one the field actually offers. A Select holding
something outside its own options renders blank and can be saved back as blank --
that happened on this site once already with the Docs -> Docs received rename.

Safe to re-run: create_custom_field is a no-op when the field exists, and a row
whose field is already set is skipped.
"""

import re

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

TRACKER = "Customs Tracker"

STATUS_OPTIONS = "\nNot Applicable\nPending\nCompleted"

NEW_FIELDS = (
	{
		"fieldname": "fps_deposit_status",
		"label": "Deposit",
		"fieldtype": "Select",
		"options": STATUS_OPTIONS,
		"insert_after": "fps_duty_paid_on",
		"description": "Customs deposit, where one is payable. The date it was paid is the field above.",
	},
	{
		"fieldname": "fps_approval_required",
		"label": "Approval if required",
		"fieldtype": "Data",
		"insert_after": "fps_deposit_claim",
		"description": "Any permit or approval this declaration needed. N/A when none applies.",
	},
)

# remarks line -> (fieldname, is a Select)
BACKFILL = (
	("Deposit", "fps_deposit_status", True),
	("Claim", "fps_deposit_claim", True),
	("Approval if Required", "fps_approval_required", False),
)

LINE = re.compile(r"^\s*(Deposit|Claim|Approval if Required)\s*:?\s*(.*)$", re.I)


def execute():
	if not frappe.db.exists("DocType", TRACKER):
		return

	_add_fields()
	frappe.clear_cache(doctype=TRACKER)
	_backfill_from_remarks()
	frappe.clear_cache(doctype=TRACKER)


def _add_fields():
	fieldnames = [f.fieldname for f in frappe.get_meta(TRACKER).fields]
	for spec in NEW_FIELDS:
		if spec["fieldname"] in fieldnames:
			continue
		if spec["insert_after"] not in fieldnames:
			# Do not guess a position; a field dropped at the end of a form is
			# worse than one that is reported and placed by hand.
			frappe.log_error(
				title="FPS: %s has no %s, %s not added"
				% (TRACKER, spec["insert_after"], spec["fieldname"])
			)
			continue
		try:
			create_custom_field(TRACKER, dict(spec), ignore_validate=True)
		except Exception:
			frappe.log_error(title="FPS: could not add %s" % spec["fieldname"])


def _allowed(fieldname):
	"""The values this Select actually offers, after Property Setters."""
	df = frappe.get_meta(TRACKER).get_field(fieldname)
	if not df or not df.options:
		return set()
	return {o.strip() for o in df.options.split("\n") if o.strip()}


def _backfill_from_remarks():
	meta_fields = [f.fieldname for f in frappe.get_meta(TRACKER).fields]
	targets = [(key, fn, sel) for key, fn, sel in BACKFILL if fn in meta_fields]
	if not targets:
		return

	allowed = {fn: _allowed(fn) for _key, fn, sel in targets if sel}

	rows = frappe.get_all(
		TRACKER,
		fields=["name", "remarks"] + [fn for _k, fn, _s in targets],
		limit_page_length=0,
	)

	filled = 0
	for row in rows:
		if not row.get("remarks"):
			continue

		found = {}
		for line in row["remarks"].split("\n"):
			match = LINE.match(line)
			if match:
				found[match.group(1).strip().lower()] = match.group(2).strip()

		update = {}
		for key, fieldname, is_select in targets:
			if row.get(fieldname):
				continue  # never overwrite a value someone set by hand
			value = found.get(key.lower())
			if not value:
				continue
			if is_select and value not in allowed.get(fieldname, set()):
				frappe.log_error(
					title="FPS: %s not an option for %s (%s)"
					% (value, fieldname, row["name"])
				)
				continue
			update[fieldname] = value

		if update:
			frappe.db.set_value(TRACKER, row["name"], update, update_modified=False)
			filled += 1

	if filled:
		frappe.db.commit()
	frappe.logger().info("FPS: filled sheet columns on %d customs trackers" % filled)
