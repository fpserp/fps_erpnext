"""The FPS Live Feed (/fps-feed): who may see it, building it, serving it.

Agam, 14 Oct 2026: a phone feed of Operations and Accounts, refreshed every
four hours from 08:00 to 20:00, for agam@ and hello@ only. The feed is a
SNAPSHOT, not a live query: build_snapshot runs at 08:00, 12:00, 16:00 and
20:00 (hooks.py scheduler_events, cron "0 8,12,16,20 * * *"; Frappe evaluates
cron against frappe.utils.now_datetime(), i.e. the System Settings time zone,
Asia/Dubai on this site -- checked in frappe/core/doctype/scheduled_job_type/
scheduled_job_type.py on the version-16 branch) and stores the result in the
Single "FPS Feed Snapshot". The page only reads the latest one.

    FEED_USERS              who may open the page (one constant; change it and
                            deploy to add someone)
    check_page_access()     for the www page: Guest -> redirect to login,
                            others -> False ("This feed is private."), allowed
                            users -> True
    get_feed_for_page()     the page's context: the stored snapshot marked NEW
                            against the previous slot, with "Open in ERPNext"
                            decided for the current user
    get_feed_meta()         whitelisted GET for the page's "is there a newer
                            snapshot?" check: {generated_at, ...}
    build_snapshot()        the scheduler entry (also callable by Administrator)

All numbers come from the two dashboards' own code, imported and called as-is:
fps_erpnext.api.command_center (OPS payload, period 7d) and
fps_erpnext.api.acc_dashboard (ACC payload, period 7d) -- their readers and
their pure logic. fps_erpnext.api.feed_logic turns the two payloads and the raw
rows into the snapshot (contract: docs/live_feed/snapshot.schema.md).

WRITES. Only build_snapshot writes, and only the FPS Feed Snapshot Single (via
frappe.db.set_single_value: no document hooks, no version rows). It runs as
Administrator: the snapshot holds every section for both viewers (hello@ sees
Accounts too -- a deliberate exception that applies to this feed only), and
what each viewer may OPEN in the desk is decided per request, never stored.

WHO ELSE CAN READ THE STORED SNAPSHOT. The DocType grants System Manager read
(SPEC section 1), so a System Manager can open /app/fps-feed-snapshot (or
frappe.client.get) and read the stored JSON, Accounts figures included. On
14 Oct 2026 that is Administrator, agam@ and abhishek@; abhishek@ is not in
FEED_USERS but is Accounts Manager and sees the same figures on the FPS ACC
Dashboard. To keep the data strictly to FEED_USERS, remove that DocPerm: the
page reads the Single with frappe.db.get_singles_dict, which checks no
permission, and Administrator can always read.

ERRORS ARE LOGGED WITH defer_insert. A scheduled run that raises is rolled
back by ScheduledJobType.execute (frappe.db.rollback), and a cron job type
keeps no Scheduled Job Log (create_log stays 0 for "Cron"), so an Error Log
inserted in the same transaction would vanish with no trace. The page's GET is
rolled back too (frappe.app.sync_database). frappe.log_error(...,
defer_insert=True) queues the Error Log outside the transaction (Redis,
flushed by frappe.deferred_insert.save_to_db), so it survives both -- see
_log().

THE FIRST SNAPSHOT. Before the first scheduled run (right after deploy) there is
nothing stored. The page then enqueues ONE background build (job id
FIRST_BUILD_JOB_ID, deduplicated) and shows a "preparing" state that polls
get_feed_meta until a snapshot exists. Why a background job and not a build in
the request: (1) the page is a GET, and Frappe rolls a GET's transaction back
(frappe.app.sync_database), so a write there would need an explicit commit;
(2) the build must run with Administrator rights, and frappe.set_user inside a
web request rewrites the live session in place (session.sid and session.data,
which Session.update then writes back) -- in a worker that is harmless, which
is exactly what frappe.utils.background_jobs.execute_job itself does. So
build_snapshot elevates to Administrator ONLY inside a background job (and
refuses in a web request for anyone else). It is not whitelisted: nothing
outside the server can call it. After deploy the lead can also run it at once
from the "Scheduled Job Type" list (feed.build_snapshot -> Execute).
"""

import frappe
from frappe import _
from frappe.utils import get_fullname, now_datetime

from fps_erpnext.api import acc_dashboard as acc_api
from fps_erpnext.api import acc_dashboard_logic as acc_logic
from fps_erpnext.api import command_center as cc_api
from fps_erpnext.api import command_center_logic as cc_logic
from fps_erpnext.api import feed_logic as logic
from fps_erpnext.api import pipeline

# The ONLY people who may open /fps-feed. Change this tuple and deploy to add
# someone. Compared case-insensitively. Administrator is here for testing.
FEED_USERS = ("Administrator", "agam@fastplanet.ae", "hello@fastplanet.ae")

DOCTYPE = "FPS Feed Snapshot"
PAGE_ROUTE = "/fps-feed"
LOGIN_URL = "/login?redirect-to=" + PAGE_ROUTE
BUILD_METHOD = "fps_erpnext.api.feed.build_snapshot"
FIRST_BUILD_JOB_ID = "fps_feed_first_snapshot"
META_METHOD = "fps_erpnext.api.feed.get_feed_meta"

# The page re-checks for a newer snapshot this often while open (and whenever it
# becomes visible again), and this often while the first one is being built.
CHECK_EVERY_SECONDS = 600
BUILDING_EVERY_SECONDS = 10

# Bounds for the three recent-document reads (newest first).
RECENT_LIMIT = 60


# --------------------------------------------------------------------------
# Gate
# --------------------------------------------------------------------------

def access(user=None):
	"""'allowed' | 'guest' | 'refused' for `user` (default: the session user)."""
	return logic.gate(user or frappe.session.user, FEED_USERS)


def check_page_access():
	"""For the www page's get_context. Guest: redirect to the login page (with
	redirect-to back here). A logged-in user outside FEED_USERS: False -- the
	page renders "This feed is private." with HTTP 200 and no data. Allowed: True."""
	state = access()
	if state == "guest":
		# 302, not frappe.Redirect's default 301: a permanent redirect cached by
		# Safari would keep sending a logged-in viewer back to the login page.
		# (frappe.website.serve catches it and builds the redirect from
		# flags.redirect_location; app.process_response adds no-store anyway.)
		frappe.local.flags.redirect_location = LOGIN_URL
		raise frappe.Redirect(302)
	return state == "allowed"


def _require_feed_user():
	if access() != "allowed":
		frappe.throw(_("This feed is private."), frappe.PermissionError)


# --------------------------------------------------------------------------
# Serving
# --------------------------------------------------------------------------

def _stored():
	"""(snapshot, previous, generated_at) from the Single; (None, None, None) when empty."""
	values = frappe.db.get_singles_dict(DOCTYPE) or {}
	snapshot = logic.loads(values.get("snapshot"))
	if snapshot and snapshot.get("version") != logic.VERSION:
		snapshot = None   # an older contract: rebuild rather than render it wrongly
	previous = logic.loads(values.get("previous"))
	generated_at = (snapshot or {}).get("generated_at")
	return snapshot, previous, generated_at


def _log(title):
	"""An Error Log with the current traceback that survives a rollback (see
	the module doc). Never raises."""
	try:
		frappe.log_error(title=title, defer_insert=True)
	except Exception:
		pass


def _building():
	try:
		from frappe.utils.background_jobs import is_job_enqueued
		return bool(is_job_enqueued(FIRST_BUILD_JOB_ID))
	except Exception:
		return False


def _enqueue_first_build():
	"""One background build, deduplicated by job id. Never raises into the page."""
	try:
		frappe.enqueue(BUILD_METHOD, queue="short", timeout=600,
		               job_id=FIRST_BUILD_JOB_ID, deduplicate=True)
		return True
	except Exception:
		_log("FPS Live Feed: could not enqueue the first snapshot")
		return False


@frappe.whitelist(methods=["GET"])
def get_feed_meta():
	"""{generated_at, slot, slot_id, building} -- the page's "is there a newer
	snapshot?" check. Allow-list gated; reads one Single, writes nothing."""
	_require_feed_user()
	_snapshot, _previous, generated_at = _stored()
	return {
		"generated_at": generated_at,
		"slot": logic.slot_label(generated_at) if generated_at else None,
		"slot_id": logic.slot_id(generated_at) if generated_at else None,
		"building": False if generated_at else _building(),
	}


def get_feed_for_page():
	"""The www page's data (see the module doc and snapshot.schema.md):

	    {"state": "ready" | "building" | "private",
	     "user": {"name", "full_name"},
	     "meta": feed_logic.feed_meta(...)       # header, computed now
	     "snapshot": <snapshot + is_new / changed / can_open>  (ready only)
	     "feed_json": <{"meta", "snapshot"} as JSON safe inside a <script>>,
	     "poll": {"meta_method", "check_every_seconds", "building_every_seconds"}}

	Gated again here (the page gates first): anyone outside FEED_USERS gets
	state "private" and no data."""
	user = frappe.session.user
	poll = {"meta_method": META_METHOD, "check_every_seconds": CHECK_EVERY_SECONDS,
	        "building_every_seconds": BUILDING_EVERY_SECONDS}
	if access(user) != "allowed":
		return {"state": "private", "poll": poll}

	now = now_datetime()
	snapshot, previous, generated_at = _stored()
	out = {"user": {"name": user, "full_name": get_fullname(user)}, "poll": poll,
	       "meta": logic.feed_meta(generated_at, now)}
	if not snapshot:
		_enqueue_first_build()
		out.update(state="building", snapshot=None)
		out["feed_json"] = logic.script_json({"meta": out["meta"], "snapshot": None})
		return out

	logic.mark_new(snapshot, previous)
	logic.apply_can_open(snapshot, _can_read_for(user))
	out.update(state="ready", snapshot=snapshot)
	out["feed_json"] = logic.script_json({"meta": out["meta"], "snapshot": snapshot})
	return out


def _can_read_for(user):
	"""can_read(doctype, name=None) for apply_can_open, memoised per request.

	Doctype-level read first (cheap, and enough for list routes); then, for a
	document, frappe.has_permission with the name -- v16 loads it lazily (no
	child tables) and applies User Permissions and shares. A report
	(feed_logic asks can_read("Report", name) for query-report routes) is
	checked the way frappe.desk.query_report.get_report_doc checks it before
	running one: Report.is_permitted() (its roles, for the session user, who
	is the viewer here) and "report" permission on its ref_doctype. Anything
	that raises (a record deleted since the snapshot) is simply not openable."""
	memo = {}

	def can_read(doctype, name=None):
		key = (doctype, name)
		if key not in memo:
			try:
				if doctype == "Report":
					report = frappe.get_doc("Report", name)
					ok = bool(not report.get("disabled") and report.is_permitted()
					          and frappe.has_permission(report.ref_doctype, "report", user=user))
				else:
					ok = bool(frappe.has_permission(doctype, "read", user=user))
					if ok and name:
						ok = bool(frappe.has_permission(doctype, "read", doc=name, user=user))
			except Exception:
				ok = False
			memo[key] = ok
		return memo[key]

	return can_read


# --------------------------------------------------------------------------
# Building (scheduler)
# --------------------------------------------------------------------------

def _ensure_administrator():
	"""Build with Administrator rights. The scheduler already runs as
	Administrator. A background job enqueued by the page runs as the page's
	user and is elevated here -- in a worker only, see the module doc."""
	if frappe.session.user == "Administrator":
		return
	in_job = bool(getattr(frappe.local, "job", None))
	in_request = getattr(frappe.local, "request", None) is not None
	if in_job and not in_request:
		frappe.set_user("Administrator")
		return
	frappe.throw(_("Only the scheduler or Administrator can build the FPS Live Feed."),
	             frappe.PermissionError)


def build_snapshot():
	"""Build the feed from the two dashboards and store it. Scheduler entry
	(hooks.py, 08/12/16/20 Asia/Dubai); also callable by Administrator.

	A section whose reads fail is stored with an error line instead of failing
	the whole feed, and the recent-document reads failing only leave a notice
	in each section. When BOTH sections fail nothing is stored (the previous
	snapshot stays) and the build raises. Every failure is in the Error Log
	(deferred insert: the scheduler's rollback does not remove it; the cron
	job type itself keeps no Scheduled Job Log)."""
	_ensure_administrator()
	now = now_datetime()
	as_of = now.date()

	stored, stored_previous, _generated_at = _stored()
	previous = logic.next_previous(stored, stored_previous, logic.slot_id(now))
	since = logic.recent_since(now, (previous or {}).get("generated_at"))

	errors = {}
	ops = acc_data = None
	try:
		ops = _ops_data(as_of, now)
	except Exception:
		_log("FPS Live Feed: Operations section failed")
		errors["ops"] = "Operations data could not be read at %s." % logic.hhmm(now)
	try:
		acc_data = _acc_data(as_of, now)
	except Exception:
		_log("FPS Live Feed: Accounts section failed")
		errors["acc"] = "Accounts data could not be read at %s." % logic.hhmm(now)
	if len(errors) == 2:
		frappe.throw(_("FPS Live Feed: neither section could be built; the previous snapshot is kept."))

	try:
		recent = _read_recent(since)
	except Exception:
		# Never fails the build: the sections are built without the recent
		# documents and say so (feed_logic.build_snapshot, errors["recent"]).
		_log("FPS Live Feed: recent documents could not be read")
		recent = {}
		errors["recent"] = "Recent documents could not be read at %s." % logic.hhmm(now)
	snapshot = logic.build_snapshot(now=now, ops=ops, acc_data=acc_data, recent=recent,
	                                since=since, errors=errors)
	frappe.db.set_single_value(DOCTYPE, {
		"generated_at": snapshot["generated_at"],
		"slot": snapshot["slot"],
		"snapshot": logic.dumps(snapshot),
		"previous": logic.dumps(previous) if previous else None,
	})
	return {"generated_at": snapshot["generated_at"], "slot": snapshot["slot"],
	        "items": sum(len(s["items"]) for s in snapshot["sections"]),
	        "errors": sorted(errors)}


def _ops_data(as_of, now):
	"""The FPS OPS Dashboard payload for 7 days, built the way command_center
	builds it (its readers, its stage strip, its logic), plus the raw rows the
	feed items are made from. Money-free by construction (OPS_FINANCE)."""
	period = logic.PERIOD
	raw = cc_api._read_rows(cc_logic.fetch_floor(period, as_of), finance=cc_api.OPS_FINANCE,
	                        keys=cc_logic.KPI_ORDER)
	payload = cc_logic.build_dashboard(
		period=period, as_of=as_of, generated_at=cc_logic.timestamp(now),
		viewer={"finance": cc_api.OPS_FINANCE, "full_name": "FPS Live Feed"},
		raw=raw, stages=cc_logic.ops_stages(pipeline.get_overview()), creatable=())
	return {"payload": payload, "raw": raw}


def _acc_data(as_of, now):
	"""The FPS ACC Dashboard payload for 7 days, built the way acc_dashboard
	builds it (its readers and logic), plus its raw rows. The role gate
	(frappe.only_for) is the whitelisted method's; this runs as Administrator."""
	period = logic.PERIOD
	company = acc_api._company()
	floor = cc_logic.fetch_floor(period, as_of).isoformat()
	raw = acc_api._read(floor, as_of, company, need=acc_api._ALL)
	payload = acc_logic.build_dashboard(
		period=period, as_of=as_of, generated_at=cc_logic.timestamp(now),
		viewer={"full_name": "FPS Live Feed"}, raw=raw, company=company, creatable=())
	return {"payload": payload, "raw": raw}


JOB_FIELDS = cc_logic.FIELDS["Job Order"] + ["creation"]


def _read_recent(since):
	"""The three reads the dashboards do not do (Administrator; GET-only SQL):

	    Job Order      created since `since` (jobs opened)
	    Sales Invoice  submitted since `since` -- its GL entries were created then
	    Payment Entry  submitted since `since` -- likewise

	See feed_logic's module doc for why "submitted" comes from GL Entry."""
	since_text = logic.stamp(since)
	recent = {}
	recent["Job Order"] = frappe.get_list(
		"Job Order", fields=JOB_FIELDS,
		filters=[["Job Order", "docstatus", "<", 2], ["Job Order", "creation", ">=", since_text]],
		order_by="creation desc", limit_page_length=RECENT_LIMIT)

	from frappe.query_builder.functions import Min

	gle = frappe.qb.DocType("GL Entry")
	vouchers = (
		frappe.qb.from_(gle)
		.select(gle.voucher_type, gle.voucher_no, Min(gle.creation).as_("submitted_at"))
		.where(gle.is_cancelled == 0)
		.where(gle.voucher_type.isin(["Sales Invoice", "Payment Entry"]))
		.where(gle.creation >= since_text)
		.groupby(gle.voucher_type, gle.voucher_no)
		.orderby("submitted_at", order=frappe.qb.desc)
		.limit(4 * RECENT_LIMIT)
	).run(as_dict=True)
	for doctype in ("Sales Invoice", "Payment Entry"):
		# Newest first; a mass import (561 Fresa invoices on 16 Sep) is cut to
		# the newest RECENT_LIMIT -- the feed shows 8 of them anyway.
		at = {}
		for v in vouchers:
			if v.get("voucher_type") == doctype and len(at) < RECENT_LIMIT:
				at.setdefault(v.get("voucher_no"), v.get("submitted_at"))
		rows = []
		if at:
			rows = frappe.get_list(
				doctype, fields=acc_logic.FIELDS[doctype],
				filters=[[doctype, "name", "in", sorted(at)], [doctype, "docstatus", "=", 1]],
				limit_page_length=0)
		for r in rows:
			r["submitted_at"] = at.get(r.get("name"))
		recent[doctype] = rows
	return recent
