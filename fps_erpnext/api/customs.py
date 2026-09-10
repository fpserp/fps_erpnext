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


def set_deadlines(doc, method=None):
	"""validate hook: derive both deadline dates from the clearance date."""
	clearance = doc.get("clearance_date")
	for spec in DEADLINES:
		# The Custom Field may not exist yet -- this hook is registered in
		# hooks.py, which the running workers pick up the moment the app is
		# deployed, while the field arrives with the patch a few seconds later.
		# Saving a tracker must not fail in that window.
		if not doc.meta.get_field(spec["date_field"]):
			continue
		doc.set(spec["date_field"],
		        add_days(getdate(clearance), spec["days"]) if clearance else None)


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
