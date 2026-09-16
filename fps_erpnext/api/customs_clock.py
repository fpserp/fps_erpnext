"""Date arithmetic for the customs chase clocks. Pure Python, no frappe import.

Everything here takes plain values or dict-like records (a frappe Document, a
frappe._dict, a plain dict) and returns plain dates and strings, so the rules can
be checked with a bare `python` and no bench -- see
fps_erpnext/tests/test_customs_clock.py. fps_erpnext.api.customs wraps these for
the hooks, the backfill and the board; nothing else should redo the arithmetic.

WHICH DATE EACH CLOCK COUNTS FROM (Agam, 16 Sep 2026: "Change ERPNext to match")

    Document submission   declaration date + 30   = Dubai Customs' Fine Start Date
    MOFA attestation      clearance date   + 14   (unchanged)

Dubai Customs fines the late submission of original documents from Declaration
Date + 30 days, that day included, at AED 5 a day; the last fine-free day is
declaration + 29. The declaration date is `ct_date` (Mirsal box 2, "BOE date" on
the declaration row). So fps_doc_deadline IS the Fine Start Date: the originals
have to be in BEFORE it. When a cleared declaration has no ct_date, the clock
falls back to the clearance date, which is what ERPNext counted from before.

ONLY AN APPROVED DECLARATION STARTS A CLOCK. A declaration counts as approved
when it has a clearance date or its status is Cleared. A pending one has no
deadline at all, whatever dates it carries.

The warn/late thresholds are days ELAPSED since the same date the deadline
counts from, which is how operations describe them ("yellow after 15 days").
"""

from datetime import date, datetime, timedelta

# key, the field it writes, the status that closes it, the dates it counts from
# (first one present wins), and the day counts. `days` is the deadline itself;
# `warn` and `late` are days elapsed since the start date.
#
# The same four thresholds are repeated in the client script
# docs/design_handoff_fps_workspace/client_scripts/customs_tracker_deadlines.js
# (a form has to recolour itself without a server round trip). Change both.
DEADLINES = (
	{
		"key": "doc",
		"date_field": "fps_doc_deadline",
		"status_field": "fps_doc_submission",
		"from": ("ct_date", "clearance_date"),
		"days": 30,
		"warn": 15,
		"late": 25,
	},
	{
		"key": "mofa",
		"date_field": "fps_mofa_deadline",
		"status_field": "fps_mofa_status",
		"from": ("clearance_date",),
		"days": 14,
		"warn": 9,
		"late": 12,
	},
)

# Every date field any clock can count from, plus what decides "approved".
# Callers that read records for these helpers fetch at least these.
CLOCK_FIELDS = ("ct_date", "clearance_date", "status")

# Compared case-insensitively. "Submitted" is here as well as "Completed"
# because it was the old wording for the same state on Document submission --
# harmless once those rows are migrated, and it keeps the clock stopped for any
# that are not.
DONE_VALUES = {"completed", "not applicable", "n/a", "submitted"}

CLEARED = "cleared"

# Worst last, so max() over the index picks the state that needs most attention.
LIVE_STATES = ("ok", "warn", "late")


def to_date(value):
	"""date | None from a date, a datetime, or a 'YYYY-MM-DD[ ...]' string."""
	if not value:
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()


def _get(record, field):
	getter = getattr(record, "get", None)
	if callable(getter):
		return getter(field)
	return getattr(record, field, None)


def is_done(status):
	return (status or "").strip().lower() in DONE_VALUES


def is_cleared(record):
	"""An approved declaration: it has a clearance date, or its status is Cleared."""
	return bool(to_date(_get(record, "clearance_date"))) or (
		(_get(record, "status") or "").strip().lower() == CLEARED)


def clock_start(record, spec):
	"""The date this clock counts from, or None when no clock is running."""
	if not is_cleared(record):
		return None
	for field in spec["from"]:
		start = to_date(_get(record, field))
		if start:
			return start
	return None


def deadline_for(record, spec):
	"""The deadline date this record should carry for one clock, or None."""
	start = clock_start(record, spec)
	return start + timedelta(days=spec["days"]) if start else None


def state_from_start(start, spec, as_of):
	""" '' | 'ok' | 'warn' | 'late' for a clock that started on `start`."""
	if not start:
		return ""
	elapsed = (to_date(as_of) - start).days
	if elapsed >= spec["late"]:
		return "late"
	if elapsed >= spec["warn"]:
		return "warn"
	return "ok"


def deadline_state(record, spec, as_of=None):
	"""'' | 'done' | 'ok' | 'warn' | 'late' for one clock on one declaration.

	Returns '' when there is nothing to chase -- no approved declaration, no
	clock. The caller renders '' as an empty cell, not as a green one.
	"""
	if is_done(_get(record, spec["status_field"])):
		return "done"
	return state_from_start(clock_start(record, spec), spec, as_of or date.today())


def rollup_deadline(rows, spec):
	"""The parent's date for one clock, from rows that already carry theirs.

	The nearest date still worth chasing; if every row is settled, the latest
	one, so the date is still visible rather than blank.
	"""
	live = [to_date(_get(r, spec["date_field"])) for r in rows
	        if _get(r, spec["date_field"]) and not is_done(_get(r, spec["status_field"]))]
	done = [to_date(_get(r, spec["date_field"])) for r in rows
	        if _get(r, spec["date_field"])]
	return min(live) if live else (max(done) if done else None)


def parent_deadline(parent, rows, spec):
	"""What the parent's date for one clock should be.

	With declaration rows: rollup_deadline over the rows' own dates, each
	computed by deadline_for. Without rows (a tracker from before the table, or
	one still being filled in): the parent is its own declaration.
	"""
	if not rows:
		return deadline_for(parent, spec)
	dated = []
	for row in rows:
		dated.append({
			spec["date_field"]: deadline_for(row, spec),
			spec["status_field"]: _get(row, spec["status_field"]),
		})
	return rollup_deadline(dated, spec)


def parent_state(parent, rows, spec, as_of=None):
	"""The colour of the parent's date for one clock.

	The parent's date belongs to its nearest outstanding row, and every row of
	one clock shares the same thresholds, so the nearest date is also the one
	with the most days elapsed: the parent takes its WORST live row's state.
	Counting from the parent's own ct_date would be wrong -- on a new tracker
	that is the job order date, and on a two-leg job it is the first leg's.
	"""
	as_of = as_of or date.today()
	if is_done(_get(parent, spec["status_field"])):
		return "done"
	if not rows:
		return deadline_state(parent, spec, as_of)
	live = [deadline_state(r, spec, as_of) for r in rows]
	live = [s for s in live if s in LIVE_STATES]
	if not live:
		return ""
	return max(live, key=LIVE_STATES.index)
