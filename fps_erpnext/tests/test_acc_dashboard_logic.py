"""FPS ACC Dashboard logic -- plain unittest, no frappe needed.

Run from the app root:

    python -m unittest fps_erpnext.tests.test_acc_dashboard_logic -v

Covers the ageing buckets (boundaries and negatives, payments on account netted
by party), per-party net overdue, the VAT quarter (selection, due date, sign,
the voucher-type split, missing accounts, the input VAT check), the cash card's
statement comparison, bank statement open months, paid to suppliers (Pay
entries + paid-at-booking bills, each once), purchases (returns negative), every
insight rule (fires / does not fire), the payload shape (keys, order, rounding),
the drawer, the role gate of fps_erpnext/api/acc_dashboard.py (with a stand-in
frappe), and drift checks against dashboard/src/types/acc.ts.
"""

import json
import os
import re
import sys
import unittest
from datetime import date

if __package__ in (None, ""):
	sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fps_erpnext.api import acc_dashboard_logic as acc  # noqa: E402 -- pure module
from fps_erpnext.api import command_center_logic as cc  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AS_OF = date(2026, 10, 14)   # a Wednesday; ISO week 42 starts Mon 12 Oct
COMPANY = "TEST COMPANY"


def d(text):
	return date.fromisoformat(text)


# --------------------------------------------------------------------------
# Fixture: fictional parties only
# --------------------------------------------------------------------------

def raw_fixture():
	return {
		"Sales Invoice": [
			# due today: not due yet
			{"name": "S1", "docstatus": 1, "posting_date": "2026-09-23", "due_date": "2026-10-14",
			 "outstanding_amount": 1000, "base_net_total": 1000, "base_grand_total": 1050,
			 "customer": "C1", "customer_name": "Key account (sample)", "status": "Unpaid"},
			# 44 days past due
			{"name": "S2", "docstatus": 1, "posting_date": "2026-08-01", "due_date": "2026-08-31",
			 "outstanding_amount": 5000, "base_net_total": 5000, "base_grand_total": 5000,
			 "customer": "C1", "customer_name": "Key account (sample)", "status": "Overdue"},
			# 612 days past due
			{"name": "S3", "docstatus": 1, "posting_date": "2025-01-10", "due_date": "2025-02-09",
			 "outstanding_amount": 2000, "base_net_total": 2000, "base_grand_total": 2000,
			 "customer": "C2", "customer_name": "Second customer (sample)", "status": "Overdue"},
			# credit note, 14 days past its due date: netted into C2 and 0-30
			{"name": "S4", "docstatus": 1, "posting_date": "2026-09-30", "due_date": "2026-09-30",
			 "outstanding_amount": -300, "base_net_total": -300, "base_grand_total": -300,
			 "is_return": 1, "customer": "C2", "customer_name": "Second customer (sample)",
			 "status": "Return"},
			{"name": "S5", "docstatus": 0, "posting_date": "2026-10-01", "base_net_total": 700,
			 "base_grand_total": 700, "outstanding_amount": 700, "fps_job_order": "J9",
			 "customer": "C3", "status": "Draft"},
			{"name": "S6", "docstatus": 1, "posting_date": "2026-10-05", "due_date": "2026-10-05",
			 "outstanding_amount": 0, "base_net_total": 4000, "base_grand_total": 4200,
			 "customer": "C3", "customer_name": "Third customer (sample)", "status": "Paid"},
		],
		"Payment Entry": [
			{"name": "P1", "docstatus": 1, "payment_type": "Receive", "posting_date": "2026-10-02",
			 "base_received_amount": 3000, "unallocated_amount": 0, "party_type": "Customer",
			 "party": "C3", "party_name": "Third customer (sample)",
			 "mode_of_payment": "Bank Transfer", "creation": "2026-10-03 10:00:00"},
			# 1500 on account, 105 days old: netted into C2 and the 91-180 bucket
			{"name": "P2", "docstatus": 1, "payment_type": "Receive", "posting_date": "2026-07-01",
			 "base_received_amount": 2500, "unallocated_amount": 1500, "party_type": "Customer",
			 "party": "C2", "party_name": "Second customer (sample)",
			 "mode_of_payment": "Bank Transfer", "creation": "2026-08-01 10:00:00"},
			{"name": "P3", "docstatus": 1, "payment_type": "Pay", "posting_date": "2026-10-06",
			 "base_paid_amount": 800, "unallocated_amount": 0, "party_type": "Supplier", "party": "SUPX",
			 "party_name": "Supplier X (sample)",
			 "mode_of_payment": "Bank Transfer", "reference_no": "T1", "creation": "2026-10-06 10:00:00"},
			# 400 paid to SUP2 on account, 116 days old
			{"name": "P4", "docstatus": 1, "payment_type": "Pay", "posting_date": "2026-06-20",
			 "base_paid_amount": 400, "unallocated_amount": 400, "party_type": "Supplier", "party": "SUP2",
			 "party_name": "Haulier (sample)", "mode_of_payment": None, "creation": "2026-06-21 10:00:00"},
		],
		"Purchase Invoice": [
			{"name": "B1", "docstatus": 1, "is_paid": 1, "posting_date": "2026-10-07",
			 "base_net_total": 200, "base_grand_total": 210, "outstanding_amount": 0,
			 "cash_bank_account": "ADCB - Current Account - TC",
			 "supplier": "SUP1", "supplier_name": "Card merchant (sample)", "status": "Paid"},
			{"name": "B2", "docstatus": 1, "is_paid": 0, "posting_date": "2026-09-01",
			 "due_date": "2026-09-15", "base_net_total": 10000, "base_grand_total": 10500,
			 "outstanding_amount": 10500, "supplier": "SUP2", "supplier_name": "Haulier (sample)",
			 "status": "Overdue", "bill_no": "H-1"},
			# debit note stored negative, past its due date
			{"name": "B3", "docstatus": 1, "is_paid": 0, "is_return": 1, "posting_date": "2026-09-14",
			 "due_date": "2026-09-14", "base_net_total": -1000, "base_grand_total": -1050,
			 "outstanding_amount": -1050, "supplier": "SUP2", "supplier_name": "Haulier (sample)",
			 "status": "Return"},
			{"name": "B4", "docstatus": 1, "is_paid": 0, "posting_date": "2026-10-10",
			 "due_date": "2026-10-20", "base_net_total": 300, "base_grand_total": 315,
			 "outstanding_amount": 315, "supplier": "SUP3", "supplier_name": "Port (sample)",
			 "status": "Unpaid"},
			{"name": "B5", "docstatus": 0, "posting_date": "2026-10-12", "base_net_total": 94,
			 "base_grand_total": 99, "outstanding_amount": 99, "supplier": "SUP3", "status": "Draft"},
			# a refund on a paid-at-booking bill
			{"name": "B6", "docstatus": 1, "is_paid": 1, "is_return": 1, "posting_date": "2026-10-08",
			 "base_net_total": -48, "base_grand_total": -50, "outstanding_amount": 0,
			 "supplier": "SUP1", "supplier_name": "Card merchant (sample)", "status": "Return"},
		],
		"Supplier": {"SUP1": "Card Merchants", "SUP2": "Services"},
		"Job Order": [{"name": "J1", "docstatus": 1, "fps_stage": "Delivered", "jo_date": "2026-09-01"}],
		"FPS Bank Statement": [
			# ADCB: every month since go-live reconciled -- up to date
			{"name": "FPS-BST-ADCB-2609", "bank_code": "ADCB", "month_code": "2609",
			 "status": "Reconciled", "closing_balance": 7000, "to_date": "2026-09-30"},
			{"name": "FPS-BST-ADCB-2608", "bank_code": "ADCB", "month_code": "2608",
			 "status": "Reconciled", "closing_balance": 6400},
			{"name": "FPS-BST-ADCB-2607", "bank_code": "ADCB", "month_code": "2607",
			 "status": "Reconciled", "closing_balance": 5100},
			{"name": "FPS-BST-ADCB-2606", "bank_code": "ADCB", "month_code": "2606",
			 "status": "Reconciled", "closing_balance": 4000},
			# WIO: Jun reconciled, Jul missing, Aug in progress, Sep missing
			{"name": "FPS-BST-WIO-2606", "bank_code": "WIO", "month_code": "2606",
			 "status": "Reconciled", "closing_balance": 10},
			{"name": "FPS-BST-WIO-2608", "bank_code": "WIO", "month_code": "2608",
			 "status": "In Progress", "closing_balance": 15.4, "to_date": "2026-08-31"},
			# QGEN: Jun only; QGOV: none
			{"name": "FPS-BST-QGEN-2606", "bank_code": "QGEN", "month_code": "2606",
			 "status": "Reconciled", "closing_balance": 2091.34},
		],
		"GL": {
			"cash": [
				{"account": "ADCB - Current Account - TC", "account_name": "ADCB - Current Account",
				 "account_type": "Bank", "debit": 10000, "credit": 2500},
				{"account": "Petty Cash - TC", "account_name": "Petty Cash", "account_type": "Cash",
				 "debit": 100, "credit": 0},
				{"account": "Main Safe - TC", "account_name": "Main Safe", "account_type": "Cash",
				 "debit": 0, "credit": 0},
			],
			"qashio": {"account": "Qashio Card Liability - TC", "debit": 500, "credit": 1200},
			# By voucher type: sales invoices 2099 output; purchase invoices 99 (on the
			# output account, as on the live site) + 500 input; a journal settling an
			# earlier return (1000) is left out of the net.
			"vat_output": {"account": "VAT 5% - TC", "debit": 1099, "credit": 2099, "voucher_types": {
				"Sales Invoice": {"debit": 0, "credit": 2099},
				"Purchase Invoice": {"debit": 99, "credit": 0},
				"Journal Entry": {"debit": 1000, "credit": 0}}},
			"vat_input": {"account": "Sales Taxes Receivables - TC", "debit": 500, "credit": 0,
			              "voucher_types": {"Purchase Invoice": {"debit": 500, "credit": 0}}},
			"vat_purchases": {"count": 3, "net": 20000, "tax": 599},
			# acc_dashboard._read_gl: logic.statement_checks + the GL sums up to to_date.
			"statements": [
				{"bank": "ADCB", "label": "ADCB", "statement": "FPS-BST-ADCB-2609", "to_date": "2026-09-30",
				 "closing_balance": 7000, "account": "ADCB - Current Account - TC",
				 "debit": 9500, "credit": 2500},
				{"bank": "WIO", "label": "WIO", "statement": "FPS-BST-WIO-2608", "to_date": "2026-08-31",
				 "closing_balance": 15.4, "account": None},
			],
		},
	}


def build(period="30d", raw=None, as_of=AS_OF, creatable=("Sales Invoice",)):
	return acc.build_dashboard(period=period, as_of=as_of, generated_at="2026-10-14 09:30:00",
	                           viewer={"full_name": "Test User", "finance": True},
	                           raw=raw if raw is not None else raw_fixture(),
	                           company=COMPANY, creatable=creatable)


def by_key(items):
	return {i["key"]: i for i in items}


# --------------------------------------------------------------------------
# Ageing
# --------------------------------------------------------------------------

class TestAgeing(unittest.TestCase):
	def test_bucket_boundaries(self):
		cases = {None: "not_due", -5: "not_due", 0: "not_due", 1: "0_30", 30: "0_30",
		         31: "31_60", 60: "31_60", 61: "61_90", 90: "61_90", 91: "91_180",
		         180: "91_180", 181: "181_365", 365: "181_365", 366: "over_365", 2000: "over_365"}
		for days, key in cases.items():
			self.assertEqual(acc.bucket_key(days), key, days)

	def test_days_past_due_uses_due_date_then_posting_date(self):
		self.assertEqual(acc.days_past_due({"due_date": "2026-10-14"}, AS_OF), 0)       # due today
		self.assertEqual(acc.days_past_due({"due_date": "2026-10-13"}, AS_OF), 1)
		self.assertEqual(acc.days_past_due({"due_date": "2026-10-20"}, AS_OF), -6)
		self.assertEqual(acc.days_past_due({"posting_date": "2026-09-14"}, AS_OF), 30)
		self.assertIsNone(acc.days_past_due({}, AS_OF))

	def test_receivables_ageing(self):
		a = acc.build_ageing("receivables", raw_fixture()["Sales Invoice"], AS_OF)
		self.assertEqual([b["key"] for b in a["buckets"]], [k for k, _l in acc.AGEING_BUCKETS])
		self.assertEqual([b["label"] for b in a["buckets"]],
		                 ["Not due", "0–30", "31–60", "61–90", "91–180", "181–365", "Over 365"])
		b = by_key(a["buckets"])
		self.assertEqual((b["not_due"]["value"], b["not_due"]["count"]), (1000.0, 1))    # due today
		self.assertEqual((b["0_30"]["value"], b["0_30"]["count"]), (-300.0, 1))         # credit note
		self.assertEqual((b["31_60"]["value"], b["over_365"]["value"]), (5000.0, 2000.0))
		self.assertEqual(b["61_90"], {"key": "61_90", "label": "61–90", "value": 0.0, "count": 0})
		self.assertEqual(a["total"], 7700.0)                     # drafts and paid invoices left out
		self.assertEqual(a["overdue"], 6700.0)                    # past-due buckets, net
		self.assertEqual(sum(x["value"] for x in a["buckets"]), a["total"])
		self.assertEqual(a["route"], "/app/query-report/FPS%20Customer%20Receivables")
		top = a["top"]
		self.assertEqual([p["party"] for p in top], ["C1", "C2"])
		self.assertEqual(top[0], {
			"party": "C1", "label": "Key account (sample)", "value": 6000.0, "overdue": 5000.0,
			"oldest_days": 44, "count": 2,
			"route": "/app/sales-invoice?customer=C1&docstatus=1&outstanding_amount=%5B%22%21%3D%22%2C0%5D"})
		# The credit note is netted into its party: 2000 - 300, oldest still the invoice.
		self.assertEqual((top[1]["value"], top[1]["overdue"], top[1]["oldest_days"], top[1]["count"]),
		                 (1700.0, 1700.0, 612, 2))

	def test_payables_ageing_nets_debit_notes(self):
		a = acc.build_ageing("payables", raw_fixture()["Purchase Invoice"], AS_OF)
		b = by_key(a["buckets"])
		self.assertEqual(b["0_30"]["value"], 9450.0)   # 10500 (29 days) - 1050 (30 days)
		self.assertEqual(b["0_30"]["count"], 2)
		self.assertEqual(b["not_due"]["value"], 315.0)
		self.assertEqual((a["total"], a["overdue"]), (9765.0, 9450.0))
		self.assertEqual(a["route"], "/app/query-report/Accounts%20Payable")
		self.assertEqual(a["top"][0]["party"], "SUP2")
		self.assertTrue(a["top"][0]["route"].startswith("/app/purchase-invoice?supplier=SUP2&docstatus=1"))

	def test_payments_on_account_are_netted_by_party(self):
		raw = raw_fixture()
		a = acc.build_ageing("receivables", raw["Sales Invoice"], AS_OF, raw["Payment Entry"])
		b = by_key(a["buckets"])
		# P2 (1500 unallocated, posted 1 Jul = 105 days) sits in 91-180, negative, counted.
		self.assertEqual((b["91_180"]["value"], b["91_180"]["count"]), (-1500.0, 1))
		self.assertEqual((a["total"], a["overdue"]), (6200.0, 5200.0))
		self.assertEqual(a["caveat"], "Net of AED 1.5K received from customers but not yet allocated to "
		                              "invoices (1 payment), aged by payment date, as in the full report.")
		c2 = by_key([dict(p, key=p["party"]) for p in a["top"]])["C2"]
		# 2000 - 300 credit note - 1500 on account; the count is invoices only.
		self.assertEqual((c2["value"], c2["overdue"], c2["oldest_days"], c2["count"]), (200.0, 200.0, 612, 2))
		# Pay entries never touch receivables, nor a receipt from a non-customer.
		other = [dict(raw["Payment Entry"][1], name="PX", party_type="Supplier")]
		self.assertEqual(acc.build_ageing("receivables", raw["Sales Invoice"], AS_OF, other)["total"], 7700.0)
		self.assertNotIn("caveat", acc.build_ageing("receivables", raw["Sales Invoice"], AS_OF, None))

	def test_customer_paid_ahead_drops_out_of_top(self):
		# The Green Team case of 14 Oct 2026: AED 109,950 received on account
		# against 92,928 of "overdue" invoices -- the customer owes nothing.
		inv = [{"name": "G1", "docstatus": 1, "due_date": "2026-02-16", "outstanding_amount": 45000,
		        "customer": "G", "customer_name": "Recycler (sample)"},
		       {"name": "G2", "docstatus": 1, "due_date": "2026-07-06", "outstanding_amount": 47928,
		        "customer": "G", "customer_name": "Recycler (sample)"},
		       {"name": "K1", "docstatus": 1, "due_date": "2026-09-01", "outstanding_amount": 1000,
		        "customer": "K", "customer_name": "Key account (sample)"}]
		pe = [{"name": n, "docstatus": 1, "payment_type": "Receive", "party_type": "Customer", "party": "G",
		       "party_name": "Recycler (sample)", "posting_date": day, "unallocated_amount": v}
		      for n, day, v in (("R1", "2026-07-20", 100000), ("R2", "2026-09-04", 4950),
		                        ("R3", "2026-09-10", 5000))]
		a = acc.build_ageing("receivables", inv, AS_OF, pe)
		self.assertEqual(a["total"], -16022.0)                    # 93,928 - 109,950
		self.assertEqual([p["party"] for p in a["top"]], ["K"])   # G's net is -17,022
		positions = acc.party_positions("receivables", acc.ageing_documents("receivables", inv, pe), AS_OF)
		self.assertEqual((positions["G"]["value"], positions["G"]["overdue"], positions["G"]["oldest_days"]),
		                 (-17022.0, 0.0, 0))
		card = acc.balance_receivables(inv, pe, AS_OF)
		self.assertEqual(card["context"][0], {"label": "Overdue", "value": "AED 1K"})
		self.assertEqual(card["context"][2], {"label": "Less unallocated receipts", "value": "AED 110K"})

	def test_party_overdue_is_net_of_its_credits_oldest_first(self):
		# The Deepak case: a 24,849.05 overdue bill and a -12,424.95 debit note due today.
		bills = [{"name": "D1", "docstatus": 1, "due_date": "2026-08-01", "outstanding_amount": 24849.05,
		          "supplier": "D", "supplier_name": "Trucker (sample)"},
		         {"name": "D2", "docstatus": 1, "due_date": "2026-10-14", "outstanding_amount": -12424.95,
		          "supplier": "D", "supplier_name": "Trucker (sample)", "is_return": 1},
		         # GULFTAINER: an overdue bill fully reversed by a debit note.
		         {"name": "G1", "docstatus": 1, "due_date": "2026-09-01", "outstanding_amount": 18607,
		          "supplier": "T", "supplier_name": "Terminal (sample)"},
		         {"name": "G2", "docstatus": 1, "due_date": "2026-10-14", "outstanding_amount": -18607,
		          "supplier": "T", "supplier_name": "Terminal (sample)", "is_return": 1},
		         # two overdue bills, a credit smaller than the oldest
		         {"name": "M1", "docstatus": 1, "due_date": "2026-06-01", "outstanding_amount": 300,
		          "supplier": "M", "supplier_name": "Port (sample)"},
		         {"name": "M2", "docstatus": 1, "due_date": "2026-09-01", "outstanding_amount": 500,
		          "supplier": "M", "supplier_name": "Port (sample)"},
		         {"name": "M3", "docstatus": 1, "due_date": "2026-11-01", "outstanding_amount": -200,
		          "supplier": "M", "supplier_name": "Port (sample)"}]
		a = acc.build_ageing("payables", bills, AS_OF)
		top = by_key([dict(p, key=p["party"]) for p in a["top"]])
		self.assertEqual((top["D"]["value"], top["D"]["overdue"], top["D"]["oldest_days"]),
		                 (12424.1, 12424.1, 74))
		self.assertEqual([p["party"] for p in a["top"]], ["D", "M"])            # T nets to zero
		self.assertEqual((top["M"]["overdue"], top["M"]["oldest_days"]), (600.0, 135))   # 300-200 left on M1
		for p in a["top"]:
			self.assertLessEqual(p["overdue"], p["value"])
		card = acc.balance_payables(bills, None, AS_OF)
		self.assertEqual(card["context"][0], {"label": "Overdue", "value": "AED 13K"})   # 12424.10 + 600
		self.assertLessEqual(acc.overdue_net("payables", acc.ageing_documents("payables", bills), AS_OF)[0],
		                     card["value"])

	def test_top_parties_skip_net_credits_and_cap_at_five(self):
		rows = [{"name": "X%d" % i, "docstatus": 1, "due_date": "2026-10-01", "customer": "P%d" % i,
		         "outstanding_amount": 100 * (i + 1)} for i in range(7)]
		rows.append({"name": "N", "docstatus": 1, "due_date": "2026-10-01", "customer": "NEG",
		             "outstanding_amount": -50})
		a = acc.build_ageing("receivables", rows, AS_OF)
		self.assertEqual([p["party"] for p in a["top"]], ["P6", "P5", "P4", "P3", "P2"])
		self.assertEqual(a["top"][0]["label"], "P6")   # no name: the id

	def test_empty(self):
		a = acc.build_ageing("payables", [], AS_OF)
		self.assertEqual((a["total"], a["overdue"], a["top"]), (0.0, 0.0, []))
		self.assertEqual(len(a["buckets"]), 7)


# --------------------------------------------------------------------------
# VAT
# --------------------------------------------------------------------------

class TestVat(unittest.TestCase):
	def test_quarter_selection(self):
		q = acc.vat_quarter(AS_OF)
		self.assertEqual((q.start, q.end, q.due, q.completed, q.window_end),
		                 (d("2026-07-01"), d("2026-09-30"), d("2026-10-28"), True, d("2026-09-30")))
		self.assertEqual(q.label, "Jul–Sep 2026")
		# The due day itself still shows the completed quarter.
		self.assertEqual(acc.vat_quarter("2026-10-28").start, d("2026-07-01"))
		# The day after: the running quarter, to date.
		q = acc.vat_quarter("2026-10-29")
		self.assertEqual((q.start, q.end, q.due, q.completed, q.window_end),
		                 (d("2026-10-01"), d("2026-12-31"), d("2027-01-28"), False, d("2026-10-29")))
		self.assertEqual(q.label, "Oct–Dec 2026")
		# Across the year end.
		q = acc.vat_quarter("2027-01-05")
		self.assertEqual((q.start, q.due, q.label), (d("2026-10-01"), d("2027-01-28"), "Oct–Dec 2026"))
		q = acc.vat_quarter("2027-02-15")
		self.assertEqual((q.start, q.end, q.due, q.label),
		                 (d("2027-01-01"), d("2027-03-31"), d("2027-04-28"), "Jan–Mar 2027"))
		self.assertEqual(acc.vat_quarter("2026-07-28").label, "Apr–Jun 2026")
		self.assertEqual(acc.vat_quarter("2026-07-29").label, "Jul–Sep 2026")

	def test_due_date(self):
		self.assertEqual(acc.vat_due_date(d("2026-09-30")), d("2026-10-28"))
		self.assertEqual(acc.vat_due_date(d("2026-12-31")), d("2027-01-28"))

	def test_card_sign_and_context(self):
		card = acc.balance_vat(raw_fixture()["GL"], COMPANY, AS_OF)
		self.assertEqual(card["label"], "VAT Jul–Sep 2026")
		# output 2099 (sales invoices) - input 599 (purchase invoices, on either account);
		# the 1000 journal is left out.
		self.assertEqual(card["value"], 1500.0)
		self.assertEqual(card["context"], [
			{"label": "Output VAT", "value": "AED 2.1K"},
			{"label": "Input VAT", "value": "AED 599"},
			{"label": "Due date", "value": "28 Oct 2026 · 14 days"},
			{"label": "Other postings, left out", "value": "−AED 1K"}])
		self.assertEqual(card["severity"], "warning")       # 14 days to go
		self.assertEqual(card["caveat"], "From ERPNext postings; the return filed on EmaraTax may differ.")
		route = card["route"]
		self.assertTrue(route.startswith("/app/query-report/General%20Ledger?company=TEST%20COMPANY"))
		self.assertIn("from_date=2026-07-01&to_date=2026-09-30", route)
		self.assertIn("account=%5B%22VAT%205%25%20-%20TC%22%2C%22Sales%20Taxes%20Receivables%20-%20TC%22%5D",
		              route)

	def test_refund_position_is_negative(self):
		# Rows without the voucher-type split fall back to the account.
		gl = {"vat_output": {"account": "O", "debit": 0, "credit": 100},
		      "vat_input": {"account": "I", "debit": 400, "credit": 0}}
		self.assertEqual(acc.balance_vat(gl, COMPANY, AS_OF)["value"], -300.0)

	def test_split_by_voucher_type_live_shape(self):
		# 14 Oct 2026: VAT 5% credit 24,254.95 from 34 sales invoices and debit 99
		# from one purchase invoice; Sales Taxes Receivables never posted to.
		gl = {"vat_output": {"account": "VAT 5% - TC", "debit": 99, "credit": 24254.95, "voucher_types": {
		          "Sales Invoice": {"debit": 0, "credit": 24254.95},
		          "Purchase Invoice": {"debit": 99, "credit": 0}}},
		      "vat_input": {"account": "Sales Taxes Receivables - TC", "debit": 0, "credit": 0,
		                    "voucher_types": {}},
		      "vat_purchases": {"count": 265, "net": 277918.65, "tax": 99}}
		f = acc.vat_figures(gl)
		self.assertEqual((f.output, f.input, f.other, f.net), (24254.95, 99.0, 0.0, 24155.95))
		card = acc.balance_vat(gl, COMPANY, AS_OF)
		self.assertEqual(card["value"], 24155.95)
		self.assertEqual(card["context"][:2], [{"label": "Output VAT", "value": "AED 24.3K"},
		                                       {"label": "Input VAT", "value": "AED 99"}])
		self.assertEqual(card["caveat"],
		                 "Only AED 99 of input VAT is posted in ERPNext for Jul–Sep 2026, on 265 purchase "
		                 "bills worth AED 277.9K before VAT, so the net is close to output VAT alone. Check "
		                 "reclaimable input VAT before filing; the return filed on EmaraTax may differ.")
		i = acc.rule_vat_due(gl, AS_OF, COMPANY)
		self.assertEqual(i["detail"], "Net VAT AED 24.2K from ERPNext postings (output AED 24.3K, input "
		                              "AED 99), due 28 Oct 2026. Input VAT looks incomplete; check it before "
		                              "filing on EmaraTax.")
		# None posted at all; no bills, no claim.
		none = dict(gl, vat_output={"account": "O", "debit": 0, "credit": 100,
		                            "voucher_types": {"Sales Invoice": {"debit": 0, "credit": 100}}})
		self.assertTrue(acc.balance_vat(none, COMPANY, AS_OF)["caveat"].startswith("No input VAT is posted"))
		self.assertEqual(acc.balance_vat(dict(none, vat_purchases={"count": 0, "net": 0}), COMPANY, AS_OF)["caveat"],
		                 acc.VAT_CAVEAT)
		self.assertEqual(acc.balance_vat(dict(none, vat_purchases=None), COMPANY, AS_OF)["caveat"], acc.VAT_CAVEAT)
		# A sales credit note nets output VAT down.
		cn = {"vat_output": {"account": "O", "voucher_types": {"Sales Invoice": {"debit": 30, "credit": 100}}}}
		self.assertEqual(acc.vat_figures(cn).output, 70.0)

	def test_severity_by_days_left(self):
		gl = raw_fixture()["GL"]
		self.assertNotIn("severity", acc.balance_vat(gl, COMPANY, "2026-10-13"))   # 15 days
		due = by_key([dict(c, key=c["label"]) for c in acc.balance_vat(gl, COMPANY, "2026-10-28")["context"]])
		self.assertEqual(due["Due date"]["value"], "28 Oct 2026 · today")
		self.assertEqual(acc.vat_severity(-1), "critical")
		self.assertEqual(acc.vat_severity(0), "warning")
		self.assertEqual(acc.vat_severity(14), "warning")
		self.assertIsNone(acc.vat_severity(15))
		self.assertEqual(acc.days_phrase(1), "1 day")
		self.assertEqual(acc.days_phrase(-3), "3 days late")

	def test_running_quarter_definition(self):
		card = acc.balance_vat(raw_fixture()["GL"], COMPANY, "2026-11-02")
		self.assertEqual(card["label"], "VAT Oct–Dec 2026")
		self.assertIn("so far", card["definition"])
		self.assertNotIn("severity", card)

	def test_missing_accounts(self):
		gl = dict(raw_fixture()["GL"], vat_output=None)
		card = acc.balance_vat(gl, COMPANY, AS_OF)
		self.assertEqual(card["value"], -500.0)
		self.assertEqual([c["label"] for c in card["context"]], ["Input VAT", "Due date"])
		self.assertNotIn("VAT%205", card["route"])
		self.assertIsNone(acc.balance_vat(dict(gl, vat_input=None), COMPANY, AS_OF))
		self.assertIsNone(acc.balance_vat(None, COMPANY, AS_OF))


# --------------------------------------------------------------------------
# Banks
# --------------------------------------------------------------------------

class TestBanks(unittest.TestCase):
	def test_statuses(self):
		banks = acc.bank_statuses(raw_fixture()["FPS Bank Statement"], AS_OF)
		self.assertEqual([b["bank"] for b in banks], ["ADCB", "WIO", "QGEN", "QGOV"])
		self.assertEqual([b["label"] for b in banks],
		                 ["ADCB", "WIO", "Qashio – General", "Qashio – Government"])
		b = by_key([dict(x, key=x["bank"]) for x in banks])
		self.assertEqual({k: v for k, v in b["ADCB"].items() if k != "key"}, {
			"bank": "ADCB", "label": "ADCB", "latest_month": "Sep 2026", "status": "Reconciled",
			"closing_balance": 7000.0, "months_behind": 0,
			"route": "/app/fps-bank-statement/FPS-BST-ADCB-2609"})
		# Highest YYMM wins for the latest statement; every month since go-live counts
		# for months_behind: Jul missing, Aug in progress, Sep missing.
		self.assertEqual((b["WIO"]["latest_month"], b["WIO"]["status"], b["WIO"]["months_behind"],
		                  b["WIO"]["open_months"]),
		                 ("Aug 2026", "In Progress", 3, "Jul missing, Aug in progress, Sep missing"))
		self.assertEqual((b["QGEN"]["latest_month"], b["QGEN"]["months_behind"], b["QGEN"]["open_months"]),
		                 ("Jun 2026", 3, "Jul–Sep missing"))
		self.assertEqual(b["QGOV"]["status"], "Missing")
		self.assertIsNone(b["QGOV"]["latest_month"])
		self.assertIsNone(b["QGOV"]["closing_balance"])
		self.assertEqual((b["QGOV"]["months_behind"], b["QGOV"]["open_months"]), (4, "Jun–Sep missing"))
		self.assertEqual(b["QGOV"]["route"], "/app/fps-bank-statement?bank_code=QGOV")
		self.assertEqual(list(banks[1]), list(acc.BankStatusKeys))
		self.assertNotIn("open_months", banks[0])    # up to date: nothing to name

	def test_gap_behind_the_latest_month(self):
		# The live ADCB of 14 Oct 2026: Jun reconciled, no July, Aug and Sep in
		# progress. It used to read "0 months behind" (only the latest was looked at).
		rows = [{"name": "FPS-BST-ADCB-2606", "status": "Reconciled"},
		        {"name": "FPS-BST-ADCB-2608", "status": "In Progress"},
		        {"name": "FPS-BST-ADCB-2609", "status": "In Progress"}]
		adcb = acc.bank_statuses(rows, AS_OF)[0]
		self.assertEqual((adcb["latest_month"], adcb["status"], adcb["months_behind"], adcb["open_months"]),
		                 ("Sep 2026", "In Progress", 2, "Jul missing, Aug in progress"))
		# Last month still in progress is not open (it is reconciled this month) ...
		self.assertEqual(acc.open_months({d("2026-09-01"): ("X", {"status": "In Progress"})}, AS_OF)[-1],
		                 (d("2026-08-01"), "missing"))
		# ... a missing last month is.
		self.assertEqual(acc.open_months({}, AS_OF)[-1], (d("2026-09-01"), "missing"))

	def test_open_months_text(self):
		months = [(d("2026-11-01"), "in progress"), (d("2026-12-01"), "missing"), (d("2027-01-01"), "missing"),
		          (d("2027-03-01"), "missing")]
		self.assertEqual(acc.open_months_text(months, "2027-04-10"),
		                 "Nov 2026 in progress, Dec 2026–Jan missing, Mar missing")
		self.assertEqual(acc.open_months_text([], AS_OF), "")

	def test_months_behind_edges(self):
		rows = [{"name": "FPS-BST-ADCB-2610", "status": "In Progress"}]   # code and month from the name
		adcb = acc.bank_statuses(rows, AS_OF)[0]
		# The running month's statement does not stand in for the missing ones.
		self.assertEqual((adcb["latest_month"], adcb["months_behind"]), ("Oct 2026", 4))
		self.assertIsNone(adcb["closing_balance"])
		self.assertEqual(acc.bank_statuses([], "2026-06-20")[0]["months_behind"], 0)  # before any was due
		self.assertEqual(acc.bank_statuses([], "2026-07-01")[0]["months_behind"], 1)
		self.assertEqual(acc.bank_statuses([{"name": "FPS-BST-ADCB-2609", "status": "Odd"}], AS_OF)[0]["status"],
		                 "In Progress")
		self.assertEqual(acc.months_between(d("2026-06-01"), d("2027-01-01")), 7)
		self.assertIsNone(acc.statement_month({"name": "FPS-BST-ADCB-26X9"}))
		# Two statements for one month: the higher name decides that month.
		two = [{"name": "FPS-BST-ADCB-%s" % m, "status": "Reconciled"} for m in ("2606", "2607", "2608")]
		two += [{"name": "FPS-BST-ADCB-2609", "status": "Reconciled"},
		        {"name": "FPS-BST-ADCB-2609-B", "bank_code": "ADCB", "month_code": "2609", "status": "In Progress"}]
		self.assertEqual(acc.bank_statuses(two, AS_OF)[0]["status"], "In Progress")

	def test_banks_behind(self):
		hits = acc.banks_behind(raw_fixture()["FPS Bank Statement"], AS_OF)
		self.assertEqual([b["bank"] for b in hits], ["WIO", "QGEN", "QGOV"])
		# Every month reconciled but last month's still in progress: not "behind".
		rows = [{"name": "FPS-BST-%s-%s" % (c, m), "status": "Reconciled"}
		        for c in ("ADCB", "WIO", "QGEN", "QGOV") for m in ("2606", "2607", "2608")]
		rows += [{"name": "FPS-BST-%s-2609" % c, "status": "In Progress"} for c in ("ADCB", "WIO", "QGEN", "QGOV")]
		self.assertEqual(acc.banks_behind(rows, AS_OF), [])


# --------------------------------------------------------------------------
# Paid out, purchases
# --------------------------------------------------------------------------

class TestPoints(unittest.TestCase):
	def test_paid_out_counts_each_document_once(self):
		raw = raw_fixture()
		points = acc.points_paid_out(raw["Payment Entry"] + [dict(raw["Payment Entry"][2])],  # P3 twice
		                             raw["Purchase Invoice"])
		self.assertEqual(sorted((p["doctype"], p["name"], p["value"]) for p in points), [
			("Payment Entry", "P3", 800.0), ("Payment Entry", "P4", 400.0),
			("Purchase Invoice", "B1", 210.0), ("Purchase Invoice", "B6", -50.0)])
		dims = {p["name"]: (p["dim"], p["dim_label"]) for p in points}
		self.assertEqual(dims["P3"], ("Bank Transfer", "Bank Transfer"))
		self.assertEqual(dims["P4"], (cc.NOT_SET_KEY, cc.NOT_SET_LABEL))
		# Paid at booking: the account it was paid from (every live one is ADCB, not
		# a card); with neither a mode nor an account, plain "Paid at booking".
		self.assertEqual(dims["B1"], ("ADCB - Current Account - TC", "ADCB (paid at booking)"))
		self.assertEqual(dims["B6"], (acc.PAID_AT_BOOKING_KEY, "Paid at booking"))
		self.assertEqual(acc.paid_at_booking_dim({"mode_of_payment": "Wire", "cash_bank_account": "X - Y"}),
		                 ("Wire", "Wire"))
		self.assertEqual(acc.account_short("Petty Cash - Administration - FPS"), "Petty Cash")
		# Receipts, unpaid bills and drafts are never money that left.
		self.assertFalse([p for p in points if p["name"] in ("P1", "P2", "B2", "B3", "B4", "B5")])

	def test_paid_out_ignores_unsubmitted(self):
		pe = [{"name": "X", "docstatus": 0, "payment_type": "Pay", "posting_date": "2026-10-01",
		       "base_paid_amount": 5}]
		pi = [{"name": "Y", "docstatus": 2, "is_paid": 1, "posting_date": "2026-10-01", "base_grand_total": 5}]
		self.assertEqual(acc.points_paid_out(pe, pi), [])

	def test_purchases_returns_are_negative(self):
		raw = raw_fixture()
		bills = raw["Purchase Invoice"] + [
			# a debit note stored with a positive total still counts negative
			{"name": "B7", "docstatus": 1, "is_return": 1, "posting_date": "2026-10-09",
			 "base_net_total": 25, "supplier": "SUP9"}]
		points = {p["name"]: p for p in acc.points_purchases(bills, raw["Supplier"])}
		self.assertEqual({k: p["value"] for k, p in points.items()},
		                 {"B1": 200.0, "B2": 10000.0, "B3": -1000.0, "B4": 300.0, "B6": -48.0, "B7": -25.0})
		self.assertNotIn("B5", points)                                   # draft
		self.assertEqual(points["B2"]["dim_label"], "Services")
		self.assertEqual(points["B4"]["dim"], cc.NOT_SET_KEY)            # supplier with no group
		self.assertEqual(points["B3"]["subtitle"], "Debit note")
		self.assertEqual(points["B1"]["subtitle"], "Paid at booking")
		self.assertEqual(points["B2"]["subtitle"], "Bill H-1")

	def test_supplier_groups_as_rows(self):
		self.assertEqual(acc._supplier_groups({"Supplier": [{"name": "S", "supplier_group": "G"}]}), {"S": "G"})
		self.assertEqual(acc._supplier_groups({}), {})


# --------------------------------------------------------------------------
# KPIs and balances
# --------------------------------------------------------------------------

class TestKpisAndBalances(unittest.TestCase):
	def test_kpis(self):
		k = by_key(build()["kpis"])
		self.assertEqual(list(k), list(acc.KPI_ORDER))
		# S1 1000 + S4 credit note -300 + S6 4000; the draft S5 is left out.
		self.assertEqual((k["invoiced"]["label"], k["invoiced"]["value"]), ("Invoiced (net)", 4700.0))
		self.assertEqual(k["invoiced"]["new_doctype"], "Sales Invoice")
		self.assertEqual(k["collected"]["value"], 3000.0)
		# Outstanding AR is the receivables card's figure (net of the 1500 on account).
		self.assertEqual(k["collected"]["context"][0], {"label": "Outstanding AR", "value": "AED 6.2K"})
		self.assertEqual(k["invoiced"]["context"][0], {"label": "Drafts waiting", "value": "1 · AED 700"})
		self.assertEqual(k["paid_out"]["label"], "Paid to suppliers")
		self.assertEqual(k["paid_out"]["value"], 960.0)            # 800 + 210 - 50
		self.assertEqual(k["paid_out"]["context"], [{"label": "Supplier payments", "value": "AED 800"},
		                                            {"label": "Paid at booking", "value": "AED 160"}])
		self.assertEqual(k["purchases"]["value"], 452.0)           # 200 + 300 - 48 (B3 is before the window)
		self.assertEqual(k["purchases"]["context"], [{"label": "Bills", "value": "2"},
		                                            {"label": "Drafts waiting", "value": "1 · AED 99"}])
		for key in acc.KPI_ORDER:
			self.assertTrue(k[key]["finance"], key)
			self.assertEqual((k[key]["unit"], k[key]["currency"]), ("currency", "AED"), key)
			self.assertEqual(list(k[key]), [f for f in cc.KpiKeys if f in k[key]], key)
			self.assertEqual(len(k[key]["series"]), 30)
		self.assertEqual((k["paid_out"]["good_direction"], k["purchases"]["good_direction"]), ("none", "none"))
		self.assertNotIn("new_doctype", k["paid_out"])
		self.assertNotIn("new_doctype", k["purchases"])
		self.assertEqual(k["paid_out"]["route"], "/app/payment-entry?payment_type=Pay&docstatus=1")
		self.assertIn("WIO, Qashio – General and Qashio – Government are not reconciled up to Sep 2026",
		              k["paid_out"]["caveat"])
		self.assertNotIn("new_doctype", by_key(build(creatable=())["kpis"])["invoiced"])

	def test_paid_out_caveat_only_when_statements_are_open(self):
		raw = raw_fixture()
		raw["FPS Bank Statement"] = [{"name": "FPS-BST-%s-%s" % (c, m), "status": "Reconciled"}
		                             for c in ("ADCB", "WIO", "QGEN", "QGOV")
		                             for m in ("2606", "2607", "2608", "2609")]
		self.assertNotIn("caveat", by_key(build(raw=raw)["kpis"])["paid_out"])
		# One month missing in the middle is enough to say so.
		raw["FPS Bank Statement"] = [r for r in raw["FPS Bank Statement"] if r["name"] != "FPS-BST-WIO-2607"]
		self.assertIn("WIO is not reconciled", by_key(build(raw=raw)["kpis"])["paid_out"]["caveat"])
		del raw["FPS Bank Statement"]
		self.assertNotIn("caveat", by_key(build(raw=raw)["kpis"])["paid_out"])

	def test_balances(self):
		b = by_key(build()["balances"])
		self.assertEqual(list(b), list(acc.BALANCE_ORDER))
		r = b["receivables"]
		self.assertEqual(r["value"], 6200.0)                       # 7700 of invoices - 1500 on account
		self.assertEqual(r["context"], [
			# C1 5000 + C2's 2000 less its credits (300 note, 1500 on account)
			{"label": "Overdue", "value": "AED 5.2K"},
			{"label": "Open invoices", "value": "4"},
			{"label": "Less unallocated receipts", "value": "AED 1.5K"},
			{"label": "Drafts waiting", "value": "1 · AED 700"}])
		self.assertEqual(r["severity"], "warning")                 # 5200 / 6200 >= 50%
		self.assertEqual(r["route"], "/app/query-report/FPS%20Customer%20Receivables")
		p = b["payables"]
		self.assertEqual(p["value"], 9365.0)                       # 9765 of bills - 400 on account
		self.assertEqual(p["context"], [
			{"label": "Overdue", "value": "AED 9.1K"},              # 10500 - 1050 note - 400 on account
			{"label": "Open bills", "value": "3"},
			{"label": "Less unallocated payments", "value": "AED 400"},
			{"label": "Draft bills", "value": "1"}])
		self.assertNotIn("severity", p)
		c = b["cash"]
		self.assertEqual((c["label"], c["value"]), ("Cash & bank", 7600.0))
		self.assertEqual(c["context"], [
			{"label": "ADCB - Current Account", "value": "AED 7.5K"},
			{"label": "Latest bank statements", "value": "AED 7K"},   # ADCB 7000 + WIO 15.40
			{"label": "Qashio card liability", "value": "AED 700"},
			{"label": "Petty Cash", "value": "AED 100"}])             # the zero account is left out
		self.assertNotIn("severity", c)                            # ADCB's books match its statement
		self.assertEqual(c["caveat"], "Book balances from ERPNext, not bank statements. WIO (statement "
		                              "AED 15) has no ledger account, so it is not in this figure.")
		self.assertTrue(c["route"].startswith("/app/query-report/General%20Ledger?company=TEST%20COMPANY"
		                                      "&to_date=2026-10-14&account=%5B"))
		self.assertTrue(c["route"].endswith("&group_by=Group%20by%20Account"))
		for card in b.values():
			self.assertEqual(list(card), [f for f in acc.BalanceKeys if f in card])
			self.assertLessEqual(len(card["context"]), 4)

	def test_receivables_severity_threshold(self):
		rows = [{"name": "A", "docstatus": 1, "due_date": "2026-10-01", "outstanding_amount": 49.99},
		        {"name": "B", "docstatus": 1, "due_date": "2026-10-30", "outstanding_amount": 50.01}]
		self.assertNotIn("severity", acc.balance_receivables(rows, None, AS_OF))
		rows[0]["outstanding_amount"] = 50.01
		self.assertEqual(acc.balance_receivables(rows, None, AS_OF)["severity"], "warning")
		# No Payment Entry access: the unallocated line is left out, never "AED 0".
		self.assertNotIn("Less unallocated receipts",
		                 [c["label"] for c in acc.balance_receivables(rows, None, AS_OF)["context"]])

	def test_drafts_line_leaves_duplicates_out(self):
		inv = raw_fixture()["Sales Invoice"]
		inv[5]["fps_job_order"] = "J6"
		inv.append({"name": "S7", "docstatus": 0, "posting_date": "2026-10-09", "fps_job_order": "J6",
		            "base_grand_total": 4200, "customer": "C3"})   # repeats S6
		line = {"label": "Drafts excl. 1 duplicate", "value": "1 · AED 700"}
		self.assertEqual(acc.sales_drafts_line(inv), line)
		self.assertIn(line, acc.balance_receivables(inv, None, AS_OF)["context"])
		raw = raw_fixture()
		raw["Sales Invoice"] = inv
		self.assertEqual(by_key(build(raw=raw)["kpis"])["invoiced"]["context"][0],
		                 {"label": "Drafts excl. 1 duplicate", "value": "1 · AED 700"})

	def test_cash_lines(self):
		gl = {"cash": [{"account": "A%d" % i, "account_name": "Acc %d" % i, "debit": 10 * i, "credit": 0}
		               for i in range(1, 6)] + [{"account": "Neg", "account_name": "Overdrawn", "debit": 0,
		                                         "credit": 45}],
		      "qashio": {"account": "Q", "debit": 5, "credit": 5}}
		c = acc.balance_cash(gl, COMPANY, AS_OF)
		self.assertEqual(c["value"], 105.0)
		self.assertEqual([x["label"] for x in c["context"]], ["Acc 5", "Overdrawn", "Acc 4"])   # by |balance|
		self.assertEqual(c["context"][1]["value"], "−AED 45")
		self.assertEqual(c["caveat"], acc.CASH_CAVEAT)               # no statements to compare with
		# A debit balance on the Qashio card account: top-ups not matched to bills.
		gl["qashio"] = {"account": "Q", "debit": 151372.97, "credit": 111866.87}
		self.assertIn({"label": "Qashio top-ups unmatched", "value": "AED 39.5K"},
		              acc.balance_cash(gl, COMPANY, AS_OF)["context"])
		self.assertIsNone(acc.balance_cash({}, COMPANY, AS_OF))
		self.assertIsNone(acc.balance_cash(None, COMPANY, AS_OF))

	def test_cash_gap_with_the_statement_is_critical(self):
		# The live ADCB of 14 Oct 2026: books 5.66M above the 30 Sep statement.
		gl = {"cash": [{"account": "ADCB - Current Account - TC", "account_name": "ADCB - Current Account",
		                "debit": 6794262.30, "credit": 770542.68}],
		      "statements": [
		          {"bank": "ADCB", "label": "ADCB", "statement": "FPS-BST-ADCB-2609", "to_date": "2026-09-30",
		           "closing_balance": 366430.77, "account": "ADCB - Current Account - TC",
		           "debit": 6700000.00, "credit": 676281.62},
		          {"bank": "WIO", "label": "WIO", "statement": "FPS-BST-WIO-2609", "to_date": "2026-09-30",
		           "closing_balance": 1995.21, "account": None}]}
		c = acc.balance_cash(gl, COMPANY, AS_OF)
		self.assertEqual(c["value"], 6023719.62)                  # still the book balance (spec)
		self.assertEqual(c["severity"], "critical")
		self.assertEqual(c["context"], [
			{"label": "ADCB - Current Account", "value": "AED 6M"},
			{"label": "Bank statements, 30 Sep", "value": "AED 368.4K"},
			{"label": "Books above statements", "value": "AED 5.7M"}])
		self.assertEqual(c["caveat"], "ERPNext's ADCB balance on 30 Sep is AED 5.7M above its bank statement "
		                              "(AED 366.4K), so this figure is not the bank position until the ledger "
		                              "is reconciled. WIO (statement AED 2K) has no ledger account, so it is "
		                              "not in this figure.")
		# Within 1 % (and over AED 100 of noise allowed): no claim.
		gl["statements"][0].update(debit=370000.00, credit=1000.00)
		self.assertNotIn("severity", acc.balance_cash(gl, COMPANY, AS_OF))
		gl["statements"][0].update(debit=362000.00, credit=0)        # 4,430.77 below: over 1 %
		low = acc.balance_cash(gl, COMPANY, AS_OF)
		self.assertEqual(low["severity"], "critical")
		self.assertIn({"label": "Books below statements", "value": "AED 4.4K"}, low["context"])

	def test_statement_checks(self):
		accounts = [{"name": "ADCB - Current Account - TC", "account_name": "ADCB - Current Account"},
		            {"name": "Petty Cash - TC", "account_name": "Petty Cash"},
		            {"name": "Wiofund - TC", "account_name": "Wiofund"}]   # not the word WIO
		checks = acc.statement_checks(accounts, raw_fixture()["FPS Bank Statement"])
		self.assertEqual(checks, [
			{"bank": "ADCB", "label": "ADCB", "statement": "FPS-BST-ADCB-2609", "to_date": "2026-09-30",
			 "closing_balance": 7000.0, "account": "ADCB - Current Account - TC"},
			{"bank": "WIO", "label": "WIO", "statement": "FPS-BST-WIO-2608", "to_date": "2026-08-31",
			 "closing_balance": 15.4, "account": None}])
		# Two ADCB accounts: which one the statement belongs to is not known -- left out.
		two = accounts + [{"name": "ADCB - Savings - TC", "account_name": "ADCB - Savings"}]
		self.assertEqual([c["bank"] for c in acc.statement_checks(two, raw_fixture()["FPS Bank Statement"])],
		                 ["WIO"])
		# No to_date: the month end; no closing balance: nothing to compare; cards never.
		rows = [{"name": "FPS-BST-ADCB-2602", "status": "In Progress", "closing_balance": 1},
		        {"name": "FPS-BST-WIO-2609", "status": "In Progress"},
		        {"name": "FPS-BST-QGEN-2609", "status": "Reconciled", "closing_balance": 5}]
		self.assertEqual([(c["bank"], c["to_date"]) for c in acc.statement_checks(accounts, rows)],
		                 [("ADCB", "2026-02-28")])
		self.assertEqual(acc.statement_checks(accounts, None), [])


# --------------------------------------------------------------------------
# Insights
# --------------------------------------------------------------------------

class TestInsights(unittest.TestCase):
	def test_vat_due(self):
		gl = raw_fixture()["GL"]
		i = acc.rule_vat_due(gl, AS_OF, COMPANY)
		self.assertEqual((i["id"], i["severity"], i["title"]),
		                 ("vat_due", "warning", "VAT return Jul–Sep 2026 due in 14 days"))
		self.assertEqual(i["detail"], "Net VAT AED 1.5K from ERPNext postings (output AED 2.1K, input AED 599), "
		                              "due 28 Oct 2026. File and pay on EmaraTax; the return filed there may "
		                              "differ.")
		self.assertIn("General%20Ledger", i["route"])
		self.assertIsNone(acc.rule_vat_due(gl, "2026-10-13", COMPANY))      # 15 days
		self.assertEqual(acc.rule_vat_due(gl, "2026-10-28", COMPANY)["title"],
		                 "VAT return Jul–Sep 2026 is due today")
		self.assertEqual(acc.rule_vat_due(gl, "2026-10-27", COMPANY)["title"],
		                 "VAT return Jul–Sep 2026 due in 1 day")
		self.assertIsNone(acc.rule_vat_due(None, AS_OF))
		self.assertIsNone(acc.rule_vat_due({"vat_output": None, "vat_input": None}, AS_OF))

	def test_unallocated_receipts(self):
		pe = raw_fixture()["Payment Entry"]
		i = acc.rule_unallocated_receipts(pe)
		self.assertEqual((i["id"], i["severity"], i["title"]),
		                 ("unallocated_receipts", "warning", "AED 1.5K received but not matched to invoices"))
		self.assertEqual(i["detail"], "1 customer receipt carries an unallocated amount (Second customer "
		                              "(sample), P2). Until it is allocated, the invoices it pays still read as "
		                              "outstanding.")
		self.assertEqual(i["route"], "/app/payment-entry?payment_type=Receive&docstatus=1"
		                             "&unallocated_amount=%5B%22%3E%22%2C0%5D")
		more = pe + [dict(pe[1], name="P9", unallocated_amount=100000, party_name="Big (sample)")]
		self.assertEqual(acc.rule_unallocated_receipts(more)["detail"],
		                 "2 customer receipts carry an unallocated amount; the largest is AED 100K from "
		                 "Big (sample) (P9). Until they are allocated, the invoices they pay still read as "
		                 "outstanding.")
		# Supplier payments and fully allocated receipts never fire it.
		self.assertIsNone(acc.rule_unallocated_receipts([r for r in pe if r["name"] != "P2"]))
		self.assertIsNone(acc.rule_unallocated_receipts([]))

	def test_supplier_overdue(self):
		raw = raw_fixture()
		bills = raw["Purchase Invoice"]
		# B2 10500 past due, less SUP2's debit note B3 (1050) -- net per supplier.
		i = acc.rule_supplier_overdue(bills, AS_OF)
		self.assertEqual((i["id"], i["severity"], i["title"]),
		                 ("supplier_overdue", "info", "AED 9.5K owed to 1 supplier is past due"))
		self.assertEqual(i["detail"], "1 bill; the oldest was due 15 Sep 2026 (B2). Net of debit notes and "
		                              "payments on account.")
		self.assertIn("due_date=%5B%22between%22%2C%5B%222000-01-01%22%2C%222026-10-13%22%5D%5D", i["route"])
		# ... and less the 400 paid to SUP2 on account (P4).
		self.assertEqual(acc.rule_supplier_overdue(bills, AS_OF, raw["Payment Entry"])["title"],
		                 "AED 9.1K owed to 1 supplier is past due")
		big = bills + [{"name": "B8", "docstatus": 1, "due_date": "2026-08-01", "outstanding_amount": 45000,
		                "supplier": "SUP8", "supplier_name": "Customs (sample)"}]
		w = acc.rule_supplier_overdue(big, AS_OF)
		self.assertEqual((w["severity"], w["title"]), ("warning", "AED 54.5K owed to 2 suppliers is past due"))
		self.assertEqual(w["detail"], "2 bills; the oldest was due 1 Aug 2026 (B8). Largest: Customs (sample), "
		                              "AED 45K. Net of debit notes and payments on account.")
		# A debit note that reverses the only overdue bill clears it (GULFTAINER, 14 Oct 2026).
		self.assertIsNone(acc.rule_supplier_overdue(
			[{"name": "G1", "docstatus": 1, "due_date": "2026-09-01", "outstanding_amount": 18607, "supplier": "T"},
			 {"name": "G2", "docstatus": 1, "due_date": "2026-10-14", "outstanding_amount": -18607, "supplier": "T"}],
			AS_OF))
		# Exactly AED 50K is still info.
		edge = [{"name": "E", "docstatus": 1, "due_date": "2026-10-01", "outstanding_amount": 50000, "supplier": "S"}]
		self.assertEqual(acc.rule_supplier_overdue(edge, AS_OF)["severity"], "info")
		# Due today, debit notes and drafts are not past due.
		self.assertIsNone(acc.rule_supplier_overdue(
			[{"name": "T", "docstatus": 1, "due_date": "2026-10-14", "outstanding_amount": 9, "supplier": "S"},
			 {"name": "D", "docstatus": 0, "due_date": "2026-01-01", "outstanding_amount": 9, "supplier": "S"},
			 {"name": "N", "docstatus": 1, "due_date": "2026-01-01", "outstanding_amount": -9, "supplier": "S"}],
			AS_OF))

	def test_bank_statements_behind(self):
		i = acc.rule_bank_statements_behind(raw_fixture()["FPS Bank Statement"], AS_OF)
		self.assertEqual((i["id"], i["severity"]), ("bank_statements_behind", "warning"))
		self.assertEqual(i["title"], "Bank statements behind for WIO, Qashio – General and Qashio – Government")
		self.assertEqual(i["detail"], "WIO: Jul missing, Aug in progress, Sep missing; Qashio – General: Jul–Sep "
		                              "missing; Qashio – Government: Jun–Sep missing. Last month was Sep 2026.")
		self.assertEqual(i["route"], "/app/fps-bank-statement")
		months = ("2606", "2607", "2608", "2609")
		one = acc.rule_bank_statements_behind(
			[{"name": "FPS-BST-%s-%s" % (c, m), "status": "Reconciled"} for c in ("ADCB", "WIO", "QGEN")
			 for m in months], AS_OF)
		self.assertEqual(one["title"], "Bank statement behind for Qashio – Government")
		up_to_date = [{"name": "FPS-BST-%s-%s" % (c, m), "status": "Reconciled" if m != "2609" else "In Progress"}
		              for c in ("ADCB", "WIO", "QGEN", "QGOV") for m in months]
		self.assertIsNone(acc.rule_bank_statements_behind(up_to_date, AS_OF))
		# The live gap: ADCB's July is missing behind an in-progress September.
		live = [{"name": n, "status": st} for n, st in (
			("FPS-BST-ADCB-2606", "Reconciled"), ("FPS-BST-ADCB-2608", "In Progress"),
			("FPS-BST-ADCB-2609", "In Progress"), ("FPS-BST-WIO-2606", "Reconciled"),
			("FPS-BST-WIO-2609", "In Progress"), ("FPS-BST-QGEN-2606", "Reconciled"),
			("FPS-BST-QGOV-2606", "Reconciled"))]
		i = acc.rule_bank_statements_behind(live, AS_OF)
		self.assertEqual(i["title"], "Bank statements behind for ADCB, WIO, Qashio – General and Qashio – Government")
		self.assertTrue(i["detail"].startswith("ADCB: Jul missing, Aug in progress; WIO: Jul–Aug missing; "))
		self.assertLessEqual(len(i["detail"]), cc.DETAIL_MAX)

	def test_sales_invoice_drafts(self):
		inv = raw_fixture()["Sales Invoice"]
		i = acc.rule_sales_invoice_drafts(inv, AS_OF)
		self.assertEqual((i["id"], i["severity"], i["title"]),
		                 ("sales_invoice_drafts", "info", "1 sales invoice in draft, worth AED 700"))
		self.assertEqual(i["detail"], "The oldest, S5, is dated 1 Oct (13 days ago). Drafts are not in "
		                              "receivables or VAT until they are submitted.")
		self.assertEqual(i["route"], "/app/sales-invoice?docstatus=0")
		self.assertIsNone(acc.rule_sales_invoice_drafts(inv, AS_OF, stall_fired=True))
		self.assertIsNone(acc.rule_sales_invoice_drafts([r for r in inv if r["docstatus"] == 1], AS_OF))
		# Every draft repeats a submitted invoice: duplicate_drafts already says it.
		dup_only = [r for r in inv if r["name"] != "S5"] + [
			{"name": "S9", "docstatus": 0, "posting_date": "2026-10-10", "fps_job_order": "J1",
			 "base_grand_total": 4200},
			dict(inv[5], fps_job_order="J1")]
		self.assertIsNone(acc.rule_sales_invoice_drafts(dup_only, AS_OF))
		# Some duplicates: said once, in the detail.
		mixed = acc.rule_sales_invoice_drafts(dup_only + [inv[4]], AS_OF)
		self.assertEqual(mixed["title"], "2 sales invoices in draft, worth AED 4.9K")
		self.assertTrue(mixed["detail"].endswith(" 1 of them repeats a submitted invoice."))

	def test_reused_rules_are_reranked(self):
		self.assertEqual(sorted(acc._RULE.values()), list(range(1, len(acc._RULE) + 1)))
		stall = acc._ranked(cc.rule_invoicing_stall(d("2026-09-01"), AS_OF, 1, 100, 120))
		self.assertEqual(stall["_rule"], acc._RULE["invoicing_stall"])
		self.assertIsNone(acc._ranked(None))

	def test_dashboard_insights(self):
		p = build()
		ids = [i["id"] for i in p["insights"]]
		self.assertEqual(ids, ["vat_due", "unallocated_receipts", "bank_statements_behind",
		                       "supplier_overdue", "delivered_not_invoiced", "sales_invoice_drafts"])
		for i in p["insights"]:
			self.assertLessEqual(len(i["title"]), cc.TITLE_MAX)
			self.assertLessEqual(len(i["detail"]), cc.DETAIL_MAX)
			self.assertFalse([k for k in i if k.startswith("_")])
			self.assertTrue(i.get("route") or i.get("metric_key"), i["id"])
		sev = [cc.SEVERITY_ORDER.index(i["severity"]) for i in p["insights"]]
		self.assertEqual(sev, sorted(sev))

	def test_dashboard_insights_with_money_rules(self):
		raw = raw_fixture()
		raw["Sales Invoice"] += [
			# a draft repeating S6 (same Job Order, same grand total) ...
			{"name": "S7", "docstatus": 0, "posting_date": "2026-10-09", "fps_job_order": "J6",
			 "base_grand_total": 4200, "customer": "C3"},
			# ... and the old book: 90+ days past due is now over 40%
			{"name": "S8", "docstatus": 1, "posting_date": "2024-01-01", "due_date": "2024-01-31",
			 "outstanding_amount": 9000, "customer": "C2"}]
		raw["Sales Invoice"][5]["fps_job_order"] = "J6"
		items = build(raw=raw)["insights"]
		ids = [i["id"] for i in items]
		self.assertEqual(ids[:2], ["vat_due", "duplicate_drafts"])
		self.assertEqual(len(ids), cc.INSIGHT_CAP)
		# AR ageing is net of C2's credits: S8 9000 - 1800 (note + receipt on account),
		# applied oldest first, and S3 2000 are over 90 days, of 15.2K net receivables.
		ar = by_key([dict(i, key=i["id"]) for i in items])["ar_ageing"]
		self.assertEqual(ar["title"], "AED 9.2K of AED 15.2K outstanding is over 90 days past due")
		self.assertEqual(ar["detail"], "All of it was posted before 1 Jan 2026.")
		# ar_ageing (info) outranks the later info rules once the cap is reached.
		full = acc.build_insights(raw, as_of=AS_OF, lookback=120, company=COMPANY)
		self.assertNotIn("sales_invoice_drafts", [i["id"] for i in full])
		# An invoicing stall replaces the drafts note (it names the same drafts).
		stalled = raw_fixture()
		stalled["Sales Invoice"][5]["posting_date"] = "2026-09-01"
		stalled["Sales Invoice"][0]["posting_date"] = "2026-09-01"
		items = acc.build_insights(stalled, as_of=AS_OF, lookback=120)
		ids = [i["id"] for i in items]
		self.assertIn("invoicing_stall", ids)
		self.assertNotIn("sales_invoice_drafts", ids)


# --------------------------------------------------------------------------
# Payload
# --------------------------------------------------------------------------

class TestPayload(unittest.TestCase):
	def test_shape_and_order(self):
		p = build()
		self.assertEqual(list(p), list(acc.AccPayloadKeys))
		self.assertEqual((p["as_of"], p["period"], p["period_label"], p["compare_label"]),
		                 ("2026-10-14", "30d", "Last 30 days", "vs previous 30 days"))
		self.assertEqual(p["viewer"], {"full_name": "Test User"})   # no finance flag on this page
		self.assertEqual([k["key"] for k in p["kpis"]], list(acc.KPI_ORDER))
		self.assertEqual([b["key"] for b in p["balances"]], list(acc.BALANCE_ORDER))
		self.assertEqual([a["key"] for a in p["ageing"]], ["receivables", "payables"])
		self.assertEqual([b["bank"] for b in p["banks"]], ["ADCB", "WIO", "QGEN", "QGOV"])
		self.assertEqual(p["ageing"][0]["total"], by_key(p["balances"])["receivables"]["value"])
		self.assertEqual(p["ageing"][1]["total"], by_key(p["balances"])["payables"]["value"])
		self.assertEqual(list(p["ageing"][0]), ["key", "label", "currency", "total", "overdue", "buckets",
		                                         "top", "route", "caveat"])   # caveat: payments on account
		json.dumps(p)   # plain JSON all the way down

	def test_one_overdue_figure_per_side(self):
		# The card's "Overdue" line and the ageing panel's Overdue are the same
		# per-party net figure (14 Oct 2026: 617.5K vs 600.5K read as an error).
		p = build()
		cards = by_key(p["balances"])
		for ageing in p["ageing"]:
			line = next(c for c in cards[ageing["key"]]["context"] if c["label"] == "Overdue")
			self.assertEqual(line["value"], acc.cc.format_money_compact(ageing["overdue"]))
			self.assertGreaterEqual(ageing["overdue"], 0)

	def test_trend(self):
		t = by_key(build()["trend"])
		self.assertEqual(list(t), ["billing", "cashflow"])
		self.assertEqual([(s["key"], s["label"], s["slot"]) for s in t["billing"]["series"]],
		                 [("invoiced", "Invoiced (net)", 1), ("collected", "Collected", 2)])
		self.assertEqual([(s["key"], s["label"], s["slot"]) for s in t["cashflow"]["series"]],
		                 [("collected", "Collected", 1), ("paid_out", "Paid to suppliers", 2)])
		for mode in t.values():
			self.assertEqual((mode["unit"], mode["currency"], mode["finance"]), ("currency", "AED", True))
			self.assertEqual(len(mode["points"]), 12)
			self.assertEqual(mode["points"][-1]["week_start"], "2026-10-12")
			self.assertTrue(mode["points"][-1]["partial"])
		# Week of 5 Oct: S6 4000 invoiced, P3 800 + B1 210 + B6 -50 paid out.
		week = t["cashflow"]["points"][-2]
		self.assertEqual(week["week_start"], "2026-10-05")
		self.assertEqual(week["values"], {"collected": 0.0, "paid_out": 960.0})
		self.assertEqual(t["billing"]["points"][-2]["values"]["invoiced"], 4000.0)

	def test_rounding(self):
		raw = raw_fixture()
		raw["Payment Entry"].append({"name": "P7", "docstatus": 1, "payment_type": "Pay",
		                             "posting_date": "2026-10-13", "base_paid_amount": 0.1})
		raw["Payment Entry"].append({"name": "P8", "docstatus": 1, "payment_type": "Pay",
		                             "posting_date": "2026-10-13", "base_paid_amount": 0.2})
		raw["GL"]["cash"][0]["debit"] = 10000.005
		p = build(raw=raw)
		self.assertEqual(by_key(p["kpis"])["paid_out"]["value"], 960.3)
		self.assertEqual(by_key(p["balances"])["cash"]["value"], 7600.01)

	def test_unreadable_sources_are_left_out(self):
		raw = raw_fixture()
		for key in ("Purchase Invoice", "GL", "FPS Bank Statement"):
			del raw[key]
		p = build(raw=raw)
		self.assertEqual([k["key"] for k in p["kpis"]], ["invoiced", "collected"])
		self.assertEqual([b["key"] for b in p["balances"]], ["receivables"])
		self.assertEqual([a["key"] for a in p["ageing"]], ["receivables"])
		self.assertEqual(p["banks"], [])
		self.assertEqual([s["key"] for s in by_key(p["trend"])["cashflow"]["series"]], ["collected"])
		ids = [i["id"] for i in p["insights"]]
		for gone in ("vat_due", "supplier_overdue", "bank_statements_behind"):
			self.assertNotIn(gone, ids)
		empty = build(raw={})
		self.assertEqual((empty["kpis"], empty["balances"], empty["ageing"], empty["banks"],
		                  empty["trend"], empty["insights"]), ([], [], [], [], [], []))

	def test_periods(self):
		for period, n in (("7d", 7), ("30d", 30), ("90d", 13)):
			for k in build(period=period)["kpis"]:
				self.assertEqual(len(k["series"]), n, (period, k["key"]))
		with self.assertRaises(ValueError):
			build(period="1y")


class TestMetricDetail(unittest.TestCase):
	def test_paid_out(self):
		m = acc.build_metric_detail("paid_out", raw_fixture(), period="30d", as_of=AS_OF)
		self.assertEqual(list(m), [k for k in cc.MetricDetailKeys if k in m])
		self.assertEqual((m["label"], m["unit"], m["currency"], m["value"]),
		                 ("Paid to suppliers", "currency", "AED", 960.0))
		self.assertEqual(m["dimension_label"], "Paid via")
		self.assertEqual({o["label"] for o in m["dimension_options"]},
		                 {"Bank Transfer", "ADCB (paid at booking)", "Paid at booking"})
		self.assertEqual(m["breakdown"]["title"], "Top payees")
		self.assertEqual([r["name"] for r in m["records"]], ["B6", "B1", "P3"])
		self.assertEqual(m["records"][1]["route"], "/app/purchase-invoice/B1")
		self.assertEqual(m["records"][2]["route"], "/app/payment-entry/P3")
		self.assertEqual(m["records"][0]["value"], -50.0)
		self.assertEqual([a["key"] for a in m["actions"]], ["open_list", "open_paid_bills"])
		self.assertFalse([a for a in m["actions"] if a["kind"] == "new_doc"])
		self.assertIn("caveat", m)
		adcb = acc.build_metric_detail("paid_out", raw_fixture(), period="30d", as_of=AS_OF,
		                               dimension="ADCB - Current Account - TC")
		self.assertEqual((adcb["dimension"], adcb["value"]), ("ADCB - Current Account - TC", 210.0))
		bare = acc.build_metric_detail("paid_out", raw_fixture(), period="30d", as_of=AS_OF,
		                               dimension=acc.PAID_AT_BOOKING_KEY)
		self.assertEqual(bare["value"], -50.0)
		self.assertIsNone(acc.build_metric_detail("paid_out", raw_fixture(), period="30d", as_of=AS_OF,
		                                          dimension="Nope")["dimension"])

	def test_purchases(self):
		m = acc.build_metric_detail("purchases", raw_fixture(), period="30d", as_of=AS_OF)
		self.assertEqual((m["value"], m["dimension_label"], m["breakdown"]["title"]),
		                 (452.0, "Supplier group", "Top suppliers"))
		self.assertEqual([a["key"] for a in m["actions"]], ["open_list", "open_report"])
		self.assertEqual(m["actions"][1]["route"], "/app/query-report/Accounts%20Payable")
		self.assertNotIn("caveat", m)

	def test_invoiced_and_collected_are_the_ops_drawers(self):
		inv = acc.build_metric_detail("invoiced", raw_fixture(), period="30d", as_of=AS_OF, can_create=True)
		self.assertEqual([a["key"] for a in inv["actions"]], ["open_list", "new", "open_report"])
		self.assertEqual(inv["records"][0]["value"], 4000.0)
		col = acc.build_metric_detail("collected", raw_fixture(), period="30d", as_of=AS_OF)
		self.assertEqual(col["value"], 3000.0)                      # Pay entries are not receipts
		self.assertEqual([r["name"] for r in col["records"]], ["P1"])
		self.assertEqual([a["key"] for a in col["actions"]], ["open_list"])

	def test_unknown_key(self):
		with self.assertRaises(KeyError):
			acc.build_metric_detail("jobs", raw_fixture(), period="30d", as_of=AS_OF)

	def test_empty(self):
		m = acc.build_metric_detail("purchases", {}, period="7d", as_of=AS_OF)
		self.assertEqual((m["value"], m["previous"], m["breakdown"], m["records"]), (0.0, None, None, []))
		json.dumps(m)


# --------------------------------------------------------------------------
# The API module: role gate, cache, reads (stand-in frappe)
# --------------------------------------------------------------------------

class TestApiGate(unittest.TestCase):
	def setUp(self):
		from fps_erpnext.tests import fake_frappe
		if fake_frappe.REAL_FRAPPE:
			self.skipTest("a real frappe is importable; covered by the bench test run")
		self.ff = fake_frappe

	def fake(self, user, roles, **kw):
		raw = raw_fixture()
		rows = {dt: raw[dt] for dt in ("Sales Invoice", "Payment Entry", "Purchase Invoice", "Job Order",
		                               "FPS Bank Statement")}
		rows["Supplier"] = [{"name": k, "supplier_group": v} for k, v in raw["Supplier"].items()]
		rows["Account"] = [{"name": r["account"], "account_name": r["account_name"],
		                    "account_type": r["account_type"]} for r in raw["GL"]["cash"]]
		return self.ff.FakeFrappe(user=user, roles=roles, rows=rows, today=AS_OF.isoformat(),
		                          company=COMPANY, creatable={"Sales Invoice"},
		                          accounts={"VAT 5%": "VAT 5% - TC",
		                                    "Sales Taxes Receivables": "Sales Taxes Receivables - TC",
		                                    "Qashio Card Liability": "Qashio Card Liability - TC"}, **kw)

	def test_refuses_without_accounts_manager_before_reading_anything(self):
		for user, roles in (("ops@example.com", ["FPS Operations", "Desk User"]),
		                    ("hello@example.com", ["FPS Viewer", "FPS Customs Access"]),
		                    # Accounts User or System Manager alone is not enough
		                    ("clerk@example.com", ["Accounts User", "System Manager"])):
			fake = self.fake(user, roles)
			with fake.installed() as mods:
				api = mods["acc_dashboard"]
				with self.assertRaises(self.ff.PermissionError):
					api.get_dashboard("30d")
				with self.assertRaises(self.ff.PermissionError):
					api.get_metric_detail("paid_out", "30d")
				# Even a bad period or key answers "not permitted", not a validation error.
				with self.assertRaises(self.ff.PermissionError):
					api.get_dashboard("1y")
			self.assertEqual([c for c in fake.calls if c[0] != "only_for"], [], user)

	def test_accounts_manager_and_administrator_pass(self):
		for user, roles in (("agam@example.com", ["Accounts Manager"]), ("Administrator", [])):
			fake = self.fake(user, roles)
			with fake.installed() as mods:
				api = mods["acc_dashboard"]
				gl_calls = []

				def gl_sums(company, accounts, to_date, from_date=None, by_voucher_type=False):
					gl_calls.append((tuple(accounts), str(to_date), str(from_date) if from_date else None,
					                 by_voucher_type))
					out = {a: {"debit": 10, "credit": 0} for a in accounts}
					if by_voucher_type:
						for s in out.values():
							s["voucher_types"] = {"Sales Invoice": {"debit": 0, "credit": 10},
							                      "Purchase Invoice": {"debit": 10, "credit": 0}}
					return out

				api._gl_sums = gl_sums
				api._purchase_totals = lambda company, from_date, to_date: {"count": 2, "net": 100, "tax": 5}
				p = api.get_dashboard("30d")
				again = api.get_dashboard("30d")
			self.assertEqual(fake.calls[0], ("only_for", "Accounts Manager"))
			# The VAT sums by voucher type for the quarter; ADCB at its statement's date.
			self.assertIn((("VAT 5% - TC", "Sales Taxes Receivables - TC"), "2026-09-30", "2026-07-01", True),
			              gl_calls)
			self.assertIn((("ADCB - Current Account - TC",), "2026-09-30", None, False), gl_calls)
			cash = by_key(p["balances"])["cash"]
			self.assertIn("WIO (statement AED 15) has no ledger account", cash["caveat"])
			self.assertEqual([c["label"] for c in by_key(p["balances"])["vat"]["context"][:2]],
			                 ["Output VAT", "Input VAT"])
			self.assertEqual([k["key"] for k in p["kpis"]], list(acc.KPI_ORDER))
			self.assertEqual([b["key"] for b in p["balances"]], list(acc.BALANCE_ORDER))
			self.assertEqual(p["viewer"], {"full_name": "Test User"})
			self.assertIs(again, p)    # served from the cache the second time
			self.assertIn(("cache_set", "fps_acc_dashboard:v1:dashboard:30d", user), fake.calls)
			self.assertEqual(sum(1 for c in fake.calls if c[0] == "cache_set"), 1)

	def test_metric_detail(self):
		fake = self.fake("abhishek@example.com", ["Accounts Manager"])
		with fake.installed() as mods:
			api = mods["acc_dashboard"]
			m = api.get_metric_detail("purchases", "30d")
			with self.assertRaises(self.ff.ValidationError):
				api.get_metric_detail("jobs", "30d")
			with self.assertRaises(self.ff.ValidationError):
				api.get_metric_detail("paid_out", "1y")
		self.assertEqual(m["value"], 452.0)
		read = fake.read_doctypes()
		self.assertIn("Purchase Invoice", read)
		self.assertNotIn("Sales Invoice", read)      # a drawer reads only what it needs

	def test_unreadable_doctype_is_left_out(self):
		fake = self.fake("agam@example.com", ["Accounts Manager"],
		                 readable={"Sales Invoice", "Payment Entry", "Purchase Invoice", "Supplier", "Job Order"})
		with fake.installed() as mods:
			p = mods["acc_dashboard"].get_dashboard("7d")
			# Without the statements paid_out only loses its caveat; without
			# Payment Entry it has no points at all, and the drawer is refused.
			self.assertNotIn("caveat", mods["acc_dashboard"].get_metric_detail("paid_out", "7d"))
			fake.readable.discard("Payment Entry")
			with self.assertRaises(self.ff.PermissionError):
				mods["acc_dashboard"].get_metric_detail("paid_out", "7d")
		self.assertEqual(p["banks"], [])
		self.assertEqual([b["key"] for b in p["balances"]], ["receivables", "payables"])
		self.assertNotIn("FPS Bank Statement", fake.read_doctypes())


# --------------------------------------------------------------------------
# Drift: dashboard/src/types/acc.ts
# --------------------------------------------------------------------------

class TestDrift(unittest.TestCase):
	def source(self, name):
		path = os.path.join(ROOT, "dashboard", "src", "types", name)
		if not os.path.exists(path):
			self.skipTest("dashboard sources not shipped with this copy")
		with open(path, encoding="utf-8") as fh:
			return fh.read()

	def ts_fields(self, interface):
		body = re.search(r"export interface %s \{(.*?)\n\}" % interface, self.source("acc.ts"), re.S).group(1)
		body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
		return [m.group(1) for m in re.finditer(r"^\s*(\w+)\??:", body, re.M)]

	def ts_union(self, name, file="acc.ts"):
		union = re.search(r"export type %s =(.*?);" % name, self.source(file), re.S).group(1)
		return re.findall(r'"(\w+)"', union)

	def test_payload_keys(self):
		self.assertEqual(self.ts_fields("AccPayload"), list(acc.AccPayloadKeys))

	def test_balance_card_keys(self):
		self.assertEqual(self.ts_fields("BalanceCard"), list(acc.BalanceKeys))

	def test_bank_status_keys(self):
		self.assertEqual(self.ts_fields("BankStatus"), list(acc.BankStatusKeys))

	def test_ageing_keys(self):
		a = acc.build_ageing("receivables", raw_fixture()["Sales Invoice"], AS_OF)
		self.assertEqual([f for f in self.ts_fields("Ageing") if f in a], list(a))
		self.assertEqual(set(self.ts_fields("Ageing")) - set(a), {"caveat"})
		self.assertEqual(self.ts_fields("AgeingBucket"), list(a["buckets"][0]))
		self.assertEqual(self.ts_fields("AgeingParty"), list(a["top"][0]))

	def test_unions(self):
		self.assertEqual(self.ts_union("AccKpiKey"), list(acc.KPI_ORDER))
		self.assertEqual(self.ts_union("BalanceKey"), list(acc.BALANCE_ORDER))
		self.assertEqual(self.ts_union("AgeingBucketKey"), [k for k, _l in acc.AGEING_BUCKETS])
		# dashboard.ts carries the ACC keys and trend modes too.
		self.assertTrue(set(acc.KPI_ORDER) <= set(self.ts_union("KpiKey", "dashboard.ts")))
		modes = re.search(r"export type TrendModeKey =(.*?);", self.source("dashboard.ts"), re.S).group(1)
		self.assertTrue({"billing", "cashflow"} <= set(re.findall(r'"(\w+)"', modes)))

	def test_fields_cover_the_reads(self):
		for dt in ("Sales Invoice", "Payment Entry", "Purchase Invoice", "Supplier", "Job Order",
		           "FPS Bank Statement"):
			self.assertIn("name", acc.FIELDS[dt], dt)
		for f in ("payment_type", "base_paid_amount", "base_received_amount", "unallocated_amount",
		          "posting_date", "creation"):
			self.assertIn(f, acc.FIELDS["Payment Entry"])


if __name__ == "__main__":
	unittest.main(verbosity=2)
