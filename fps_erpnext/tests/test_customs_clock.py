"""Customs chase clocks -- plain unittest, no frappe needed.

Run from the app root:

    python -m unittest fps_erpnext.tests.test_customs_clock -v
    python fps_erpnext/tests/test_customs_clock.py

Covers the rule Agam chose on 16 Sep 2026: the document deadline is Dubai
Customs' Fine Start Date, declaration date + 30, and only an approved (cleared)
declaration starts a clock. MOFA still counts from clearance.
"""

import os
import sys
import unittest
from datetime import date

if __package__ in (None, ""):
	sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fps_erpnext.api import customs_clock as cc  # noqa: E402 -- pure module, no frappe

DOC = next(s for s in cc.DEADLINES if s["key"] == "doc")
MOFA = next(s for s in cc.DEADLINES if s["key"] == "mofa")


def d(text):
	return date.fromisoformat(text)


class TestSpec(unittest.TestCase):
	def test_every_clock_names_where_it_counts_from(self):
		for spec in cc.DEADLINES:
			self.assertTrue(spec["from"], spec["key"])
			for field in spec["from"]:
				self.assertIn(field, cc.CLOCK_FIELDS)

	def test_doc_counts_from_declaration_then_clearance(self):
		self.assertEqual(DOC["from"], ("ct_date", "clearance_date"))
		self.assertEqual((DOC["days"], DOC["warn"], DOC["late"]), (30, 15, 25))

	def test_mofa_unchanged(self):
		self.assertEqual(MOFA["from"], ("clearance_date",))
		self.assertEqual((MOFA["days"], MOFA["warn"], MOFA["late"]), (14, 9, 12))

	def test_client_script_carries_the_same_rules(self):
		root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
		path = os.path.join(root, "docs", "design_handoff_fps_workspace",
		                    "client_scripts", "customs_tracker_deadlines.js")
		if not os.path.exists(path):
			self.skipTest("handoff docs not shipped with this copy")
		with open(path, encoding="utf-8") as fh:
			js = fh.read()
		for spec in cc.DEADLINES:
			self.assertIn("from: [%s]" % ", ".join("'%s'" % f for f in spec["from"]), js)
			self.assertIn("warn: %d, late: %d" % (spec["warn"], spec["late"]), js)


class TestDeadlineFor(unittest.TestCase):
	def test_ct_2609_082_fines_from_04_oct(self):
		# Declared 04 Sep, cleared 10 Sep. ERPNext used to say 10 Oct.
		row = {"ct_date": "2026-09-04", "clearance_date": "2026-09-10", "status": "Cleared"}
		self.assertEqual(cc.deadline_for(row, DOC), d("2026-10-04"))
		self.assertEqual(cc.deadline_for(row, MOFA), d("2026-09-24"))

	def test_dubai_customs_notices(self):
		# Reminder 876: declared 11-Aug-26, Fine Start 10-Sep-26.
		self.assertEqual(cc.deadline_for(
			{"ct_date": date(2026, 8, 11), "clearance_date": date(2026, 8, 11)}, DOC),
			d("2026-09-10"))
		# Reminder 875: declared 10-Sep-26, Fine Start 10-Oct-26.
		self.assertEqual(cc.deadline_for(
			{"ct_date": "2026-09-10", "status": "Cleared"}, DOC), d("2026-10-10"))

	def test_no_declaration_date_falls_back_to_clearance(self):
		row = {"ct_date": None, "clearance_date": "2026-09-10", "status": "Cleared"}
		self.assertEqual(cc.deadline_for(row, DOC), d("2026-10-10"))
		self.assertEqual(cc.deadline_for({**row, "ct_date": ""}, DOC), d("2026-10-10"))

	def test_status_cleared_without_clearance_date_starts_the_doc_clock(self):
		row = {"ct_date": "2026-09-04", "clearance_date": None, "status": "Cleared"}
		self.assertEqual(cc.deadline_for(row, DOC), d("2026-10-04"))
		self.assertIsNone(cc.deadline_for(row, MOFA))  # nothing to count MOFA from

	def test_clearance_date_counts_as_approved_whatever_the_status(self):
		row = {"ct_date": "2026-09-04", "clearance_date": "2026-09-10", "status": "Pending"}
		self.assertEqual(cc.deadline_for(row, DOC), d("2026-10-04"))

	def test_pending_declaration_has_no_clock(self):
		for status in ("Pending", "In Process", "On Hold", "Delayed", "", None):
			row = {"ct_date": "2026-09-11", "clearance_date": None, "status": status}
			self.assertIsNone(cc.deadline_for(row, DOC), status)
			self.assertIsNone(cc.deadline_for(row, MOFA), status)

	def test_cleared_with_no_dates_at_all(self):
		self.assertIsNone(cc.deadline_for({"status": "Cleared"}, DOC))

	def test_accepts_datetimes_and_objects(self):
		from datetime import datetime

		class Row:
			ct_date = datetime(2026, 9, 4, 13, 0)
			clearance_date = None
			status = "cleared "

		self.assertEqual(cc.deadline_for(Row(), DOC), d("2026-10-04"))
		self.assertEqual(cc.to_date("2026-09-04 00:00:00"), d("2026-09-04"))

	def test_month_and_year_ends(self):
		self.assertEqual(cc.deadline_for({"ct_date": "2026-12-15", "status": "Cleared"}, DOC),
		                 d("2027-01-14"))
		self.assertEqual(cc.deadline_for({"ct_date": "2028-02-01", "status": "Cleared"}, DOC),
		                 d("2028-03-02"))  # leap year


class TestState(unittest.TestCase):
	ROW = {"ct_date": "2026-09-04", "clearance_date": "2026-09-10", "status": "Cleared"}

	def test_thresholds_count_from_the_declaration_date(self):
		# ct 04 Sep: day 14 -> ok, day 15 -> warn, day 24 -> warn, day 25 -> late
		self.assertEqual(cc.deadline_state(self.ROW, DOC, "2026-09-18"), "ok")
		self.assertEqual(cc.deadline_state(self.ROW, DOC, "2026-09-19"), "warn")
		self.assertEqual(cc.deadline_state(self.ROW, DOC, "2026-09-28"), "warn")
		self.assertEqual(cc.deadline_state(self.ROW, DOC, "2026-09-29"), "late")
		# Counted from clearance (10 Sep) 19 Sep would still be day 9, ok.

	def test_mofa_thresholds_count_from_clearance(self):
		self.assertEqual(cc.deadline_state(self.ROW, MOFA, "2026-09-18"), "ok")     # day 8
		self.assertEqual(cc.deadline_state(self.ROW, MOFA, "2026-09-19"), "warn")   # day 9
		self.assertEqual(cc.deadline_state(self.ROW, MOFA, "2026-09-22"), "late")   # day 12

	def test_done_values_stop_the_clock(self):
		for status in ("Completed", " not applicable ", "N/A", "Submitted"):
			row = dict(self.ROW, fps_doc_submission=status)
			self.assertEqual(cc.deadline_state(row, DOC, "2026-12-01"), "done")

	def test_no_clock_is_blank(self):
		row = {"ct_date": "2026-09-11", "status": "Pending"}
		self.assertEqual(cc.deadline_state(row, DOC, "2026-12-01"), "")

	def test_fallback_colour_counts_from_clearance(self):
		row = {"clearance_date": "2026-09-10", "status": "Cleared"}
		self.assertEqual(cc.deadline_state(row, DOC, "2026-09-24"), "ok")    # day 14
		self.assertEqual(cc.deadline_state(row, DOC, "2026-09-25"), "warn")  # day 15


class TestRollup(unittest.TestCase):
	def leg(self, ct, cleared, doc=None, status="Cleared"):
		return {"ct_date": ct, "clearance_date": cleared, "status": status,
		        "fps_doc_submission": doc}

	def test_two_leg_job_takes_the_nearest_outstanding(self):
		# FZ transfer declared 06 Jul, import to local declared 09 Jul.
		rows = [self.leg("2026-07-06", "2026-07-06"), self.leg("2026-07-09", "2026-07-09")]
		parent = {"ct_date": "2026-07-06", "clearance_date": "2026-07-09", "status": "Cleared"}
		self.assertEqual(cc.parent_deadline(parent, rows, DOC), d("2026-08-05"))

	def test_done_leg_hands_over_to_the_next(self):
		rows = [self.leg("2026-07-06", "2026-07-06", doc="Completed"),
		        self.leg("2026-07-09", "2026-07-09")]
		parent = {"ct_date": "2026-07-06", "clearance_date": "2026-07-09",
		          "status": "Cleared", "fps_doc_submission": "Pending"}
		self.assertEqual(cc.parent_deadline(parent, rows, DOC), d("2026-08-08"))
		# Coloured by the leg the date came from (declared 09 Jul), not by the
		# parent's own ct_date (06 Jul): 24 Jul is day 15 from 09 Jul.
		self.assertEqual(cc.parent_state(parent, rows, DOC, "2026-07-23"), "ok")
		self.assertEqual(cc.parent_state(parent, rows, DOC, "2026-07-24"), "warn")

	def test_all_done_shows_the_latest(self):
		rows = [self.leg("2026-07-06", "2026-07-06", doc="Completed"),
		        self.leg("2026-07-09", "2026-07-09", doc="Not Applicable")]
		parent = {"fps_doc_submission": "Not Applicable", "status": "Cleared"}
		self.assertEqual(cc.parent_deadline(parent, rows, DOC), d("2026-08-08"))
		self.assertEqual(cc.parent_state(parent, rows, DOC, "2026-12-01"), "done")

	def test_part_cleared_job(self):
		# Leg 1 cleared, leg 2 still pending: leg 1's clock is live on its own.
		rows = [self.leg("2026-09-01", "2026-09-02"),
		        self.leg("2026-09-05", None, status="Pending")]
		parent = {"ct_date": "2026-09-01", "clearance_date": None, "status": "Pending"}
		self.assertEqual(cc.parent_deadline(parent, rows, DOC), d("2026-10-01"))
		self.assertEqual(cc.parent_state(parent, rows, DOC, "2026-09-16"), "warn")

	def test_only_uncleared_rows_outstanding(self):
		rows = [self.leg("2026-09-01", "2026-09-02", doc="Completed"),
		        self.leg("2026-09-05", None, status="Pending")]
		parent = {"status": "Pending", "fps_doc_submission": None}
		self.assertEqual(cc.parent_deadline(parent, rows, DOC), d("2026-10-01"))
		self.assertEqual(cc.parent_state(parent, rows, DOC, "2026-09-30"), "")

	def test_tracker_without_rows_is_its_own_declaration(self):
		parent = {"ct_date": "2026-09-04", "clearance_date": "2026-09-10", "status": "Cleared"}
		self.assertEqual(cc.parent_deadline(parent, [], DOC), d("2026-10-04"))
		self.assertEqual(cc.parent_state(parent, [], DOC, "2026-09-19"), "warn")
		self.assertIsNone(cc.parent_deadline({"ct_date": "2026-09-11", "status": "Pending"}, [], DOC))

	def test_rollup_deadline_mixes_strings_and_dates(self):
		rows = [{"fps_doc_deadline": "2026-10-04"}, {"fps_doc_deadline": date(2026, 9, 30)}]
		self.assertEqual(cc.rollup_deadline(rows, DOC), d("2026-09-30"))
		self.assertIsNone(cc.rollup_deadline([{"fps_doc_deadline": None}], DOC))


if __name__ == "__main__":
	unittest.main(verbosity=2)
