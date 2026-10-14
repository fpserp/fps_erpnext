"""FPS Command Center logic -- plain unittest, no frappe needed.

Run from the app root:

    python -m unittest fps_erpnext.tests.test_command_center_logic -v
    python fps_erpnext/tests/test_command_center_logic.py

Covers the period windows, bucketing (partial flags included), the "previous"
and delta null cases, number/date formatting, every insight rule at its
thresholds, money gating, ranking and capping, the drawer, and two drift checks:
the copies of pipeline.py constants, and the field names of the TypeScript
contract in dashboard/src/types/dashboard.ts.
"""

import ast
import json
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

if __package__ in (None, ""):
	sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fps_erpnext.api import command_center_logic as cc  # noqa: E402 -- pure module, no frappe

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AS_OF = date(2026, 10, 10)  # a Saturday; ISO week 41 starts Mon 5 Oct


def d(text):
	return date.fromisoformat(text)


def pts(*pairs):
	return [(d(a), v) for a, v in pairs]


def route_filters(route):
	"""{field: parsed value} of a list route, as list_view.js would see it:
	a JSON value is decoded, anything else is the plain string."""
	out = {}
	for field, values in parse_qs(urlsplit(route).query, keep_blank_values=True).items():
		value = values[0]
		out[field] = json.loads(value) if value.startswith("[") and value.endswith("]") else value
	return out


# --------------------------------------------------------------------------

class TestWindows(unittest.TestCase):
	def test_7d(self):
		cur, prev = cc.period_windows("7d", AS_OF)
		self.assertEqual((cur.start, cur.end), (d("2026-10-04"), AS_OF))
		self.assertEqual((prev.start, prev.end), (d("2026-09-27"), d("2026-10-03")))
		self.assertEqual(cur.days, 7)
		self.assertEqual(prev.days, 7)

	def test_30d(self):
		cur, prev = cc.period_windows("30d", "2026-10-10")
		self.assertEqual((cur.start, cur.end), (d("2026-09-11"), AS_OF))
		self.assertEqual((prev.start, prev.end), (d("2026-08-12"), d("2026-09-10")))

	def test_90d_is_13_whole_weeks(self):
		cur, prev = cc.period_windows("90d", AS_OF)
		self.assertEqual(cur.days, 91)
		self.assertEqual(prev.days, 91)
		self.assertEqual(cur.start, d("2026-07-12"))
		self.assertEqual(prev.end, d("2026-07-11"))

	def test_window_membership(self):
		cur, _ = cc.period_windows("7d", AS_OF)
		self.assertIn(d("2026-10-04"), cur)
		self.assertIn(AS_OF, cur)
		self.assertNotIn(d("2026-10-03"), cur)
		self.assertNotIn(None, cur)

	def test_bad_period(self):
		for bad in ("14d", "", None, "7D"):
			with self.assertRaises(ValueError):
				cc.check_period(bad)

	def test_trend_weeks(self):
		weeks = cc.trend_week_starts(AS_OF)
		self.assertEqual(len(weeks), 12)
		self.assertEqual(weeks[0], d("2026-07-20"))
		self.assertEqual(weeks[-1], d("2026-10-05"))
		self.assertTrue(all(w.weekday() == 0 for w in weeks))
		# A Sunday still belongs to the week that started the Monday before.
		self.assertEqual(cc.iso_week_start(d("2026-10-11")), d("2026-10-05"))

	def test_fetch_floor_covers_every_need(self):
		# 7d: the 120-day lag window is the earliest need.
		self.assertEqual(cc.fetch_floor("7d", AS_OF), d("2026-06-12"))
		# 90d: previous window start minus the history margin.
		self.assertEqual(cc.fetch_floor("90d", AS_OF), d("2026-04-12") - timedelta(days=28))
		for period in cc.PERIODS:
			floor = cc.fetch_floor(period, AS_OF)
			_cur, prev = cc.period_windows(period, AS_OF)
			self.assertLess(floor, prev.start)
			self.assertLessEqual(floor, cc.trend_week_starts(AS_OF)[0])


class TestBucketing(unittest.TestCase):
	def test_daily_7(self):
		points = pts(("2026-10-04", 1), ("2026-10-08", 1), ("2026-10-08", 1),
		             ("2026-10-03", 5), ("2026-10-11", 9))  # outside on both sides
		series = cc.bucket_series(points, "7d", AS_OF)
		self.assertEqual([p["date"] for p in series][:2], ["2026-10-04", "2026-10-05"])
		self.assertEqual([p["value"] for p in series], [1, 0, 0, 0, 2, 0, 0])
		self.assertEqual([p.get("partial", False) for p in series], [False] * 6 + [True])

	def test_daily_30_length(self):
		series = cc.bucket_series([], "30d", AS_OF)
		self.assertEqual(len(series), 30)
		self.assertEqual(series[0]["date"], "2026-09-11")
		self.assertTrue(series[-1]["partial"])
		self.assertEqual(sum(1 for p in series if p.get("partial")), 1)

	def test_rolling_weeks_for_90d(self):
		points = pts(("2026-07-12", 1), ("2026-07-18", 1),   # bucket 0
		             ("2026-07-19", 1),                      # bucket 1
		             ("2026-10-04", 1), ("2026-10-10", 1))   # bucket 12 (last)
		series = cc.bucket_series(points, "90d", AS_OF)
		self.assertEqual(len(series), 13)
		self.assertEqual(series[0]["date"], "2026-07-12")
		self.assertEqual(series[1]["date"], "2026-07-19")
		self.assertEqual(series[-1]["date"], "2026-10-04")
		self.assertEqual((series[0]["value"], series[1]["value"], series[-1]["value"]), (2, 1, 2))
		self.assertTrue(series[-1]["partial"])
		self.assertNotIn("partial", series[-2])

	def test_money_series_rounds_to_fils(self):
		series = cc.bucket_series(pts(("2026-10-05", 0.1), ("2026-10-05", 0.2)), "7d", AS_OF, "currency")
		self.assertEqual(series[1]["value"], 0.3)

	def test_weekly_totals(self):
		points = pts(("2026-07-20", 2), ("2026-07-26", 1),  # first ISO week (Mon-Sun)
		             ("2026-07-19", 7),                    # before the 12 weeks
		             ("2026-10-05", 1), ("2026-10-10", 1),
		             ("2026-10-11", 5))                    # after as_of: never counted
		weeks = cc.weekly_totals(points, AS_OF)
		self.assertEqual(len(weeks), 12)
		self.assertEqual(weeks[0][:2], (d("2026-07-20"), 3))
		self.assertEqual(weeks[-1][:2], (d("2026-10-05"), 2))
		self.assertEqual([w[2] for w in weeks], [False] * 11 + [True])

	def test_week_is_partial_through_its_sunday(self):
		weeks = cc.weekly_totals([], d("2026-10-11"))
		self.assertTrue(weeks[-1][2])
		self.assertEqual(weeks[-1][0], d("2026-10-05"))


class TestTotalsAndDelta(unittest.TestCase):
	def test_previous_needs_history_before_the_window(self):
		_cur, prev = cc.period_windows("7d", AS_OF)
		points = pts(("2026-09-28", 2), ("2026-10-05", 1))
		self.assertIsNone(cc.previous_total(points, prev, None))
		self.assertIsNone(cc.previous_total(points, prev, prev.start))        # starts ON it
		self.assertIsNone(cc.previous_total(points, prev, d("2026-09-28")))   # starts inside it
		self.assertEqual(cc.previous_total(points, prev, d("2026-09-26")), 2)
		self.assertEqual(cc.previous_total([], prev, d("2026-07-20")), 0)     # a real zero

	def test_delta(self):
		self.assertEqual(cc.delta_pct(15, 14), 7.1)
		self.assertEqual(cc.delta_pct(0, 3), -100.0)
		self.assertEqual(cc.delta_pct(3, 3), 0.0)
		self.assertEqual(cc.delta_pct(1, 8), -87.5)
		self.assertEqual(cc.delta_pct(1, 3), -66.7)
		self.assertEqual(cc.delta_pct(-700, 1000), -170.0)  # a negative value is fine

	def test_delta_null_cases(self):
		self.assertIsNone(cc.delta_pct(12, 0))   # never against a zero base
		self.assertIsNone(cc.delta_pct(0, 0))
		self.assertIsNone(cc.delta_pct(5, None))
		# Spec: only against previous > 0. Net credit notes make a negative
		# base, and a % of a negative is no signal.
		self.assertIsNone(cc.delta_pct(-50, -100))
		self.assertIsNone(cc.delta_pct(100, -0.01))

	def test_summarize(self):
		points = [{"date": d("2026-09-01"), "value": 1},   # evidence of history
		          {"date": d("2026-09-30"), "value": 1},
		          {"date": d("2026-10-08"), "value": 1},
		          {"date": d("2026-10-08"), "value": 1}]
		s = cc.summarize(points, "7d", AS_OF)
		self.assertEqual((s["value"], s["previous"], s["delta_pct"]), (2, 1, 100.0))
		self.assertEqual(s["granularity"], "day")
		self.assertEqual(len(s["series"]), 7)
		s = cc.summarize(points[1:], "7d", AS_OF)  # history starts inside previous
		self.assertIsNone(s["previous"])
		self.assertIsNone(s["delta_pct"])
		self.assertEqual(cc.summarize(points, "90d", AS_OF)["granularity"], "week")

	def test_summarize_money(self):
		points = [{"date": d("2026-01-01"), "value": 1.0},
		          {"date": d("2026-10-05"), "value": 1000.105}]
		s = cc.summarize(points, "7d", AS_OF, "currency")
		self.assertEqual(s["value"], 1000.11)
		self.assertEqual(s["previous"], 0.0)
		self.assertIsNone(s["delta_pct"])

	def test_source_first_seen_is_clamped_to_the_live_from_date(self):
		# FPS Job Update: back-dated rows reach to June, the logger started 11 Sep.
		points = [{"date": d("2026-06-10"), "value": 1}, {"date": d("2026-10-08"), "value": 1}]
		self.assertEqual(cc.SOURCE_LIVE_FROM["job_activity"], d("2026-09-11"))
		self.assertEqual(cc.source_first_seen("job_activity", points), d("2026-09-11"))
		# A source that started after its live-from date keeps its real first row.
		self.assertEqual(cc.source_first_seen("job_activity", points[1:]), d("2026-10-08"))
		self.assertIsNone(cc.source_first_seen("job_activity", []))
		# Other sources have no live-from date and are untouched.
		self.assertEqual(cc.source_first_seen("jobs", points), d("2026-06-10"))
		# So the 30d previous window (12 Aug - 10 Sep) is not comparable, while
		# the 7d one (27 Sep - 3 Oct) is.
		s30 = cc.summarize(points, "30d", AS_OF, first_seen=cc.source_first_seen("job_activity", points))
		self.assertIsNone(s30["previous"])
		self.assertIsNone(s30["delta_pct"])
		s7 = cc.summarize(points, "7d", AS_OF, first_seen=cc.source_first_seen("job_activity", points))
		self.assertEqual(s7["previous"], 0)

	def test_median_and_rounding(self):
		self.assertEqual(cc.median([0, 29, 56]), 29)
		self.assertEqual(cc.median([1, 2]), 1.5)
		self.assertIsNone(cc.median([]))
		self.assertEqual(cc.round_half_up(2.25, 1), 2.3)   # float round() gives 2.2
		self.assertEqual(cc.round_half_up(0.5), 1.0)
		self.assertEqual(cc.money(0.1 + 0.2), 0.3)


class TestFormatting(unittest.TestCase):
	def test_count(self):
		self.assertEqual(cc.format_count(1284), "1,284")
		self.assertEqual(cc.format_count(0), "0")
		self.assertEqual(cc.format_count(None), "0")

	def test_compact_rule(self):
		cases = {
			0: "0", 7: "7", 949.5: "950", 999.4: "999",
			999.6: "1K",            # rounds up into the next unit
			1000: "1K", 1050: "1.1K", 12874.5: "12.9K", 12000: "12K",
			756615.87: "756.6K", 736871.83: "736.9K",
			999949: "999.9K", 999960: "1M",  # 999.96K rounds to 1000.0K -> 1M
			# M and B to 1 dp, like dashboard/src/lib/format.ts (DESIGN.md §5).
			1474740.78: "1.5M", 2_000_000: "2M", 1_500_000: "1.5M", 1_250_000: "1.3M",
			16130800: "16.1M", 999_960_000: "1B", 2.5e9: "2.5B",
		}
		for n, text in cases.items():
			self.assertEqual(cc.format_compact(n), text, n)

	def test_money_compact(self):
		self.assertEqual(cc.format_money_compact(12874.5), "AED 12.9K")
		self.assertEqual(cc.format_money_compact(1474740.78), "AED 1.5M")
		self.assertEqual(cc.format_money_compact(756615.87), "AED 756.6K")
		self.assertEqual(cc.format_money_compact(0), "AED 0")
		self.assertEqual(cc.format_money_compact(-700), "−AED 700")
		self.assertEqual(cc.format_money_compact(-0.001), "AED 0")  # no "−0"
		self.assertEqual(cc.format_money_compact(5000, "USD"), "USD 5K")

	def test_money_full(self):
		self.assertEqual(cc.format_money(12874.5), "AED 12,874.50")
		self.assertEqual(cc.format_money(-700), "−AED 700.00")
		self.assertEqual(cc.format_money(None), "AED 0.00")

	def test_short_date(self):
		self.assertEqual(cc.short_date("2026-08-08"), "8 Aug")
		self.assertEqual(cc.short_date(date(2026, 10, 5)), "5 Oct")
		self.assertEqual(cc.short_date(datetime(2026, 12, 31, 23, 0)), "31 Dec")

	def test_clip(self):
		self.assertEqual(cc.clip("short", 90), "short")
		long = "word " * 40
		out = cc.clip(long, 90)
		self.assertLessEqual(len(out), 90)
		self.assertTrue(out.endswith("…"))
		self.assertEqual(cc.clip("  spaced   out  ", 90), "spaced out")

	def test_plural_and_sentence(self):
		self.assertEqual(cc.plural(1, "job", "jobs"), "job")
		self.assertEqual(cc.plural(0, "job", "jobs"), "jobs")
		self.assertEqual(cc.sentence("2 drafts worth AED 1.47M"), "2 drafts worth AED 1.47M")
		self.assertEqual(cc.sentence("drafts worth AED 1K"), "Drafts worth AED 1K")


class TestRoutes(unittest.TestCase):
	def test_form_route_encodes_slashes(self):
		self.assertEqual(cc.form_route("Job Order", "FPS/JO/2610/094"),
		                 "/app/job-order/FPS%2FJO%2F2610%2F094")
		self.assertEqual(cc.form_route("Proof of Delivery", "FPS/POD/2610/050"),
		                 "/app/proof-of-delivery/FPS%2FPOD%2F2610%2F050")
		# encodeURIComponent leaves these alone.
		self.assertEqual(cc.form_route("Payment Entry", "ACC-PAY-2026-00494"),
		                 "/app/payment-entry/ACC-PAY-2026-00494")

	def test_list_route(self):
		self.assertEqual(cc.list_route("FPS Enquiry"), "/app/fps-enquiry")
		self.assertEqual(cc.list_route("Proof of Delivery", {"delivery_status": "Delivered"}),
		                 "/app/proof-of-delivery?delivery_status=Delivered")
		route = cc.list_route("Job Order", {"fps_stage": ["not in", ["Closed", "Invoiced"]]})
		self.assertEqual(route, "/app/job-order?fps_stage=%5B%22not%20in%22%2C%5B%22Closed%22%2C%22Invoiced%22%5D%5D")

	def test_every_metric_route_is_a_desk_route(self):
		for key, spec in cc.METRICS.items():
			self.assertTrue(spec["route"].startswith("/app/"), key)


class TestPoints(unittest.TestCase):
	def test_enquiries_drop_cancelled_and_undated(self):
		rows = [{"name": "E1", "enquiry_date": "2026-10-08", "status": "Open",
		         "enquiry_source": "WhatsApp", "client_name": "Customer A", "movement_type": "SEA"},
		        {"name": "E2", "enquiry_date": "2026-10-08", "status": "Cancelled"},
		        {"name": "E3", "enquiry_date": None, "status": "Open"}]
		points = cc.points_enquiries(rows)
		self.assertEqual([p["name"] for p in points], ["E1"])
		self.assertEqual(points[0]["subtitle"], "WhatsApp · SEA")
		self.assertEqual(points[0]["dim"], "WhatsApp")

	def test_quotations_drop_cancelled(self):
		rows = [{"name": "Q1", "transaction_date": "2026-10-08", "docstatus": 0, "status": "Draft",
		         "base_grand_total": 100},
		        {"name": "Q2", "transaction_date": "2026-10-08", "docstatus": 2, "status": "Cancelled"}]
		self.assertEqual([p["name"] for p in cc.points_quotations(rows)], ["Q1"])

	def test_jobs_short_service_line(self):
		rows = [{"name": "J1", "jo_date": "2026-10-08", "docstatus": 0,
		         "fps_category": "CC - Customs Clearance", "client_reference_no": "PO 1"},
		        {"name": "J2", "jo_date": "2026-10-08", "docstatus": 1, "fps_category": None},
		        {"name": "J3", "jo_date": "2026-10-08", "docstatus": 2}]
		points = cc.points_jobs(rows)
		self.assertEqual([p["name"] for p in points], ["J1", "J2"])
		self.assertEqual(points[0]["dim_label"], "Customs clearance")
		self.assertEqual(points[0]["subtitle"], "Customs clearance · PO 1")
		self.assertEqual((points[1]["dim"], points[1]["dim_label"]), (cc.NOT_SET_KEY, cc.NOT_SET_LABEL))

	def test_customs_counts_on_clearance_date_only(self):
		rows = [{"name": "C1", "clearance_date": "2026-10-05", "boe_number": "101-1"},
		        {"name": "C2", "clearance_date": None, "status": "Pending"}]
		points = cc.points_customs_cleared(rows)
		self.assertEqual([p["name"] for p in points], ["C1"])
		self.assertIn("BOE 101-1", points[0]["subtitle"])

	def test_deliveries_count_delivered_drafts_too(self):
		rows = [{"name": "P1", "pod_date": "2026-10-01", "docstatus": 0, "delivery_status": "Delivered"},
		        {"name": "P2", "pod_date": "2026-10-01", "docstatus": 1, "delivery_status": "Pending"},
		        {"name": "P3", "pod_date": "2026-10-01", "docstatus": 2, "delivery_status": "Delivered"}]
		self.assertEqual([p["name"] for p in cc.points_deliveries(rows)], ["P1"])

	def test_job_updates_skip_backfill_and_name_the_job(self):
		rows = [{"name": "u1", "parent": "FPS/JO/1", "update_date": "2026-10-08", "source": "Manual",
		         "milestone": "BOE", "job_customer": "Customer A", "creation": "2026-10-08 10:00:00"},
		        {"name": "u2", "parent": "FPS/JO/1", "update_date": "2026-07-20", "source": "Backfill"},
		        {"name": "u3", "parent": "FPS/JO/2", "update_date": "2026-10-08", "source": None,
		         "milestone": ""},
		        {"name": "u4", "parent": "FPS/JO/2", "update_date": "2026-10-09", "source": "System",
		         "milestone": "PICKED_UP", "status_line": "Truck loaded"}]
		points = cc.points_job_updates(rows)
		self.assertEqual([p["name"] for p in points], ["FPS/JO/1", "FPS/JO/2", "FPS/JO/2"])
		self.assertEqual(points[0]["title"], "Customer A")
		self.assertEqual(points[1]["dim_label"], "No milestone")
		self.assertEqual((points[2]["dim"], points[2]["dim_label"]), ("PICKED_UP", "Picked up"))
		self.assertEqual(points[2]["subtitle"], "Picked up · Truck loaded")

	def test_invoiced_is_submitted_net_without_payment_requests(self):
		rows = [{"name": "I1", "posting_date": "2026-09-23", "docstatus": 1, "base_net_total": 12051.11,
		         "fps_is_payment_request": 0, "status": "Paid"},
		        {"name": "I2", "posting_date": "2026-09-30", "docstatus": 0, "base_net_total": 999},
		        {"name": "I3", "posting_date": "2026-06-13", "docstatus": 1, "base_net_total": 88000,
		         "fps_is_payment_request": 1},
		        {"name": "I4", "posting_date": "2026-09-24", "docstatus": 1, "base_net_total": -700,
		         "is_return": 1}]
		points = cc.points_invoiced(rows)
		self.assertEqual([(p["name"], p["value"]) for p in points], [("I1", 12051.11), ("I4", -700.0)])

	def test_collected(self):
		rows = [{"name": "R1", "posting_date": "2026-09-28", "base_received_amount": "12051.11",
		         "payment_type": "Receive", "mode_of_payment": "Bank Transfer", "reference_no": "X1"},
		        {"name": "R2", "posting_date": "2026-09-28", "base_received_amount": 5,
		         "payment_type": "Pay"}]
		points = cc.points_collected(rows)
		self.assertEqual([(p["name"], p["value"]) for p in points], [("R1", 12051.11)])
		self.assertEqual(points[0]["subtitle"], "Bank Transfer · Ref X1")


class TestFacts(unittest.TestCase):
	def test_receipt_lag(self):
		rows = [{"posting_date": "2026-09-01", "creation": "2026-09-30 10:00:00"},   # 29
		        {"posting_date": "2026-09-28", "creation": datetime(2026, 10, 5, 17)},  # 7
		        {"posting_date": "2026-08-01", "creation": "2026-09-26 08:00:00"},   # 56
		        {"posting_date": "2026-05-01", "creation": "2026-09-30 08:00:00"},   # outside 120 d
		        {"posting_date": "2026-09-20", "creation": "2026-09-19 08:00:00"},   # clamps to 0
		        {"posting_date": "2026-09-01", "creation": "2026-10-11 08:00:00"}]   # 40
		self.assertEqual(cc.receipt_lag_days(rows, AS_OF), 29)
		self.assertIsNone(cc.receipt_lag_days([], AS_OF))

	def test_receipt_lag_needs_three_receipts(self):
		# Spec: omit the caveat if fewer than 3 receipts in the 120-day window.
		two = [{"posting_date": "2026-09-01", "creation": "2026-09-30"},
		       {"posting_date": "2026-08-01", "creation": "2026-09-26"},
		       {"posting_date": "2026-05-01", "creation": "2026-09-30"}]   # outside: not counted
		self.assertIsNone(cc.receipt_lag_days(two, AS_OF))
		self.assertIsNone(cc.caveat_for("collected", {"Payment Entry": two}, AS_OF))
		three = two + [{"posting_date": "2026-09-10", "creation": "2026-10-01"}]
		self.assertEqual(cc.receipt_lag_days(three, AS_OF), 29)

	def test_caveats(self):
		lagged = [{"posting_date": "2026-09-01", "creation": "2026-09-30"},
		          {"posting_date": "2026-09-02", "creation": "2026-10-01"},
		          {"posting_date": "2026-09-03", "creation": "2026-10-02"}]
		raw = {"Payment Entry": lagged,
		       "Sales Invoice": [{"docstatus": 0, "base_grand_total": 1000000},
		                         {"docstatus": 1, "base_grand_total": 5}]}
		self.assertEqual(cc.caveat_for("collected", raw, AS_OF),
		                 "Receipts are booked a median of 29 days after the payment date, "
		                 "so recent weeks fill in later.")
		# Spec: no invoiced caveat -- the card's "Drafts waiting" line and the
		# invoicing insights carry the drafts.
		self.assertIsNone(cc.caveat_for("invoiced", raw, AS_OF))
		short_lag = {"Payment Entry": [dict(r, creation=r["posting_date"]) for r in lagged]}
		self.assertIsNone(cc.caveat_for("collected", short_lag, AS_OF))  # 0 < 7 days
		self.assertIsNone(cc.caveat_for("jobs", raw, AS_OF))

	def test_last_submitted_invoice(self):
		rows = [{"docstatus": 1, "posting_date": "2026-09-23"},
		        {"docstatus": 1, "posting_date": "2026-09-28", "is_return": 1},   # credit note: not billing
		        {"docstatus": 0, "posting_date": "2026-09-30"},                   # draft
		        {"docstatus": 1, "posting_date": "2026-12-01"},                   # after as_of
		        {"docstatus": 1, "posting_date": "2026-06-13", "fps_is_payment_request": 1}]
		self.assertEqual(cc.last_submitted_invoice(rows, AS_OF), d("2026-09-23"))
		self.assertIsNone(cc.last_submitted_invoice(rows[1:4], AS_OF))
		self.assertIsNone(cc.last_submitted_invoice(None, AS_OF))

	def test_duplicate_drafts_match_job_and_grand_total(self):
		rows = [
			{"name": "INV-PAID-1", "docstatus": 1, "fps_job_order": "JO-1", "base_grand_total": 471943.63,
			 "posting_date": "2026-08-11"},
			{"name": "INV-PAID-2", "docstatus": 1, "fps_job_order": "JO-2", "base_grand_total": 159420.92,
			 "posting_date": "2026-08-11"},
			{"name": "INV-D1", "docstatus": 0, "fps_job_order": "JO-1", "base_grand_total": 471943.630001,
			 "posting_date": "2026-09-25"},                         # same to the fils
			{"name": "INV-D2", "docstatus": 0, "fps_job_order": "JO-2", "base_grand_total": "159420.92",
			 "posting_date": "2026-09-25"},
			{"name": "INV-D3", "docstatus": 0, "fps_job_order": "JO-1", "base_grand_total": 471943.64,
			 "posting_date": "2026-09-26"},                         # 1 fils off: not a repeat
			{"name": "INV-D4", "docstatus": 0, "fps_job_order": "JO-3", "base_grand_total": 159420.92,
			 "posting_date": "2026-09-27"},                         # same amount, other job
			{"name": "INV-D5", "docstatus": 0, "fps_job_order": None, "base_grand_total": 5,
			 "posting_date": "2026-09-27"},
			{"name": "INV-U1", "docstatus": 1, "fps_job_order": None, "base_grand_total": 5,
			 "posting_date": "2026-09-01"},                         # unlinked pairs prove nothing
			{"name": "INV-X", "docstatus": 2, "fps_job_order": "JO-4", "base_grand_total": 10,
			 "posting_date": "2026-09-01"},
			{"name": "INV-D6", "docstatus": 0, "fps_job_order": "JO-4", "base_grand_total": 10,
			 "posting_date": "2026-09-28"},                         # matches a CANCELLED one only
		]
		self.assertEqual([r["name"] for r in cc.duplicate_drafts(rows)], ["INV-D2", "INV-D1"])
		self.assertEqual(cc.duplicate_drafts([]), [])

	def test_quotation_drafts_window(self):
		rows = [{"docstatus": 0, "transaction_date": "2026-09-11"},   # as_of - 29: in
		        {"docstatus": 0, "transaction_date": "2026-09-10"},   # as_of - 30: out
		        {"docstatus": 1, "transaction_date": "2026-10-01"},   # submitted
		        {"docstatus": 0, "transaction_date": "2026-10-11"},   # future
		        {"docstatus": 0, "transaction_date": None}]
		self.assertEqual(len(cc.quotation_drafts(rows, AS_OF)), 1)
		# The window's first day, shared with the insight's route.
		self.assertEqual(cc.quote_draft_since(AS_OF), d("2026-09-11"))
		self.assertEqual(cc.quote_draft_since("2026-10-10"), d("2026-09-11"))

	def test_open_jobs_match_pipeline_rule(self):
		rows = [{"name": "a", "docstatus": 0, "fps_stage": "New"},
		        {"name": "b", "docstatus": 1, "fps_stage": "Delivered"},
		        {"name": "c", "docstatus": 1, "fps_stage": "Invoiced"},
		        {"name": "d", "docstatus": 2, "fps_stage": "In Progress"},
		        {"name": "e", "docstatus": 0, "fps_stage": None}]
		self.assertEqual([r["name"] for r in cc.open_jobs(rows)], ["a", "b", "e"])


# --------------------------------------------------------------------------
# Insights
# --------------------------------------------------------------------------

def tracker(name, **kw):
	return dict({"name": name}, **kw)


class TestInsightRules(unittest.TestCase):
	# ---- R1: customs deadlines ------------------------------------------

	def test_docs_overdue_is_critical(self):
		trackers = [
			tracker("CT1", fps_doc_submission="Pending", fps_doc_deadline="2026-08-08"),
			tracker("CT2", fps_doc_submission="Pending", fps_doc_deadline="2026-09-30"),
			tracker("CT3", fps_doc_submission="", fps_doc_deadline="2026-09-01"),        # blank: not counted
			tracker("CT8", fps_doc_submission="pending ", fps_doc_deadline="2026-09-01"),  # case/space tolerant
			tracker("CT4", fps_doc_submission="Completed", fps_doc_deadline="2026-08-01"),
			tracker("CT5", fps_doc_submission="Not Applicable", fps_doc_deadline="2026-08-01"),
			tracker("CT6", fps_doc_submission="Pending", fps_doc_deadline="2026-10-10"),  # fine start day: overdue
			tracker("CT7", fps_doc_submission="Pending", fps_doc_deadline=None),
			tracker("CT9", fps_doc_submission="Pending", fps_doc_deadline="2026-10-24"),  # +14: upcoming
			tracker("CT10", fps_doc_submission="Pending", fps_doc_deadline="2026-10-25"), # +15: neither
		]
		i = cc.rule_customs_deadline(trackers, AS_OF, "fps_doc_submission")
		self.assertEqual((i["id"], i["severity"]), ("customs_docs", "critical"))
		self.assertEqual(i["title"], "4 document submissions are past the Dubai Customs deadline")
		self.assertNotIn("CT3", json.dumps(i))
		self.assertTrue(i["detail"].startswith(
			"Oldest deadline 8 Aug (CT1); 1 more falls due in the next 14 days."), i["detail"])
		self.assertIn("fps_doc_deadline=%5B%22%3C%3D%22%2C%222026-10-10%22%5D", i["route"])
		self.assertIn("fps_doc_submission=%5B%22in%22%2C%5B%22Pending%22%5D%5D", i["route"])
		one = cc.rule_customs_deadline(trackers[:1], AS_OF, "fps_doc_submission")
		self.assertEqual(one["title"], "1 document submission is past the Dubai Customs deadline")
		self.assertIn("none other falls due in the next 14 days", one["detail"])

	def test_docs_deadline_day_is_late_mofa_deadline_day_is_not(self):
		# fps_doc_deadline is Dubai Customs' Fine Start Date: fines run from that
		# day, included (customs_clock.py), so on it the originals are already
		# late. A MOFA deadline is the last day to attest, so today is not missed.
		due_today = [tracker("CT6", fps_doc_submission="Pending", fps_doc_deadline="2026-10-10",
		                     fps_mofa_status="Pending", fps_mofa_deadline="2026-10-10")]
		docs = cc.rule_customs_deadline(due_today, AS_OF, "fps_doc_submission")
		self.assertEqual((docs["severity"], docs["title"]),
		                 ("critical", "1 document submission is past the Dubai Customs deadline"))
		self.assertTrue(docs["detail"].startswith("Oldest deadline 10 Oct (CT6); none other falls due"))
		# The route cuts where the count does: <= today for documents.
		self.assertEqual(route_filters(docs["route"])["fps_doc_deadline"], ["<=", "2026-10-10"])
		mofa = cc.rule_customs_deadline(due_today, AS_OF, "fps_mofa_status")
		self.assertEqual((mofa["severity"], mofa["title"]),
		                 ("warning", "1 MOFA attestation falls due in the next 14 days"))
		self.assertTrue(mofa["detail"].startswith("Next: CT6, due 10 Oct."))
		# ... and an overdue MOFA route still stops before today.
		late = cc.rule_customs_deadline(
			[tracker("CT1", fps_mofa_status="Pending", fps_mofa_deadline="2026-10-09")], AS_OF, "fps_mofa_status")
		self.assertEqual(late["severity"], "critical")
		self.assertEqual(route_filters(late["route"])["fps_mofa_deadline"], ["<", "2026-10-10"])
		# The "Docs overdue" context line counts the same way.
		self.assertEqual(len(cc._overdue(due_today, "fps_doc_submission", AS_OF)), 1)
		self.assertEqual(len(cc._overdue(due_today, "fps_mofa_status", AS_OF)), 0)
		# Yesterday it was still "upcoming" for both clocks.
		self.assertEqual(cc.rule_customs_deadline(due_today, d("2026-10-09"), "fps_doc_submission")["severity"],
		                 "warning")

	def test_docs_upcoming_only_is_a_warning(self):
		trackers = [tracker("CT6", fps_doc_submission="Pending", fps_doc_deadline="2026-10-19"),
		            tracker("CT7", fps_doc_submission="Pending", fps_doc_deadline="2026-11-07"),  # +28
		            tracker("CT4", fps_doc_submission="Completed", fps_doc_deadline="2026-08-01")]
		i = cc.rule_customs_deadline(trackers, AS_OF, "fps_doc_submission")
		self.assertEqual((i["id"], i["severity"]), ("customs_docs", "warning"))
		self.assertEqual(i["title"], "1 document submission falls due in the next 14 days")
		self.assertTrue(i["detail"].startswith("Next: CT6, due 19 Oct."))
		self.assertIn("fps_doc_deadline=%5B%22%3C%3D%22%2C%222026-10-24%22%5D", i["route"])
		self.assertIsNone(cc.rule_customs_deadline(trackers[1:], AS_OF, "fps_doc_submission"))
		self.assertIsNone(cc.rule_customs_deadline([], AS_OF, "fps_doc_submission"))

	def test_mofa_is_a_separate_insight(self):
		trackers = [
			tracker("CT1", fps_mofa_status="Pending", fps_mofa_deadline="2026-08-03"),
			tracker("CT2", fps_mofa_status="Under Client", fps_mofa_deadline="2026-09-24"),
			tracker("CT3", fps_mofa_status="N/A", fps_mofa_deadline="2026-08-01"),
			tracker("CT5", fps_mofa_status="", fps_mofa_deadline="2026-07-28"),   # blank: not counted
			tracker("CT6", fps_mofa_status="Under Process", fps_mofa_deadline="2026-10-01"),
			tracker("CT4", fps_mofa_status="Pending", fps_mofa_deadline="2026-10-14"),
			# A document clock on the same tracker does not leak into MOFA.
			tracker("CT9", fps_doc_submission="Pending", fps_doc_deadline="2026-08-01"),
		]
		i = cc.rule_customs_deadline(trackers, AS_OF, "fps_mofa_status")
		self.assertEqual((i["id"], i["severity"]), ("customs_mofa", "critical"))
		self.assertEqual(i["title"], "3 MOFA attestations are past the deadline")
		self.assertIn("Oldest deadline 3 Aug (CT1); 1 more falls due in the next 14 days.", i["detail"])
		upcoming = cc.rule_customs_deadline(trackers[5:6], AS_OF, "fps_mofa_status")
		self.assertEqual((upcoming["severity"], upcoming["title"]),
		                 ("warning", "1 MOFA attestation falls due in the next 14 days"))

	def test_live_customs_shape(self):
		# 2026-10-10: 5 document submissions + 3 MOFA overdue (Pending only).
		docs = ["2026-08-08", "2026-08-08", "2026-08-19", "2026-08-21", "2026-09-30"]
		mofa = ["2026-08-03", "2026-08-04", "2026-09-24"]
		trackers = ([tracker("D%d" % i, fps_doc_submission="Pending", fps_doc_deadline=x) for i, x in enumerate(docs)]
		            + [tracker("D9", fps_doc_submission="Pending", fps_doc_deadline="2026-10-19"),
		               tracker("D10", fps_doc_submission="Pending", fps_doc_deadline="2026-11-07")]
		            + [tracker("M%d" % i, fps_mofa_status="Pending", fps_mofa_deadline=x) for i, x in enumerate(mofa)]
		            + [tracker("M%d" % (i + 5), fps_mofa_status="Pending", fps_mofa_deadline=x)
		               for i, x in enumerate(["2026-10-14", "2026-10-19", "2026-10-22"])])
		doc = cc.rule_customs_deadline(trackers, AS_OF, "fps_doc_submission")
		self.assertTrue(doc["title"].startswith("5 document submissions are past"))
		self.assertIn("1 more falls due", doc["detail"])
		mo = cc.rule_customs_deadline(trackers, AS_OF, "fps_mofa_status")
		self.assertTrue(mo["title"].startswith("3 MOFA attestations are past"))
		self.assertIn("3 more fall due", mo["detail"])

	# ---- R2: invoicing stall (finance) ----------------------------------

	def test_invoicing_stall(self):
		self.assertIsNone(cc.rule_invoicing_stall(d("2026-10-01"), AS_OF, 3, 100, 120))  # 9 days
		i = cc.rule_invoicing_stall(d("2026-09-30"), AS_OF, 1, 500, 120)                   # 10 days
		self.assertEqual((i["id"], i["severity"], i["metric_key"]), ("invoicing_stall", "warning", "invoiced"))
		self.assertEqual(i["title"], "No invoice submitted for 10 days")
		self.assertEqual(i["detail"], "The last one was posted 30 Sep. 1 draft invoice worth AED 500 is waiting.")
		live = cc.rule_invoicing_stall(d("2026-09-23"), AS_OF, 26, 1474740.78, 120)
		self.assertEqual(live["title"], "No invoice submitted for 17 days")
		self.assertEqual(live["detail"], "The last one was posted 23 Sep. 26 draft invoices worth "
		                                 "AED 1.5M are waiting.")
		none = cc.rule_invoicing_stall(None, AS_OF, 2, 1000, 120)
		self.assertEqual(none["title"], "No invoice submitted in the last 120 days")
		# A future-dated invoice is not recent billing.
		self.assertIsNotNone(cc.rule_invoicing_stall(d("2026-12-01"), AS_OF, 1, 1, 120))

	def test_invoicing_stall_needs_drafts(self):
		# A quiet month with nothing drafted is not a stall.
		self.assertIsNone(cc.rule_invoicing_stall(d("2026-09-23"), AS_OF, 0, 0, 120))

	# ---- R3: duplicate drafts (finance) ---------------------------------

	def live_duplicates(self):
		return [
			{"name": "FPS/INV/2608/101", "docstatus": 1, "status": "Paid", "fps_job_order": "FPS/JO/2607/040",
			 "base_grand_total": 471943.63, "posting_date": "2026-08-11"},
			{"name": "FPS/INV/2608/102", "docstatus": 1, "status": "Paid", "fps_job_order": "FPS/JO/2607/041",
			 "base_grand_total": 159420.92, "posting_date": "2026-08-11"},
			{"name": "FPS/INV/2609/131", "docstatus": 0, "status": "Draft", "fps_job_order": "FPS/JO/2607/040",
			 "base_grand_total": 471943.63, "posting_date": "2026-09-25"},
			{"name": "FPS/INV/2609/132", "docstatus": 0, "status": "Draft", "fps_job_order": "FPS/JO/2607/041",
			 "base_grand_total": 159420.92, "posting_date": "2026-09-25"},
			{"name": "FPS/INV/2609/140", "docstatus": 0, "status": "Draft", "fps_job_order": "FPS/JO/2609/001",
			 "base_grand_total": 1050, "posting_date": "2026-09-30"},
		]

	def test_duplicate_drafts(self):
		i = cc.rule_duplicate_drafts(self.live_duplicates())
		self.assertEqual((i["id"], i["severity"]), ("duplicate_drafts", "warning"))
		self.assertEqual(i["title"], "2 draft invoices repeat an already submitted invoice")
		self.assertEqual(i["detail"], "FPS/INV/2609/131 and FPS/INV/2609/132 have the Job Order and "
		                              "grand total of a submitted invoice (AED 631.4K in all); "
		                              "check before submitting.")
		self.assertEqual(i["route"], "/app/sales-invoice?docstatus=0")
		self.assertNotIn("metric_key", i)
		one = cc.rule_duplicate_drafts(self.live_duplicates()[:3])
		self.assertEqual(one["title"], "1 draft invoice repeats an already submitted invoice")
		self.assertTrue(one["detail"].startswith("FPS/INV/2609/131 has the Job Order"))
		self.assertIsNone(cc.rule_duplicate_drafts(self.live_duplicates()[2:]))  # nothing submitted

	def test_duplicate_drafts_names_at_most_two(self):
		rows = [{"name": "S", "docstatus": 1, "fps_job_order": "J", "base_grand_total": 10}]
		rows += [{"name": "D%d" % n, "docstatus": 0, "fps_job_order": "J", "base_grand_total": 10,
		          "posting_date": "2026-09-2%d" % n} for n in range(4)]
		i = cc.rule_duplicate_drafts(rows)
		self.assertEqual(i["title"], "4 draft invoices repeat an already submitted invoice")
		self.assertTrue(i["detail"].startswith("D0 and D1 (and 2 more) have"), i["detail"])
		self.assertNotIn("D2", i["detail"].split("(and")[0])

	# ---- R4: swings -------------------------------------------------------

	def kpi(self, key, value, previous, **kw):
		base = {"key": key, "label": key.title(), "unit": "count", "good_direction": "up",
		        "value": value, "previous": previous, "delta_pct": cc.delta_pct(value, previous)}
		base.update(kw)
		return base

	def test_swings(self):
		kpis = [
			self.kpi("deliveries", 0, 3),        # -100%, base 3: warning
			self.kpi("jobs", 6, 3),              # +100%: positive
			self.kpi("customs", 1, 2),            # base 2 < 3: skipped
			self.kpi("quotes", 4, 3),             # +33%: skipped
			self.kpi("enquiries", 12, 0),         # new: info
			self.kpi("small", 4, 0),              # new but < 5: skipped
			self.kpi("job_activity", 30, 3, good_direction="none"),
			self.kpi("invoiced", 0, 9000, unit="currency"),
			self.kpi("collected", 0, 9000, caveat="lag"),
			self.kpi("nohistory", 9, None),       # not comparable: never "after a quiet period"
			self.kpi("backlog", 9, 3, good_direction="down"),  # up is bad: warning
		]
		out = {i["id"]: i for i in cc.rule_volume_swings(kpis, "vs previous 7 days")}
		self.assertEqual(sorted(out), ["swing:backlog", "swing:deliveries", "swing:enquiries", "swing:jobs"])
		self.assertEqual(out["swing:deliveries"]["severity"], "warning")
		self.assertEqual(out["swing:deliveries"]["title"], "Deliveries down 100% vs previous 7 days")
		self.assertEqual(out["swing:deliveries"]["detail"], "0 this period against 3 in the previous 7 days.")
		self.assertEqual(out["swing:jobs"]["severity"], "positive")
		self.assertEqual(out["swing:backlog"]["severity"], "warning")
		self.assertEqual(out["swing:enquiries"]["severity"], "info")
		self.assertEqual(out["swing:enquiries"]["title"], "Enquiries: 12 after a quiet previous 7 days")
		self.assertEqual(out["swing:enquiries"]["metric_key"], "enquiries")

	def test_swing_wording_like_the_spec(self):
		k = self.kpi("enquiries", 12, 5, label="New enquiries")
		self.assertEqual(cc.rule_volume_swings([k], "vs previous 7 days")[0]["title"],
		                 "New enquiries up 140% vs previous 7 days")

	def test_swing_threshold_is_inclusive(self):
		out = cc.rule_volume_swings([self.kpi("jobs", 6, 4)], "vs previous 7 days")  # +50%
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["title"], "Jobs up 50% vs previous 7 days")
		self.assertEqual(cc.rule_volume_swings([self.kpi("jobs", 5, 0)], "vs previous 7 days")[0]["severity"],
		                 "info")  # exactly SWING_NEW_MIN

	# ---- R5: jobs past ETA ------------------------------------------------

	def test_jobs_past_eta(self):
		jobs = [{"name": "J1", "eta": "2026-10-02"}, {"name": "J2", "eta": "2026-09-26"},
		        {"name": "J3", "eta": "2026-10-10"}, {"name": "J4", "eta": None}]
		i = cc.rule_jobs_past_eta(jobs, AS_OF)
		self.assertEqual((i["id"], i["severity"]), ("jobs_past_eta", "warning"))
		self.assertEqual(i["title"], "2 open jobs are past their ETA")
		self.assertIn("26 Sep on J2", i["detail"])
		self.assertEqual(cc.rule_jobs_past_eta(jobs[:1], AS_OF)["title"], "1 open job is past its ETA")
		self.assertIsNone(cc.rule_jobs_past_eta(jobs[2:], AS_OF))
		# The list behind the number must show the same jobs. In the v16 list
		# view '<' on a Date is IFNULL(eta,'0001-01-01') < x, which matches every
		# job with NO eta (J4 here, 23 live jobs on 2026-10-10); 'between' never
		# matches NULL. Cancelled jobs keep their stage, so docstatus is explicit.
		self.assertEqual(i["route"],
		                 "/app/job-order?fps_stage=%5B%22not%20in%22%2C%5B%22Closed%22%2C%22Completed%22%2C%22Invoiced%22%5D%5D"
		                 "&eta=%5B%22between%22%2C%5B%222000-01-01%22%2C%222026-10-09%22%5D%5D"
		                 "&docstatus=%5B%22%3C%22%2C2%5D")
		q = route_filters(i["route"])
		self.assertNotEqual(q["eta"][0], "<")
		self.assertEqual(q["eta"][0], "between")
		self.assertEqual(q["eta"][1][1], (AS_OF - timedelta(days=1)).isoformat())  # inclusive end: J3 (today) is out
		self.assertEqual(q["docstatus"], ["<", 2])
		self.assertEqual(q["fps_stage"], ["not in", list(cc.CLOSED_JOB_STAGES)])

	# ---- R6: delivered not invoiced ---------------------------------------

	def test_delivered_not_invoiced(self):
		jobs = [{"name": "J1", "docstatus": 0, "fps_stage": "Delivered", "jo_date": "2026-09-20"},
		        {"name": "J2", "docstatus": 1, "fps_stage": "Delivered", "jo_date": "2026-08-14"},
		        {"name": "J3", "docstatus": 2, "fps_stage": "Delivered", "jo_date": "2026-05-01"},  # cancelled
		        {"name": "J4", "docstatus": 1, "fps_stage": "Invoiced", "jo_date": "2026-05-01"}]
		i = cc.rule_delivered_not_invoiced(jobs)
		self.assertEqual((i["id"], i["severity"]), ("delivered_not_invoiced", "info"))
		self.assertEqual(i["title"], "2 delivered jobs are waiting to be invoiced")
		self.assertEqual(i["detail"], "Oldest: J2, opened 14 Aug. The next step on each is the invoice.")
		self.assertEqual(i["route"], "/app/job-order?fps_stage=Delivered")
		self.assertEqual(cc.rule_delivered_not_invoiced(jobs[:1])["title"],
		                 "1 delivered job is waiting to be invoiced")
		self.assertIsNone(cc.rule_delivered_not_invoiced(jobs[2:]))

	# ---- R7: AR ageing (finance) ------------------------------------------

	def test_ar_ageing_live_shape(self):
		# 2026-10-10: AED 756,615.87 outstanding, 458,222.94 of it more than 90
		# days past due -- 60.6%.
		invoices = [
			{"posting_date": "2024-03-01", "due_date": "2024-03-31", "outstanding_amount": 400000.00},
			{"posting_date": "2026-03-01", "due_date": "2026-03-31", "outstanding_amount": 58222.94},
			{"posting_date": "2026-08-01", "due_date": "2026-08-31", "outstanding_amount": 278648.89},
			{"posting_date": "2026-09-25", "due_date": "2026-10-25", "outstanding_amount": 19744.04},
		]
		i = cc.rule_ar_ageing(invoices, AS_OF)
		self.assertEqual((i["id"], i["severity"]), ("ar_ageing", "info"))
		self.assertEqual(i["title"], "AED 458.2K of AED 756.6K outstanding is over 90 days past due")
		self.assertEqual(i["detail"], "AED 400K of it was posted before 1 Jan 2026.")
		self.assertEqual(i["route"], cc.AR_REPORT_ROUTE)

	def test_ar_ageing_threshold_and_edges(self):
		at_40 = [{"posting_date": "2026-01-05", "due_date": "2026-06-01", "outstanding_amount": 40},
		         {"posting_date": "2026-09-01", "due_date": "2026-10-01", "outstanding_amount": 60}]
		self.assertEqual(cc.rule_ar_ageing(at_40, AS_OF)["detail"],
		                 "None of it was posted before 1 Jan 2026.")
		below = [dict(at_40[0], outstanding_amount=39.99), at_40[1]]
		self.assertIsNone(cc.rule_ar_ageing(below, AS_OF))
		# Exactly 90 days past due is not "over 90".
		edge = [{"posting_date": "2025-01-01", "due_date": "2026-07-12", "outstanding_amount": 100}]
		self.assertIsNone(cc.rule_ar_ageing(edge, AS_OF))
		legacy_only = [dict(edge[0], due_date="2026-07-11")]
		self.assertEqual(cc.rule_ar_ageing(legacy_only, AS_OF)["detail"],
		                 "All of it was posted before 1 Jan 2026.")
		self.assertIsNone(cc.rule_ar_ageing([], AS_OF))
		self.assertIsNone(cc.rule_ar_ageing([{"due_date": "2025-01-01", "outstanding_amount": -5}], AS_OF))

	# ---- R8: quotation drafts ---------------------------------------------

	def drafts(self, n):
		return [{"docstatus": 0, "transaction_date": (AS_OF - timedelta(days=i * 3)).isoformat(),
		         "base_grand_total": 10000} for i in range(n)]

	def test_quotation_drafts(self):
		self.assertIsNone(cc.rule_quotation_drafts(self.drafts(4), AS_OF, finance=True))
		fin = cc.rule_quotation_drafts(self.drafts(5), AS_OF, finance=True)
		self.assertEqual((fin["id"], fin["severity"]), ("quotation_drafts", "info"))
		self.assertEqual(fin["title"], "5 quotations still in draft (AED 50K)")
		self.assertEqual(fin["detail"], "Dated in the last 30 days, the oldest 28 Sep; 2 are more than 7 days old.")
		# The list is bounded to the same 30-day window as the count (every
		# draft on the site would otherwise open behind the number).
		self.assertEqual(fin["route"],
		                 "/app/quotation?docstatus=0&transaction_date=%5B%22between%22%2C%5B%222026-09-11%22%2C%222026-10-10%22%5D%5D")
		q = route_filters(fin["route"])
		self.assertEqual(q["docstatus"], "0")
		self.assertEqual(q["transaction_date"],
		                 ["between", [cc.quote_draft_since(AS_OF).isoformat(), AS_OF.isoformat()]])

	def test_quotation_drafts_amount_is_finance_only(self):
		ops = cc.rule_quotation_drafts(self.drafts(5), AS_OF, finance=False)
		self.assertEqual(ops["title"], "5 quotations still in draft")
		self.assertNotIn("AED", json.dumps(ops))

	# ---- not in the spec: enquiry silence -----------------------------------

	def test_enquiry_silence(self):
		self.assertIsNone(cc.rule_enquiry_silence(d("2026-10-04"), AS_OF, 120))  # 6 days
		i = cc.rule_enquiry_silence(d("2026-10-03"), AS_OF, 120)
		self.assertEqual((i["id"], i["severity"], i["metric_key"]), ("enquiry_silence", "warning", "enquiries"))
		self.assertEqual(i["title"], "No new enquiry logged for 7 days")
		# The real Sep 13 - Oct 5 hole, seen on 4 Oct.
		hole = cc.rule_enquiry_silence(d("2026-09-12"), d("2026-10-04"), 120)
		self.assertEqual(hole["title"], "No new enquiry logged for 22 days")
		self.assertIn("12 Sep", hole["detail"])
		self.assertEqual(cc.rule_enquiry_silence(None, AS_OF, 120)["title"],
		                 "No new enquiry logged in the last 120 days")


class TestRanking(unittest.TestCase):
	def make(self, id_, severity, rule, weight):
		return cc._insight(id_, severity, "t " + id_, "d", rule, weight)

	def test_severity_order_is_the_spec(self):
		self.assertEqual(cc.SEVERITY_ORDER, ("critical", "warning", "positive", "info"))

	def test_order_and_cap(self):
		items = [self.make("swing:a", "info", 7, 50), self.make("jobs_past_eta", "warning", 5, 2),
		         self.make("customs_mofa", "critical", 2, 3), self.make("customs_docs", "critical", 1, 1),
		         self.make("swing:b", "positive", 7, 90), self.make("invoicing_stall", "warning", 4, 17),
		         self.make("swing:c", "warning", 7, 100), self.make("swing:d", "warning", 7, 200),
		         None]
		ranked = cc.rank_insights(items)
		self.assertEqual([i["id"] for i in ranked],
		                 ["customs_docs", "customs_mofa", "invoicing_stall", "jobs_past_eta",
		                  "swing:d", "swing:c"])
		self.assertEqual(len(ranked), cc.INSIGHT_CAP)
		for i in ranked:
			self.assertFalse([k for k in i if k.startswith("_")])

	def test_positive_outranks_info(self):
		items = [self.make("delivered_not_invoiced", "info", 8, 9), self.make("swing:jobs", "positive", 7, 1),
		         self.make("quotation_drafts", "info", 10, 99), self.make("ar_ageing", "info", 9, 1e6)]
		self.assertEqual([i["id"] for i in cc.rank_insights(items)],
		                 ["swing:jobs", "delivered_not_invoiced", "ar_ageing", "quotation_drafts"])

	def test_magnitude_orders_within_a_rule(self):
		items = [self.make("swing:a", "warning", 7, 60), self.make("swing:b", "warning", 7, 100)]
		self.assertEqual([i["id"] for i in cc.rank_insights(items)], ["swing:b", "swing:a"])

	def test_rule_table_is_complete_and_unique(self):
		self.assertEqual(sorted(cc._RULE.values()), list(range(1, len(cc._RULE) + 1)))

	def test_copy_limits(self):
		i = cc._insight("X", "info", "t" * 200, "d " * 200, 1, 1)
		self.assertLessEqual(len(i["title"]), cc.TITLE_MAX)
		self.assertLessEqual(len(i["detail"]), cc.DETAIL_MAX)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

STAGES = {"tiles": [
	{"key": "enquiry", "label": "Enquiry", "note": "open", "count": 37, "route": "/app/fps-enquiry?status=Open"},
	{"key": "job_order", "label": "Job Order", "note": "open", "count": 34, "route": "/app/job-order"},
	{"key": "delivered", "label": "Delivered", "note": "awaiting invoice", "count": 2,
	 "route": "/app/job-order?fps_stage=Delivered"},
], "footnotes": ["2 past ETA"]}


def raw_fixture():
	return {
		"FPS Enquiry": [
			{"name": "E0", "enquiry_date": "2026-07-21", "status": "Quoted", "client_name": "Customer A"},
			{"name": "E1", "enquiry_date": "2026-10-08", "status": "Open", "client_name": "Customer B",
			 "enquiry_source": "WhatsApp"},
			{"name": "E2", "enquiry_date": "2026-10-09", "status": "Quoted", "client_name": "Customer C",
			 "enquiry_source": "Email"},
		],
		"Quotation": [
			{"name": "Q1", "transaction_date": "2026-10-08", "docstatus": 1, "status": "Open",
			 "base_grand_total": 21000, "customer_name": "Customer B", "quotation_to": "Lead"},
		] + [
			# Five drafts from mid-September: inside the 30-day draft window,
			# outside the 7-day KPI window.
			{"name": "QD%d" % i, "transaction_date": "2026-09-1%d" % (5 + i), "docstatus": 0,
			 "status": "Draft", "base_grand_total": 1000, "customer_name": "Customer D"}
			for i in range(5)
		],
		"Job Order": [
			{"name": "J1", "jo_date": "2026-05-20", "docstatus": 1, "fps_stage": "Invoiced",
			 "fps_category": "CC - Customs Clearance", "customer_name": "Customer A"},
			{"name": "J2", "jo_date": "2026-10-07", "docstatus": 0, "fps_stage": "New",
			 "fps_category": "XB - Cross-Border Land Transport", "eta": "2026-10-02",
			 "customer_name": "Customer B"},
			{"name": "J3", "jo_date": "2026-09-20", "docstatus": 0, "fps_stage": "Delivered",
			 "fps_category": "CC - Customs Clearance", "customer_name": "Customer C"},
		],
		"Customs Tracker": [
			{"name": "CT1", "clearance_date": "2026-10-05", "status": "Cleared",
			 "fps_doc_submission": "Pending", "fps_doc_deadline": "2026-08-08"},
			{"name": "CT2", "clearance_date": "2026-09-30", "status": "Cleared",
			 "fps_mofa_status": "Pending", "fps_mofa_deadline": "2026-10-14"},
		],
		"Proof of Delivery": [],
		"FPS Job Update": [
			{"name": "u1", "parent": "J2", "update_date": "2026-10-08", "source": "Manual",
			 "milestone": "OPENED", "job_customer": "Customer B", "job_stage": "New",
			 "creation": "2026-10-08 09:00:00"},
		],
		"Sales Invoice": [
			{"name": "I1", "posting_date": "2026-09-23", "docstatus": 1, "status": "Overdue",
			 "base_net_total": 12051.11, "base_grand_total": 12051.11, "outstanding_amount": 12051.11,
			 "due_date": "2026-09-30", "customer_name": "Customer A", "fps_job_order": "J1"},
			{"name": "I0", "posting_date": "2023-04-07", "docstatus": 1, "status": "Overdue",
			 "base_net_total": 500, "outstanding_amount": 500, "due_date": "2023-05-07",
			 "customer_name": "Customer A"},
			{"name": "I2", "posting_date": "2026-09-30", "docstatus": 0, "status": "Draft",
			 "base_net_total": 1000, "base_grand_total": 1050, "outstanding_amount": 1050,
			 "fps_job_order": "J2"},
			# Repeats I1: same Job Order, same grand total.
			{"name": "I3", "posting_date": "2026-09-25", "docstatus": 0, "status": "Draft",
			 "base_net_total": 12051.11, "base_grand_total": 12051.11, "outstanding_amount": 12051.11,
			 "fps_job_order": "J1"},
		],
		"Payment Entry": [
			{"name": "R1", "posting_date": "2026-09-28", "base_received_amount": 12051.11,
			 "party_name": "Customer A", "creation": "2026-10-05 17:57:45", "payment_type": "Receive"},
			{"name": "R2", "posting_date": "2026-08-15", "base_received_amount": 2500,
			 "party_name": "Customer B", "creation": "2026-09-20 10:00:00", "payment_type": "Receive"},
			# Older receipt: proves the source reaches back past the previous window.
			{"name": "R0", "posting_date": "2026-07-01", "base_received_amount": 5000,
			 "party_name": "Customer A", "creation": "2026-08-30 10:00:00", "payment_type": "Receive"},
		],
	}


def build(finance=True, period="7d", raw=None):
	return cc.build_dashboard(
		period=period, as_of=AS_OF, generated_at="2026-10-10 09:30:00",
		viewer={"finance": finance, "full_name": "Test User"},
		raw=raw if raw is not None else raw_fixture(), stages=STAGES,
		creatable={"FPS Enquiry", "Job Order", "Sales Invoice", "Customs Tracker", "Payment Entry"})


FINANCE_ONLY_INSIGHTS = ("duplicate_drafts", "invoicing_stall", "ar_ageing")


class TestDashboard(unittest.TestCase):
	def test_shape_and_order(self):
		p = build()
		self.assertEqual([k["key"] for k in p["kpis"]], list(cc.KPI_ORDER))
		self.assertEqual((p["as_of"], p["period"], p["period_label"], p["compare_label"]),
		                 ("2026-10-10", "7d", "Last 7 days", "vs previous 7 days"))
		self.assertEqual(p["viewer"], {"finance": True, "full_name": "Test User"})
		self.assertEqual(p["stages"], {"tiles": STAGES["tiles"], "footnotes": STAGES["footnotes"]})
		json.dumps(p)  # plain JSON all the way down: no date objects leak

	def test_kpi_values(self):
		k = {x["key"]: x for x in build()["kpis"]}
		self.assertEqual((k["enquiries"]["value"], k["enquiries"]["previous"]), (2, 0))
		self.assertIsNone(k["enquiries"]["delta_pct"])
		self.assertEqual(k["enquiries"]["context"], [{"label": "Open now", "value": "37"},
		                                            {"label": "Quoted", "value": "1"}])
		self.assertEqual(k["quotations"]["value"], 1)
		self.assertEqual(k["quotations"]["context"], [{"label": "Submitted", "value": "1"},
		                                             {"label": "Drafts, last 30 days", "value": "5"}])
		self.assertEqual(k["jobs"]["context"], [{"label": "Active pipeline", "value": "34"}])
		self.assertEqual(k["customs_cleared"]["context"][0], {"label": "Docs overdue", "value": "1"})
		self.assertEqual(k["jobs"]["new_doctype"], "Job Order")
		self.assertNotIn("new_doctype", k["quotations"])       # not creatable for this viewer
		self.assertNotIn("new_doctype", k["job_activity"])     # child rows have no form
		self.assertNotIn("new_doctype", k["customs_cleared"])  # spec: trackers are auto-created
		self.assertNotIn("new_doctype", k["collected"])        # spec: no blank receipts
		self.assertEqual(k["invoiced"]["label"], "Invoiced (net)")
		self.assertEqual(k["invoiced"]["currency"], "AED")
		self.assertEqual(k["invoiced"]["value"], 0.0)
		self.assertNotIn("caveat", k["invoiced"])               # spec: no invoiced caveat
		self.assertEqual(k["invoiced"]["context"], [{"label": "Drafts waiting", "value": "2 · AED 13.1K"},
		                                           {"label": "Last submitted", "value": "23 Sep"}])
		self.assertEqual((k["collected"]["value"], k["collected"]["previous"]), (0.0, 12051.11))
		self.assertEqual(k["collected"]["delta_pct"], -100.0)
		self.assertEqual(k["collected"]["context"], [{"label": "Outstanding AR", "value": "AED 12.6K"},
		                                            {"label": "Receipts", "value": "0"}])
		self.assertIn("median of 36 days", k["collected"]["caveat"])  # 7, 36, 60
		self.assertTrue(k["invoiced"]["finance"])
		self.assertFalse(k["jobs"]["finance"])

	def test_collected_context_omits_ar_when_invoices_unreadable(self):
		raw = raw_fixture()
		del raw["Sales Invoice"]
		k = {x["key"]: x for x in build(raw=raw)["kpis"]}
		self.assertNotIn("invoiced", k)
		self.assertEqual(k["collected"]["context"], [{"label": "Receipts", "value": "0"}])

	def test_insights(self):
		p = build()
		self.assertEqual([i["id"] for i in p["insights"]],
		                 ["customs_docs", "customs_mofa", "duplicate_drafts", "invoicing_stall",
		                  "jobs_past_eta", "delivered_not_invoiced"])  # capped at 6
		sev = [cc.SEVERITY_ORDER.index(i["severity"]) for i in p["insights"]]
		self.assertEqual(sev, sorted(sev))
		by_id = {i["id"]: i for i in p["insights"]}
		self.assertEqual(by_id["customs_mofa"]["severity"], "warning")       # upcoming only
		self.assertEqual(by_id["duplicate_drafts"]["detail"],
		                 "I3 has the Job Order and grand total of a submitted invoice (AED 12.1K in all); "
		                 "check before submitting.")
		self.assertEqual(by_id["invoicing_stall"]["title"], "No invoice submitted for 17 days")

	def test_insight_cap_keeps_the_most_severe(self):
		full = cc.rank_insights([cc._insight("x%d" % i, "info", "t", "d", 8, i) for i in range(9)])
		self.assertEqual(len(full), cc.INSIGHT_CAP)
		self.assertLessEqual(len(build(period="30d")["insights"]), cc.INSIGHT_CAP)

	def test_money_is_gated_server_side(self):
		# Even if a caller handed over money rows, a non-finance viewer gets none:
		# no money KPI, no money trend, no money insight, and no amount anywhere.
		p = build(finance=False)
		keys = [k["key"] for k in p["kpis"]]
		self.assertNotIn("invoiced", keys)
		self.assertNotIn("collected", keys)
		self.assertEqual([t["key"] for t in p["trend"]], ["pipeline", "activity"])
		ids = [i["id"] for i in p["insights"]]
		self.assertFalse([i for i in ids if i in FINANCE_ONLY_INSIGHTS])
		self.assertEqual(ids, ["customs_docs", "customs_mofa", "jobs_past_eta",
		                       "delivered_not_invoiced", "quotation_drafts"])
		self.assertEqual(p["viewer"]["finance"], False)
		self.assertNotIn("AED", json.dumps(p))
		drafts = next(i for i in p["insights"] if i["id"] == "quotation_drafts")
		self.assertEqual(drafts["title"], "5 quotations still in draft")

	def test_duplicate_drafts_rule_is_finance_only(self):
		fin = [i["id"] for i in build(finance=True)["insights"]]
		ops = [i["id"] for i in build(finance=False)["insights"]]
		self.assertIn("duplicate_drafts", fin)
		self.assertNotIn("duplicate_drafts", ops)
		# The invoice names a draft carries never reach an ops payload either.
		self.assertNotIn("I3", json.dumps(build(finance=False)))

	def test_finance_sees_quotation_draft_value(self):
		raw = raw_fixture()
		raw["Sales Invoice"] = None   # drop the money rules so the info insight fits the cap
		raw["Customs Tracker"] = None
		p = build(raw=raw)
		drafts = next(i for i in p["insights"] if i["id"] == "quotation_drafts")
		self.assertEqual(drafts["title"], "5 quotations still in draft (AED 5K)")

	def test_unreadable_doctype_is_omitted_not_zeroed(self):
		raw = raw_fixture()
		del raw["Customs Tracker"]
		raw["Proof of Delivery"] = None
		p = build(raw=raw)
		keys = [k["key"] for k in p["kpis"]]
		self.assertNotIn("customs_cleared", keys)
		self.assertNotIn("deliveries", keys)
		self.assertFalse([i for i in p["insights"] if i["id"].startswith("customs_")])
		# Both of its series are gone, so the whole mode is.
		self.assertNotIn("activity", [t["key"] for t in p["trend"]])
		raw = raw_fixture()
		del raw["Job Order"]
		ids = [i["id"] for i in build(raw=raw)["insights"]]
		self.assertNotIn("jobs_past_eta", ids)
		self.assertNotIn("delivered_not_invoiced", ids)
		raw = raw_fixture()
		del raw["Quotation"]
		self.assertNotIn("quotation_drafts", [i["id"] for i in build(raw=raw, finance=False)["insights"]])

	def test_trend(self):
		trend = {t["key"]: t for t in build()["trend"]}
		self.assertEqual(list(trend), ["pipeline", "activity", "money"])
		pipe = trend["pipeline"]
		self.assertEqual([(s["key"], s["slot"]) for s in pipe["series"]],
		                 [("enquiries", 1), ("quotations", 2), ("jobs", 3)])
		self.assertEqual(len(pipe["points"]), 12)
		self.assertEqual(pipe["points"][-1]["week_start"], "2026-10-05")
		self.assertEqual(pipe["points"][-1]["label"], "5 Oct")
		self.assertTrue(pipe["points"][-1]["partial"])
		self.assertEqual(pipe["points"][-1]["values"], {"enquiries": 2, "quotations": 1, "jobs": 1})
		self.assertEqual(pipe["points"][0]["values"]["enquiries"], 1)  # 21 Jul
		money_mode = trend["money"]
		self.assertEqual(money_mode["currency"], "AED")
		self.assertTrue(money_mode["finance"])
		self.assertIn("caveat", money_mode)
		# The money series are the KPIs' own points, so they wear the KPIs'
		# labels: "Invoiced (net)" in the legend, tooltip and table header too.
		labels = {s["key"]: s["label"] for s in money_mode["series"]}
		self.assertEqual(labels, {"invoiced": "Invoiced (net)", "collected": "Collected"})
		for key, label in labels.items():
			self.assertEqual(label, cc.METRICS[key]["label"], key)

	def test_job_activity_previous_is_null_before_the_logger_went_live(self):
		# Live 30d on 2026-10-10: 93 updates against 9 back-dated rows in the
		# previous window read "+933.3%" -- the logger going live, not growth.
		raw = raw_fixture()
		raw["FPS Job Update"] = [
			{"name": "u0", "parent": "J1", "update_date": "2026-06-10", "source": "System",   # retro-logged
			 "milestone": "OPENED", "job_customer": "Customer A", "creation": "2026-09-13 09:00:00"},
			{"name": "u1", "parent": "J2", "update_date": "2026-08-20", "source": "System",   # in the 30d previous window
			 "milestone": "BOE", "job_customer": "Customer B", "creation": "2026-09-12 09:00:00"},
			{"name": "u2", "parent": "J2", "update_date": "2026-10-08", "source": "Manual",
			 "milestone": "DO", "job_customer": "Customer B", "creation": "2026-10-08 09:00:00"},
		]
		k = {x["key"]: x for x in build(period="30d", raw=raw)["kpis"]}["job_activity"]
		self.assertEqual(k["value"], 1)
		self.assertIsNone(k["previous"])
		self.assertIsNone(k["delta_pct"])
		m = cc.build_metric_detail("job_activity", raw, period="30d", as_of=AS_OF)
		self.assertEqual((m["value"], m["previous"], m["delta_pct"]), (1, None, None))
		# 7d: the source reaches back past 27 Sep, so previous is a real 0.
		k7 = {x["key"]: x for x in build(period="7d", raw=raw)["kpis"]}["job_activity"]
		self.assertEqual((k7["value"], k7["previous"]), (1, 0))
		# No swing insight is built on the clamped comparison.
		self.assertNotIn("swing:job_activity", [i["id"] for i in build(period="30d", raw=raw)["insights"]])

	def test_slot_follows_key_when_a_series_is_hidden(self):
		raw = raw_fixture()
		del raw["Quotation"]
		pipe = next(t for t in build(raw=raw)["trend"] if t["key"] == "pipeline")
		self.assertEqual([(s["key"], s["slot"]) for s in pipe["series"]], [("enquiries", 1), ("jobs", 3)])

	def test_periods(self):
		for period, n in (("7d", 7), ("30d", 30), ("90d", 13)):
			p = build(period=period)
			for k in p["kpis"]:
				self.assertEqual(len(k["series"]), n, (period, k["key"]))
		with self.assertRaises(ValueError):
			build(period="1y")


class TestMetricDetail(unittest.TestCase):
	def jobs_raw(self):
		rows = []
		cats = (["CC - Customs Clearance"] * 6 + ["LT - Local Land Transport"] * 2
		        + ["XB - Cross-Border Land Transport", "FF - Freight Forwarding", "GJ - General Job", None])
		for i, cat in enumerate(cats):
			rows.append({"name": "FPS/JO/2610/%03d" % i, "jo_date": (AS_OF - timedelta(days=i)).isoformat(),
			             "docstatus": 0, "fps_category": cat, "fps_stage": "New",
			             "customer_name": "Customer %s" % "ABCDEFGHIJKL"[i]})
		rows.append({"name": "FPS/JO/2601/001", "jo_date": "2026-01-05", "docstatus": 1,
		             "fps_category": "CC - Customs Clearance", "fps_stage": "Invoiced"})
		return {"Job Order": rows}

	def test_dimension_options_and_breakdown(self):
		m = cc.build_metric_detail("jobs", self.jobs_raw(), period="30d", as_of=AS_OF, can_create=True)
		self.assertEqual(m["value"], 12)
		self.assertEqual(m["dimension_label"], "Service line")
		self.assertEqual([o["label"] for o in m["dimension_options"]][:2], ["Customs clearance", "Local transport"])
		self.assertEqual(m["dimension_options"][0]["key"], "CC - Customs Clearance")
		rows = m["breakdown"]["rows"]
		self.assertEqual(m["breakdown"]["title"], "By service line")
		self.assertEqual(len(rows), 6)  # top 5 + Other
		self.assertEqual(rows[0], {"key": "CC - Customs Clearance", "label": "Customs clearance", "value": 6})
		self.assertEqual(rows[-1], {"key": cc.OTHER_KEY, "label": "Other", "value": 1})
		self.assertEqual(sum(r["value"] for r in rows), 12)
		self.assertIsNone(m["dimension"])

	def test_filter_by_dimension(self):
		m = cc.build_metric_detail("jobs", self.jobs_raw(), period="30d", as_of=AS_OF,
		                           dimension="LT - Local Land Transport")
		self.assertEqual(m["dimension"], "LT - Local Land Transport")
		self.assertEqual(m["value"], 2)
		self.assertEqual({r["subtitle"].split(" · ")[0] for r in m["records"]}, {"Local transport"})
		self.assertEqual(sum(p["value"] for p in m["series"]), 2)
		# The breakdown still shows the whole distribution the chips choose from.
		self.assertEqual(sum(r["value"] for r in m["breakdown"]["rows"]), 12)

	def test_unknown_dimension_falls_back_to_all(self):
		m = cc.build_metric_detail("jobs", self.jobs_raw(), period="30d", as_of=AS_OF, dimension="Nope")
		self.assertIsNone(m["dimension"])
		self.assertEqual(m["value"], 12)

	def test_records(self):
		m = cc.build_metric_detail("jobs", self.jobs_raw(), period="30d", as_of=AS_OF)
		self.assertEqual(len(m["records"]), cc.RECORDS_CAP)
		self.assertEqual(m["records"][0]["name"], "FPS/JO/2610/000")
		self.assertEqual(m["records"][0]["route"], "/app/job-order/FPS%2FJO%2F2610%2F000")
		self.assertEqual(m["records"][0]["date"], "2026-10-10")
		dates = [r["date"] for r in m["records"]]
		self.assertEqual(dates, sorted(dates, reverse=True))
		self.assertNotIn("value", m["records"][0])

	def test_actions(self):
		m = cc.build_metric_detail("jobs", self.jobs_raw(), period="7d", as_of=AS_OF, can_create=True)
		self.assertEqual(m["actions"], [
			{"key": "open_list", "label": "Open list", "kind": "route", "route": "/app/job-order"},
			{"key": "new", "label": "New Job Order", "kind": "new_doc", "doctype": "Job Order"}])
		m = cc.build_metric_detail("jobs", self.jobs_raw(), period="7d", as_of=AS_OF, can_create=False)
		self.assertEqual([a["key"] for a in m["actions"]], ["open_list"])
		inv = cc.build_metric_detail("invoiced", raw_fixture(), period="30d", as_of=AS_OF,
		                             finance=True, can_create=True)
		self.assertEqual([a["key"] for a in inv["actions"]], ["open_list", "new", "open_report"])
		self.assertEqual(inv["actions"][2]["route"], "/app/query-report/Accounts%20Receivable")
		act = cc.build_metric_detail("job_activity", raw_fixture(), period="7d", as_of=AS_OF, can_create=True)
		self.assertEqual([a["key"] for a in act["actions"]], ["open_list"])
		# Spec: trackers are auto-created per job, so no blank "New" form.
		ct = cc.build_metric_detail("customs_cleared", raw_fixture(), period="7d", as_of=AS_OF, can_create=True)
		self.assertEqual([a["key"] for a in ct["actions"]], ["open_list"])

	def test_money_detail(self):
		inv = cc.build_metric_detail("invoiced", raw_fixture(), period="30d", as_of=AS_OF, finance=True)
		self.assertEqual((inv["unit"], inv["currency"], inv["value"]), ("currency", "AED", 12051.11))
		self.assertEqual(inv["breakdown"]["title"], "Top customers")
		self.assertEqual(inv["breakdown"]["rows"], [{"key": "Customer A", "label": "Customer A", "value": 12051.11}])
		self.assertEqual(inv["records"][0]["value"], 12051.11)
		self.assertNotIn("caveat", inv)   # same as the card: no invoiced caveat (spec)
		col = cc.build_metric_detail("collected", raw_fixture(), period="30d", as_of=AS_OF, finance=True,
		                             can_create=True)
		self.assertIn("median of 36 days", col["caveat"])
		self.assertEqual([a["key"] for a in col["actions"]], ["open_list"])  # no blank receipts

	def test_quotation_value_only_for_finance(self):
		ops = cc.build_metric_detail("quotations", raw_fixture(), period="7d", as_of=AS_OF, finance=False)
		fin = cc.build_metric_detail("quotations", raw_fixture(), period="7d", as_of=AS_OF, finance=True)
		self.assertNotIn("value", ops["records"][0])
		self.assertEqual(fin["records"][0]["value"], 21000.0)
		self.assertEqual(fin["records"][0]["subtitle"], "Lead")

	def test_job_activity_lists_jobs_once(self):
		raw = raw_fixture()
		raw["FPS Job Update"] = [
			{"name": "u%d" % i, "parent": "J%d" % (i % 2), "update_date": "2026-10-0%d" % (i + 1),
			 "source": "Manual", "milestone": "BOE" if i % 2 else "", "job_customer": "Customer A",
			 "creation": "2026-10-0%d 09:00:00" % (i + 1)} for i in range(6)]
		m = cc.build_metric_detail("job_activity", raw, period="30d", as_of=AS_OF)
		self.assertEqual([r["name"] for r in m["records"]], ["J1", "J0"])
		self.assertEqual(m["value"], 6)
		self.assertEqual(m["records"][0]["route"], "/app/job-order/J1")

	def test_empty(self):
		m = cc.build_metric_detail("deliveries", {}, period="7d", as_of=AS_OF)
		self.assertEqual((m["value"], m["previous"], m["delta_pct"]), (0, None, None))
		self.assertIsNone(m["breakdown"])
		self.assertEqual((m["dimension_options"], m["records"]), ([], []))
		json.dumps(m)


# --------------------------------------------------------------------------
# The FPS OPS Dashboard: no money for anyone (14 Oct 2026)
# --------------------------------------------------------------------------

OPS_KPIS = ["enquiries", "quotations", "jobs", "customs_cleared", "deliveries", "job_activity"]

INVOICES_TILE = {"key": "invoices", "label": "Invoices", "note": "open", "count": 26,
                 "route": "/app/sales-invoice?status=x"}


def stages_with_invoices():
	return {"tiles": STAGES["tiles"] + [dict(INVOICES_TILE)], "footnotes": list(STAGES["footnotes"])}


def ops_build(period="7d", raw=None):
	"""build_dashboard exactly as command_center._dashboard calls it now."""
	return cc.build_dashboard(
		period=period, as_of=AS_OF, generated_at="2026-10-10 09:30:00",
		viewer={"finance": False, "full_name": "Test User"},
		raw=raw if raw is not None else raw_fixture(),
		stages=cc.ops_stages(stages_with_invoices()),
		creatable={"FPS Enquiry", "Job Order", "Sales Invoice"})


class TestOpsPayload(unittest.TestCase):
	def test_ops_stages_drops_the_invoices_tile_only(self):
		src = stages_with_invoices()
		out = cc.ops_stages(src)
		self.assertEqual([t["key"] for t in out["tiles"]], ["enquiry", "job_order", "delivered"])
		self.assertEqual(out["footnotes"], STAGES["footnotes"])
		self.assertIn("invoices", [t["key"] for t in src["tiles"]])   # input untouched
		self.assertEqual(cc.ops_stages(None), {"tiles": [], "footnotes": []})
		self.assertEqual(cc.OPS_HIDDEN_TILES, ("invoices",))

	def test_pipeline_still_has_the_invoices_tile(self):
		# The tile is filtered on the OPS page, not removed from pipeline.TILES
		# (the classic strip and other callers keep it).
		keys = [k for k, _dt, _r in TestDrift().pipeline_tiles()]
		self.assertIn("invoices", keys)

	def test_ops_payload_has_six_kpis_and_no_money(self):
		for period in cc.PERIODS:
			p = ops_build(period)
			self.assertEqual([k["key"] for k in p["kpis"]], OPS_KPIS, period)
			self.assertFalse([k for k in p["kpis"] if k["finance"] or k["unit"] == "currency"])
			self.assertEqual([t["key"] for t in p["trend"]], ["pipeline", "activity"])
			self.assertFalse([t for t in p["trend"] if t["finance"]])
			self.assertEqual(p["viewer"], {"finance": False, "full_name": "Test User"})
			self.assertNotIn("invoices", [t["key"] for t in p["stages"]["tiles"]])
			ids = [i["id"] for i in p["insights"]]
			self.assertFalse(set(ids) & set(FINANCE_ONLY_INSIGHTS), ids)
			text = json.dumps(p)
			self.assertNotIn("AED", text)
			self.assertNotIn("Sales Invoice", text)
			for name in ("I0", "I1", "I2", "I3", "R0", "R1", "R2"):   # money rows handed in anyway
				self.assertNotIn('"%s"' % name, text)

	def test_ops_keeps_delivered_not_invoiced_and_quote_drafts_without_amount(self):
		p = ops_build()
		by_id = {i["id"]: i for i in p["insights"]}
		self.assertIn("delivered_not_invoiced", by_id)       # a job count, not money
		self.assertEqual(by_id["quotation_drafts"]["title"], "5 quotations still in draft")

	def test_ops_drawer_never_carries_a_value(self):
		m = cc.build_metric_detail("quotations", raw_fixture(), period="7d", as_of=AS_OF, finance=False)
		self.assertFalse([r for r in m["records"] if "value" in r])
		self.assertNotIn("AED", json.dumps(m))


class _FakeApiCase(unittest.TestCase):
	def setUp(self):
		from fps_erpnext.tests import fake_frappe
		if fake_frappe.REAL_FRAPPE:
			self.skipTest("a real frappe is importable; covered by the bench test run")
		self.fake_frappe = fake_frappe

	def fake(self, **kw):
		raw = raw_fixture()
		rows = {dt: raw[dt] for dt in ("FPS Enquiry", "Quotation", "Customs Tracker", "Proof of Delivery",
		                               "Job Order", "Sales Invoice", "Payment Entry")}
		rows["FPS Job Update"] = raw["FPS Job Update"]
		return self.fake_frappe.FakeFrappe(rows=rows, today=AS_OF.isoformat(), **kw)


class TestOpsApi(_FakeApiCase):
	"""command_center.py itself, with a stand-in frappe: the money gate is now
	"nobody", Administrator and the finance roles included."""

	FINANCE = ["System Manager", "Accounts Manager", "Accounts User", "FPS Operations"]

	def test_dashboard_reads_no_money_for_administrator(self):
		fake = self.fake(user="Administrator", roles=self.FINANCE,
		                 creatable={"Sales Invoice", "Job Order"})
		with fake.installed() as mods:
			p = mods["command_center"].get_dashboard("7d")
		read = fake.read_doctypes()
		self.assertNotIn("Sales Invoice", read)
		self.assertNotIn("Payment Entry", read)
		self.assertEqual([k["key"] for k in p["kpis"]], OPS_KPIS)
		self.assertIs(p["viewer"]["finance"], False)
		self.assertNotIn("invoices", [t["key"] for t in p["stages"]["tiles"]])
		self.assertNotIn("AED", json.dumps(p))
		# The cache key moved to v3, so no v2 payload with money is served after deploy.
		self.assertIn(("cache_set", "fps_command_center:v3:dashboard:7d", "Administrator"), fake.calls)

	def test_dashboard_for_ops_user(self):
		fake = self.fake(user="ops@example.com", roles=["FPS Operations", "Desk User"])
		with fake.installed() as mods:
			p = mods["command_center"].get_dashboard("30d")
		self.assertEqual([k["key"] for k in p["kpis"]], OPS_KPIS)
		self.assertNotIn("Sales Invoice", fake.read_doctypes())

	def test_drawer_refuses_money_metrics_for_everyone(self):
		for user, roles in (("Administrator", self.FINANCE), ("agam@example.com", self.FINANCE),
		                    ("ops@example.com", ["FPS Operations"])):
			fake = self.fake(user=user, roles=roles)
			with fake.installed() as mods:
				api = mods["command_center"]
				for key in ("invoiced", "collected"):
					with self.assertRaises(self.fake_frappe.PermissionError, msg=(user, key)):
						api.get_metric_detail(key, "30d")
				m = api.get_metric_detail("quotations", "7d")
			self.assertNotIn("Sales Invoice", fake.read_doctypes())
			self.assertNotIn("Payment Entry", fake.read_doctypes())
			self.assertFalse([r for r in m["records"] if "value" in r], user)

	def test_creatable_has_no_money_doctype(self):
		fake = self.fake(creatable={"Sales Invoice", "Job Order"})
		with fake.installed() as mods:
			self.assertEqual(mods["command_center"]._creatable(), {"Job Order"})


# --------------------------------------------------------------------------
# Drift checks
# --------------------------------------------------------------------------

class TestDrift(unittest.TestCase):
	def pipeline_tree(self):
		path = os.path.join(ROOT, "fps_erpnext", "api", "pipeline.py")
		with open(path, encoding="utf-8") as fh:
			return ast.parse(fh.read())

	def assignment(self, tree, name):
		for node in tree.body:
			if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
				return node.value
		self.fail("%s not found in pipeline.py" % name)

	def test_closed_job_stages_match_pipeline_open_job(self):
		open_job = ast.literal_eval(self.assignment(self.pipeline_tree(), "OPEN_JOB"))
		stage_rule = next(f for f in open_job if f[1] == "fps_stage")
		self.assertEqual(stage_rule[2], "not in")
		self.assertEqual(tuple(stage_rule[3]), cc.CLOSED_JOB_STAGES)

	def test_sow_short_matches_pipeline(self):
		self.assertEqual(ast.literal_eval(self.assignment(self.pipeline_tree(), "SOW_SHORT")), cc.SOW_SHORT)

	def pipeline_tiles(self):
		"""[(key, doctype, route)] from pipeline.TILES (the filters may name OPEN_JOB)."""
		tiles = []
		for tile in self.assignment(self.pipeline_tree(), "TILES").elts:
			key, _label, _note, doctype = (ast.literal_eval(e) for e in tile.elts[:4])
			tiles.append((key, doctype, ast.literal_eval(tile.elts[5])))
		return tiles

	def test_pipeline_tile_routes_reproduce_their_counts(self):
		# The stage strip links each tile to its route. Report and list views
		# show cancelled documents unless told otherwise, and a route with no
		# query leaves frappe.route_options empty, so the list view keeps the
		# user's last saved filters instead of clearing them.
		tiles = self.pipeline_tiles()
		self.assertEqual(len(tiles), 7)
		for key, doctype, route in tiles:
			self.assertTrue(route.startswith("/app/%s?" % cc.slug(doctype)), (key, route))
			q = route_filters(route)
			if doctype == "Job Order":
				self.assertEqual(q["docstatus"], ["<", 2], key)
				self.assertIn("fps_stage", q, key)
			if key == "customs":
				self.assertEqual(q["status"], ["not in", ["Cleared"]])

	def test_fixture_generator_mirrors_pipeline_tile_routes(self):
		path = os.path.join(ROOT, "dashboard", "dev", "make_fixtures.py")
		if not os.path.exists(path):
			self.skipTest("dashboard sources not shipped with this copy")
		with open(path, encoding="utf-8") as fh:
			tree = ast.parse(fh.read())
		fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "simulate_stages")
		mirrored = {n.value for n in ast.walk(fn)
		            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/app/")}
		self.assertTrue(mirrored)
		self.assertLessEqual(mirrored, {route for _k, _dt, route in self.pipeline_tiles()})

	def test_customs_open_statuses_are_not_done(self):
		for status in cc.CUSTOMS_OPEN_DOC + cc.CUSTOMS_OPEN_MOFA:
			self.assertFalse(cc.is_done(status), status)

	def ts_fields(self, interface):
		path = os.path.join(ROOT, "dashboard", "src", "types", "dashboard.ts")
		if not os.path.exists(path):
			self.skipTest("dashboard sources not shipped with this copy")
		with open(path, encoding="utf-8") as fh:
			src = fh.read()
		body = re.search(r"export interface %s \{(.*?)\n\}" % interface, src, re.S).group(1)
		body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
		return [m.group(1) for m in re.finditer(r"^\s*(\w+)\??:", body, re.M)]

	def test_kpi_keys_match_typescript(self):
		self.assertEqual(self.ts_fields("Kpi"), list(cc.KpiKeys))

	def test_metric_detail_keys_match_typescript(self):
		self.assertEqual(self.ts_fields("MetricDetail"), list(cc.MetricDetailKeys))

	def test_kpi_order_matches_typescript_union(self):
		# KpiKey lists the OPS keys in KPI_ORDER, then the keys only the FPS ACC
		# Dashboard returns (acc_dashboard_logic.KPI_ORDER, 14 Oct 2026).
		from fps_erpnext.api import acc_dashboard_logic as acc
		path = os.path.join(ROOT, "dashboard", "src", "types", "dashboard.ts")
		if not os.path.exists(path):
			self.skipTest("dashboard sources not shipped with this copy")
		with open(path, encoding="utf-8") as fh:
			union = re.search(r"export type KpiKey =(.*?);", fh.read(), re.S).group(1)
		acc_only = [k for k in acc.KPI_ORDER if k not in cc.KPI_ORDER]
		self.assertEqual(re.findall(r'"(\w+)"', union), list(cc.KPI_ORDER) + acc_only)

	def test_fields_cover_every_metric_source(self):
		for key, doctype in cc.METRIC_SOURCE.items():
			self.assertIn(doctype, cc.FIELDS, key)
			self.assertIn("name", cc.FIELDS[doctype])


if __name__ == "__main__":
	unittest.main(verbosity=2)
