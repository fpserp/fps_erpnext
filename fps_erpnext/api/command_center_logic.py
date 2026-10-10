"""Arithmetic, copy and payload assembly for the FPS Command Center. Pure Python.

No frappe import, standard library only (plus fps_erpnext.api.customs_clock,
which is itself pure). Everything here takes plain values or dict-like rows -- a
frappe._dict, a plain dict -- and returns plain dicts, lists, strings and
numbers, so the whole dashboard can be built and checked with a bare `python`
and no bench:

    fps_erpnext/tests/test_command_center_logic.py   the rules, unit-tested
    dashboard/dev/make_fixtures.py                   the UI fixtures, built by
                                                     running THIS module over
                                                     synthetic rows

fps_erpnext.api.command_center does the permission checks and the database
reads, then hands the raw rows to build_dashboard / build_metric_detail here.
The payload shape is dashboard/src/types/dashboard.ts; change both together.

READ-ONLY BY CONSTRUCTION. Nothing in this module can reach the database; it
only reshapes rows it is given.

THE CHOICES THAT ARE NOT OBVIOUS, all made against the live profile of
2026-10-10 (research_livedata.json):

* Drafts count where ops leave records in draft (Job Order 56/94 drafts, every
  Proof of Delivery since July is a draft, quotations wait as drafts for
  Agam's "ok") -- and never for money, where a draft would double-count (two
  Sep drafts mirror two Paid August invoices).
* "previous" is null, not 0, when the data does not reach back over the whole
  previous window: a source that started mid-window would otherwise read as a
  real comparison. Evidence that it did reach back = a row dated before the
  previous window starts (see previous_total).
* A delta is never computed against a zero base (DESIGN.md §4): delta_pct is
  null and the UI says "new" or "—".
* Money is compacted one way everywhere the server formats it, and the same
  way dashboard/src/lib/format.ts formats the card values next to it
  (DESIGN.md §5: "AED 12.9K", "AED 1.2M"): K, M and B to 1 dp, trailing zeros
  dropped, rounding half up, and the unit chosen AFTER rounding so 999,960
  reads "AED 1M", never "AED 1000K". 12,874.50 -> "AED 12.9K", 756,615.87 ->
  "AED 756.6K", 1,474,740.78 -> "AED 1.5M". A context line must never read
  "AED 1.47M" beside a card that says "AED 1.5M" for the same kind of number.

RECONCILED WITH THE KPI SPEC (kpi_spec.md, 2026-10-10). The definitions below
follow that spec line by line. Where this module deliberately differs, the
reason sits next to the code and is marked "SPEC DEVIATION":

* previous: null when the source does not reach back over the whole previous
  window (the spec: only when there is no data at all before the current
  window). See previous_total.
* job_activity: good_direction "none" (the spec: "up"). See METRICS.
* trend: deliveries sit in "Operations" beside customs cleared, and job updates
  stay out of the chart (the spec: deliveries in "Sales pipeline", job updates
  in "Operations"). See TREND_MODES.
* invoiced: payment requests (fps_is_payment_request) are left out of the
  KPI. See points_invoiced.
* collected: the receipt-lag caveat also needs a median of >= 7 days. See
  caveat_for.
* insights: the swing rule skips money, neutral and caveated KPIs, and treats
  a null previous as "not comparable", not as quiet; one extra rule the spec
  does not list (enquiry silence) is kept. See the Insights section.
"""

from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple
from urllib.parse import quote

from fps_erpnext.api.customs_clock import is_done, to_date  # noqa: F401 -- is_done: see CUSTOMS_OPEN_DOC

# --------------------------------------------------------------------------
# Periods and windows
# --------------------------------------------------------------------------

# 90d is 13 rolling 7-day buckets ending today, i.e. 91 days, so every bucket
# is a whole week and the last one is the one still filling up.
PERIODS = {
	"7d": {"days": 7, "bucket": 1, "granularity": "day",
	       "label": "Last 7 days", "compare": "vs previous 7 days"},
	"30d": {"days": 30, "bucket": 1, "granularity": "day",
	        "label": "Last 30 days", "compare": "vs previous 30 days"},
	"90d": {"days": 91, "bucket": 7, "granularity": "week",
	        "label": "Last 13 weeks", "compare": "vs previous 13 weeks"},
}

# Weekly trend chart: 12 ISO weeks, Monday first, the last one partial.
TREND_WEEKS = 12

# Receipts are booked late (median 29, max 56 days on 2026-10-10), so the lag
# is measured over this many days of posting dates.
LAG_WINDOW_DAYS = 120

# How far before the previous window a row has to exist before "previous" is
# trusted as a real number rather than reported as null.
HISTORY_MARGIN_DAYS = 28

CURRENCY = "AED"  # Company default currency; every base_* amount is in it.

NOT_SET_KEY = "__not_set__"
NOT_SET_LABEL = "Not set"
OTHER_KEY = "__other__"
NO_PARTY = "Not set"

# Insight banner limits (dashboard.ts: title <= 90, detail <= 200, 0-6 items).
INSIGHT_CAP = 6
TITLE_MAX = 90
DETAIL_MAX = 200
# Most severe first (spec: critical > warning > positive > info). A good-news
# swing outranks a standing info note.
SEVERITY_ORDER = ("critical", "warning", "positive", "info")

RECORDS_CAP = 8
BREAKDOWN_TOP = 5

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class Window(NamedTuple):
	"""Inclusive date range."""
	start: date
	end: date

	def __contains__(self, d):
		return d is not None and self.start <= d <= self.end

	@property
	def days(self):
		return (self.end - self.start).days + 1


def check_period(period):
	"""The period if it is one of PERIODS, else ValueError (the API maps it)."""
	if period not in PERIODS:
		raise ValueError("period must be one of %s" % ", ".join(PERIODS))
	return period


def period_windows(period, as_of):
	"""(current, previous) windows for a period ending on as_of, both inclusive."""
	days = PERIODS[check_period(period)]["days"]
	as_of = to_date(as_of)
	current = Window(as_of - timedelta(days=days - 1), as_of)
	previous = Window(current.start - timedelta(days=days), current.start - timedelta(days=1))
	return current, previous


def iso_week_start(d):
	"""Monday of d's ISO week."""
	d = to_date(d)
	return d - timedelta(days=d.weekday())


def trend_week_starts(as_of, weeks=TREND_WEEKS):
	"""Mondays of the last `weeks` ISO weeks, oldest first, the current one last."""
	this_week = iso_week_start(as_of)
	return [this_week - timedelta(weeks=weeks - 1 - i) for i in range(weeks)]


def fetch_floor(period, as_of):
	"""Earliest date any query for this call needs.

	One read per doctype serves the KPI, its previous window (plus the margin
	that proves the source reaches back), the 12-week trend and the receipt
	lag window, so every query is bounded by the earliest of the four.
	"""
	as_of = to_date(as_of)
	_current, previous = period_windows(period, as_of)
	return min(previous.start - timedelta(days=HISTORY_MARGIN_DAYS),
	           trend_week_starts(as_of)[0],
	           as_of - timedelta(days=LAG_WINDOW_DAYS))


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------

def round_half_up(value, places=0):
	"""Round like a person does (2.25 -> 2.3), not like float round() (2.2)."""
	q = Decimal(1).scaleb(-places)
	return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def money(value):
	"""A currency total cleaned of float noise (0.1 + 0.2 -> 0.3)."""
	return round_half_up(value or 0, 2)


def as_unit(value, unit):
	"""Counts are ints in the payload; money is rounded to fils."""
	if unit == "count":
		return int(round_half_up(value or 0))
	return money(value)


def window_total(points, window):
	"""Sum of values for (date, value) pairs inside the window."""
	return sum(v for d, v in points if d in window)


def previous_total(points, previous, first_seen):
	"""Total of the previous window, or None when it is not comparable.

	Comparable means the source demonstrably existed for the WHOLE previous
	window: a row is dated before the window starts. FPS Enquiry, for one,
	starts on 2026-07-20, so its 90-day "previous" (12 Apr - 11 Jul) is None,
	not a zero that would make every number look "new".

	SPEC DEVIATION: the spec makes previous null only when there is no data at
	all before the current window. That would compare a 90-day window against a
	previous one the system was live for only part of (Job Orders start in May
	2026, so the 90d "previous" would hold six weeks of go-live) and report the
	go-live itself as growth. Null here means "not comparable", never "quiet".
	"""
	if first_seen is None or first_seen >= previous.start:
		return None
	return window_total(points, previous)


def delta_pct(value, previous):
	"""% change rounded to 1 dp, only against a positive base (spec: previous > 0).

	None for no previous, a zero base (DESIGN.md §4: never +inf%) and a
	negative base (net credit notes): a percentage of a negative is no signal.
	"""
	if previous is None or previous <= 0:
		return None
	return round_half_up((value - previous) / previous * 100, 1)


def median(values):
	values = [v for v in values if v is not None]
	if not values:
		return None
	return statistics.median(values)


def bucket_series(points, period, as_of, unit="count"):
	"""SeriesPoint list for the current window, oldest first.

	7d / 30d: one point per day. 90d: 13 rolling 7-day buckets ending today,
	each dated by its first day. The point holding as_of is partial: today is
	still filling up.
	"""
	spec = PERIODS[check_period(period)]
	current, _previous = period_windows(period, as_of)
	size = spec["bucket"]
	totals = {}
	for d, v in points:
		if d in current:
			idx = (d - current.start).days // size
			totals[idx] = totals.get(idx, 0) + v
	series = []
	for idx in range(current.days // size):
		start = current.start + timedelta(days=idx * size)
		end = start + timedelta(days=size - 1)
		point = {"date": start.isoformat(), "value": as_unit(totals.get(idx, 0), unit)}
		if start <= current.end <= end:
			point["partial"] = True
		series.append(point)
	return series


def weekly_totals(points, as_of, weeks=TREND_WEEKS):
	"""[(monday, total, partial)] for the trend chart, oldest first.

	Rows dated after as_of (a future ETA-style date typed by mistake) are left
	out of the running week, so the partial week never counts tomorrow.
	"""
	as_of = to_date(as_of)
	starts = trend_week_starts(as_of, weeks)
	index = {s: i for i, s in enumerate(starts)}
	totals = [0] * weeks
	for d, v in points:
		if d is None or d > as_of:
			continue
		i = index.get(iso_week_start(d))
		if i is not None:
			totals[i] += v
	return [(s, totals[i], s <= as_of <= s + timedelta(days=6)) for i, s in enumerate(starts)]


# --------------------------------------------------------------------------
# Formatting (server-side strings: context lines and insight copy)
# --------------------------------------------------------------------------

def format_count(n):
	"""1284 -> '1,284'."""
	return "{:,}".format(int(round_half_up(n or 0)))


def _strip_zeros(text):
	return text.rstrip("0").rstrip(".") if "." in text else text


# (divisor, suffix, decimals), largest first.
_COMPACT_TIERS = ((10 ** 9, "B", 1), (10 ** 6, "M", 1), (10 ** 3, "K", 1), (1, "", 0))


def format_compact(n):
	"""12874.5 -> '12.9K', 1474740.78 -> '1.5M', 999960 -> '1M'. See module doc."""
	negative = float(n or 0) < 0
	n = abs(float(n or 0))
	body = "0"
	for i, (base, suffix, places) in enumerate(_COMPACT_TIERS):
		if n >= base or base == 1:
			scaled = round_half_up(n / base, places)
			if i > 0 and scaled >= 1000:
				# Rounding pushed it into the next unit up.
				base, suffix, places = _COMPACT_TIERS[i - 1]
				scaled = round_half_up(n / base, places)
			body = _strip_zeros("%.*f" % (places, scaled)) + suffix
			break
	# No sign on something that rounds to nothing ("−0" reads as an error).
	return ("−" + body) if negative and body != "0" else body


def format_money_compact(n, currency=CURRENCY):
	"""'AED 12.9K'. A negative amount reads '−AED 700' (U+2212, as the UI's deltas)."""
	text = format_compact(n)
	if text.startswith("−"):
		return "−%s %s" % (currency, text[1:])
	return "%s %s" % (currency, text)


def format_money(n, currency=CURRENCY):
	"""Full figure, 'AED 12,874.50', for places that must not round."""
	value = round_half_up(n or 0, 2)
	sign = "−" if value < 0 else ""
	return "%s%s %s" % (sign, currency, "{:,.2f}".format(abs(value)))


def short_date(d):
	"""2026-08-08 -> '8 Aug'. Month names are fixed, not locale-dependent."""
	d = to_date(d)
	return "%d %s" % (d.day, MONTHS[d.month - 1])


def plural(n, one, many):
	return one if int(n) == 1 else many


def sentence(text):
	"""First letter up, the rest untouched (str.capitalize would lower 'AED')."""
	return text[:1].upper() + text[1:]


def clip(text, limit):
	"""Hard length cap for banner copy; cuts at a word and adds an ellipsis."""
	text = " ".join(str(text or "").split())
	if len(text) <= limit:
		return text
	cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:·-")
	return cut + "…"


# --------------------------------------------------------------------------
# Desk routes (navigation only)
# --------------------------------------------------------------------------

def slug(doctype):
	"""frappe.router.slug: lower case, spaces to hyphens."""
	return doctype.lower().replace(" ", "-")


def form_route(doctype, name):
	"""'/app/job-order/FPS%2FJO%2F2610%2F094'.

	Names here carry slashes. The desk router splits the path on "/" and runs
	decodeURIComponent on each part (router.js decode_component), so the name is
	encoded exactly as frappe.utils.get_form_link does: encodeURIComponent,
	which escapes "/" too.
	"""
	return "/app/%s/%s" % (slug(doctype), quote(str(name), safe="-_.!~*'()"))


def list_route(doctype, filters=None):
	"""List view URL. Filter values that are lists go as the JSON the list view
	parses from route options (same format as pipeline.TILES routes)."""
	route = "/app/" + slug(doctype)
	if not filters:
		return route
	parts = []
	for field, value in filters.items():
		if isinstance(value, list | tuple):
			value = json.dumps(list(value), separators=(",", ":"))
		parts.append("%s=%s" % (field, quote(str(value), safe="")))
	return route + "?" + "&".join(parts)


AR_REPORT_ROUTE = "/app/query-report/Accounts%20Receivable"


# --------------------------------------------------------------------------
# What each doctype means here
# --------------------------------------------------------------------------

# Same list as pipeline.OPEN_JOB (the strip's "open job" rule). Copied, not
# imported, because pipeline imports frappe; test_command_center_logic parses
# pipeline.py and fails if the two drift apart.
CLOSED_JOB_STAGES = ("Closed", "Completed", "Invoiced")

# Same mapping as pipeline.SOW_SHORT (fps_category is stored with its code
# prefix). Same drift test.
SOW_SHORT = {
	"CC - Customs Clearance": "Customs clearance",
	"FF - Freight Forwarding": "Freight forwarding",
	"LT - Local Land Transport": "Local transport",
	"XB - Cross-Border Land Transport": "Cross-border",
	"GJ - General Job": "General job",
}

# FPS Job Update.milestone codes (the Select options) as the drawer shows them.
MILESTONE_LABELS = {
	"OPENED": "Opened", "BOOKED": "Booked", "DOCS": "Docs", "DEPARTED": "Departed",
	"ARRIVED": "Arrived", "FZ_BOE": "FZ BOE", "FZ_CLEARED": "FZ cleared",
	"OMAN_BOE": "Oman BOE", "OMAN_CLEARED": "Oman cleared",
	"TRUCKS_DEPARTED": "Trucks departed", "MOFA": "MOFA", "BOE": "BOE", "DO": "DO",
	"DUTY": "Duty", "CLEARED": "Cleared", "VEHICLE": "Vehicle", "PICKED_UP": "Picked up",
	"BORDER": "Border", "DELIVERED": "Delivered", "DOCS_IN": "Docs in",
	"SUBMITTED": "Submitted", "COMPLETED": "Completed", "INVOICED": "Invoiced",
	"CLOSED": "Closed", "HOLD": "On hold", "RESUME": "Resumed",
}

# Customs Tracker statuses that are explicitly still open. They bound the read
# (an old tracker still waiting on originals must not fall out of the query)
# AND decide what the overdue / due-soon insights count.
#
# Deliberately narrower than customs_clock.is_done, which the board uses to
# colour cells: there a BLANK status still colours, here it does not count.
# On 2026-10-10 the blank-status trackers with past deadlines were June/July
# rows from before these fields were kept (CT 2606/001-002 on documents; those
# plus two July rows on MOFA) -- counting them would have reported 7 + 7
# "overdue" where operations have 5 + 3 actually marked Pending. Every value
# here is also not-done by is_done (asserted in the tests).
CUSTOMS_OPEN_DOC = ("Pending",)
CUSTOMS_OPEN_MOFA = ("Pending", "Under Process", "Under Client")

# Fields each read selects. command_center passes these to frappe.get_list and
# make_fixtures builds rows with exactly these keys, so the two cannot disagree.
FIELDS = {
	"FPS Enquiry": ["name", "enquiry_date", "status", "enquiry_source",
	                "client_name", "movement_type"],
	"Quotation": ["name", "transaction_date", "status", "docstatus", "base_grand_total",
	              "customer_name", "party_name", "quotation_to", "valid_till"],
	"Job Order": ["name", "jo_date", "docstatus", "fps_category", "fps_stage", "eta",
	              "customer_name", "customer", "client_reference_no", "sales_invoice"],
	"Customs Tracker": ["name", "ct_date", "clearance_date", "status", "customer",
	                    "job_order", "boe_number", "fps_clearance_type",
	                    "fps_doc_submission", "fps_doc_deadline",
	                    "fps_mofa_status", "fps_mofa_deadline"],
	"Proof of Delivery": ["name", "pod_date", "docstatus", "delivery_status", "customer",
	                      "job_order", "movement_type", "client_reference_no"],
	# Child rows; command_center adds job_customer / job_stage from the parent.
	"FPS Job Update": ["name", "parent", "update_date", "milestone", "status_line",
	                   "event_type", "source", "creation"],
	"Sales Invoice": ["name", "posting_date", "docstatus", "status", "base_net_total",
	                  "base_grand_total", "outstanding_amount", "due_date",
	                  "customer_name", "customer", "fps_job_order", "is_return",
	                  "fps_is_payment_request"],
	"Payment Entry": ["name", "posting_date", "payment_type", "base_received_amount",
	                  "party_name", "party", "mode_of_payment", "reference_no", "creation"],
}

KPI_ORDER = ("enquiries", "quotations", "jobs", "customs_cleared",
             "deliveries", "job_activity", "invoiced", "collected")

METRICS = {
	"enquiries": {
		"label": "New enquiries",
		"definition": "Enquiries logged in FPS Enquiry, by enquiry date. "
		              "Cancelled bot-line duplicates are left out.",
		"unit": "count", "good_direction": "up", "finance": False,
		"doctype": "FPS Enquiry", "new_doctype": "FPS Enquiry",
		"route": list_route("FPS Enquiry"),
		"dimension_label": "Source",
	},
	"quotations": {
		"label": "Quotations",
		"definition": "Quotations dated in the period, draft or submitted. "
		              "Cancelled quotations are left out.",
		"unit": "count", "good_direction": "up", "finance": False,
		"doctype": "Quotation", "new_doctype": "Quotation",
		"route": list_route("Quotation"),
		"dimension_label": "Status",
	},
	"jobs": {
		"label": "New jobs",
		"definition": "Job Orders opened in the period, by job date, draft or "
		              "submitted. Cancelled jobs are left out.",
		"unit": "count", "good_direction": "up", "finance": False,
		"doctype": "Job Order", "new_doctype": "Job Order",
		"route": list_route("Job Order"),
		"dimension_label": "Service line",
	},
	"customs_cleared": {
		"label": "Customs cleared",
		"definition": "Customs Trackers whose last declaration cleared in the "
		              "period, by clearance date.",
		"unit": "count", "good_direction": "up", "finance": False,
		# No "New" action: a tracker is created per job by the Job Order flow,
		# never as a blank form (spec).
		"doctype": "Customs Tracker", "new_doctype": None,
		"route": list_route("Customs Tracker", {"status": "Cleared"}),
		"dimension_label": "Clearance type",
	},
	"deliveries": {
		"label": "Deliveries",
		"definition": "Proofs of delivery marked Delivered, by POD date, draft "
		              "or submitted.",
		"unit": "count", "good_direction": "up", "finance": False,
		"doctype": "Proof of Delivery", "new_doctype": "Proof of Delivery",
		"route": list_route("Proof of Delivery", {"delivery_status": "Delivered"}),
		"dimension_label": "Movement",
	},
	"job_activity": {
		"label": "Job updates",
		"definition": "Updates logged on Job Orders, by update date. Rows "
		              "loaded by the go-live backfill are left out.",
		# SPEC DEVIATION (spec: "up"). More updates is not better or worse in
		# itself -- an issue-heavy week (holds, re-filed BOEs, customer chasers)
		# logs more of them -- so a rise must not paint mint nor a fall rose.
		# The delta stays neutral and the swing insight skips it.
		"unit": "count", "good_direction": "none", "finance": False,
		"doctype": "Job Order", "new_doctype": None,  # a child row, no form of its own
		"route": list_route("Job Order"),
		"dimension_label": "Milestone",
	},
	"invoiced": {
		"label": "Invoiced (net)",
		"definition": "Net value (before VAT) of submitted sales invoices, by "
		              "posting date, credit notes included. Payment requests "
		              "and drafts are left out.",
		"unit": "currency", "good_direction": "up", "finance": True,
		"doctype": "Sales Invoice", "new_doctype": "Sales Invoice",
		"route": list_route("Sales Invoice", {"docstatus": 1}),
		"dimension_label": "Status",
	},
	"collected": {
		"label": "Collected",
		"definition": "Customer receipts (submitted Payment Entries of type "
		              "Receive), by posting date.",
		"unit": "currency", "good_direction": "up", "finance": True,
		# No "New" action (spec): receipts are booked against bank statements
		# and invoices, not started from a dashboard.
		"doctype": "Payment Entry", "new_doctype": None,
		"route": list_route("Payment Entry", {"payment_type": "Receive", "docstatus": 1}),
		"dimension_label": "Mode of payment",
	},
}

# Which raw rows feed which metric.
METRIC_SOURCE = {
	"enquiries": "FPS Enquiry",
	"quotations": "Quotation",
	"jobs": "Job Order",
	"customs_cleared": "Customs Tracker",
	"deliveries": "Proof of Delivery",
	"job_activity": "FPS Job Update",
	"invoiced": "Sales Invoice",
	"collected": "Payment Entry",
}

# Doctypes that are only read for, and only reach, finance viewers.
MONEY_DOCTYPES = frozenset(METRIC_SOURCE[k] for k, spec in METRICS.items() if spec["finance"])

# (key, label, unit, finance, ((series key, label, slot), ...)).
# A series keeps its slot whichever others are hidden (DESIGN.md §4).
#
# SPEC DEVIATION. The spec puts deliveries in "Sales pipeline" (slot 4) and
# job updates + customs cleared in "Operations". On the live 12 weeks that
# would put customs cleared (0-6 a week) on one y-axis with job updates
# (14-49 a week, more before the backfill filter) and deliveries (0-3) on one
# axis with enquiries/quotations (up to 22): the small series flatten into the
# baseline, and DESIGN.md §6 allows no second axis. So the pipeline keeps the
# three sales series, Operations pairs the two like-sized ops series, and job
# updates are read on their own KPI card and drawer.
TREND_MODES = (
	("pipeline", "Sales pipeline", "count", False,
	 (("enquiries", "Enquiries", 1), ("quotations", "Quotations", 2), ("jobs", "Jobs", 3))),
	("activity", "Operations", "count", False,
	 (("customs_cleared", "Cleared", 1), ("deliveries", "Delivered", 2))),
	# The invoiced series is the KPI's own points, credit notes included, so it
	# wears the KPI's label: legend, tooltip and table header all say "(net)".
	("money", "Money", "currency", True,
	 (("invoiced", "Invoiced (net)", 1), ("collected", "Collected", 2))),
)


# --------------------------------------------------------------------------
# Raw rows -> points
#
# A point is one dated contribution to a metric:
#   name, date, value, dim, dim_label, title, subtitle, status, amount, seq
# `seq` breaks ties between points on the same date (newest first).
# --------------------------------------------------------------------------

def _text(value):
	return str(value).strip() if value is not None else ""


def _num(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _dim(value, labels=None):
	key = _text(value)
	if not key:
		return NOT_SET_KEY, NOT_SET_LABEL
	return key, (labels or {}).get(key, key)


def _join(*parts):
	return " · ".join(p for p in (_text(x) for x in parts) if p)


def _point(row, d, value, dim, title, subtitle="", status="", amount=None, name=None, seq=None):
	key, label = dim
	name = name or row.get("name")
	return {
		"name": name, "date": d, "value": value,
		"dim": key, "dim_label": label,
		"title": _text(title) or NO_PARTY, "subtitle": _text(subtitle),
		"status": _text(status), "amount": amount,
		"seq": _text(seq if seq is not None else name),
	}


def _docstatus(row):
	return int(_num(row.get("docstatus")))


def points_enquiries(rows):
	out = []
	for r in rows:
		d = to_date(r.get("enquiry_date"))
		if not d or _text(r.get("status")) == "Cancelled":
			continue
		dim = _dim(r.get("enquiry_source"))
		out.append(_point(r, d, 1, dim, r.get("client_name"),
		                  _join(r.get("enquiry_source"), r.get("movement_type")),
		                  r.get("status")))
	return out


def points_quotations(rows):
	out = []
	for r in rows:
		d = to_date(r.get("transaction_date"))
		if not d or _docstatus(r) not in (0, 1):
			continue
		valid = to_date(r.get("valid_till"))
		out.append(_point(r, d, 1, _dim(r.get("status")),
		                  r.get("customer_name") or r.get("party_name"),
		                  _join("Lead" if _text(r.get("quotation_to")) == "Lead" else "",
		                        "Valid till " + short_date(valid) if valid else ""),
		                  r.get("status"), amount=money(_num(r.get("base_grand_total")))))
	return out


def points_jobs(rows):
	out = []
	for r in rows:
		d = to_date(r.get("jo_date"))
		if not d or _docstatus(r) not in (0, 1):
			continue
		dim = _dim(r.get("fps_category"), SOW_SHORT)
		out.append(_point(r, d, 1, dim, r.get("customer_name") or r.get("customer"),
		                  _join(dim[1] if dim[0] != NOT_SET_KEY else "",
		                        r.get("client_reference_no")),
		                  r.get("fps_stage")))
	return out


def points_customs_cleared(rows):
	out = []
	for r in rows:
		d = to_date(r.get("clearance_date"))
		if not d:
			continue
		boe = _text(r.get("boe_number"))
		out.append(_point(r, d, 1, _dim(r.get("fps_clearance_type")), r.get("customer"),
		                  _join(r.get("fps_clearance_type"), ("BOE " + boe) if boe else ""),
		                  r.get("status")))
	return out


def points_deliveries(rows):
	out = []
	for r in rows:
		d = to_date(r.get("pod_date"))
		if (not d or _docstatus(r) not in (0, 1)
		        or _text(r.get("delivery_status")) != "Delivered"):
			continue
		out.append(_point(r, d, 1, _dim(r.get("movement_type")), r.get("customer"),
		                  _join(r.get("job_order"), r.get("client_reference_no")),
		                  r.get("delivery_status")))
	return out


def points_job_updates(rows):
	"""One point per update; the point is named after its Job Order (the
	record a person can open), with the row's creation time as tie-break."""
	out = []
	for r in rows:
		d = to_date(r.get("update_date"))
		if not d or _text(r.get("source")) == "Backfill" or not r.get("parent"):
			continue
		dim = _dim(r.get("milestone"), MILESTONE_LABELS)
		if dim[0] == NOT_SET_KEY:
			dim = (NOT_SET_KEY, "No milestone")
		out.append(_point(r, d, 1, dim, r.get("job_customer"),
		                  _join(dim[1] if dim[0] != NOT_SET_KEY else "", r.get("status_line")),
		                  r.get("job_stage"), name=r.get("parent"),
		                  seq=_text(r.get("creation")) or _text(r.get("name"))))
	return out


def points_invoiced(rows):
	"""Submitted invoices by posting date, value base_net_total (spec).

	SPEC DEVIATION (an addition): payment requests (fps_is_payment_request = 1,
	an advance billed on the Sales Invoice doctype -- one on the site, 13 Jun,
	AED 88,000) are left out, so the KPI is revenue invoiced, not cash called.
	"""
	out = []
	for r in rows:
		d = to_date(r.get("posting_date"))
		if not d or _docstatus(r) != 1 or int(_num(r.get("fps_is_payment_request"))):
			continue
		amount = money(_num(r.get("base_net_total")))
		due = to_date(r.get("due_date"))
		out.append(_point(r, d, amount, _dim(r.get("status")), r.get("customer_name") or r.get("customer"),
		                  _join(r.get("fps_job_order"), ("Due " + short_date(due)) if due else ""),
		                  r.get("status"), amount=amount))
	return out


def points_collected(rows):
	out = []
	for r in rows:
		d = to_date(r.get("posting_date"))
		if not d or (r.get("payment_type") and _text(r.get("payment_type")) != "Receive"):
			continue
		amount = money(_num(r.get("base_received_amount")))
		ref = _text(r.get("reference_no"))
		out.append(_point(r, d, amount, _dim(r.get("mode_of_payment")),
		                  r.get("party_name") or r.get("party"),
		                  _join(r.get("mode_of_payment"), ("Ref " + ref) if ref else ""),
		                  "", amount=amount))
	return out


POINT_BUILDERS = {
	"enquiries": points_enquiries,
	"quotations": points_quotations,
	"jobs": points_jobs,
	"customs_cleared": points_customs_cleared,
	"deliveries": points_deliveries,
	"job_activity": points_job_updates,
	"invoiced": points_invoiced,
	"collected": points_collected,
}


def _pairs(points):
	return [(p["date"], p["value"]) for p in points]


def _first_seen(points):
	return min((p["date"] for p in points), default=None)


# FPS Job Update rows are logged by the System hooks from 2026-09-11 (the
# go-live backfill ran the same evening), but update_date is the EVENT date, so
# retro-logged rows reach back to June. Stray back-dated rows must not count as
# proof that the source covered the whole previous window (previous_total).
SOURCE_LIVE_FROM = {
	"job_activity": date(2026, 9, 11),
}


def source_first_seen(key, points):
	"""Earliest point, but never before the source went live."""
	first = _first_seen(points)
	live_from = SOURCE_LIVE_FROM.get(key)
	if first is None or live_from is None:
		return first
	return max(first, live_from)


def summarize(points, period, as_of, unit="count", first_seen=None):
	"""value / previous / delta_pct / series for one metric over one period.

	first_seen defaults to the earliest point; a filtered view passes the
	unfiltered one, since the question is whether the SOURCE reaches back.
	"""
	as_of = to_date(as_of)
	current, previous = period_windows(period, as_of)
	pairs = _pairs(points)
	if first_seen is None:
		first_seen = _first_seen(points)
	value = as_unit(window_total(pairs, current), unit)
	prev = previous_total(pairs, previous, first_seen)
	prev = None if prev is None else as_unit(prev, unit)
	return {
		"value": value,
		"previous": prev,
		"delta_pct": delta_pct(value, prev),
		"granularity": PERIODS[period]["granularity"],
		"series": bucket_series(pairs, period, as_of, unit),
	}


# --------------------------------------------------------------------------
# Facts the context lines, caveats and insights share
# --------------------------------------------------------------------------

def receipt_lag_days(payment_rows, as_of):
	"""Median days between a receipt's posting date and the day it was booked
	(creation), over receipts posted in the last LAG_WINDOW_DAYS.

	None when fewer than LAG_MIN_RECEIPTS receipts fall in that window (spec):
	a median of one or two bookings is an anecdote, not a booking habit.
	"""
	as_of = to_date(as_of)
	since = as_of - timedelta(days=LAG_WINDOW_DAYS)
	lags = []
	for r in payment_rows or []:
		posted = to_date(r.get("posting_date"))
		booked = to_date(r.get("creation"))
		if posted and booked and since <= posted <= as_of:
			lags.append(max((booked - posted).days, 0))
	if len(lags) < LAG_MIN_RECEIPTS:
		return None
	return int(round_half_up(median(lags)))


LAG_MIN_RECEIPTS = 3
# SPEC DEVIATION (an addition): the spec always shows the lag caveat. Below a
# week it only says "recent days may move", which every live number does, so it
# would be noise on the card. On 2026-10-10 the median is 29 days.
LAG_CAVEAT_DAYS = 7


def drafts_pending(invoice_rows):
	"""(count, grand total) of draft sales invoices -- what is waiting to be billed."""
	drafts = [r for r in invoice_rows or [] if _docstatus(r) == 0]
	return len(drafts), money(sum(_num(r.get("base_grand_total")) for r in drafts))


def open_receivables(invoice_rows):
	"""Submitted invoices that still carry an outstanding amount."""
	return [r for r in invoice_rows or []
	        if _docstatus(r) == 1 and _num(r.get("outstanding_amount")) != 0]


def last_submitted_invoice(invoice_rows, as_of):
	"""Posting date of the latest submitted invoice (credit notes do not count as
	billing; payment requests do), ignoring any dated after as_of. None if none."""
	as_of = to_date(as_of)
	dates = [to_date(r.get("posting_date")) for r in invoice_rows or []
	         if _docstatus(r) == 1 and not int(_num(r.get("is_return")))]
	return max((x for x in dates if x and x <= as_of), default=None)


def duplicate_drafts(invoice_rows):
	"""Draft invoices whose (fps_job_order, base_grand_total to the fils) equals a
	SUBMITTED invoice's -- the shape of an invoice raised twice for one job.

	On 2026-10-10 two drafts of 25 Sep (AED 471,943.63 and 159,420.92) repeat
	two invoices of 11 Aug that are already Paid. Rows without a Job Order are
	never matched: two unlinked invoices of the same amount prove nothing.
	Returns the draft rows, newest first.
	"""
	rows = invoice_rows or []
	submitted = {(_text(r.get("fps_job_order")), money(_num(r.get("base_grand_total"))))
	             for r in rows if _docstatus(r) == 1 and _text(r.get("fps_job_order"))}
	hits = [r for r in rows
	        if _docstatus(r) == 0 and _text(r.get("fps_job_order"))
	        and (_text(r.get("fps_job_order")), money(_num(r.get("base_grand_total")))) in submitted]
	return sorted(hits, key=lambda r: (to_date(r.get("posting_date")) or date.min, _text(r.get("name"))),
	              reverse=True)


QUOTE_DRAFT_DAYS = 30


def quote_draft_since(as_of):
	"""First day of the draft-quotation window (QUOTE_DRAFT_DAYS days, as_of included).

	Shared by quotation_drafts() and rule_quotation_drafts' route, so the count
	and the list it opens cannot drift apart."""
	return to_date(as_of) - timedelta(days=QUOTE_DRAFT_DAYS - 1)


def quotation_drafts(quote_rows, as_of):
	"""Draft quotations (docstatus 0) dated in the last QUOTE_DRAFT_DAYS days, as_of included."""
	as_of = to_date(as_of)
	since = quote_draft_since(as_of)
	return [r for r in quote_rows or []
	        if _docstatus(r) == 0 and to_date(r.get("transaction_date"))
	        and since <= to_date(r.get("transaction_date")) <= as_of]


def open_jobs(job_rows):
	"""pipeline.OPEN_JOB in Python: not cancelled, stage not closed."""
	return [r for r in job_rows or []
	        if _docstatus(r) < 2 and _text(r.get("fps_stage")) not in CLOSED_JOB_STAGES]


def caveat_for(key, raw, as_of):
	"""The honest caveat a KPI or drawer carries, or None.

	raw is the dict of raw rows by doctype (only the metric's own is needed).
	Only "collected" has one (spec). Invoiced drafts are not a caveat: the
	card's "Drafts waiting" line and the invoicing insights carry them.
	"""
	if key == "collected":
		lag = receipt_lag_days(raw.get("Payment Entry"), as_of)
		if lag is not None and lag >= LAG_CAVEAT_DAYS:
			return ("Receipts are booked a median of %d days after the payment date, "
			        "so recent weeks fill in later." % lag)
	return None


def tile_count(stages, key):
	"""Count of one pipeline tile, or None when the tile was omitted."""
	for tile in (stages or {}).get("tiles", []):
		if tile.get("key") == key:
			return tile.get("count")
	return None


# --------------------------------------------------------------------------
# Insights
#
# Deterministic, rule-based copy -- no model call anywhere (the UI labels the
# banner "Auto-insights · rule-based"). Each rule takes plain inputs and
# returns an Insight dict (or None / a list). The numbers in the third column
# are the KPI spec's rule numbers (kpi_spec.md, 2026-10-10).
#
#   id                      severity                  spec  what
#   customs_docs            critical | warning        R1    originals past / within 14 days of the
#                                                           Dubai Customs deadline (fps_doc_deadline)
#   customs_mofa            critical | warning        R1    MOFA attestation past / within 14 days
#                                                           of its deadline (fps_mofa_deadline)
#   duplicate_drafts        warning   (finance)       R3    a draft repeats a submitted invoice
#                                                           (same Job Order, same grand total)
#   invoicing_stall         warning   (finance)       R2    no invoice submitted for >= 10 days
#                                                           while drafts are waiting
#   jobs_past_eta           warning                   R5    open jobs whose ETA has passed
#   enquiry_silence         warning                   --    no enquiry logged for >= 7 days
#   swing:<kpi>             positive | warning | info R4    big moves in the count KPIs
#   delivered_not_invoiced  info                      R6    jobs at stage Delivered
#   ar_ageing               info      (finance)       R7    >= 40% of outstanding AR is more than
#                                                           90 days past due
#   quotation_drafts        info                      R8    >= 5 draft quotations from the last
#                                                           30 days (AED total for finance only)
#
# enquiry_silence is not in the spec. It is kept from the first build because
# the enquiry log really did go silent for 22 days (13 Sep - 5 Oct) without
# anything on the dashboard saying so.
#
# MONEY. Rules marked (finance) are only evaluated for finance viewers
# (build_dashboard), and the one shared rule that can name an amount
# (quotation_drafts) only adds it when finance=True. No other rule's text
# carries an amount, so a non-finance payload holds no money anywhere.
#
# RANKING (rank_insights): severity critical > warning > positive > info, then
# the order of the table above (_rule), then magnitude (_weight, bigger first),
# then id. The spec says "then by magnitude"; the rules' magnitudes are in
# different units (trackers, AED, days, %), so magnitude only orders insights
# of the same rule (the swings) and the table order decides between rules:
# customs fines first, then billing, then operations.
# --------------------------------------------------------------------------

CUSTOMS_HORIZON_DAYS = 14
INVOICE_STALL_DAYS = 10
ENQUIRY_SILENCE_DAYS = 7
SWING_MIN_BASE = 3      # a previous below this is too small to quote a % on
SWING_MIN_PCT = 50
SWING_NEW_MIN = 5       # "N after none" only once N is worth mentioning
AR_OLD_DAYS = 90
AR_OLD_SHARE = 0.40
# The AR insight says how much of the 90+ day debt was posted before this date
# (spec). See rule_ar_ageing for why the copy does not call it "legacy".
LEGACY_BEFORE = date(2026, 1, 1)
QUOTE_DRAFTS_MIN = 5
QUOTE_DRAFT_STALE_DAYS = 7

_RULE = {
	"customs_docs": 1, "customs_mofa": 2, "duplicate_drafts": 3, "invoicing_stall": 4,
	"jobs_past_eta": 5, "enquiry_silence": 6, "swing": 7, "delivered_not_invoiced": 8,
	"ar_ageing": 9, "quotation_drafts": 10,
}


def _insight(id_, severity, title, detail, rule, weight, metric_key=None, route=None):
	item = {
		"id": id_,
		"severity": severity,
		"title": clip(title, TITLE_MAX),
		"detail": clip(detail, DETAIL_MAX),
		"_rule": rule,
		"_weight": weight,
	}
	if metric_key:
		item["metric_key"] = metric_key
	if route:
		item["route"] = route
	return item


_CUSTOMS_CLOCKS = {
	# status field -> (deadline field, statuses that are still open,
	#                  late ON the deadline day)
	# fps_doc_deadline is Dubai Customs' Fine Start Date (customs_clock.py):
	# fines run from that day, included, so on it the originals are already
	# late. A MOFA deadline is the last day to attest, so it is not missed yet.
	"fps_doc_submission": ("fps_doc_deadline", CUSTOMS_OPEN_DOC, True),
	"fps_mofa_status": ("fps_mofa_deadline", CUSTOMS_OPEN_MOFA, False),
}


def customs_open(row, status_field):
	"""True when this clock is explicitly marked open (see CUSTOMS_OPEN_DOC)."""
	open_values = {v.lower() for v in _CUSTOMS_CLOCKS[status_field][1]}
	return _text(row.get(status_field)).lower() in open_values


def customs_deadlines(trackers, status_field, as_of, horizon=CUSTOMS_HORIZON_DAYS):
	"""(overdue, upcoming) for one clock, each [(deadline, tracker name)] oldest first.

	overdue: marked open with the deadline before as_of -- and, for the
	documents clock, ON as_of too: fps_doc_deadline is the first fine day, so a
	deadline of today is already missed. For MOFA a deadline of today is not
	missed yet. upcoming: marked open with the deadline from there to as_of +
	horizon, inclusive. Trackers without a deadline are in neither.
	"""
	as_of = to_date(as_of)
	end = as_of + timedelta(days=horizon)
	date_field, _open, late_on_day = _CUSTOMS_CLOCKS[status_field]
	overdue, upcoming = [], []
	for r in trackers or []:
		deadline = to_date(r.get(date_field))
		if not deadline or not customs_open(r, status_field):
			continue
		if deadline < as_of or (late_on_day and deadline == as_of):
			overdue.append((deadline, _text(r.get("name"))))
		elif deadline <= end:
			upcoming.append((deadline, _text(r.get("name"))))
	return sorted(overdue), sorted(upcoming)


def _overdue(trackers, status_field, as_of):
	"""[(deadline, name)] marked open and already late on as_of, oldest first
	(before as_of; on as_of too for the documents clock -- see customs_deadlines)."""
	return customs_deadlines(trackers, status_field, as_of)[0]


_CUSTOMS_COPY = {
	"fps_doc_submission": {
		"id": "customs_docs",
		"noun": ("document submission", "document submissions"),
		"past": "past the Dubai Customs deadline",
		"why": "Dubai Customs fines late originals every day until they are submitted.",
	},
	"fps_mofa_status": {
		"id": "customs_mofa",
		"noun": ("MOFA attestation", "MOFA attestations"),
		"past": "past the deadline",
		"why": "Attestation is due 14 days after clearance.",
	},
}


def rule_customs_deadline(trackers, as_of, status_field, horizon=CUSTOMS_HORIZON_DAYS):
	"""R1, one insight per clock (documents, MOFA).

	Critical when any deadline has passed (the detail names the oldest and
	counts what falls due within `horizon` days); warning when none has passed
	but some fall due within `horizon` days; None otherwise. Only trackers whose
	status is explicitly open count (CUSTOMS_OPEN_DOC / CUSTOMS_OPEN_MOFA).
	"""
	as_of = to_date(as_of)
	copy = _CUSTOMS_COPY[status_field]
	date_field, open_values, late_on_day = _CUSTOMS_CLOCKS[status_field]
	open_values = list(open_values)
	overdue, upcoming = customs_deadlines(trackers, status_field, as_of, horizon)
	one, many = copy["noun"]
	if overdue:
		n = len(overdue)
		oldest, name = overdue[0]
		soon = len(upcoming)
		detail = "Oldest deadline %s (%s); %s. %s" % (
			short_date(oldest), name,
			("%d more %s due in the next %d days" % (soon, plural(soon, "falls", "fall"), horizon))
			if soon else "none other falls due in the next %d days" % horizon,
			copy["why"])
		return _insight(
			copy["id"], "critical",
			"%d %s %s" % (n, plural(n, one + " is", many + " are"), copy["past"]),
			detail, _RULE[copy["id"]], n,
			route=list_route("Customs Tracker", {
				status_field: ["in", open_values],
				# Same cut as customs_deadlines: the deadline day is late for documents.
				date_field: ["<=" if late_on_day else "<", as_of.isoformat()],
			}))
	if upcoming:
		n = len(upcoming)
		deadline, name = upcoming[0]
		end = as_of + timedelta(days=horizon)
		return _insight(
			copy["id"], "warning",
			"%d %s due in the next %d days" % (n, plural(n, one + " falls", many + " fall"), horizon),
			"Next: %s, due %s. %s" % (name, short_date(deadline), copy["why"]),
			_RULE[copy["id"]], n,
			route=list_route("Customs Tracker", {
				status_field: ["in", open_values],
				date_field: ["<=", end.isoformat()],
			}))
	return None


def rule_duplicate_drafts(invoice_rows):
	"""R3 (finance). Drafts that repeat a submitted invoice -- see duplicate_drafts."""
	hits = duplicate_drafts(invoice_rows)
	if not hits:
		return None
	n = len(hits)
	names = sorted(_text(r.get("name")) for r in hits)
	total = money(sum(_num(r.get("base_grand_total")) for r in hits))
	named = " and ".join(names[:2]) + (" (and %d more)" % (n - 2) if n > 2 else "")
	return _insight(
		"duplicate_drafts", "warning",
		"%d draft %s an already submitted invoice" % (n, plural(n, "invoice repeats", "invoices repeat")),
		"%s %s the Job Order and grand total of a submitted invoice (%s in all); "
		"check before submitting." % (named, plural(n, "has", "have"), format_money_compact(total)),
		_RULE["duplicate_drafts"], total,
		route=list_route("Sales Invoice", {"docstatus": 0}))


def rule_invoicing_stall(last_invoice_date, as_of, drafts_count, drafts_value, lookback_days):
	"""R2 (finance). No invoice submitted for INVOICE_STALL_DAYS days while drafts wait.

	Without drafts a quiet stretch is not a stall (nothing is ready to bill);
	delivered jobs with no invoice yet are delivered_not_invoiced's job.
	"""
	if not drafts_count:
		return None
	as_of = to_date(as_of)
	last = to_date(last_invoice_date)
	if last and last > as_of:
		last = None  # a future-dated invoice is not evidence of recent billing
	days = (as_of - last).days if last else lookback_days
	if days < INVOICE_STALL_DAYS:
		return None
	waiting = "%d draft %s worth %s %s waiting." % (
		drafts_count, plural(drafts_count, "invoice", "invoices"),
		format_money_compact(drafts_value), plural(drafts_count, "is", "are"))
	if last:
		title = "No invoice submitted for %d days" % days
		detail = "The last one was posted %s. %s" % (short_date(last), waiting)
	else:
		title = "No invoice submitted in the last %d days" % lookback_days
		detail = waiting
	return _insight("invoicing_stall", "warning", title, detail, _RULE["invoicing_stall"], days,
	                metric_key="invoiced")


def rule_jobs_past_eta(open_job_rows, as_of):
	"""R5. Open jobs whose ETA has passed -- same rule as the strip's footnote."""
	as_of = to_date(as_of)
	hits = sorted((to_date(r.get("eta")), _text(r.get("name"))) for r in open_job_rows or []
	              if to_date(r.get("eta")) and to_date(r.get("eta")) < as_of)
	if not hits:
		return None
	n = len(hits)
	eta, name = hits[0]
	return _insight(
		"jobs_past_eta", "warning",
		"%d open %s past %s ETA" % (n, plural(n, "job is", "jobs are"), plural(n, "its", "their")),
		"Oldest ETA %s on %s. Move the job on or update its ETA." % (short_date(eta), name),
		_RULE["jobs_past_eta"], n,
		route=list_route("Job Order", {
			"fps_stage": ["not in", list(CLOSED_JOB_STAGES)],
			# '<' on a Date field is wrapped as IFNULL(eta,'0001-01-01') in list view
			# (db_query_compat), so it would match every job with no ETA. 'between'
			# skips IFNULL, so NULL never matches. The end date is inclusive, hence
			# as_of - 1 day. Same open-job rule as open_jobs(): exclude cancelled.
			"eta": ["between", ["2000-01-01", (as_of - timedelta(days=1)).isoformat()]],
			"docstatus": ["<", 2],
		}))


def rule_enquiry_silence(last_enquiry_date, as_of, lookback_days):
	"""Not in the spec (see the table). The enquiry log has gone quiet."""
	as_of = to_date(as_of)
	last = to_date(last_enquiry_date)
	if last and last > as_of:
		last = None
	days = (as_of - last).days if last else lookback_days
	if days < ENQUIRY_SILENCE_DAYS:
		return None
	if last:
		title = "No new enquiry logged for %d days" % days
		detail = "The last one is dated %s. " % short_date(last)
	else:
		title = "No new enquiry logged in the last %d days" % lookback_days
		detail = ""
	detail += "Check that bot-line and mailbox enquiries are still being logged."
	return _insight("enquiry_silence", "warning", title, detail, _RULE["enquiry_silence"], days,
	                metric_key="enquiries")


def rule_volume_swings(kpis, compare_label):
	"""R4. Big moves in the count KPIs, one insight per KPI.

	previous >= SWING_MIN_BASE and |delta| >= SWING_MIN_PCT: positive when the
	move is in the KPI's good direction, warning when not. previous == 0 and
	value >= SWING_NEW_MIN: info, "N after none".

	SPEC DEVIATION (the spec says "every returned KPI", and null like 0):
	skipped are money KPIs (a count threshold of 3 means nothing in AED, and
	invoicing_stall / ar_ageing already speak for money), neutral KPIs (no good
	direction to judge by), KPIs with a caveat (their recent numbers are known
	to be incomplete -- receipts are booked weeks late, so "Collected down 100%"
	would be a false alarm) and a null previous (it means "not comparable", see
	previous_total, so "after a quiet period" would not be true).
	"""
	compare = compare_label.replace("vs ", "", 1)  # "previous 7 days"
	out = []
	for k in kpis or []:
		if (k.get("unit") != "count" or k.get("good_direction") == "none"
		        or k.get("caveat") or k.get("previous") is None):
			continue
		value, prev, pct = k["value"], k["previous"], k.get("delta_pct")
		label = k["label"]
		if prev >= SWING_MIN_BASE and pct is not None and abs(pct) >= SWING_MIN_PCT:
			improving = (pct > 0) == (k["good_direction"] == "up")
			out.append(_insight(
				"swing:" + k["key"], "positive" if improving else "warning",
				"%s %s %s%% %s" % (label, "up" if pct > 0 else "down",
				                   _strip_zeros("%.1f" % abs(pct)), compare_label),
				"%s this period against %s in the %s."
				% (format_count(value), format_count(prev), compare),
				_RULE["swing"], abs(pct), metric_key=k["key"]))
		elif prev == 0 and value >= SWING_NEW_MIN:
			out.append(_insight(
				"swing:" + k["key"], "info",
				"%s: %s after a quiet %s" % (label, format_count(value), compare),
				"Nothing was logged in the %s, so there is no percentage to compare."
				% compare,
				_RULE["swing"], value, metric_key=k["key"]))
	return out


def rule_delivered_not_invoiced(job_rows):
	"""R6. Jobs at stage Delivered (not cancelled): the work is done, the invoice is not."""
	hits = sorted((to_date(r.get("jo_date")) or date.max, _text(r.get("name")))
	              for r in job_rows or []
	              if _docstatus(r) < 2 and _text(r.get("fps_stage")) == "Delivered")
	if not hits:
		return None
	n = len(hits)
	opened, name = hits[0]
	detail = "Oldest: %s" % name
	if opened != date.max:
		detail += ", opened %s" % short_date(opened)
	detail += ". The next step on %s is the invoice." % plural(n, "it", "each")
	return _insight(
		"delivered_not_invoiced", "info",
		"%d delivered %s waiting to be invoiced" % (n, plural(n, "job is", "jobs are")),
		detail, _RULE["delivered_not_invoiced"], n,
		route=list_route("Job Order", {"fps_stage": "Delivered"}))


def rule_ar_ageing(open_invoices, as_of):
	"""R7 (finance). Outstanding more than AR_OLD_DAYS past due, as a share of all
	outstanding, when that share is >= AR_OLD_SHARE.

	Past due comes from due_date, not the status field: status flips overnight,
	so an invoice due today still reads "Unpaid" until the scheduler runs. Info,
	not a warning (spec): it is a standing position that moves slowly, and on
	2026-10-10 almost all of it (AED 439.9K of 458.2K) sits on invoices carried
	over from Fresa (FPF/INV/...), most of them posted in 2026 -- so "posted
	before 1 Jan 2026" (the spec's cut, AED 108.8K) is stated as a date, never
	labelled "legacy".
	"""
	as_of = to_date(as_of)
	rows = list(open_invoices or [])
	total = money(sum(_num(r.get("outstanding_amount")) for r in rows))
	if total <= 0:
		return None
	old = [r for r in rows
	       if to_date(r.get("due_date")) and (as_of - to_date(r.get("due_date"))).days > AR_OLD_DAYS]
	old_total = money(sum(_num(r.get("outstanding_amount")) for r in old))
	if old_total <= 0 or old_total / total < AR_OLD_SHARE:
		return None
	legacy = money(sum(_num(r.get("outstanding_amount")) for r in old
	                   if to_date(r.get("posting_date")) and to_date(r.get("posting_date")) < LEGACY_BEFORE))
	when = "%d %s %d" % (LEGACY_BEFORE.day, MONTHS[LEGACY_BEFORE.month - 1], LEGACY_BEFORE.year)
	if legacy >= old_total:
		detail = "All of it was posted before %s." % when
	elif legacy > 0:
		detail = "%s of it was posted before %s." % (format_money_compact(legacy), when)
	else:
		detail = "None of it was posted before %s." % when
	return _insight(
		"ar_ageing", "info",
		"%s of %s outstanding is over %d days past due"
		% (format_money_compact(old_total), format_money_compact(total), AR_OLD_DAYS),
		detail, _RULE["ar_ageing"], old_total, route=AR_REPORT_ROUTE)


def rule_quotation_drafts(drafts, as_of, *, finance):
	"""R8. A backlog of draft quotations (quotation_drafts: last 30 days).

	The AED total goes in the title for finance viewers only.
	"""
	n = len(drafts or [])
	if n < QUOTE_DRAFTS_MIN:
		return None
	as_of = to_date(as_of)
	dates = sorted(to_date(r.get("transaction_date")) for r in drafts)
	stale = sum(1 for x in dates if (as_of - x).days > QUOTE_DRAFT_STALE_DAYS)
	title = "%d quotations still in draft" % n
	if finance:
		title += " (%s)" % format_money_compact(sum(_num(r.get("base_grand_total")) for r in drafts))
	detail = "Dated in the last %d days, the oldest %s; %d %s more than %d days old." % (
		QUOTE_DRAFT_DAYS, short_date(dates[0]), stale, plural(stale, "is", "are"),
		QUOTE_DRAFT_STALE_DAYS)
	return _insight("quotation_drafts", "info", title, detail, _RULE["quotation_drafts"], n,
	                # Bounded to the same window as the count: every draft on the
	                # site (50 on 2026-10-10) would otherwise open behind "16".
	                route=list_route("Quotation", {
	                    "docstatus": 0,
	                    "transaction_date": ["between", [quote_draft_since(as_of).isoformat(),
	                                                     as_of.isoformat()]],
	                }))


def rank_insights(items, cap=INSIGHT_CAP):
	"""Most severe first, then rule priority, weight and id; capped; private keys stripped."""
	items = [i for i in items if i]
	items.sort(key=lambda i: (SEVERITY_ORDER.index(i["severity"]), i["_rule"],
	                          -float(i["_weight"]), i["id"]))
	return [{k: v for k, v in i.items() if not k.startswith("_")} for i in items[:cap]]


# --------------------------------------------------------------------------
# Breakdown, options and records (the drawer)
# --------------------------------------------------------------------------

def top_n_with_other(totals, n=BREAKDOWN_TOP, other_label="Other", unit="count"):
	"""totals: {key: (label, value)} -> BreakdownRow list, top n + Other.

	Ties sort by label so the order is stable between polls.
	"""
	ranked = sorted(totals.items(), key=lambda kv: (-kv[1][1], kv[1][0], kv[0]))
	rows = [{"key": k, "label": label, "value": as_unit(v, unit)} for k, (label, v) in ranked[:n]]
	rest = sum(v for _k, (_label, v) in ranked[n:])
	if len(ranked) > n:
		rows.append({"key": OTHER_KEY, "label": other_label, "value": as_unit(rest, unit)})
	return rows


def dimension_options(points):
	"""Distinct dimension values in these points, most frequent first."""
	counts = {}
	for p in points:
		label, n = counts.get(p["dim"], (p["dim_label"], 0))
		counts[p["dim"]] = (label, n + 1)
	ranked = sorted(counts.items(), key=lambda kv: (-kv[1][1], kv[1][0], kv[0]))
	return [{"key": k, "label": label} for k, (label, _n) in ranked]


def latest_records(points, doctype, *, with_value, dedupe=False, cap=RECORDS_CAP):
	"""DrillRecord list: newest first, at most `cap`.

	dedupe keeps only the newest point per name -- for job updates, so the list
	is "the last jobs touched", not one job eight times.
	"""
	ordered = sorted(points, key=lambda p: (p["date"], p["seq"]), reverse=True)
	seen = set()
	records = []
	for p in ordered:
		if dedupe:
			if p["name"] in seen:
				continue
			seen.add(p["name"])
		rec = {"name": p["name"], "title": p["title"], "date": p["date"].isoformat(),
		       "route": form_route(doctype, p["name"])}
		if p["subtitle"]:
			rec["subtitle"] = p["subtitle"]
		if with_value and p["amount"] is not None:
			rec["value"] = p["amount"]
		if p["status"]:
			rec["status"] = p["status"]
		records.append(rec)
		if len(records) >= cap:
			break
	return records


def drill_actions(key, *, finance, can_create):
	spec = METRICS[key]
	actions = [{"key": "open_list", "label": "Open list", "kind": "route", "route": spec["route"]}]
	if spec["new_doctype"] and can_create:
		actions.append({"key": "new", "label": "New " + spec["new_doctype"],
		                "kind": "new_doc", "doctype": spec["new_doctype"]})
	if key == "invoiced" and finance:
		actions.append({"key": "open_report", "label": "Open report", "kind": "route",
		                "route": AR_REPORT_ROUTE})
	return actions


def build_metric_detail(key, raw, *, period, as_of, dimension=None, finance=False,
                        can_create=False):
	"""MetricDetail for one KPI. raw: {doctype: rows} -- at least the metric's own.

	The breakdown for a count metric is by its dimension over ALL rows in the
	window (the distribution the chips choose from); for a money metric it is
	the top customers of the rows the chip selects. A dimension that is not
	among the options (data changed under an open drawer) falls back to "All".
	"""
	spec = METRICS[key]
	as_of = to_date(as_of)
	unit = spec["unit"]
	doctype = spec["doctype"]  # job_activity records open their Job Order
	points = POINT_BUILDERS[key](raw.get(METRIC_SOURCE[key]) or [])
	current, _previous = period_windows(period, as_of)
	in_window = [p for p in points if p["date"] in current]

	options = dimension_options(in_window)
	if dimension is not None and dimension not in {o["key"] for o in options}:
		dimension = None
	chosen = points if dimension is None else [p for p in points if p["dim"] == dimension]
	chosen_window = [p for p in chosen if p["date"] in current]
	summary = summarize(chosen, period, as_of, unit, first_seen=source_first_seen(key, points))

	if unit == "currency":
		totals = {}
		for p in chosen_window:
			label, v = totals.get(p["title"], (p["title"], 0))
			totals[p["title"]] = (label, v + p["value"])
		title = "Top customers"
	else:
		totals = {}
		for p in in_window:
			label, v = totals.get(p["dim"], (p["dim_label"], 0))
			totals[p["dim"]] = (label, v + 1)
		title = "By " + spec["dimension_label"].lower()
	rows = top_n_with_other(totals, unit=unit)
	breakdown = {"title": title, "rows": rows} if rows else None

	detail = {
		"key": key,
		"label": spec["label"],
		"unit": unit,
		"period": period,
		"period_label": PERIODS[period]["label"],
		"compare_label": PERIODS[period]["compare"],
		"granularity": summary["granularity"],
		"value": summary["value"],
		"previous": summary["previous"],
		"delta_pct": summary["delta_pct"],
		"good_direction": spec["good_direction"],
		"series": summary["series"],
		"dimension_label": spec["dimension_label"],
		"dimension_options": options,
		"dimension": dimension,
		"breakdown": breakdown,
		# DrillRecord.value is always MONEY (dashboard.ts): the amount behind a
		# money metric, or a quotation's total behind the Quotations count --
		# the latter only for Accounts roles. The UI formats it as money.
		"records": latest_records(chosen_window, doctype,
		                          with_value=(unit == "currency" or finance),
		                          dedupe=(key == "job_activity")),
		"actions": drill_actions(key, finance=finance, can_create=can_create),
	}
	if unit == "currency":
		detail["currency"] = CURRENCY
	caveat = caveat_for(key, raw, as_of)
	if caveat:
		detail["caveat"] = caveat
	return _ordered(detail, MetricDetailKeys)


# Field order of the TS interfaces, so payloads diff cleanly against them.
MetricDetailKeys = ("key", "label", "unit", "currency", "period", "period_label",
                    "compare_label", "granularity", "value", "previous", "delta_pct",
                    "good_direction", "series", "dimension_label", "dimension_options",
                    "dimension", "breakdown", "records", "actions", "caveat")
KpiKeys = ("key", "label", "definition", "unit", "currency", "value", "previous",
           "delta_pct", "good_direction", "granularity", "series", "context",
           "caveat", "route", "new_doctype", "finance")


def _ordered(d, keys):
	return {k: d[k] for k in keys if k in d}


# --------------------------------------------------------------------------
# KPIs, trend, dashboard
# --------------------------------------------------------------------------

def _line(label, value):
	return {"label": label, "value": value}


def kpi_context(key, *, points, raw, stages, period, as_of, finance):
	"""Up to two pre-formatted facts under a KPI value.

	The spec's line comes first; a second line, where there is one, is a
	builder addition that answers the next obvious question. Money appears only
	on the two finance KPIs, which non-finance viewers never receive.
	"""
	as_of = to_date(as_of)
	current, _previous = period_windows(period, as_of)
	in_window = [p for p in points if p["date"] in current]
	lines = []

	def tile(label, tile_key):
		n = tile_count(stages, tile_key)
		if n is not None:
			lines.append(_line(label, format_count(n)))

	if key == "enquiries":
		tile("Open now", "enquiry")                     # spec: count of status Open
		lines.append(_line("Quoted", format_count(sum(1 for p in in_window if p["status"] == "Quoted"))))
	elif key == "quotations":
		quotes = raw.get("Quotation") or []
		submitted = sum(1 for r in quotes
		                if _docstatus(r) == 1 and to_date(r.get("transaction_date")) in current)
		lines.append(_line("Submitted", format_count(submitted)))
		lines.append(_line("Drafts, last %d days" % QUOTE_DRAFT_DAYS,
		                   format_count(len(quotation_drafts(quotes, as_of)))))
	elif key == "jobs":
		tile("Active pipeline", "job_order")             # spec: pipeline.OPEN_JOB
		tile("In progress", "in_progress")
	elif key == "customs_cleared":
		overdue = _overdue(raw.get("Customs Tracker"), "fps_doc_submission", as_of)
		lines.append(_line("Docs overdue", format_count(len(overdue))))
		tile("Not cleared", "customs")
	elif key == "deliveries":
		tile("Awaiting invoice", "delivered")
		pending = sum(1 for r in raw.get("Proof of Delivery") or []
		              if _docstatus(r) in (0, 1) and _text(r.get("delivery_status")) == "Pending"
		              and to_date(r.get("pod_date")) in current)
		lines.append(_line("PODs pending", format_count(pending)))
	elif key == "job_activity":
		lines.append(_line("Jobs updated", format_count(len({p["name"] for p in in_window}))))
		lines.append(_line("Milestones", format_count(sum(1 for p in in_window if p["dim"] != NOT_SET_KEY))))
	elif key == "invoiced":
		invoices = raw.get("Sales Invoice")
		n, value = drafts_pending(invoices)
		lines.append(_line("Drafts waiting", "%s · %s" % (format_count(n), format_money_compact(value))))
		last = last_submitted_invoice(invoices, as_of)
		if last:
			lines.append(_line("Last submitted", short_date(last)))
	elif key == "collected":
		if raw.get("Sales Invoice") is not None:   # unreadable -> omitted, never "AED 0"
			receivable = open_receivables(raw["Sales Invoice"])
			lines.append(_line("Outstanding AR", format_money_compact(
				sum(_num(r.get("outstanding_amount")) for r in receivable))))
		lines.append(_line("Receipts", format_count(len(in_window))))
	return lines[:2]


def build_kpi(key, points, *, period, as_of, context, caveat, creatable):
	spec = METRICS[key]
	summary = summarize(points, period, as_of, spec["unit"], first_seen=source_first_seen(key, points))
	kpi = {
		"key": key,
		"label": spec["label"],
		"definition": spec["definition"],
		"unit": spec["unit"],
		"value": summary["value"],
		"previous": summary["previous"],
		"delta_pct": summary["delta_pct"],
		"good_direction": spec["good_direction"],
		"granularity": summary["granularity"],
		"series": summary["series"],
		"context": context,
		"route": spec["route"],
		"finance": spec["finance"],
	}
	if spec["unit"] == "currency":
		kpi["currency"] = CURRENCY
	if caveat:
		kpi["caveat"] = caveat
	if spec["new_doctype"] and spec["new_doctype"] in creatable:
		kpi["new_doctype"] = spec["new_doctype"]
	return _ordered(kpi, KpiKeys)


def build_trend(points_by_key, as_of, finance, raw):
	"""TrendMode list. A series is shown only when its metric is available; a
	mode with no series is dropped; money only for finance viewers."""
	modes = []
	for mode_key, label, unit, money_mode, series_spec in TREND_MODES:
		if money_mode and not finance:
			continue
		series = [(k, l, slot) for k, l, slot in series_spec if k in points_by_key]
		if not series:
			continue
		columns = {k: weekly_totals(_pairs(points_by_key[k]), as_of) for k, _l, _s in series}
		points = []
		for i, week_start in enumerate(trend_week_starts(as_of)):
			points.append({
				"week_start": week_start.isoformat(),
				"label": short_date(week_start),
				"partial": week_start <= as_of <= week_start + timedelta(days=6),
				"values": {k: as_unit(columns[k][i][1], unit) for k, _l, _s in series},
			})
		mode = {
			"key": mode_key,
			"label": label,
			"unit": unit,
			"series": [{"key": k, "label": l, "slot": slot} for k, l, slot in series],
			"points": points,
			"finance": money_mode,
		}
		if unit == "currency":
			mode["currency"] = CURRENCY
		if money_mode and "collected" in points_by_key:
			caveat = caveat_for("collected", raw, as_of)
			if caveat:
				mode["caveat"] = caveat
		modes.append(_ordered(mode, ("key", "label", "unit", "currency", "series",
		                             "points", "caveat", "finance")))
	return modes


def build_dashboard(*, period, as_of, generated_at, viewer, raw, stages, creatable=()):
	"""DashboardPayload.

	raw: {doctype: rows} for every doctype the viewer may read. A doctype that
	is absent (or None) was not readable and its KPIs, trend series and
	insights are left out -- never shown as zero. Money doctypes are only
	present for finance viewers; build_dashboard re-checks viewer["finance"]
	anyway so a caller mistake cannot leak them.
	"""
	check_period(period)
	as_of = to_date(as_of)
	finance = bool(viewer.get("finance"))
	creatable = set(creatable or ())
	floor = fetch_floor(period, as_of)
	lookback = (as_of - floor).days
	if not finance:
		# Belt and braces: whatever the caller passed, no money row is even
		# looked at for a viewer without an Accounts role.
		raw = {dt: rows for dt, rows in raw.items() if dt not in MONEY_DOCTYPES}

	points_by_key = {}
	for key in KPI_ORDER:
		source = raw.get(METRIC_SOURCE[key])
		if source is None or (METRICS[key]["finance"] and not finance):
			continue
		points_by_key[key] = POINT_BUILDERS[key](source)

	kpis = []
	for key in KPI_ORDER:
		if key not in points_by_key:
			continue
		kpis.append(build_kpi(
			key, points_by_key[key], period=period, as_of=as_of,
			context=kpi_context(key, points=points_by_key[key], raw=raw, stages=stages,
			                    period=period, as_of=as_of, finance=finance),
			caveat=caveat_for(key, raw, as_of), creatable=creatable))

	# Insights: a rule runs only when its doctype was readable (raw present);
	# the money rules only for finance viewers. See the Insights section.
	insights = []
	trackers = raw.get("Customs Tracker")
	if trackers is not None:
		insights += [rule_customs_deadline(trackers, as_of, "fps_doc_submission"),
		             rule_customs_deadline(trackers, as_of, "fps_mofa_status")]
	if finance and raw.get("Sales Invoice") is not None:
		invoices = raw["Sales Invoice"]
		n_drafts, drafts_value = drafts_pending(invoices)
		insights += [rule_duplicate_drafts(invoices),
		             rule_invoicing_stall(last_submitted_invoice(invoices, as_of), as_of,
		                                  n_drafts, drafts_value, lookback),
		             rule_ar_ageing(open_receivables(invoices), as_of)]
	if raw.get("Job Order") is not None:
		insights += [rule_jobs_past_eta(open_jobs(raw["Job Order"]), as_of),
		             rule_delivered_not_invoiced(raw["Job Order"])]
	if "enquiries" in points_by_key:
		last = max((p["date"] for p in points_by_key["enquiries"] if p["date"] <= as_of),
		           default=None)
		insights.append(rule_enquiry_silence(last, as_of, lookback))
	if raw.get("Quotation") is not None:
		insights.append(rule_quotation_drafts(quotation_drafts(raw["Quotation"], as_of), as_of,
		                                      finance=finance))
	insights += rule_volume_swings(kpis, PERIODS[period]["compare"])

	return {
		"as_of": as_of.isoformat(),
		"generated_at": generated_at,
		"period": period,
		"period_label": PERIODS[period]["label"],
		"compare_label": PERIODS[period]["compare"],
		"viewer": _viewer(viewer, finance),
		"kpis": kpis,
		"stages": {"tiles": list((stages or {}).get("tiles", [])),
		           "footnotes": list((stages or {}).get("footnotes", []))},
		"trend": build_trend(points_by_key, as_of, finance, raw),
		"insights": rank_insights(insights),
	}


def _viewer(viewer, finance):
	out = {"finance": finance}
	if viewer.get("full_name"):
		out["full_name"] = viewer["full_name"]
	return out


def timestamp(dt):
	"""'yyyy-mm-dd HH:mm:ss' for generated_at."""
	if isinstance(dt, datetime):
		return dt.strftime("%Y-%m-%d %H:%M:%S")
	return str(dt)[:19]
