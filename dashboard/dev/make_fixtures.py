"""Dev fixtures for the FPS Command Center, built by the REAL server logic.

    python dashboard/dev/make_fixtures.py              # writes dashboard/dev/fixtures/*.json
    python dashboard/dev/make_fixtures.py --typecheck  # ...then checks every file against
                                                       # dashboard/src/types/dashboard.ts with tsc

Nothing here talks to ERPNext. A synthetic "site" is built from the live profile
of 2026-10-10 (research_livedata.json: daily and weekly counts, AED amounts,
statuses, the 13 Sep - 5 Oct enquiry hole, the October invoicing gap, receipts
booked weeks late, customs deadlines already overdue). The rows go through the
same filters fps_erpnext.api.command_center applies (simulate_reads below) and
then through fps_erpnext.api.command_center_logic -- the module the API uses --
so a fixture is exactly what the API would return for that data.

Party names are placeholders ("Key account (sample)", "Customer A" ...). Never
put a real customer name in this file or in the fixtures -- nor a real invoice
amount or PO-number range that would identify one.

Deterministic: a fixed seed, a fixed as_of (2026-10-10) and a fixed timestamp,
so re-running produces byte-identical files unless the logic changed.
"""

import argparse
import json
import random
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DASHBOARD = HERE.parent
REPO = DASHBOARD.parent
sys.path.insert(0, str(REPO))

from fps_erpnext.api import command_center_logic as logic  # noqa: E402 -- path set above

AS_OF = date(2026, 10, 10)
GENERATED_AT = "2026-10-10 09:30:00"
OUT = HERE / "fixtures"
SEED = 20261010

WEEKS = logic.trend_week_starts(AS_OF)                         # Mon 20 Jul .. Mon 5 Oct
DAYS14 = [date(2026, 9, 27) + timedelta(days=i) for i in range(14)]  # Sun 27 Sep .. Sat 10 Oct

# The one large account (60% of rows), a neutral placeholder like the others.
KEY = "Key account (sample)"
PARTIES = [KEY, "Customer A", "Customer B", "Customer C",
           "Customer D", "Customer E", "Customer F", "Customer G"]
PARTY_WEIGHTS = [60, 8, 7, 6, 6, 5, 4, 4]

VIEWERS = {
	"finance": {"finance": True, "full_name": "Sample Finance User"},
	"ops": {"finance": False, "full_name": "Sample Ops User"},
}
CREATABLE = {
	"finance": {"FPS Enquiry", "Quotation", "Job Order", "Customs Tracker",
	            "Proof of Delivery", "Sales Invoice", "Payment Entry"},
	"ops": {"FPS Enquiry", "Job Order", "Customs Tracker", "Proof of Delivery"},
}


# --------------------------------------------------------------------------
# Calendar helpers
# --------------------------------------------------------------------------

def d(text):
	return date.fromisoformat(text)


def workdays(start, n_days=6):
	"""Mon-Sat of the week starting `start` (UAE offices work Saturdays often enough)."""
	return [start + timedelta(days=i) for i in range(n_days)]


def spread(rng, days, n):
	return [rng.choice(days) for _ in range(n)]


def profile_dates(rng, weekly, daily14):
	"""Dates reproducing a 12-week weekly profile whose last 14 days are known exactly.

	Weeks 1-9 are spread over Mon-Sat; week 10 (21-27 Sep) ends on the first
	day of the daily profile; weeks 11-12 come straight from the daily profile.
	"""
	assert len(weekly) == 12 and len(daily14) == 14
	assert sum(daily14[1:8]) == weekly[10] and sum(daily14[8:]) == weekly[11], "profile mismatch"
	out = []
	for i in range(9):
		out += spread(rng, workdays(WEEKS[i]), weekly[i])
	out += [DAYS14[0]] * daily14[0]
	out += spread(rng, workdays(WEEKS[9]), weekly[9] - daily14[0])
	for day, n in zip(DAYS14[1:], daily14[1:]):
		out += [day] * n
	return sorted(out)


def between(rng, start, end, n):
	span = (end - start).days
	return sorted(start + timedelta(days=rng.randint(0, span)) for _ in range(n))


def split_amount(rng, total, n):
	"""n amounts (2 dp) that add up to `total` to the fils."""
	if n <= 0:
		return []
	cents = round(total * 100)
	weights = [rng.uniform(0.4, 1.6) for _ in range(n)]
	parts = [int(cents * w / sum(weights)) for w in weights]
	parts[-1] += cents - sum(parts)
	return [p / 100 for p in parts]


def namer(prefix, start=1):
	"""FPS/<prefix>/YYMM/NNN with one serial running across months (as on the site)."""
	serial = [start - 1]

	def name(day):
		serial[0] += 1
		return "FPS/%s/%s/%03d" % (prefix, day.strftime("%y%m"), serial[0])
	return name


def party(rng):
	return rng.choices(PARTIES, PARTY_WEIGHTS)[0]


# --------------------------------------------------------------------------
# The synthetic site
# --------------------------------------------------------------------------

def make_enquiries(rng):
	# Live profile, Cancelled excluded: 52 rows since 20 Jul, none 13 Sep - 5 Oct.
	dates = profile_dates(rng, [2, 8, 5, 5, 7, 7, 4, 2, 0, 0, 0, 12],
	                      [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 5, 6, 0, 0])
	assert not [x for x in dates if d("2026-09-13") <= x <= d("2026-10-05")]
	name = namer("ENQ")
	rows = []
	october = [i for i, x in enumerate(dates) if x >= d("2026-10-01")]
	older = [i for i, x in enumerate(dates) if x < d("2026-10-01")]
	quoted = set(rng.sample(october, 4)) | set(rng.sample(older, 11))   # Quoted 15, Open 37
	whatsapp = set(rng.sample(october, 10)) | set(rng.sample(older, 24))
	for i, day in enumerate(dates):
		via_bot = i in whatsapp
		rows.append({
			"name": name(day), "enquiry_date": day,
			"status": "Quoted" if i in quoted else "Open",
			"enquiry_source": "WhatsApp" if via_bot else "Email",
			"client_name": ("Lead %d (sample)" % (i + 1)) if via_bot and day.month == 10 else party(rng),
			"movement_type": rng.choices(["SEA", "AIR", "LAND"], [5, 3, 2])[0],
		})
	# The 10 bot-line duplicates of 6-8 Oct, cancelled (the read drops them).
	for day in [d("2026-10-06")] * 3 + [d("2026-10-07")] * 3 + [d("2026-10-08")] * 4:
		rows.append({"name": name(day), "enquiry_date": day, "status": "Cancelled",
		             "enquiry_source": "WhatsApp", "client_name": "Lead (duplicate)",
		             "movement_type": "SEA"})
	return rows


def make_quotations(rng):
	weekly = [1, 0, 2, 0, 4, 0, 5, 2, 1, 5, 0, 20]
	daily = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 15, 3, 0]
	values = [11750, 0, 16397084.26, 0, 2497817.32, 0, 2501734.59, 1872719.11, 6880, 1953646.40, 0, None]
	dates = profile_dates(rng, weekly, daily)
	name = namer("QT")
	rows = []

	def add(day, value, docstatus=0, status="Draft", lead=False):
		rows.append({
			"name": None, "transaction_date": day, "docstatus": docstatus, "status": status,
			"base_grand_total": value,
			"customer_name": ("Lead %d (sample)" % (len(rows) + 1)) if lead else party(rng),
			"party_name": None, "quotation_to": "Lead" if lead else "Customer",
			"valid_till": day + timedelta(days=7),
		})

	# Before the 12 weeks: 26 quotations since go-live (25 May).
	for day in between(rng, d("2026-05-25"), d("2026-07-19"), 26):
		add(day, round(rng.uniform(3000, 90000), 2))
	# Weeks 1-11 with the live weekly values; week 3 holds the AED 16.13M draft.
	by_week = {}
	for day in dates:
		by_week.setdefault(logic.iso_week_start(day), []).append(day)
	for i, monday in enumerate(WEEKS[:-1]):
		days = by_week.get(monday, [])
		if not days:
			continue
		if i == 2:
			amounts = [16130800.00] + split_amount(rng, values[i] - 16130800.00, len(days) - 1)
		else:
			amounts = split_amount(rng, values[i], len(days))
		for j, (day, value) in enumerate(zip(days, amounts)):
			if i == 0 and j == 0:
				add(day, value, 1, "Expired")  # the one submitted before October
			else:
				add(day, value)
	# October, day by day (the 9 Oct trio is the live one: 24,600 / 21,750 / 21,000).
	oct7 = split_amount(rng, 416542.50, 2)
	for value in oct7:
		add(d("2026-10-07"), value, 1, "Open", lead=True)
	oct8 = [1147500.00] + split_amount(rng, 2033550.00 - 1147500.00, 14)
	for j, value in enumerate(oct8):
		if j < 5:
			add(d("2026-10-08"), value, 1, "Open", lead=j > 0)
		elif j < 7:
			add(d("2026-10-08"), value, 1, "Lost", lead=True)
		else:
			add(d("2026-10-08"), value)
	add(d("2026-10-09"), 24600.00)
	add(d("2026-10-09"), 21750.00, 1, "Open", lead=True)
	add(d("2026-10-09"), 21000.00, 1, "Open", lead=True)
	# One cancelled quotation (the read drops docstatus 2).
	add(d("2026-07-29"), 5400.00, 2, "Cancelled")

	rows.sort(key=lambda r: r["transaction_date"])
	for r in rows:
		r["name"] = name(r["transaction_date"])
	return rows


def make_jobs(rng):
	dates = profile_dates(rng, [20, 1, 7, 6, 9, 3, 1, 6, 3, 2, 0, 2],
	                      [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0])
	dates = sorted([d("2026-07-20")] * 10 + dates[10:])          # the 20 Jul batch entry
	dates += between(rng, d("2026-07-13"), d("2026-07-19"), 7)
	dates += between(rng, d("2026-05-20"), d("2026-07-12"), 27)
	dates.sort(reverse=True)                                     # newest first
	assert len(dates) == 94

	categories = (["CC - Customs Clearance"] * 78 + ["LT - Local Land Transport"] * 5
	              + ["GJ - General Job"] * 4 + ["XB - Cross-Border Land Transport"] * 3
	              + ["FF - Freight Forwarding"] * 3 + [None])
	rng.shuffle(categories)
	categories.remove("XB - Cross-Border Land Transport")
	categories.insert(1, "XB - Cross-Border Land Transport")    # 7 Oct: cross-border

	# 34 open jobs among the 45 newest; everything else invoiced (60).
	open_pool = (["New"] * 9 + ["In Progress"] * 6 + ["Docs received"] * 5
	             + ["Cleared - Ready"] * 10 + ["Delivered"] * 2)
	stages = ["In Progress", "New"] + open_pool + ["Invoiced"] * 11
	rest = stages[2:]
	rng.shuffle(rest)
	stages = stages[:2] + rest + ["Invoiced"] * (94 - 45)

	rows = []
	for i, (day, stage, cat) in enumerate(zip(dates, stages, categories)):
		who = party(rng)
		rows.append({
			"name": None, "jo_date": day, "docstatus": 0, "fps_category": cat, "fps_stage": stage,
			"eta": None, "customer_name": who, "customer": who,
			"client_reference_no": ("PO# %d" % rng.randint(10000, 19999)) if who == KEY
			else "REF-%04d" % rng.randint(1, 9999),
			"sales_invoice": None,
		})
	# ETAs: exactly two open jobs past ETA (both September jobs), 20 open jobs
	# with none, the rest still ahead.
	open_rows = [r for r in rows if r["fps_stage"] not in logic.CLOSED_JOB_STAGES]  # newest first
	for r in open_rows:
		r["eta"] = AS_OF + timedelta(days=rng.randint(2, 20))
	september = [r for r in open_rows if r["jo_date"].month == 9]
	for r in september[:2]:
		r["eta"] = min(r["jo_date"] + timedelta(days=4), AS_OF - timedelta(days=1))
	for r in [r for r in open_rows if r not in september[:2]][2:22]:
		r["eta"] = None
	invoiced = [r for r in rows if r["fps_stage"] == "Invoiced"]
	for r in invoiced:
		r["eta"] = r["jo_date"] + timedelta(days=rng.randint(1, 10))
	for r in rng.sample(invoiced, 38):
		r["docstatus"] = 1                                   # 38 submitted, 56 drafts
	# Three cancelled May jobs (the read drops docstatus 2).
	for day in (d("2026-05-12"), d("2026-05-14"), d("2026-05-19")):
		rows.append({"name": None, "jo_date": day, "docstatus": 2,
		             "fps_category": "CC - Customs Clearance", "fps_stage": "In Progress",
		             "eta": None, "customer_name": "Customer A", "customer": "Customer A",
		             "client_reference_no": None, "sales_invoice": None})

	name = namer("JO")
	for r in sorted(rows, key=lambda r: r["jo_date"]):
		r["name"] = name(r["jo_date"])
	return rows


# Clearance, document status / deadline, MOFA status / deadline -- the live
# shape of all 56 trackers on 2026-10-10 (dates and statuses only).
CUSTOMS_SHAPE = [
	("2026-06-03", "", "2026-07-03", "", "2026-06-17"),
	("2026-06-05", "", "2026-07-05", "", "2026-06-19"),
	("2026-06-06", "Completed", "2026-07-06", "Completed", "2026-06-20"),
	("2026-06-06", "Completed", "2026-07-06", "N/A", "2026-06-20"),
	("2026-06-06", "Completed", "2026-07-06", "Completed", "2026-06-20"),
	("2026-06-10", "Completed", "2026-07-10", "Completed", "2026-06-24"),
	("2026-07-20", "Pending", "2026-08-19", "Pending", "2026-08-03"),
	("2026-06-10", "Completed", "2026-07-10", "Completed", "2026-06-24"),
	("2026-06-18", "Completed", "2026-07-18", "Completed", "2026-07-02"),
	("2026-06-24", "Completed", "2026-07-24", "Completed", "2026-07-08"),
	("2026-06-24", "Not Applicable", "2026-07-24", "N/A", "2026-07-08"),
	("2026-06-26", "Completed", "2026-07-26", "Completed", "2026-07-10"),
	("2026-06-27", "Completed", "2026-07-27", "Completed", "2026-07-11"),
	("2026-06-27", "Completed", "2026-07-27", "N/A", "2026-07-11"),
	("2026-07-06", "Completed", "2026-08-05", "N/A", "2026-07-20"),
	("2026-07-09", "Completed", "2026-08-08", "N/A", "2026-07-23"),
	("2026-07-06", "Completed", "2026-08-05", "N/A", "2026-07-20"),
	("2026-07-04", "Completed", "2026-08-03", "Completed", "2026-07-18"),
	("2026-07-21", "Completed", "2026-08-20", "Completed", "2026-08-04"),
	("2026-10-05", "Completed", "2026-08-08", "N/A", None),
	("2026-07-14", "Pending", "2026-08-08", "", "2026-07-28"),
	("2026-07-22", "Completed", "2026-08-21", "N/A", "2026-08-05"),
	("2026-07-21", "Completed", "2026-08-20", "Pending", "2026-08-04"),
	("2026-09-28", "Completed", "2026-10-28", "Completed", "2026-10-12"),
	("2026-07-31", "Completed", "2026-08-30", "Completed", "2026-08-14"),
	("2026-07-19", "Completed", "2026-08-18", "Completed", "2026-08-02"),
	("2026-07-22", "Pending", "2026-08-21", "N/A", "2026-08-05"),
	("2026-09-17", "Completed", "2026-10-17", "Completed", "2026-10-01"),
	("2026-07-28", "Completed", "2026-08-27", "N/A", "2026-08-11"),
	("2026-09-10", "Completed", "2026-09-30", "Pending", "2026-09-24"),
	("2026-07-28", "Completed", "2026-08-27", "Completed", "2026-08-11"),
	("2026-07-09", "Pending", "2026-08-08", "", "2026-07-23"),
	("2026-09-18", "Completed", "2026-10-18", "Completed", "2026-10-02"),
	("2026-07-22", "Completed", "2026-08-21", "N/A", "2026-08-05"),
	("2026-09-28", "Completed", "2026-10-28", "Completed", "2026-10-12"),
	("2026-08-05", "Completed", "2026-09-04", "N/A", "2026-08-19"),
	("2026-09-14", "Completed", "2026-10-14", "Completed", "2026-09-28"),
	("2026-09-12", "Completed", "2026-10-12", "Completed", "2026-09-26"),
	("2026-08-12", "Completed", "2026-09-11", "N/A", "2026-08-26"),
	("2026-08-12", "Completed", "2026-09-11", "N/A", "2026-08-26"),
	("2026-09-30", "Completed", "2026-10-30", "Pending", "2026-10-14"),
	("2026-09-14", "Completed", "2026-10-14", "Completed", "2026-09-28"),
	("2026-08-19", "Completed", "2026-09-18", "N/A", "2026-09-02"),
	("2026-08-21", "Completed", "2026-09-20", "Completed", "2026-09-04"),
	("2026-08-27", "Completed", "2026-09-26", "N/A", "2026-09-10"),
	("2026-08-27", "Completed", "2026-09-26", "Completed", "2026-09-10"),
	("2026-08-31", "Pending", "2026-09-30", "N/A", "2026-09-14"),
	("2026-09-10", "Completed", "2026-10-04", "N/A", "2026-09-24"),
	(None, "", None, "", None),
	(None, "", None, "", None),
	("2026-09-20", "Completed", "2026-10-20", "N/A", "2026-10-04"),
	(None, "", None, "", None),
	("2026-10-05", "Pending", "2026-10-19", "Pending", "2026-10-19"),
	(None, "", None, "", None),
	(None, "", None, "", None),
	("2026-10-08", "Pending", "2026-11-07", "Pending", "2026-10-22"),
]
CLEARANCE_TYPES = ["Import to Local from ROW", "Import into Free Zone", "Transfer within FZ",
                   "FZ Transit", "Export", "Import to Local from FZ"]


def make_customs(rng, jobs):
	cc_jobs = [j["name"] for j in jobs if j["docstatus"] < 2]
	rows = []
	for clearance, doc, doc_due, mofa, mofa_due in CUSTOMS_SHAPE:
		cleared = d(clearance) if clearance else None
		# The declaration (BOE) date is the document clock's start: deadline - 30.
		ct = (d(doc_due) - timedelta(days=30)) if doc_due else AS_OF - timedelta(days=rng.randint(3, 20))
		rows.append({
			"name": None, "ct_date": ct, "clearance_date": cleared,
			"status": "Cleared" if cleared else "Pending", "customer": party(rng),
			"job_order": rng.choice(cc_jobs),
			"boe_number": "%d-0%07d-26" % (rng.choice([101, 102, 103]), rng.randint(1000000, 1999999)),
			"fps_clearance_type": rng.choices(CLEARANCE_TYPES, [10, 4, 2, 2, 2, 1])[0] if cleared else "",
			"fps_doc_submission": doc, "fps_doc_deadline": d(doc_due) if doc_due else None,
			"fps_mofa_status": mofa, "fps_mofa_deadline": d(mofa_due) if mofa_due else None,
		})
	name = namer("CT")
	for r in sorted(rows, key=lambda r: r["ct_date"]):
		r["name"] = name(r["ct_date"])
	return rows


# POD date, delivery status, movement, docstatus -- the live shape since 1 Jul.
POD_SHAPE = [
	("2026-10-08", "Pending", "SEA", 0), ("2026-10-08", "Pending", "AIR", 0),
	("2026-10-01", "Delivered", "SEA", 0), ("2026-10-01", "Delivered", "SEA", 0),
	("2026-09-30", "Delivered", "SEA", 0), ("2026-09-23", "Delivered", "SEA", 0),
	("2026-09-21", "Delivered", "AIR", 0), ("2026-09-18", "Delivered", "SEA", 0),
	("2026-09-16", "Delivered", "SEA", 0), ("2026-09-12", "Pending", "AIR", 0),
	("2026-09-01", "Pending", "SEA", 0), ("2026-08-27", "Pending", "AIR", 0),
	("2026-08-27", "Delivered", "AIR", 0), ("2026-08-20", "Delivered", "AIR", 0),
	("2026-08-19", "Delivered", "AIR", 0), ("2026-08-05", "Delivered", "AIR", 0),
	("2026-08-05", "Delivered", "AIR", 0), ("2026-08-03", "Delivered", "SEA", 0),
	("2026-07-28", "Delivered", "SEA", 0), ("2026-07-28", "Delivered", "SEA", 0),
	("2026-07-26", "Pending", "LAND", 0), ("2026-07-24", "Pending", "SEA", 0),
	("2026-07-21", "Pending", "SEA", 1), ("2026-07-21", "Pending", "SEA", 1),
	("2026-07-20", "Delivered", "AIR", 0), ("2026-07-20", "Pending", "AIR", 0),
	("2026-07-14", "Delivered", "LAND", 0), ("2026-07-10", "Delivered", "SEA", 0),
	("2026-07-07", "Delivered", "SEA", 0), ("2026-07-02", "Pending", "LAND", 0),
]


def make_deliveries(rng, jobs):
	shape = list(POD_SHAPE)
	# June: 15 more (the submitted ones are all from before 27 Jun) + 3 cancelled.
	for day in between(rng, d("2026-05-28"), d("2026-06-30"), 15):
		shape.append((day.isoformat(), "Delivered", rng.choice(["SEA", "AIR", "LAND"]),
		              1 if day < d("2026-06-27") and rng.random() < 0.8 else 0))
	for day in ("2026-06-02", "2026-06-09", "2026-06-16"):
		shape.append((day, "Delivered", "SEA", 2))
	job_names = [j["name"] for j in jobs if j["docstatus"] < 2]
	rows = []
	for day, status, movement, docstatus in shape:
		who = party(rng)
		rows.append({"name": None, "pod_date": d(day), "docstatus": docstatus,
		             "delivery_status": status, "customer": who,
		             "job_order": rng.choice(job_names), "movement_type": movement,
		             "client_reference_no": ("PO# %d" % rng.randint(10000, 19999))
		             if who == KEY else None})
	name = namer("POD")
	for r in sorted(rows, key=lambda r: r["pod_date"]):
		r["name"] = name(r["pod_date"])
	return rows


STATUS_LINES = {
	"": "Called the client for the commercial invoice", "OPENED": "Job opened from PO",
	"DOCS": "Shipping documents received", "BOE": "Bill of entry filed",
	"DUTY": "Duty paid via deposit account", "CLEARED": "Cleared by customs",
	"DO": "Delivery order collected", "VEHICLE": "Truck arranged for tomorrow",
	"PICKED_UP": "Cargo picked up at the port", "DELIVERED": "Delivered to consignee",
	"DOCS_IN": "Original documents handed to customs", "SUBMITTED": "Documents submitted",
	"INVOICED": "Invoice drafted",
}
MILESTONES = [m for m in STATUS_LINES if m]


def make_job_updates(rng, jobs):
	# Live-entered updates since go-live; weeks 1-6 were only ever backfill.
	weekly = [0, 0, 0, 0, 0, 0, 4, 20, 27, 23, 14, 15]
	daily = [0, 0, 0, 2, 9, 0, 3, 0, 4, 1, 1, 4, 5, 0]
	live = profile_dates(rng, weekly, daily)
	backfill = between(rng, d("2026-07-20"), d("2026-09-09"), 260)
	open_jobs = [j for j in jobs if j["docstatus"] < 2 and j["fps_stage"] not in logic.CLOSED_JOB_STAGES]
	recent = [j for j in jobs if j["docstatus"] < 2 and j["jo_date"] >= d("2026-07-20")]
	rows = []
	for day, source in [(x, None) for x in live] + [(x, "Backfill") for x in backfill]:
		job = rng.choice(open_jobs if rng.random() < 0.7 else recent)
		if source is None:
			source = rng.choices(["Manual", "System", "Claude"], [4, 4, 2])[0]
			created = datetime.combine(day, datetime.min.time()) + timedelta(
				hours=rng.randint(8, 19), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
		else:
			created = datetime(2026, 9, 10, 13, 9) if rng.random() < 0.5 else datetime(2026, 9, 11, 20, 18)
		milestone = rng.choice(MILESTONES) if rng.random() < 0.65 else ""
		rows.append({
			"name": "%010x" % rng.getrandbits(40), "parent": job["name"], "update_date": day,
			"milestone": milestone,
			"status_line": STATUS_LINES[milestone],
			"event_type": "Milestone" if milestone else "Note", "source": source, "creation": created,
			"parenttype": "Job Order", "parentfield": "fps_updates",
		})
	return rows


def make_invoices(rng, jobs):
	rows = []
	job_names = [j["name"] for j in jobs if j["docstatus"] < 2]

	def add(day, net, grand, docstatus, status, outstanding, who, due_days=30, payment_request=0):
		rows.append({
			"name": None, "posting_date": day, "docstatus": docstatus, "status": status,
			"base_net_total": round(net, 2), "base_grand_total": round(grand, 2),
			"outstanding_amount": round(outstanding, 2),
			"due_date": day + timedelta(days=due_days), "customer_name": who, "customer": who,
			"fps_job_order": rng.choice(job_names) if day.year == 2026 else None,
			"is_return": 1 if net < 0 else 0, "fps_is_payment_request": payment_request,
		})

	def terms(who):
		return 60 if who == KEY else 30

	# Submitted, weeks 1-10: live counts and net totals; week 4 holds two large
	# pass-through customs invoices of 11 Aug (paid). Their amounts are
	# synthetic -- same scale and duty-plus-VAT shape as the live pair, not the
	# live figures -- so week 4's net is their sum plus the week's other 3.
	counts = [11, 8, 2, 5, 5, 2, 0, 4, 5, 1]
	nets = [84858.68, 26601.61, 2361.15, 621153.21, 28466.58, 3437.50, 0, 46956.13, 22404.11, 12051.11]
	# Net -> grand total of the two pass-through invoices of 11 Aug.
	pass_through = {450000.00: 465600.00, 160000.00: 165500.00}
	paid_pass_through = []
	for i, (n, total) in enumerate(zip(counts, nets)):
		if i == 3:
			for net, grand in pass_through.items():
				add(d("2026-08-11"), net, grand, 1, "Paid", 0, KEY)
				paid_pass_through.append(rows[-1])
			n, total = 3, 11153.21
		if i == 9:
			add(d("2026-09-23"), total, total, 1, "Paid", 0, KEY, 60)  # last one: 23 Sep
			continue
		for day, net in zip(spread(rng, workdays(WEEKS[i]), n), split_amount(rng, total, n)):
			who = party(rng)
			grand = round(net * 1.05, 2) if rng.random() < 0.5 else net  # half carry VAT
			due_days = terms(who)
			due = day + timedelta(days=due_days)
			if due >= AS_OF:
				# Live: only AED 19.7K of receivables is not yet due.
				status, out = ("Unpaid", grand) if rng.random() < 0.25 else ("Paid", 0)
			elif rng.random() < 0.55:
				status, out = "Overdue", grand
			else:
				status, out = "Paid", 0
			add(day, net, grand, 1, status, out, who, due_days)
	# A payment request (not invoicing) and a credit note.
	add(d("2026-06-13"), 85000, 85000, 1, "Paid", 0, KEY, payment_request=1)
	add(d("2026-08-24"), -700, -700, 1, "Return", 0, "Customer C")

	# Drafts: 26 waiting, AED 1,474,740.78 in grand total; the two 25 Sep ones
	# mirror the two paid pass-through invoices.
	draft_weeks = {3: (1, 928.00), 4: (2, 306962.00), 6: (2, 197813.35), 7: (2, 16435.64),
	               8: (8, 265893.16)}
	for i, (n, total) in draft_weeks.items():
		for day, grand in zip(spread(rng, workdays(WEEKS[i]), n), split_amount(rng, total, n)):
			add(day, grand / 1.05, grand, 0, "Draft", grand, party(rng))
	for paid in paid_pass_through:
		grand = paid["base_grand_total"]
		add(d("2026-09-25"), paid["base_net_total"], grand, 0, "Draft", grand, KEY, 60)
		# Live: same Job Order and grand total as the paid one (the duplicate-draft insight).
		rows[-1]["fps_job_order"] = paid["fps_job_order"]
	for day, grand in zip(spread(rng, workdays(WEEKS[9]), 5),
	                      split_amount(rng, 653487.21 - sum(pass_through.values()), 5)):
		add(day, grand / 1.05, grand, 0, "Draft", grand, party(rng))
	for grand in split_amount(rng, 33221.42, 4):
		add(d("2026-09-30"), grand / 1.05, grand, 0, "Draft", grand, party(rng), 60)

	# Earlier 2026 (Fresa migration onwards): mostly paid, some overdue.
	for day in between(rng, d("2026-03-01"), d("2026-07-19"), 40):
		who = party(rng)
		net = round(rng.uniform(800, 25000), 2)
		overdue = rng.random() < 0.3
		add(day, net, net * 1.05, 1, "Overdue" if overdue else "Paid",
		    net * 1.05 if overdue else 0, who, terms(who))

	# Legacy receivables (2023-2025), sized so that total outstanding is the
	# live AED 756,615.87.
	open_now = sum(r["outstanding_amount"] for r in rows if r["docstatus"] == 1)
	assert 0 < open_now < 756615.87, open_now
	legacy_days = between(rng, d("2023-04-07"), d("2025-12-15"), 40)
	for day, amount in zip(legacy_days, split_amount(rng, 756615.87 - open_now, 40)):
		add(day, amount, amount, 1, "Overdue", amount, party(rng))

	name = namer("INV")
	for r in sorted(rows, key=lambda r: r["posting_date"]):
		r["name"] = name(r["posting_date"])
	return rows


def make_receipts(rng):
	rows = []

	def add(day, amount, created):
		who = party(rng)
		rows.append({
			"name": None, "posting_date": day, "payment_type": "Receive",
			"base_received_amount": round(amount, 2), "party_name": who, "party": who,
			"mode_of_payment": rng.choices(["Bank Transfer", "Cheque"], [9, 1])[0],
			"reference_no": "SAMPLE-%06d" % rng.randint(0, 999999), "creation": created,
			"docstatus": 1,
		})

	counts = [1, 2, 5, 2, 3, 3, 2, 1, 0, 1, 1, 0]
	values = [100000, 21693.49, 164689.21, 2090, 165322.50, 29667.52, 478393, 5000, 0,
	          59064.46, 12051.11, 0]
	# Receipts were batch-booked on 10-11, 14 and 16-17 Sep; the recent two the
	# same day and a week later.
	batches = [datetime(2026, 9, 10, 18), datetime(2026, 9, 11, 9), datetime(2026, 9, 14, 11),
	           datetime(2026, 9, 16, 21), datetime(2026, 9, 17, 10)]
	for i, (n, total) in enumerate(zip(counts, values)):
		if i == 0:
			add(d("2026-07-22"), total, datetime(2026, 9, 16, 21, 26))   # 56 days late
			continue
		if i == 9:
			add(d("2026-09-24"), total, datetime(2026, 9, 24, 17, 13))
			continue
		if i == 10:
			add(d("2026-09-28"), total, datetime(2026, 10, 5, 17, 57))
			continue
		for day, amount in zip(spread(rng, workdays(WEEKS[i]), n), split_amount(rng, total, n)):
			booked = rng.choice([b for b in batches if b.date() > day])
			add(day, amount, booked)
	# Before the 12 weeks (and before the 120-day lag window): receipts since
	# March, booked within a few days.
	for day in between(rng, d("2026-03-05"), d("2026-06-10"), 18):
		add(day, rng.uniform(2000, 90000),
		    datetime.combine(day, datetime.min.time()) + timedelta(days=rng.randint(1, 6), hours=10))
	name = namer("PR")
	for r in sorted(rows, key=lambda r: r["posting_date"]):
		r["name"] = name(r["posting_date"])
	return rows


def make_site():
	rng = random.Random(SEED)
	jobs = make_jobs(rng)
	return {
		"FPS Enquiry": make_enquiries(rng),
		"Quotation": make_quotations(rng),
		"Job Order": jobs,
		"Customs Tracker": make_customs(rng, jobs),
		"Proof of Delivery": make_deliveries(rng, jobs),
		"FPS Job Update": make_job_updates(rng, jobs),
		"Sales Invoice": make_invoices(rng, jobs),
		"Payment Entry": make_receipts(rng),
	}


# --------------------------------------------------------------------------
# What the API would read (mirrors fps_erpnext.api.command_center filters)
# --------------------------------------------------------------------------

def _keep(row, doctype, extra=()):
	return {k: row.get(k) for k in list(logic.FIELDS[doctype]) + list(extra)}


def _desc(rows, *keys):
	return sorted(rows, key=lambda r: tuple(str(r.get(k) or "") for k in keys), reverse=True)


def simulate_reads(site, floor, *, finance, keys=logic.KPI_ORDER):
	"""Same filters, OR-filters and ordering as command_center._read_rows."""
	need = {logic.METRIC_SOURCE[k] for k in keys if finance or not logic.METRICS[k]["finance"]}
	raw = {}
	if "FPS Enquiry" in need:
		raw["FPS Enquiry"] = _desc([_keep(r, "FPS Enquiry") for r in site["FPS Enquiry"]
		                            if r["enquiry_date"] >= floor and r["status"] != "Cancelled"],
		                           "enquiry_date", "name")
	if "Quotation" in need:
		raw["Quotation"] = _desc([_keep(r, "Quotation") for r in site["Quotation"]
		                          if r["docstatus"] in (0, 1) and r["transaction_date"] >= floor],
		                         "transaction_date", "name")
	if "Customs Tracker" in need:
		raw["Customs Tracker"] = _desc([
			_keep(r, "Customs Tracker") for r in site["Customs Tracker"]
			if (r["clearance_date"] and r["clearance_date"] >= floor)
			or r["ct_date"] >= floor
			or r["fps_doc_submission"] in logic.CUSTOMS_OPEN_DOC
			or r["fps_mofa_status"] in logic.CUSTOMS_OPEN_MOFA], "ct_date", "name")
	if "Proof of Delivery" in need:
		raw["Proof of Delivery"] = _desc([_keep(r, "Proof of Delivery") for r in site["Proof of Delivery"]
		                                  if r["docstatus"] in (0, 1) and r["pod_date"] >= floor],
		                                 "pod_date", "name")
	if "Sales Invoice" in need:
		rows = _desc([
			_keep(r, "Sales Invoice") for r in site["Sales Invoice"]
			if r["docstatus"] in (0, 1)
			and (r["posting_date"] >= floor or r["outstanding_amount"] != 0 or r["docstatus"] == 0)],
			"posting_date", "name")
		# command_center._read_invoices' second read: older submitted invoices
		# on the drafts' Job Orders.
		draft_jobs = {r["fps_job_order"] for r in rows if r["docstatus"] == 0 and r["fps_job_order"]}
		seen = {r["name"] for r in rows}
		rows += _desc([_keep(r, "Sales Invoice") for r in site["Sales Invoice"]
		               if r["docstatus"] == 1 and r["fps_job_order"] in draft_jobs
		               and r["posting_date"] < floor and r["name"] not in seen], "posting_date", "name")
		raw["Sales Invoice"] = rows
	if "Payment Entry" in need:
		raw["Payment Entry"] = _desc([_keep(r, "Payment Entry") for r in site["Payment Entry"]
		                              if r["docstatus"] == 1 and r["posting_date"] >= floor],
		                             "posting_date", "name")
	if need & {"Job Order", "FPS Job Update"}:
		updates = []
		if "FPS Job Update" in need:
			updates = _desc([r for r in site["FPS Job Update"]
			                 if r["update_date"] >= floor and r["source"] != "Backfill"],
			                "update_date", "creation")
		parents = {u["parent"] for u in updates}
		jobs = _desc([_keep(r, "Job Order") for r in site["Job Order"]
		              if r["docstatus"] < 2 and (r["jo_date"] >= floor
		                                         or (r["fps_stage"] or "") not in logic.CLOSED_JOB_STAGES
		                                         or r["name"] in parents)], "jo_date", "name")
		raw["Job Order"] = jobs
		if "FPS Job Update" in need:
			by_name = {j["name"]: j for j in jobs}
			kept = []
			for u in updates:
				job = by_name.get(u["parent"])
				if job:
					row = _keep(u, "FPS Job Update")
					row["job_customer"] = job["customer_name"] or job["customer"]
					row["job_stage"] = job["fps_stage"]
					kept.append(row)
			raw["FPS Job Update"] = kept
	return raw


# pipeline.TILES labels / notes / routes, counted over the synthetic site.
def simulate_stages(site, *, with_invoices):
	jobs = [j for j in site["Job Order"] if j["docstatus"] < 2]
	open_jobs = [j for j in jobs if (j["fps_stage"] or "") not in logic.CLOSED_JOB_STAGES]
	tiles = [
		("enquiry", "Enquiry", "open", sum(1 for r in site["FPS Enquiry"] if r["status"] == "Open"),
		 "/app/fps-enquiry?status=Open"),
		("quotation", "Quotation", "open",
		 sum(1 for r in site["Quotation"] if r["status"] == "Open" and r["docstatus"] < 2),
		 "/app/quotation?status=Open"),
		("job_order", "Job Order", "open", len(open_jobs),
		 "/app/job-order?fps_stage=%5B%22not%20in%22%2C%5B%22Closed%22%2C%22Completed%22%2C%22Invoiced%22%5D%5D"
		 "&docstatus=%5B%22%3C%22%2C2%5D"),
		("customs", "Customs Tracker", "not cleared",
		 sum(1 for r in site["Customs Tracker"] if r["status"] != "Cleared"),
		 "/app/customs-tracker?status=%5B%22not%20in%22%2C%5B%22Cleared%22%5D%5D"),
		("in_progress", "In Progress", "jobs", sum(1 for j in jobs if j["fps_stage"] == "In Progress"),
		 "/app/job-order?fps_stage=In%20Progress&docstatus=%5B%22%3C%22%2C2%5D"),
		("delivered", "Delivered", "awaiting invoice", sum(1 for j in jobs if j["fps_stage"] == "Delivered"),
		 "/app/job-order?fps_stage=Delivered&docstatus=%5B%22%3C%22%2C2%5D"),
	]
	if with_invoices:
		tiles.append(("invoices", "Invoices", "open",
		              sum(1 for r in site["Sales Invoice"] if r["docstatus"] == 1
		                  and r["status"] in ("Unpaid", "Overdue", "Partly Paid")),
		              "/app/sales-invoice?status=%5B%22in%22%2C%5B%22Unpaid%22%2C%22Overdue%22%2C%22Partly%20Paid%22%5D%5D"))
	past_eta = sum(1 for j in open_jobs if j["eta"] and j["eta"] < AS_OF)
	no_eta = sum(1 for j in open_jobs if not j["eta"])
	pods = sum(1 for p in site["Proof of Delivery"] if p["docstatus"] != 2)
	footnotes = ["%d past ETA" % past_eta]
	if no_eta:
		footnotes.append("%d with no ETA" % no_eta)
	footnotes.append("%d PODs on file" % pods)
	return {"tiles": [{"key": k, "label": l, "note": n, "count": c, "route": r}
	                  for k, l, n, c, r in tiles],
	        "footnotes": footnotes}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def build_all():
	site = make_site()
	files = {}
	for viewer_key, viewer in VIEWERS.items():
		finance = viewer["finance"]
		# The ops fixture models a viewer without Accounts roles AND without
		# Sales Invoice read (like hello@), so get_overview omits the invoices
		# tile too. ops@ itself can read Sales Invoice and would see that tile.
		stages = simulate_stages(site, with_invoices=finance)
		for period in logic.PERIODS:
			raw = simulate_reads(site, logic.fetch_floor(period, AS_OF), finance=finance)
			files["dashboard.%s.%s.json" % (viewer_key, period)] = logic.build_dashboard(
				period=period, as_of=AS_OF, generated_at=GENERATED_AT, viewer=viewer, raw=raw,
				stages=stages, creatable=CREATABLE[viewer_key])
	# Drawer fixtures, as a finance viewer (so the money keys exist).
	for key in logic.KPI_ORDER:
		spec = logic.METRICS[key]
		for period in logic.PERIODS:
			raw = simulate_reads(site, logic.fetch_floor(period, AS_OF), finance=True, keys=(key,))
			files["metric_detail.%s.%s.json" % (key, period)] = logic.build_metric_detail(
				key, raw, period=period, as_of=AS_OF, finance=True,
				can_create=bool(spec["new_doctype"]))
	raw = simulate_reads(site, logic.fetch_floor("30d", AS_OF), finance=True, keys=("jobs",))
	files["metric_detail.jobs.30d.dimension.json"] = logic.build_metric_detail(
		"jobs", raw, period="30d", as_of=AS_OF, finance=True, can_create=True,
		dimension="CC - Customs Clearance")
	return files


def write(files):
	OUT.mkdir(parents=True, exist_ok=True)
	for old in OUT.glob("*.json"):
		if old.name not in files:
			old.unlink()
	for name, payload in sorted(files.items()):
		text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
		(OUT / name).write_text(text, encoding="utf-8", newline="\n")
	print("wrote %d fixtures to %s" % (len(files), OUT))


def typecheck(files):
	"""Assign every fixture to its contract type in a throwaway .ts file and run
	tsc: excess or missing fields, wrong literals and wrong types all fail."""
	tsc = DASHBOARD / "node_modules" / "typescript" / "bin" / "tsc"
	if not tsc.exists():
		sys.exit("typescript is not installed in dashboard/node_modules (run npm install)")
	work = DASHBOARD / "node_modules" / ".tmp" / "fixture-typecheck"
	if work.exists():
		shutil.rmtree(work)
	work.mkdir(parents=True)
	lines = ['import type { DashboardPayload, MetricDetail } from "../../../src/types/dashboard";', ""]
	for i, (name, payload) in enumerate(sorted(files.items())):
		kind = "DashboardPayload" if name.startswith("dashboard.") else "MetricDetail"
		lines.append("// %s" % name)
		lines.append("export const f%d: %s = %s;" % (i, kind, json.dumps(payload, ensure_ascii=False)))
	(work / "check.ts").write_text("\n".join(lines) + "\n", encoding="utf-8")
	(work / "tsconfig.json").write_text(json.dumps({
		"compilerOptions": {"target": "ES2022", "module": "ESNext", "moduleResolution": "bundler",
		                    "strict": True, "noEmit": True, "skipLibCheck": True,
		                    "exactOptionalPropertyTypes": True},
		"files": ["check.ts"],
	}), encoding="utf-8")
	try:
		result = subprocess.run(["node", str(tsc), "-p", str(work / "tsconfig.json")],
		                        capture_output=True, text=True, cwd=str(DASHBOARD))
	finally:
		shutil.rmtree(work, ignore_errors=True)
	if result.returncode:
		print(result.stdout + result.stderr)
		sys.exit("fixtures do NOT match dashboard.ts")
	print("typecheck ok: %d fixtures match dashboard.ts (tsc --strict, exactOptionalPropertyTypes)"
	      % len(files))


def main():
	parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	parser.add_argument("--typecheck", action="store_true",
	                    help="also check every fixture against dashboard/src/types/dashboard.ts")
	args = parser.parse_args()
	files = build_all()
	write(files)
	if args.typecheck:
		typecheck(files)


if __name__ == "__main__":
	main()
