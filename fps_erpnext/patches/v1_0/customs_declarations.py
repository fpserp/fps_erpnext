"""One Customs Tracker per job, with every BOE as a row inside it.

A job can clear on more than one declaration -- an FZ transfer followed by an
import to local is the standard pair. That used to mean two whole Customs
Tracker documents for one job, told apart only by a "Leg no." field, and there
was no way to record a second BOE inside a tracker. Four live jobs are in that
shape: 2607/020, 2607/025, 2607/027 and 2608/065.

The tracker is now the JOB. Each BOE is a row in `fps_declarations`.

WHAT THIS DOES, IN ORDER

 1. Adds the fps_declarations table to Customs Tracker.
 2. Turns every existing tracker into ONE declaration row holding its own BOE,
    type, dates, MOFA, doc submission, deposit, claim and remarks. Nothing is
    read from anywhere but the tracker it came from.
 3. Merges the four two-leg jobs: the leg-2 tracker's row is appended to the
    leg-1 tracker, in leg order, and the now-empty leg-2 tracker is deleted --
    through frappe.delete_doc without force, so it is archived to Deleted
    Document and can be restored.
 4. Rolls each parent up from its rows.

48 trackers become 44, holding 48 declarations between them. No declaration is
lost; four documents stop existing.

THE PARENT IS NOW A SUMMARY. boe_number becomes "5020033112626, 1020044973726",
clearance_date the date the LAST declaration cleared, and the four chase columns
show whichever row still needs work. That is what keeps the board, the list and
the print formats working without any of them knowing the table exists.

NO PARENT IS SAVED. Rows are inserted directly and the rolled-up values are
written with db.set_value, so the "CT BOE to Job Order" script -- which fires on
Customs Tracker save and writes back onto the Job Order -- cannot run 48 times
against half-migrated data. The rollup itself is computed by calling the same
fps_erpnext.api.customs.rollup_declarations the live hook uses, so a migrated
tracker and a freshly saved one agree by construction.

Safe to re-run: a tracker that already has rows is skipped.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.utils import add_days, getdate

from fps_erpnext.api.customs import DEADLINES, DECLARATIONS, rollup_declarations

TRACKER = "Customs Tracker"
CHILD = "FPS Customs Declaration"

# A Table inside a column break is rendered at that column's width -- roughly a
# fifth of the page, which is unusable for a grid with five columns of its own.
# Its OWN Section Break gives it the full width.
SECTION_FIELD = {
	"fieldname": "fps_declarations_sec",
	"fieldtype": "Section Break",
	"label": "Declarations",
	"insert_after": "boe_number",
	"description": "One row per BOE. A job that clears on two declarations has two rows.",
}

TABLE_FIELD = {
	"fieldname": DECLARATIONS,
	"fieldtype": "Table",
	"label": "Declarations",
	"options": CHILD,
	"insert_after": "fps_declarations_sec",
}

# Copied straight across from the tracker to its first declaration row.
CARRY = (
	"boe_number", "ct_date", "status", "clearance_date", "fps_leg",
	"fps_clearance_type", "fps_clearance_location", "fps_mofa_status",
	"fps_doc_submission", "fps_do_status", "fps_duty_paid_on",
	"fps_deposit_status", "fps_deposit_claim",
	"customs_value", "duty_amount", "vat_amount", "remarks",
)

# The rolled-up fields this patch writes back onto the parent.
ROLLED_UP = (
	"boe_number", "clearance_date", "status",
	"fps_clearance_type", "fps_clearance_location",
	"fps_mofa_status", "fps_doc_submission",
	"fps_deposit_status", "fps_deposit_claim",
	"fps_doc_deadline", "fps_mofa_deadline",
)


def execute():
	if not (frappe.db.exists("DocType", TRACKER) and frappe.db.exists("DocType", CHILD)):
		return

	_add_table()
	frappe.clear_cache(doctype=TRACKER)

	if DECLARATIONS not in [f.fieldname for f in frappe.get_meta(TRACKER).fields]:
		frappe.log_error(title="FPS: fps_declarations missing, declarations not migrated")
		return

	created = _seed_rows()
	merged = _merge_legs()
	rolled = _rollup_all()

	frappe.db.commit()
	frappe.clear_cache(doctype=TRACKER)
	frappe.logger().info(
		"FPS: %d declarations created, %d leg trackers merged, %d parents rolled up"
		% (created, merged, rolled)
	)


def _add_table():
	"""Section first, then the table inside it -- order matters, the table
	anchors on the section."""
	for spec in (SECTION_FIELD, TABLE_FIELD):
		fieldnames = [f.fieldname for f in frappe.get_meta(TRACKER).fields]
		if spec["fieldname"] in fieldnames:
			continue
		if spec["insert_after"] not in fieldnames:
			frappe.log_error(
				title="FPS: %s has no %s, %s not added"
				% (TRACKER, spec["insert_after"], spec["fieldname"])
			)
			continue
		try:
			create_custom_field(TRACKER, dict(spec), ignore_validate=True)
			frappe.clear_cache(doctype=TRACKER)
		except Exception:
			frappe.log_error(title="FPS: could not add %s" % spec["fieldname"])


def _deadlines_for(clearance_date):
	out = {}
	for spec in DEADLINES:
		out[spec["date_field"]] = (add_days(getdate(clearance_date), spec["days"])
		                           if clearance_date else None)
	return out


def _insert_row(parent, source, idx):
	"""One declaration, inserted directly so the parent is never saved."""
	row = {
		"doctype": CHILD,
		"parent": parent,
		"parenttype": TRACKER,
		"parentfield": DECLARATIONS,
		"idx": idx,
	}
	for field in CARRY:
		row[field] = source.get(field)
	row["fps_leg"] = source.get("fps_leg") or 1
	row.update(_deadlines_for(source.get("clearance_date")))
	frappe.get_doc(row).insert(ignore_permissions=True)


def _seed_rows():
	rows = frappe.get_all(TRACKER, fields=["name"] + list(CARRY), limit_page_length=0)
	created = 0
	for tracker in rows:
		if frappe.db.exists(CHILD, {"parenttype": TRACKER, "parent": tracker.name}):
			continue
		try:
			_insert_row(tracker.name, tracker, 1)
			created += 1
		except Exception:
			frappe.log_error(title="FPS: could not seed declaration for %s" % tracker.name)
	return created


def _merge_legs():
	"""Fold every extra tracker of a job into the job's first tracker."""
	by_job = {}
	for row in frappe.get_all(
		TRACKER,
		fields=["name", "job_order", "fps_leg", "creation"],
		order_by="job_order asc, fps_leg asc, creation asc",
		limit_page_length=0,
	):
		if row.job_order:
			by_job.setdefault(row.job_order, []).append(row)

	merged = 0
	for job, trackers in by_job.items():
		if len(trackers) < 2:
			continue
		keeper = trackers[0]
		try:
			for extra in trackers[1:]:
				existing = frappe.get_all(
					CHILD,
					filters={"parenttype": TRACKER, "parent": keeper.name},
					fields=["name"],
				)
				idx = len(existing)
				for child in frappe.get_all(
					CHILD,
					filters={"parenttype": TRACKER, "parent": extra.name},
					fields=["name"] + list(CARRY),
					order_by="idx asc",
				):
					idx += 1
					_insert_row(keeper.name, child, idx)

				# No force: the emptied tracker is archived, not destroyed.
				frappe.delete_doc(TRACKER, extra.name, ignore_permissions=True,
				                  ignore_missing=True)
				merged += 1
		except Exception:
			frappe.log_error(title="FPS: could not merge customs legs for %s" % job)

	return merged


def _rollup_all():
	"""Recompute each parent from its rows, using the live hook's own logic."""
	rolled = 0
	for name in frappe.get_all(TRACKER, pluck="name", limit_page_length=0):
		try:
			doc = frappe.get_doc(TRACKER, name)
			if not doc.get(DECLARATIONS):
				continue
			rollup_declarations(doc)
			update = {f: doc.get(f) for f in ROLLED_UP if doc.meta.get_field(f)}
			frappe.db.set_value(TRACKER, name, update, update_modified=False)
			rolled += 1
		except Exception:
			frappe.log_error(title="FPS: could not roll up %s" % name)
	return rolled
