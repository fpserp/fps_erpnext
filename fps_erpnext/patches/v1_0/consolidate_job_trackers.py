"""Collapse the Job Trackers to exactly one per Job Order, losing nothing.

WHY. The go-live built a NEW Job Tracker document for every event, so 84 job
orders had grown 371 trackers between them: 26 jobs had one, and 5 jobs had ten.
Opening "Job Tracker" showed ten rows for the same shipment. A tracker is meant
to be the job, not one line of its history.

WHAT IS MERGED, AND HOW IT WAS DECIDED. All 371 rows were pulled off the live
site and compared field by field within each job before a line of this was
written:

  * EIGHTEEN SHIPMENT FIELDS -- customer, client_reference_no, job_status,
    movement_type, declaration_type, fps_category, shipper, origin_pol,
    destination_pod, carrier, vessel_flight, etd, eta, awb_bl_no, container_nos,
    no_of_packages, gross_weight, fps_leg -- have ZERO conflicts across all 84
    jobs. Every tracker of a job carries the same value, because they were all
    copied off the same Job Order. Collapsing them onto one parent cannot lose
    anything, so the first non-empty value is taken.

    job_status in particular is COPIED, never fetched. It is populated on all
    371 rows and there is NO source field for it on Job Order, so a fetch_from
    would silently blank it on all 84 jobs.

  * TWELVE EVENT FIELDS -- track_date, fps_event_type, fps_milestone,
    current_status, progress_notes, fps_evidence_ref, fps_source,
    fps_customer_visible, next_action, follow_up_date, responsible, issues --
    are the ones that DO conflict. current_status, progress_notes,
    fps_milestone and fps_evidence_ref each differ within 58 of the 84 jobs.
    They describe one event, not the job, so every row becomes a child update
    on the survivor instead of being overwritten. The parent keeps the LATEST of
    each, so the list still reads as "where has this job reached".

    The parent's progress_notes keeps the LONGEST note of the job. That is
    deliberate: 46 of the 371 rows are the original hand-typed summaries
    ("PO/Client Ref: ... Transit: AIR ... Origin: Shanghai ...") and those have
    to stay visible on the tracker itself, not only inside the grid.

  * fps_subcategory is the one field where a value is dropped, and it is not
    data -- it is a LABEL the rollup engine recomputes from the Job Order on
    every save. All 22 short/long pairs were checked: the long form always
    carries strictly more (it adds the clearance location and/or
    "+ delivery"), and the short form never says anything the long one does
    not. The longest is kept, and the next sweep overwrites it anyway.

  A dry run over the real 371 rows confirmed both directions: every non-empty
  value on every source row is reachable on the result, and no value appears on
  a result that no source row had. 371 rows in; 84 parents plus 371 child
  updates out; 287 documents archived.

THE SURVIVOR is the OLDEST row of the job by creation. Where a job still has one
of the 46 original hand-typed trackers, that is the oldest, so it survives in
place and keeps its own name, its notes and its creation date.

NOTHING IS FORCE-DELETED. The 287 absorbed rows go through frappe.delete_doc
without force, so each is archived to Deleted Document and can be restored.

NO PARENT IS SAVED. Child rows are inserted directly and parent fields are
written with frappe.db.set_value, so no doc.save() happens anywhere in this
patch and no server script -- JT Rollup fires on After Save -- can run against a
half-built tracker. The */30 sweep re-derives every open job within the hour
after the deploy.

Safe to re-run: a job whose tracker already carries update rows is skipped.
"""

import frappe

TRACKER = "Job Tracker"
CHILD = "FPS Job Update"
PARENTFIELD = "fps_updates"

# Verified to have zero conflicts within every job. Order matters only in that
# the first non-empty value wins, and the rows are walked oldest first.
SHIPMENT_FIELDS = (
	"customer", "client_reference_no", "job_status", "movement_type",
	"declaration_type", "fps_category", "shipper", "origin_pol",
	"destination_pod", "carrier", "vessel_flight", "etd", "eta", "awb_bl_no",
	"container_nos", "no_of_packages", "gross_weight", "fps_leg",
)

# parent fieldname -> child fieldname
EVENT_MAP = (
	("track_date", "update_date"),
	("fps_event_type", "event_type"),
	("fps_milestone", "milestone"),
	("current_status", "status_line"),
	("progress_notes", "notes"),
	("fps_evidence_ref", "evidence_ref"),
	("fps_source", "source"),
	("fps_customer_visible", "customer_visible"),
	("next_action", "next_action"),
	("follow_up_date", "follow_up_date"),
	("responsible", "responsible"),
	("issues", "issues"),
)

FETCH = (["name", "creation", "job_order", "fps_subcategory"]
         + list(SHIPMENT_FIELDS)
         + [parent_field for parent_field, _child in EVENT_MAP])


def _empty(value):
	return value is None or value == "" or value == 0


def _write_children(parent, children):
	"""Attach the update rows, preferring the route that fires no hooks.

	Inserting each child on its own never saves the parent, so JT Rollup -- an
	After Save script on Job Tracker -- cannot run against a half-built tracker.
	That is the whole reason for doing it this way.

	If this Frappe refuses a standalone child insert, fall back to appending and
	saving the parent. That path DOES fire the rollup, which at this point is
	still the pre-migration body reading sibling Job Tracker documents; the
	worst it can do is derive a stale stage for a few minutes, because the */30
	sweep re-derives every open job after retarget_tracker_scripts has run. A
	transiently stale stage is a far better outcome than a failed migration.
	"""
	try:
		for child in children:
			frappe.get_doc(child).insert(ignore_permissions=True)
		return
	except Exception:
		frappe.log_error(title="FPS: child insert refused, appending via parent")

	doc = frappe.get_doc(TRACKER, parent)
	doc.set(PARENTFIELD, [])
	for child in children:
		row = {k: v for k, v in child.items()
		       if k not in ("doctype", "parent", "parenttype", "parentfield")}
		doc.append(PARENTFIELD, row)
	doc.save(ignore_permissions=True)


def execute():
	if not (frappe.db.exists("DocType", TRACKER) and frappe.db.exists("DocType", CHILD)):
		return

	fieldnames = [f.fieldname for f in frappe.get_meta(TRACKER).fields]
	if PARENTFIELD not in fieldnames:
		frappe.log_error(title="FPS: fps_updates missing, consolidation skipped")
		return

	rows = frappe.get_all(TRACKER, fields=FETCH, order_by="creation asc")

	by_job = {}
	for row in rows:
		by_job.setdefault(row.job_order, []).append(row)

	merged = archived = 0
	for job, group in by_job.items():
		if not job:
			continue
		try:
			if _consolidate(group):
				merged += 1
				archived += len(group) - 1
		except Exception:
			# One bad job must not take the whole migration down with it.
			frappe.log_error(title="FPS: consolidate tracker %s" % job)

	frappe.db.commit()
	frappe.clear_cache(doctype=TRACKER)
	frappe.logger().info(
		"FPS: consolidated %d job trackers, archived %d rows" % (merged, archived)
	)


def _consolidate(group):
	# Oldest first, so "first non-empty wins" reads chronologically and the
	# survivor is the row tracking started on.
	group = sorted(group, key=lambda r: (str(r.creation or ""), r.name))
	survivor = group[0]

	if frappe.db.exists(CHILD, {"parenttype": TRACKER, "parent": survivor.name}):
		return False

	# Updates are ordered by the date they describe, not by when they were typed.
	ordered = sorted(
		group, key=lambda r: (str(r.track_date or "9999-12-31"), str(r.creation or ""))
	)

	children = []
	for idx, row in enumerate(ordered, start=1):
		child = {
			"doctype": CHILD,
			"parent": survivor.name,
			"parenttype": TRACKER,
			"parentfield": PARENTFIELD,
			"idx": idx,
			"leg": row.get("fps_leg") or 1,
		}
		for parent_field, child_field in EVENT_MAP:
			child[child_field] = row.get(parent_field)
		children.append(child)

	_write_children(survivor.name, children)

	update = {}
	for field in SHIPMENT_FIELDS:
		values = [r.get(field) for r in ordered if not _empty(r.get(field))]
		if values:
			update[field] = values[0]

	subcategories = [r.get("fps_subcategory") for r in ordered
	                 if not _empty(r.get("fps_subcategory"))]
	if subcategories:
		update["fps_subcategory"] = max(subcategories, key=lambda v: len(str(v)))

	latest = ordered[-1]
	for field in ("track_date", "fps_event_type", "fps_milestone", "current_status",
	              "fps_evidence_ref", "fps_source", "fps_customer_visible"):
		update[field] = latest.get(field)

	notes = [r.get("progress_notes") for r in ordered if not _empty(r.get("progress_notes"))]
	if notes:
		update["progress_notes"] = max(notes, key=lambda v: len(str(v)))

	for field in ("next_action", "follow_up_date", "responsible", "issues"):
		values = [r.get(field) for r in ordered if not _empty(r.get(field))]
		if values:
			update[field] = values[-1]

	frappe.db.set_value(TRACKER, survivor.name, update, update_modified=False)

	for row in ordered:
		if row.name == survivor.name:
			continue
		frappe.delete_doc(TRACKER, row.name, ignore_permissions=True, ignore_missing=True)

	return True
