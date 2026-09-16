"""Customs Tracker chase clocks: document submission and MOFA attestation.

Two dates per declaration, each shown in the colour of how much rope is left:

    Document submission   due declaration + 30 days   amber from day 15, red from day 25
    MOFA attestation      due clearance   + 14 days   amber from day  9, red from day 12

THE DOCUMENT CLOCK FOLLOWS DUBAI CUSTOMS (Agam, 16 Sep 2026). Dubai Customs fines
late original documents from Declaration Date + 30 days, that day included, at
AED 5 a day. fps_doc_deadline is therefore that Fine Start Date, counted from
ct_date (the declaration date, Mirsal box 2) -- not from the clearance date,
which ops may enter days later (FPS/CT/2609/082: declared 04 Sep, cleared 10 Sep,
fines from 04 Oct, not 10 Oct). A cleared declaration with no ct_date falls back
to clearance + 30. The last fine-free day is the deadline minus one. The MOFA
clock was not part of that decision and still counts from clearance.

THE CLOCK STOPS WHEN THE WORK IS DONE. A tracker whose Document submission or
MOFA attestation reads "Completed" is finished, and so is one reading
"Not Applicable" / "N/A" -- chasing an attestation that was never required is
noise, not diligence. Both are treated as done and lose their colour.

ONLY AN APPROVED DECLARATION STARTS A CLOCK. One that has not cleared yet (no
clearance date, status not Cleared) gets no dates at all, rather than a deadline
counted from a pending declaration or the entry date that invents urgency.

THE RULES LIVE IN fps_erpnext/api/customs_clock.py -- pure Python, so they can be
tested without a bench -- and are used in three places: the deadline dates
written on save, the colours on the customs board, and the colours on the form.
The board takes the STATE from here rather than recomputing it, so there is one
definition of "amber" on the site. The one exception is the client script, which
cannot import Python; it carries the same numbers and the same "count from"
dates with a comment pointing here, because a form has to colour itself without
a server round trip on every keystroke.
"""

import frappe

from fps_erpnext.api.customs_clock import (  # noqa: F401 -- re-exported
	CLOCK_FIELDS,
	DEADLINES,
	DONE_VALUES,
	deadline_for,
	parent_deadline,
	parent_state,
	rollup_deadline,
	to_date,
)
from fps_erpnext.api.customs_clock import deadline_state as _deadline_state

TRACKER = "Customs Tracker"
CHILD = "FPS Customs Declaration"


def deadline_state(record, spec, as_of=None):
	"""'' | 'done' | 'ok' | 'warn' | 'late' for one clock on one declaration.

	`record` is anything with .get() carrying the clock's status field and
	ct_date / clearance_date / status. Returns '' when there is nothing to
	chase. For a Customs Tracker PARENT use parent_state, which colours the
	date by the declaration row it came from.
	"""
	return _deadline_state(record, spec, as_of or frappe.utils.today())


def _specs(keys=None):
	return [s for s in DEADLINES if keys is None or s["key"] in keys]


def backfill_deadlines(keys=None):
	"""Recompute the deadline dates on every declaration row and every tracker.

	`keys` limits it to some clocks ("doc", "mofa"); None means all. Returns
	{"rows": n, "parents": n, "changes": [...]} -- only values that actually
	differ are written, so a re-run changes nothing.

	Used by the patches. Writes with db.set_value rather than doc.save() so the
	trackers do not each fire the Customs Tracker save hooks -- CT BOE to Job
	Order writes back onto the Job Order, and re-running it across the whole
	table to set a derived date would be a lot of side effect for no gain. The
	parent value comes from customs_clock.parent_deadline, the same rollup the
	validate hook uses, so a backfilled tracker and a freshly saved one agree.
	"""
	specs = _specs(keys)
	tracker_meta = frappe.get_meta(TRACKER)
	specs = [s for s in specs if tracker_meta.get_field(s["date_field"])]
	if not specs:
		return {"rows": 0, "parents": 0, "changes": []}

	status_fields = [s["status_field"] for s in specs]
	date_fields = [s["date_field"] for s in specs]

	parents = frappe.get_all(
		TRACKER,
		fields=["name"] + list(CLOCK_FIELDS) + status_fields + date_fields,
		limit_page_length=0,
	)

	# Before the declarations table exists (a fresh install runs the older
	# deadline patch first) every tracker is its own declaration.
	rows_by_parent = {}
	has_table = bool(tracker_meta.get_field(DECLARATIONS))
	if has_table and frappe.db.exists("DocType", CHILD):
		child_meta = frappe.get_meta(CHILD)
		child_specs = [s for s in specs if child_meta.get_field(s["date_field"])]
		for row in frappe.get_all(
			CHILD,
			filters={"parenttype": TRACKER, "parentfield": DECLARATIONS},
			fields=["name", "parent", "idx"] + list(CLOCK_FIELDS)
			+ [s["status_field"] for s in child_specs]
			+ [s["date_field"] for s in child_specs],
			order_by="parent asc, idx asc",
			limit_page_length=0,
		):
			rows_by_parent.setdefault(row.parent, []).append(row)
	else:
		child_specs = []

	changes = []
	rows_changed = parents_changed = 0

	for parent in parents:
		rows = rows_by_parent.get(parent.name, [])

		for row in rows:
			update = {}
			for spec in child_specs:
				wanted = deadline_for(row, spec)
				current = to_date(row.get(spec["date_field"]))
				if wanted != current:
					update[spec["date_field"]] = wanted
					changes.append((parent.name, row.name, spec["date_field"], current, wanted))
			if update:
				frappe.db.set_value(CHILD, row.name, update, update_modified=False)
				rows_changed += 1

		update = {}
		for spec in specs:
			wanted = parent_deadline(parent, rows, spec)
			current = to_date(parent.get(spec["date_field"]))
			if wanted != current:
				update[spec["date_field"]] = wanted
				changes.append((parent.name, None, spec["date_field"], current, wanted))
		if update:
			frappe.db.set_value(TRACKER, parent.name, update, update_modified=False)
			parents_changed += 1

	return {"rows": rows_changed, "parents": parents_changed, "changes": changes}


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

	Each BOE is declared and clears on its own dates and so carries its own two
	clocks, each counted from the date its spec names (customs_clock.DEADLINES,
	"from"). The parent's pair is the nearest one still outstanding.
	"""
	rows = _rows(doc)

	for row in rows:
		for spec in DEADLINES:
			# The Custom Field may not exist yet: hooks.py is live the moment the
			# app deploys, while the fields arrive with the patch seconds later.
			# Saving a tracker must not fail in that window.
			if not row.meta.get_field(spec["date_field"]):
				continue
			row.set(spec["date_field"], deadline_for(row, spec))

	if not rows:
		# No declarations yet -- a tracker created before the table existed, or
		# one still being filled in. The parent is its own declaration: its own
		# ct_date / clearance_date / status, same rule as a row.
		for spec in DEADLINES:
			if not doc.meta.get_field(spec["date_field"]):
				continue
			doc.set(spec["date_field"], deadline_for(doc, spec))
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
	# the earlier BOE's. The clocks do not read this: each row runs its own.
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
	# one, so the date is still visible rather than blank. The rows already
	# carry their own dates (set_deadlines, or the migration that inserted them).
	for spec in DEADLINES:
		if not doc.meta.get_field(spec["date_field"]):
			continue
		doc.set(spec["date_field"], rollup_deadline(rows, spec))
