"""Customs Tracker chase clocks: document submission and MOFA attestation.

Dubai Customs gives you a window after a declaration clears. Miss it and the
deposit is at risk, so the two dates that matter are derived from the clearance
date and shown in the colour of how much rope is left:

    Document submission   due clearance + 30 days   amber from day 15, red from day 25
    MOFA attestation      due clearance + 14 days   amber from day  9, red from day 12

THE CLOCK STOPS WHEN THE WORK IS DONE. A tracker whose Document submission or
MOFA attestation reads "Completed" is finished, and so is one reading
"Not Applicable" / "N/A" -- chasing an attestation that was never required is
noise, not diligence. Both are treated as done and lose their colour.

NO CLEARANCE DATE, NO DEADLINE. A declaration that has not cleared yet has
nothing to count from, so both fields stay empty rather than counting from the
entry date and inventing urgency. Two of the 48 live trackers are in that state.

THE THRESHOLDS LIVE HERE AND ARE USED IN THREE PLACES -- the deadline dates
written on save, the colours on the customs board, and the colours on the form.
The board and the form both take the STATE from this module rather than
recomputing it, so there is one definition of "amber" on the site. The one
exception is the client script, which cannot import Python; it carries the same
four numbers with a comment pointing here, because a form has to colour itself
without a server round trip on every keystroke.
"""

import frappe
from frappe.utils import add_days, date_diff, getdate, today

# key, the field it writes, the status that closes it, and the day counts.
# `days` is the deadline itself; `warn` and `late` are days ELAPSED since
# clearance, which is how operations describe them ("yellow after 15 days").
DEADLINES = (
	{
		"key": "doc",
		"date_field": "fps_doc_deadline",
		"status_field": "fps_doc_submission",
		"days": 30,
		"warn": 15,
		"late": 25,
	},
	{
		"key": "mofa",
		"date_field": "fps_mofa_deadline",
		"status_field": "fps_mofa_status",
		"days": 14,
		"warn": 9,
		"late": 12,
	},
)

# Compared case-insensitively. "Submitted" is here as well as "Completed"
# because it was the old wording for the same state on Document submission --
# harmless once those rows are migrated, and it keeps the clock stopped for any
# that are not.
DONE_VALUES = {"completed", "not applicable", "n/a", "submitted"}


def deadline_state(clearance_date, status, spec, as_of=None):
	"""'' | 'done' | 'ok' | 'warn' | 'late' for one deadline on one tracker.

	Returns '' when there is nothing to chase -- no clearance date means no
	clock. The caller renders '' as an empty cell, not as a green one.
	"""
	if (status or "").strip().lower() in DONE_VALUES:
		return "done"
	if not clearance_date:
		return ""

	elapsed = date_diff(getdate(as_of or today()), getdate(clearance_date))
	if elapsed >= spec["late"]:
		return "late"
	if elapsed >= spec["warn"]:
		return "warn"
	return "ok"


def backfill_deadlines():
	"""Write both deadline dates onto every existing tracker.

	Used by the patch. Writes with db.set_value rather than doc.save() so the
	46 rows do not each fire the Customs Tracker save hooks -- CT BOE to Job
	Order writes back onto the Job Order, and re-running it across the whole
	table to set a derived date would be a lot of side effect for no gain.
	"""
	rows = frappe.get_all(
		"Customs Tracker",
		fields=["name", "clearance_date"] + [s["date_field"] for s in DEADLINES],
		limit_page_length=0,
	)

	changed = 0
	for row in rows:
		update = {}
		for spec in DEADLINES:
			wanted = (add_days(getdate(row.clearance_date), spec["days"])
			          if row.clearance_date else None)
			current = row.get(spec["date_field"])
			current = getdate(current) if current else None
			if wanted != current:
				update[spec["date_field"]] = wanted
		if update:
			frappe.db.set_value("Customs Tracker", row["name"], update,
			                    update_modified=False)
			changed += 1

	return changed


# ==========================================================================
# Declarations
#
# A job can clear on more than one BOE -- an FZ transfer and then an import to
# local is the common pair, and four live jobs are in that shape. That used to
# mean two whole Customs Tracker documents told apart by a "Leg no." field.
# The tracker is now the JOB and each BOE is a row in `fps_declarations`.
#
# THE PARENT BECOMES A SUMMARY OF ITS ROWS. Its boe_number, clearance_date,
# status and the four chase columns are rolled up here on every save, so
# everything that already reads the parent -- the board, the list, the print
# formats -- keeps working without knowing the table exists.
# ==========================================================================

DECLARATIONS = "fps_declarations"

# Worst-first. The parent shows what still needs chasing, so the first row that
# is NOT done wins; only when every row is done does the last row's value show.
ROLLUP_STATUS_FIELDS = (
	"fps_mofa_status",
	"fps_doc_submission",
	"fps_deposit_status",
	"fps_deposit_claim",
)

# Ordered by how much attention the job needs.
STATUS_PRIORITY = ("On Hold", "Delayed", "Pending", "In Process", "Cleared")


def _rows(doc):
	return [r for r in (doc.get(DECLARATIONS) or [])]


def set_deadlines(doc, method=None):
	"""validate hook: deadlines on every declaration, then roll the parent up.

	Each BOE clears on its own date and so carries its own two clocks. The
	parent's pair is the nearest one still outstanding.
	"""
	rows = _rows(doc)

	for row in rows:
		for spec in DEADLINES:
			# The Custom Field may not exist yet: hooks.py is live the moment the
			# app deploys, while the fields arrive with the patch seconds later.
			# Saving a tracker must not fail in that window.
			if not row.meta.get_field(spec["date_field"]):
				continue
			row.set(spec["date_field"],
			        add_days(getdate(row.clearance_date), spec["days"])
			        if row.get("clearance_date") else None)

	if not rows:
		# No declarations yet -- a tracker created before the table existed, or
		# one still being filled in. Fall back to the parent's own clearance
		# date rather than blanking fields that are in use.
		clearance = doc.get("clearance_date")
		for spec in DEADLINES:
			if not doc.meta.get_field(spec["date_field"]):
				continue
			doc.set(spec["date_field"],
			        add_days(getdate(clearance), spec["days"]) if clearance else None)
		return

	rollup_declarations(doc)


def rollup_declarations(doc):
	"""Summarise the declaration rows onto the parent."""
	rows = _rows(doc)
	if not rows:
		return

	boes = [r.boe_number for r in rows if r.get("boe_number")]
	if boes:
		doc.boe_number = ", ".join(boes)

	# The job is cleared on the day the LAST of its declarations clears, and not
	# before -- so a part-cleared job shows no clearance date at all rather than
	# the earlier BOE's, which would start both clocks too soon.
	dates = [r.clearance_date for r in rows if r.get("clearance_date")]
	doc.clearance_date = max(dates) if len(dates) == len(rows) else None

	statuses = [r.status for r in rows if r.get("status")]
	if statuses:
		for candidate in STATUS_PRIORITY:
			if candidate in statuses:
				doc.status = candidate
				break

	# The last declaration is what the consignment finally became -- an FZ
	# transfer followed by an import to local is an import, not a transfer.
	last = rows[-1]
	for field in ("fps_clearance_type", "fps_clearance_location"):
		if last.get(field):
			doc.set(field, last.get(field))

	for field in ROLLUP_STATUS_FIELDS:
		if not doc.meta.get_field(field):
			continue
		outstanding = [r.get(field) for r in rows
		               if (r.get(field) or "").strip().lower() not in DONE_VALUES]
		if outstanding:
			doc.set(field, outstanding[0])
		else:
			doc.set(field, last.get(field))

	# Nearest deadline still worth chasing; if every row is settled, the latest
	# one, so the date is still visible rather than blank.
	for spec in DEADLINES:
		if not doc.meta.get_field(spec["date_field"]):
			continue
		live = [r.get(spec["date_field"]) for r in rows
		        if r.get(spec["date_field"])
		        and (r.get(spec["status_field"]) or "").strip().lower() not in DONE_VALUES]
		done = [r.get(spec["date_field"]) for r in rows if r.get(spec["date_field"])]
		doc.set(spec["date_field"],
		        min(live) if live else (max(done) if done else None))
