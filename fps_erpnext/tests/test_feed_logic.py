"""FPS Live Feed logic -- plain unittest, no frappe needed.

Run from the app root:

    python -m unittest fps_erpnext.tests.test_feed_logic -v

Covers the slots (07:59, 08:00, 11:59, 20:00, 23:30, 00:10 and the labels the
page shows), the "since the previous update" window, NEW marking (a new key, a
changed fingerprint, an unchanged item, the first snapshot, a rebuild in the
same slot), ordering and caps, the allow-list gate and the page / meta / build
entry points of fps_erpnext/api/feed.py (with the stand-in frappe of
fake_frappe.py), "Open in ERPNext" filtering, money formatting, the snapshot's
JSON round trip, and drift checks against hooks.py, snapshot.schema.md and the
fictional fixture docs/live_feed/sample_snapshot.json.

The fixture below is fictional: every party is "... (sample)". It also builds
docs/live_feed/sample_snapshot.json -- regenerate it with

    python -m fps_erpnext.tests.test_feed_logic --write-sample
"""

import ast
import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta

if __package__ in (None, ""):
	sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fps_erpnext.api import acc_dashboard_logic as acc  # noqa: E402 -- pure module
from fps_erpnext.api import command_center_logic as cc  # noqa: E402
from fps_erpnext.api import feed_logic as feed  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SAMPLE_PATH = os.path.join(ROOT, "docs", "live_feed", "sample_snapshot.json")
SCHEMA_PATH = os.path.join(ROOT, "docs", "live_feed", "snapshot.schema.md")
NOW = datetime(2026, 10, 14, 12, 0, 5)       # the 12:00 run, five seconds late
AS_OF = NOW.date()
COMPANY = "SAMPLE COMPANY"


def dt(text):
	return datetime.strptime(text, "%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------
# Fixture: fictional parties only
# --------------------------------------------------------------------------

HARBOUR, DESERT, GULF, OLDPORT = ("Harbour Trading (sample)", "Desert Metals (sample)",
                                  "Gulf Cooling (sample)", "Old Port Logistics (sample)")
HAULIER, AGENT, PORT, CARD = ("Line Haul Carrier (sample)", "Shipping Line Agent (sample)",
                              "Port Services (sample)", "Card Merchant (sample)")


def ops_raw():
	jobs = [
		{"name": "FPS/JO/2610/058", "jo_date": "2026-10-14", "docstatus": 0, "fps_stage": "New",
		 "fps_category": "FF - Freight Forwarding", "eta": "2026-10-30", "customer": HARBOUR,
		 "customer_name": HARBOUR, "client_reference_no": "PO 4410"},
		{"name": "FPS/JO/2610/057", "jo_date": "2026-10-14", "docstatus": 0, "fps_stage": "In Progress",
		 "fps_category": "CC - Customs Clearance", "customer": DESERT, "customer_name": DESERT},
		{"name": "FPS/JO/2610/052", "jo_date": "2026-10-09", "docstatus": 0, "fps_stage": "In Progress",
		 "fps_category": "CC - Customs Clearance", "eta": "2026-10-10", "customer": DESERT,
		 "customer_name": DESERT},
		{"name": "FPS/JO/2610/047", "jo_date": "2026-10-05", "docstatus": 0, "fps_stage": "Delivered",
		 "fps_category": "LT - Local Land Transport", "customer": GULF, "customer_name": GULF},
		{"name": "FPS/JO/2609/041", "jo_date": "2026-09-01", "docstatus": 1, "fps_stage": "In Progress",
		 "fps_category": "CC - Customs Clearance", "eta": "2026-09-05", "customer": HARBOUR,
		 "customer_name": HARBOUR},
		{"name": "FPS/JO/2609/030", "jo_date": "2026-09-03", "docstatus": 1, "fps_stage": "Invoiced",
		 "fps_category": "FF - Freight Forwarding", "customer": GULF, "customer_name": GULF},
		{"name": "FPS/JO/2607/012", "jo_date": "2026-07-15", "docstatus": 1, "fps_stage": "Completed",
		 "fps_category": "CC - Customs Clearance", "customer": OLDPORT, "customer_name": OLDPORT},
	]
	stage = {j["name"]: (j["customer_name"], j["fps_stage"]) for j in jobs}

	def upd(name, parent, update_date, milestone, line, source, creation):
		customer, job_stage = stage[parent]
		return {"name": name, "parent": parent, "update_date": update_date, "milestone": milestone,
		        "status_line": line, "event_type": source, "source": source, "creation": creation,
		        "job_customer": customer, "job_stage": job_stage}

	return {
		"FPS Enquiry": [
			{"name": "FPS/ENQ/2610/031", "enquiry_date": "2026-10-13", "status": "Open",
			 "enquiry_source": "WhatsApp", "client_name": HARBOUR, "movement_type": "Sea"},
			{"name": "FPS/ENQ/2610/030", "enquiry_date": "2026-10-12", "status": "Quoted",
			 "enquiry_source": "Email", "client_name": DESERT, "movement_type": "Land"},
			{"name": "FPS/ENQ/2610/029", "enquiry_date": "2026-10-09", "status": "Quoted",
			 "enquiry_source": "Email", "client_name": GULF},
			{"name": "FPS/ENQ/2610/028", "enquiry_date": "2026-10-08", "status": "Open",
			 "enquiry_source": "WhatsApp", "client_name": HARBOUR},
			{"name": "FPS/ENQ/2610/027", "enquiry_date": "2026-10-02", "status": "Quoted",
			 "enquiry_source": "Phone", "client_name": OLDPORT},
			{"name": "FPS/ENQ/2607/001", "enquiry_date": "2026-07-21", "status": "Quoted",
			 "enquiry_source": "Email", "client_name": OLDPORT},
		],
		"Quotation": [
			{"name": "FPS/QT/2610/0%02d" % (40 + i), "transaction_date": "2026-10-%02d" % (2 + 2 * i),
			 "docstatus": 0, "status": "Draft", "base_grand_total": 1000 + 250 * i,
			 "customer_name": (HARBOUR, DESERT, GULF, OLDPORT, HARBOUR)[i], "party_name": None,
			 "quotation_to": "Customer"}
			for i in range(5)
		] + [
			{"name": "FPS/QT/2610/039", "transaction_date": "2026-10-01", "docstatus": 1, "status": "Open",
			 "base_grand_total": 8800, "customer_name": DESERT, "quotation_to": "Customer"},
		],
		"Customs Tracker": [
			{"name": "FPS/CT/2609/041", "ct_date": "2026-09-01", "clearance_date": "2026-09-02",
			 "status": "Cleared", "customer": HARBOUR, "job_order": "FPS/JO/2609/041",
			 "boe_number": "101018000001", "fps_clearance_type": "Import to Local from ROW",
			 "fps_doc_submission": "Pending", "fps_doc_deadline": "2026-10-01",
			 "fps_mofa_status": "Completed", "fps_mofa_deadline": "2026-09-16"},
			{"name": "FPS/CT/2610/052", "ct_date": "2026-10-13", "clearance_date": "2026-10-14",
			 "status": "Cleared", "customer": DESERT, "job_order": "FPS/JO/2610/052",
			 "boe_number": "101018000077", "fps_clearance_type": "FZ to Local",
			 "fps_doc_submission": "Pending", "fps_doc_deadline": "2026-11-12",
			 "fps_mofa_status": "Pending", "fps_mofa_deadline": "2026-10-28"},
			{"name": "FPS/CT/2610/049", "ct_date": "2026-10-05", "clearance_date": "2026-10-06",
			 "status": "Cleared", "customer": GULF, "job_order": "FPS/JO/2610/047",
			 "fps_doc_submission": "Submitted"},
			{"name": "FPS/CT/2610/055", "ct_date": "2026-10-13", "status": "In Process",
			 "customer": HARBOUR, "job_order": "FPS/JO/2610/058"},
		],
		"Proof of Delivery": [
			{"name": "FPS/POD/2610/022", "pod_date": "2026-10-14", "docstatus": 0,
			 "delivery_status": "Pending", "customer": DESERT, "job_order": "FPS/JO/2610/052"},
			{"name": "FPS/POD/2610/021", "pod_date": "2026-10-13", "docstatus": 0,
			 "delivery_status": "Delivered", "customer": GULF, "job_order": "FPS/JO/2610/047",
			 "movement_type": "Local", "client_reference_no": "PO 7781"},
			{"name": "FPS/POD/2610/020", "pod_date": "2026-10-10", "docstatus": 1,
			 "delivery_status": "Delivered", "customer": GULF, "job_order": "FPS/JO/2609/030"},
		],
		"Job Order": jobs,
		"FPS Job Update": [
			upd("u-0101", "FPS/JO/2610/058", "2026-10-14", "OPENED", "Job opened", "System",
			    "2026-10-14 10:12:40.120000"),
			upd("u-0102", "FPS/JO/2610/058", "2026-10-14", "", "Customs entry opened", "System",
			    "2026-10-14 10:12:40.140000"),
			upd("u-0100", "FPS/JO/2610/052", "2026-10-14", "CLEARED", "Customs released - BOE 101018000077",
			    "System", "2026-10-14 11:20:02.000000"),
			upd("u-0099", "FPS/JO/2610/057", "2026-10-14", "OPENED", "Job opened", "System",
			    "2026-10-14 09:05:11.200000"),
			upd("u-0097", "FPS/JO/2609/041", "2026-10-13", "HOLD",
			    "On hold: waiting for the consignee's documents", "Manual", "2026-10-13 16:45:00.000000"),
			upd("u-0096", "FPS/JO/2610/047", "2026-10-13", "DELIVERED", "Delivered to the consignee",
			    "Claude", "2026-10-13 15:02:10.000000"),
			upd("u-0095", "FPS/JO/2610/052", "2026-10-13", "BOE", "BOE 101018000077 filed (FZ to Local)",
			    "System", "2026-10-13 11:10:00.000000"),
			upd("u-0050", "FPS/JO/2607/012", "2026-07-20", "CLOSED", "Closed", "Backfill",
			    "2026-09-11 21:00:00.000000"),
		],
	}


STAGES = {
	"tiles": [
		{"key": "enquiry", "label": "Enquiry", "note": "open", "count": 6, "route": "/app/fps-enquiry?status=Open"},
		{"key": "quotation", "label": "Quotation", "note": "open", "count": 4, "route": "/app/quotation?status=Open"},
		{"key": "job_order", "label": "Job Order", "note": "open", "count": 5, "route": "/app/job-order?x=open"},
		{"key": "customs", "label": "Customs Tracker", "note": "not cleared", "count": 1,
		 "route": "/app/customs-tracker?x=open"},
		{"key": "in_progress", "label": "In Progress", "note": "jobs", "count": 3,
		 "route": "/app/job-order?fps_stage=In%20Progress"},
		{"key": "delivered", "label": "Delivered", "note": "awaiting invoice", "count": 1,
		 "route": "/app/job-order?fps_stage=Delivered"},
	],
	"footnotes": ["2 past ETA", "2 with no ETA", "21 PODs on file"],
}


def acc_raw():
	return {
		"Sales Invoice": [
			{"name": "FPS/INV/2610/071", "docstatus": 1, "posting_date": "2026-10-13", "due_date": "2026-11-12",
			 "outstanding_amount": 13125, "base_net_total": 12500, "base_grand_total": 13125,
			 "customer": HARBOUR, "customer_name": HARBOUR, "fps_job_order": "FPS/JO/2609/041",
			 "status": "Unpaid", "is_return": 0, "fps_is_payment_request": 0},
			{"name": "FPS/INV/2610/069", "docstatus": 1, "posting_date": "2026-10-08", "due_date": "2026-10-08",
			 "outstanding_amount": 0, "base_net_total": 15000, "base_grand_total": 15750,
			 "customer": DESERT, "customer_name": DESERT, "status": "Paid"},
			{"name": "FPS/INV/2609/066", "docstatus": 1, "posting_date": "2026-09-10", "due_date": "2026-09-25",
			 "outstanding_amount": 42000, "base_net_total": 40000, "base_grand_total": 42000,
			 "customer": HARBOUR, "customer_name": HARBOUR, "status": "Overdue"},
			{"name": "FPS/INV/2608/044", "docstatus": 1, "posting_date": "2026-08-15", "due_date": "2026-08-30",
			 "outstanding_amount": 9800, "base_net_total": 9333.33, "base_grand_total": 9800,
			 "customer": GULF, "customer_name": GULF, "status": "Overdue"},
			{"name": "FPS/INV/2607/031", "docstatus": 1, "posting_date": "2026-06-20", "due_date": "2026-07-05",
			 "outstanding_amount": 18350.5, "base_net_total": 17476.67, "base_grand_total": 18350.5,
			 "customer": DESERT, "customer_name": DESERT, "status": "Overdue"},
			{"name": "FPF/INV/25/0112", "docstatus": 1, "posting_date": "2025-03-02", "due_date": "2025-04-01",
			 "outstanding_amount": 4250, "base_net_total": 4250, "base_grand_total": 4250,
			 "customer": OLDPORT, "customer_name": OLDPORT, "status": "Overdue"},
			{"name": "FPS/INV/2610/072", "docstatus": 0, "posting_date": "2026-10-14",
			 "outstanding_amount": 7600, "base_net_total": 7238.1, "base_grand_total": 7600,
			 "customer": GULF, "customer_name": GULF, "fps_job_order": "FPS/JO/2610/047", "status": "Draft"},
		],
		"Payment Entry": [
			{"name": "FPS/PR/2610/034", "docstatus": 1, "payment_type": "Receive", "posting_date": "2026-10-14",
			 "base_received_amount": 15750, "unallocated_amount": 0, "party_type": "Customer",
			 "party": DESERT, "party_name": DESERT, "mode_of_payment": "Bank Transfer",
			 "reference_no": "TT-88412", "creation": "2026-10-14 11:05:33"},
			{"name": "FPS/PR/2609/029", "docstatus": 1, "payment_type": "Receive", "posting_date": "2026-09-21",
			 "base_received_amount": 9000, "unallocated_amount": 9000, "party_type": "Customer",
			 "party": HARBOUR, "party_name": HARBOUR, "mode_of_payment": "Cheque",
			 "creation": "2026-09-22 10:00:00"},
			{"name": "FPS/PR/2607/010", "docstatus": 1, "payment_type": "Receive", "posting_date": "2026-07-03",
			 "base_received_amount": 5000, "unallocated_amount": 0, "party_type": "Customer",
			 "party": OLDPORT, "party_name": OLDPORT, "creation": "2026-07-30 10:00:00"},
			{"name": "FPS/PV/2610/015", "docstatus": 1, "payment_type": "Pay", "posting_date": "2026-10-12",
			 "base_paid_amount": 3200, "unallocated_amount": 0, "party_type": "Supplier",
			 "party": HAULIER, "party_name": HAULIER, "mode_of_payment": "Bank Transfer",
			 "creation": "2026-10-12 15:00:00"},
		],
		"Purchase Invoice": [
			{"name": "FPS/PI/2609/120", "docstatus": 1, "is_paid": 0, "posting_date": "2026-09-05",
			 "due_date": "2026-09-20", "base_net_total": 13523.81, "base_grand_total": 14200,
			 "outstanding_amount": 14200, "supplier": HAULIER, "supplier_name": HAULIER,
			 "status": "Overdue", "bill_no": "LH-2291"},
			{"name": "FPS/PI/2609/131", "docstatus": 1, "is_paid": 0, "posting_date": "2026-09-16",
			 "due_date": "2026-10-01", "base_net_total": 6000, "base_grand_total": 6300,
			 "outstanding_amount": 6300, "supplier": AGENT, "supplier_name": AGENT, "status": "Overdue"},
			{"name": "FPS/PI/2610/140", "docstatus": 1, "is_paid": 0, "posting_date": "2026-10-05",
			 "due_date": "2026-10-20", "base_net_total": 1500, "base_grand_total": 1575,
			 "outstanding_amount": 1575, "supplier": PORT, "supplier_name": PORT, "status": "Unpaid"},
			{"name": "FPS/PI/2610/141", "docstatus": 1, "is_paid": 1, "posting_date": "2026-10-09",
			 "base_net_total": 400, "base_grand_total": 420, "outstanding_amount": 0,
			 "cash_bank_account": "ADCB - Current Account - SC", "supplier": CARD, "supplier_name": CARD,
			 "status": "Paid"},
			{"name": "FPS/PI/2610/142", "docstatus": 0, "posting_date": "2026-10-13", "base_net_total": 951.43,
			 "base_grand_total": 999, "outstanding_amount": 999, "supplier": PORT, "status": "Draft"},
		],
		"Supplier": {HAULIER: "Transporters", AGENT: "Shipping Lines", PORT: "Services", CARD: "Card Merchants"},
		"Job Order": [{"name": "FPS/JO/2610/047", "docstatus": 0, "fps_stage": "Delivered", "jo_date": "2026-10-05"}],
		"FPS Bank Statement": [
			{"name": "FPS-BST-ADCB-2609", "bank_code": "ADCB", "month_code": "2609", "status": "In Progress",
			 "closing_balance": 380000, "to_date": "2026-09-30"},
			{"name": "FPS-BST-ADCB-2608", "bank_code": "ADCB", "month_code": "2608", "status": "Reconciled",
			 "closing_balance": 341000},
			{"name": "FPS-BST-ADCB-2607", "bank_code": "ADCB", "month_code": "2607", "status": "Reconciled",
			 "closing_balance": 298000},
			{"name": "FPS-BST-ADCB-2606", "bank_code": "ADCB", "month_code": "2606", "status": "Reconciled",
			 "closing_balance": 251000},
			{"name": "FPS-BST-WIO-2606", "bank_code": "WIO", "month_code": "2606", "status": "Reconciled",
			 "closing_balance": 2100},
			{"name": "FPS-BST-QGEN-2606", "bank_code": "QGEN", "month_code": "2606", "status": "Reconciled",
			 "closing_balance": 1800},
		],
		"GL": {
			"cash": [
				{"account": "ADCB - Current Account - SC", "account_name": "ADCB - Current Account",
				 "account_type": "Bank", "debit": 512000, "credit": 120000},
				{"account": "Petty Cash - SC", "account_name": "Petty Cash", "account_type": "Cash",
				 "debit": 1500, "credit": 900},
			],
			"qashio": {"account": "Qashio Card Liability - SC", "debit": 2000, "credit": 3500},
			"vat_output": {"account": "VAT 5% - SC", "debit": 0, "credit": 6200, "voucher_types": {
				"Sales Invoice": {"debit": 0, "credit": 6200}}},
			"vat_input": {"account": "Sales Taxes Receivables - SC", "debit": 1100, "credit": 0,
			              "voucher_types": {"Purchase Invoice": {"debit": 1100, "credit": 0}}},
			"vat_purchases": {"count": 14, "net": 64000, "tax": 1100},
			"statements": [
				{"bank": "ADCB", "label": "ADCB", "statement": "FPS-BST-ADCB-2609", "to_date": "2026-09-30",
				 "closing_balance": 380000, "account": "ADCB - Current Account - SC",
				 "debit": 501000, "credit": 110000},
			],
		},
	}


def recent_rows():
	jobs = {j["name"]: j for j in ops_raw()["Job Order"]}
	sales = {r["name"]: r for r in acc_raw()["Sales Invoice"]}
	pays = {r["name"]: r for r in acc_raw()["Payment Entry"]}
	return {
		"Job Order": [dict(jobs["FPS/JO/2610/058"], creation="2026-10-14 10:12:40.090000"),
		              dict(jobs["FPS/JO/2610/057"], creation="2026-10-14 09:05:11.150000")],
		"Sales Invoice": [dict(sales["FPS/INV/2610/071"], submitted_at="2026-10-14 11:42:09.310000")],
		"Payment Entry": [dict(pays["FPS/PR/2610/034"], submitted_at="2026-10-14 11:05:40.020000")],
	}


def payloads(now=NOW):
	as_of = now.date()
	o_raw, a_raw = ops_raw(), acc_raw()
	ops_payload = cc.build_dashboard(period="7d", as_of=as_of, generated_at=cc.timestamp(now),
	                                 viewer={"finance": False, "full_name": "FPS Live Feed"},
	                                 raw=o_raw, stages=cc.ops_stages(STAGES), creatable=())
	acc_payload = acc.build_dashboard(period="7d", as_of=as_of, generated_at=cc.timestamp(now),
	                                  viewer={"full_name": "FPS Live Feed"}, raw=a_raw,
	                                  company=COMPANY, creatable=())
	return {"payload": ops_payload, "raw": o_raw}, {"payload": acc_payload, "raw": a_raw}


def build_sample_snapshot(now=NOW, previous_generated_at="2026-10-14 08:00:04"):
	ops, acc_data = payloads(now)
	since = feed.recent_since(now, previous_generated_at)
	return feed.build_snapshot(now=now, ops=ops, acc_data=acc_data, recent=recent_rows(), since=since)


def sample_previous(snapshot):
	"""The 08:00 slot's fingerprints, as if the newest things had not happened yet."""
	prev = feed.fingerprints_of(snapshot)
	prev.update(generated_at="2026-10-14 08:00:04", slot_id="2026-10-14 08:00")
	for key in ("jo:FPS/JO/2610/058", "si:FPS/INV/2610/071", "pe:FPS/PR/2610/034",
	            "ct:FPS/CT/2610/052:cleared"):
		prev["items"].pop(key, None)
	prev["items"]["ins:ops:customs_mofa"] = "0123456789ab"       # changed since 08:00
	prev["chips"]["open_jobs"] = {"fp": "0123456789ab", "value": 4}
	prev["chips"]["receivables"] = {"fp": "0123456789ab",
	                                "value": prev["chips"]["receivables"]["value"] - 13125}
	return prev


def build_sample_page(now=NOW + timedelta(minutes=37)):
	"""feed.get_feed_for_page() for an allowed viewer who may open everything,
	viewed at 12:37 -- the shape the www page renders."""
	snapshot = feed.loads(feed.dumps(build_sample_snapshot()))
	previous = sample_previous(snapshot)
	feed.mark_new(snapshot, previous)
	feed.apply_can_open(snapshot, lambda doctype, name=None: True)
	return {
		"state": "ready",
		"user": {"name": "viewer@example.com", "full_name": "Sample Viewer"},
		"poll": {"meta_method": "fps_erpnext.api.feed.get_feed_meta", "check_every_seconds": 600,
		         "building_every_seconds": 10},
		"meta": feed.feed_meta(snapshot["generated_at"], now),
		"snapshot": snapshot,
	}


def sections(snapshot):
	return {s["key"]: s for s in snapshot["sections"]}


def items_by_key(section):
	return {i["key"]: i for i in section["items"]}


def chips_by_key(section):
	return {c["key"]: c for c in section["chips"]}


# --------------------------------------------------------------------------
# Slots
# --------------------------------------------------------------------------

class TestSlots(unittest.TestCase):
	def test_slot_boundaries(self):
		for when, slot, slot_id, nxt in (
			("2026-10-14 07:59", "20:00", "2026-10-13 20:00", "08:00"),
			("2026-10-14 08:00", "08:00", "2026-10-14 08:00", "12:00"),
			("2026-10-14 11:59", "08:00", "2026-10-14 08:00", "12:00"),
			("2026-10-14 12:00", "12:00", "2026-10-14 12:00", "16:00"),
			("2026-10-14 16:00", "16:00", "2026-10-14 16:00", "20:00"),
			("2026-10-14 20:00", "20:00", "2026-10-14 20:00", "08:00 tomorrow"),
			("2026-10-14 23:30", "20:00", "2026-10-14 20:00", "08:00 tomorrow"),
			("2026-10-15 00:10", "20:00", "2026-10-14 20:00", "08:00"),
		):
			with self.subTest(when=when):
				self.assertEqual(feed.slot_label(dt(when)), slot)
				self.assertEqual(feed.slot_id(dt(when)), slot_id)
				self.assertEqual(feed.next_slot_label(dt(when)), nxt)

	def test_strings_and_seconds(self):
		self.assertEqual(feed.slot_label("2026-10-14 12:00:41.123456"), "12:00")
		self.assertEqual(feed.next_slot_start("2026-10-14 11:59:59"), dt("2026-10-14 12:00"))
		self.assertEqual(feed.next_slot_start("2026-10-14 20:00:00"), dt("2026-10-15 08:00"))
		self.assertEqual(feed.stamp("2026-10-14 16:30:35.358689"), "2026-10-14 16:30:35")
		self.assertIsNone(feed.to_datetime("not a date"))

	def test_updated_label(self):
		now = dt("2026-10-14 13:00")
		self.assertEqual(feed.updated_label("2026-10-14 12:03:10", now), "12:00")    # a late run
		self.assertEqual(feed.updated_label("2026-10-14 12:25:00", now), "12:25")    # off-slot build
		self.assertEqual(feed.updated_label("2026-10-14 20:00:30", dt("2026-10-15 00:10")), "20:00 yesterday")
		self.assertEqual(feed.updated_label("2026-10-12 16:00:02", now), "16:00 on 12 Oct")

	def test_late(self):
		self.assertFalse(feed.is_late("2026-10-14 08:00:04", dt("2026-10-14 12:20")))   # within grace
		self.assertTrue(feed.is_late("2026-10-14 08:00:04", dt("2026-10-14 12:31")))
		self.assertFalse(feed.is_late("2026-10-14 12:00:40", dt("2026-10-14 12:31")))
		self.assertFalse(feed.is_late("2026-10-13 20:00:10", dt("2026-10-14 07:59")))   # overnight is normal
		self.assertTrue(feed.is_late("2026-10-13 16:00:10", dt("2026-10-14 07:00")))    # 20:00 was missed
		self.assertFalse(feed.is_late(None, dt("2026-10-14 07:00")))

	def test_meta_is_computed_at_render_time(self):
		night = feed.feed_meta("2026-10-14 20:00:03", dt("2026-10-15 00:10"))
		self.assertEqual((night["slot"], night["next_slot"], night["next_at"], night["updated_label"]),
		                 ("20:00", "08:00", "2026-10-15 08:00:00", "20:00 yesterday"))
		evening = feed.feed_meta("2026-10-14 20:00:03", dt("2026-10-14 20:30"))
		self.assertEqual(evening["next_slot"], "08:00 tomorrow")
		self.assertFalse(evening["late"])
		empty = feed.feed_meta(None, dt("2026-10-14 09:00"))
		self.assertIsNone(empty["generated_at"])
		self.assertEqual(empty["next_slot"], "12:00")

	def test_cron_matches_hooks_and_slots(self):
		with open(os.path.join(ROOT, "fps_erpnext", "hooks.py"), encoding="utf-8") as fh:
			tree = ast.parse(fh.read())
		hooks = {}
		for node in tree.body:
			if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "scheduler_events":
				hooks = ast.literal_eval(node.value)
		self.assertEqual(hooks["cron"][feed.CRON], ["fps_erpnext.api.feed.build_snapshot"])
		# The jobs sweep is still there, untouched.
		self.assertEqual(hooks["cron"]["*/30 * * * *"], ["fps_erpnext.api.jobs.sweep"])
		minute, hours, *_rest = feed.CRON.split()
		self.assertEqual(minute, "0")
		self.assertEqual(tuple(int(h) for h in hours.split(",")), feed.SLOT_HOURS)

	def test_recent_since(self):
		now = dt("2026-10-14 12:00")
		self.assertEqual(feed.recent_since(now), dt("2026-10-13 12:00"))
		self.assertEqual(feed.recent_since(now, "2026-10-14 08:00:04"), dt("2026-10-13 12:00"))
		self.assertEqual(feed.recent_since(now, "2026-10-11 20:00:00"), dt("2026-10-11 20:00"))
		self.assertEqual(feed.recent_since(now, "2026-10-01 20:00:00"), dt("2026-10-07 12:00"))

	def test_since_label(self):
		now = dt("2026-10-14 12:00")
		self.assertEqual(feed.since_label(dt("2026-10-14 08:00"), now), "since 08:00")
		self.assertEqual(feed.since_label(dt("2026-10-13 12:00"), now), "since 12:00 yesterday")
		self.assertEqual(feed.since_label(dt("2026-10-11 20:00"), now), "since 11 Oct")


# --------------------------------------------------------------------------
# NEW marks
# --------------------------------------------------------------------------

def mini_snapshot(items, chips=(), slot_id="2026-10-14 12:00", generated_at="2026-10-14 12:00:05"):
	return {"version": feed.VERSION, "generated_at": generated_at, "slot_id": slot_id,
	        "sections": [{"key": "ops", "items": list(items), "chips": list(chips), "counts": {}}]}


def item(key, title="A title", kind="job", severity="info", at=None, **kw):
	return feed.make_item(key, kind, severity, title, at=at, **kw)


class TestNew(unittest.TestCase):
	def test_new_changed_and_unchanged(self):
		old = mini_snapshot([item("a"), item("b", "Before"), item("c")])
		new = mini_snapshot([item("a"), item("b", "After"), item("d")])
		previous = feed.fingerprints_of(old)
		feed.mark_new(new, previous)
		marks = {i["key"]: i["is_new"] for i in new["sections"][0]["items"]}
		self.assertEqual(marks, {"a": False, "b": True, "d": True})
		self.assertEqual(new["sections"][0]["counts"]["new"], 2)
		self.assertEqual(new["compared_with"], "2026-10-14 12:00:05")

	def test_first_snapshot_marks_nothing(self):
		snap = mini_snapshot([item("a"), item("b")])
		feed.mark_new(snap, None)
		self.assertFalse(any(i["is_new"] for i in snap["sections"][0]["items"]))
		self.assertIsNone(snap["compared_with"])

	def test_fingerprint_is_what_the_viewer_sees(self):
		base = item("a", "Title", amount=615028.22)
		self.assertEqual(base["fingerprint"], item("a", "Title", amount=615028.22,
		                                           detail=[feed.row("x", "y")], doctype="Job Order",
		                                           name="J1")["fingerprint"])
		self.assertNotEqual(base["fingerprint"], item("a", "Title 2", amount=615028.22)["fingerprint"])
		self.assertNotEqual(base["fingerprint"], item("a", "Title", amount=716000)["fingerprint"])
		self.assertNotEqual(base["fingerprint"], item("a", "Title", amount=615028.22,
		                                              severity="warning")["fingerprint"])
		# Stable across runs (no salt, no ordering effects).
		self.assertEqual(feed.fingerprint("x", 1, None), feed.fingerprint("x", 1, None))
		self.assertEqual(len(base["fingerprint"]), 12)

	def test_chip_changes(self):
		count_old = feed.make_chip("open_jobs", "Open jobs", 4, "4")
		money_old = feed.make_chip("receivables", "Receivables", 600000, "AED 600K", unit="currency")
		same = feed.make_chip("past_eta", "Past ETA", 2, "2")
		previous = feed.fingerprints_of(mini_snapshot([], [count_old, money_old, same]))
		snap = mini_snapshot([], [feed.make_chip("open_jobs", "Open jobs", 6, "6"),
		                          feed.make_chip("receivables", "Receivables", 612345.67, "AED 612.3K",
		                                         unit="currency"),
		                          feed.make_chip("past_eta", "Past ETA", 2, "2"),
		                          feed.make_chip("brand_new", "New chip", 1, "1")])
		feed.mark_new(snap, previous)
		chips = {c["key"]: c for c in snap["sections"][0]["chips"]}
		self.assertEqual((chips["open_jobs"]["changed"], chips["open_jobs"]["since_previous"],
		                  chips["open_jobs"]["since_previous_display"]), (True, 2, "+2"))
		self.assertEqual((chips["receivables"]["since_previous"], chips["receivables"]["since_previous_display"]),
		                 (12345.67, "+AED 12.3K"))
		self.assertFalse(chips["past_eta"]["changed"])
		self.assertNotIn("since_previous", chips["past_eta"])
		self.assertFalse(chips["brand_new"]["changed"])      # nothing to compare with

	def test_chip_going_down(self):
		previous = feed.fingerprints_of(mini_snapshot([], [feed.make_chip("k", "K", 5, "5")]))
		snap = mini_snapshot([], [feed.make_chip("k", "K", 3, "3")])
		feed.mark_new(snap, previous)
		self.assertEqual(snap["sections"][0]["chips"][0]["since_previous_display"], "−2")

	def test_next_previous(self):
		at_08 = mini_snapshot([item("a")], slot_id="2026-10-14 08:00", generated_at="2026-10-14 08:00:04")
		at_12 = mini_snapshot([item("a"), item("b")], slot_id="2026-10-14 12:00")
		# Nothing stored yet: nothing to compare with.
		self.assertIsNone(feed.next_previous(None, None, "2026-10-14 08:00"))
		# The 12:00 build compares with the 08:00 snapshot it replaces.
		prev = feed.next_previous(at_08, None, "2026-10-14 12:00")
		self.assertEqual((prev["slot_id"], sorted(prev["items"])), ("2026-10-14 08:00", ["a"]))
		# A re-run at 12:05 keeps comparing with 08:00, not with the 12:00 build.
		self.assertIs(feed.next_previous(at_12, prev, "2026-10-14 12:00"), prev)
		# The 16:00 build compares with 12:00.
		self.assertEqual(sorted(feed.next_previous(at_12, prev, "2026-10-14 16:00")["items"]), ["a", "b"])


# --------------------------------------------------------------------------
# Order and caps
# --------------------------------------------------------------------------

class TestOrderAndCaps(unittest.TestCase):
	def test_order(self):
		items = [
			item("info-insight", kind="insight", severity="info"),
			item("party", kind="overdue_customer", severity="warning"),
			item("old-event", kind="receipt", severity="positive", at="2026-10-13 09:00:00"),
			item("warn-insight", kind="insight", severity="warning"),
			item("new-event", kind="job", at="2026-10-14 11:00:00"),
			item("crit", kind="insight", severity="critical"),
			item("hold", kind="update", severity="warning", at="2026-10-14 10:00:00"),
			item("date-event", kind="customs", severity="positive", at=date(2026, 10, 14)),
		]
		self.assertEqual([i["key"] for i in feed.order_items(items)],
		                 ["crit", "warn-insight", "new-event", "hold", "date-event", "old-event", "party",
		                  "info-insight"])

	def test_section_cap_drops_the_oldest_events_never_an_alert(self):
		alerts = [item("alert%d" % n, kind="insight", severity="warning") for n in range(3)]
		events = [item("job%02d" % n, kind="job", at=datetime(2026, 10, 14, 0, n)) for n in range(30)]
		kept, dropped = feed.cap_items(events + alerts)
		self.assertEqual(len(kept), feed.SECTION_CAP)
		self.assertTrue(all(("alert%d" % n) in [i["key"] for i in kept] for n in range(3)))
		self.assertEqual({i["key"] for i in dropped}, {"job%02d" % n for n in range(8)})
		section = feed._section("ops", "Operations", "", [], events + alerts, {})
		self.assertEqual(section["more"], [{"kind": "job", "count": 8, "label": "8 more jobs opened"}])
		self.assertEqual(len(section["items"]), feed.SECTION_CAP)

	def test_kind_caps_count_into_more(self):
		more = {}
		self.assertEqual(len(feed._take(list(range(11)), "job", more)), 8)
		self.assertEqual(feed.more_lines(more), [{"kind": "job", "count": 3, "label": "3 more jobs opened"}])
		self.assertEqual(feed.more_lines({"delivery": 1}),
		                 [{"kind": "delivery", "count": 1, "label": "1 more delivery"}])


# --------------------------------------------------------------------------
# The fictional snapshot
# --------------------------------------------------------------------------

class TestSnapshot(unittest.TestCase):
	def setUp(self):
		self.snap = build_sample_snapshot()
		self.ops, self.acc = sections(self.snap)["ops"], sections(self.snap)["acc"]

	def test_shape(self):
		s = self.snap
		self.assertEqual(list(s), list(feed.SnapshotKeys))
		self.assertEqual((s["version"], s["generated_at"], s["slot"], s["slot_id"], s["next_slot"]),
		                 (1, "2026-10-14 12:00:05", "12:00", "2026-10-14 12:00", "16:00"))
		self.assertEqual((s["since"], s["since_label"]), ("2026-10-13 12:00:05", "since 12:00 yesterday"))
		self.assertEqual([x["key"] for x in s["sections"]], ["ops", "acc"])
		self.assertEqual([c["key"] for c in self.ops["chips"]],
		                 ["open_jobs", "in_progress", "customs_open", "awaiting_invoice", "past_eta",
		                  "enquiries_7d"])
		self.assertEqual([c["key"] for c in self.acc["chips"]],
		                 ["receivables", "payables", "cash", "vat", "invoiced_7d", "collected_7d"])
		keys = [i["key"] for sec in s["sections"] for i in sec["items"]]
		self.assertEqual(len(keys), len(set(keys)), "item keys are unique across the snapshot")
		for sec in s["sections"]:
			self.assertEqual(list(sec), [k for k in feed.SectionKeys if k in sec])
			self.assertLessEqual(len(sec["items"]), feed.SECTION_CAP)
			for i in sec["items"]:
				self.assertLessEqual(set(i), set(feed.ItemKeys), i["key"])
				self.assertIn(i["severity"], feed.SEVERITIES)
				self.assertLessEqual(len(i["title"]), feed.TITLE_MAX)
				if i["kind"] not in feed.PARTY_KINDS:
					self.assertEqual(i["fingerprint"], feed.item_fingerprint(i))
				for r in i.get("records") or []:
					self.assertLessEqual(set(r), set(feed.RecordKeys))
			for c in sec["chips"]:
				self.assertIn(c["tone"], feed.TONES)
				self.assertLessEqual(set(c), set(feed.ChipKeys))

	def test_operations_carry_no_money(self):
		text = json.dumps(self.ops, ensure_ascii=False)
		self.assertNotIn("AED", text)
		self.assertFalse([i["key"] for i in self.ops["items"] if "amount" in i])

	def test_operations_items(self):
		items = items_by_key(self.ops)
		docs = items["ins:ops:customs_docs"]
		self.assertEqual(docs["severity"], "critical")
		self.assertEqual(docs["records"][0]["name"], "FPS/CT/2609/041")
		self.assertIn("13 days ago", docs["records"][0]["subtitle"])
		mofa = items["ins:ops:customs_mofa"]
		self.assertEqual((mofa["severity"], mofa["records"][0]["subtitle"]),
		                 ("warning", "FPS/CT/2610/052 · MOFA due 28 Oct, in 14 days"))
		eta = items["ins:ops:jobs_past_eta"]
		self.assertEqual([r["name"] for r in eta["records"]], ["FPS/JO/2609/041", "FPS/JO/2610/052"])
		self.assertEqual(items["ins:ops:delivered_not_invoiced"]["records"][0]["name"], "FPS/JO/2610/047")
		self.assertEqual(len(items["ins:ops:quotation_drafts"]["records"]), 5)
		# Jobs opened in the window, with what the System logged while opening them.
		job = items["jo:FPS/JO/2610/058"]
		# The party is the title; the kind is the tag beside the time (not a
		# "New job · " prefix eating the title's first line on a narrow phone).
		self.assertEqual((job["title"], job["tag"], job["at"]), (HARBOUR, "New job", "2026-10-14 10:12:40"))
		self.assertEqual(job["subtitle"], "FPS/JO/2610/058 · Freight forwarding · PO\u00a04410")
		self.assertIn({"label": "Also logged", "value": "Job opened; Customs entry opened"}, job["detail"])
		self.assertEqual(job["route"], "/app/job-order/FPS%2FJO%2F2610%2F058")
		# Updates: the rows that say the same as an event item (opening a job,
		# clearing customs, delivering) are folded into it; Backfill rows never show.
		updates = [k for k in items if k.startswith("upd:")]
		self.assertEqual(sorted(updates), ["upd:u-0095", "upd:u-0097"])
		self.assertEqual(items["upd:u-0097"]["severity"], "warning")    # HOLD
		# Clearances and deliveries in the window only (today and yesterday), timed
		# by the job update that logged them.
		cleared = items["ct:FPS/CT/2610/052:cleared"]
		self.assertEqual(cleared["at"], "2026-10-14 11:20:02")
		self.assertEqual(cleared["detail"][0], {"label": "Also logged", "value": "Customs released - BOE 101018000077"})
		self.assertNotIn("ct:FPS/CT/2610/049:cleared", items)
		self.assertEqual(items["pod:FPS/POD/2610/021"]["at"], "2026-10-13 15:02:10")
		self.assertNotIn("pod:FPS/POD/2610/020", items)
		# Order: critical, warning, then events newest first, then the quiet notes.
		order = [i["key"] for i in self.ops["items"]]
		self.assertEqual(order[:3], ["ins:ops:customs_docs", "ins:ops:customs_mofa", "ins:ops:jobs_past_eta"])
		self.assertEqual(order[3:9], ["ct:FPS/CT/2610/052:cleared", "jo:FPS/JO/2610/058", "jo:FPS/JO/2610/057",
		                              "upd:u-0097", "pod:FPS/POD/2610/021", "upd:u-0095"])
		self.assertEqual(order[-2:], ["ins:ops:delivered_not_invoiced", "ins:ops:quotation_drafts"])

	def test_operations_chips(self):
		chips = chips_by_key(self.ops)
		self.assertEqual({k: c["value"] for k, c in chips.items()},
		                 {"open_jobs": 5, "in_progress": 3, "customs_open": 1, "awaiting_invoice": 1,
		                  "past_eta": 2, "enquiries_7d": 4})
		self.assertEqual(chips["past_eta"]["tone"], "warning")
		self.assertIn({"label": "Open jobs with no ETA", "value": "2"}, chips["past_eta"]["detail"])
		self.assertEqual(chips["enquiries_7d"]["delta"]["previous"], 1)
		self.assertIn({"label": "Pipeline", "value": "2 past ETA"}, chips["open_jobs"]["detail"])

	def test_accounts_items(self):
		items = items_by_key(self.acc)
		order = [i["key"] for i in self.acc["items"]]
		self.assertEqual(order[0], "cash:statement_gap")                 # the critical one
		self.assertEqual(items["cash:statement_gap"]["severity"], "critical")
		self.assertIn("ins:acc:vat_due", items)
		self.assertIn("ins:acc:unallocated_receipts", items)
		self.assertEqual(items["ins:acc:unallocated_receipts"]["records"][0]["value"], "AED 9K")
		# Not repeated: delivered-not-invoiced is an Operations item, statements are the bank item.
		self.assertNotIn("ins:acc:delivered_not_invoiced", items)
		self.assertNotIn("ins:acc:bank_statements_behind", items)
		bank = items["bank:statements"]
		self.assertEqual((bank["severity"], len(bank["records"])), ("warning", 4))
		self.assertEqual(bank["records"][0]["name"], "FPS-BST-ADCB-2609")
		self.assertNotIn("name", bank["records"][3])                     # QGOV has no statement
		invoice = items["si:FPS/INV/2610/071"]
		self.assertEqual((invoice["amount"], invoice["amount_display"], invoice["at"]),
		                 (13125.0, "AED 13.1K", "2026-10-14 11:42:09"))
		self.assertIn({"label": "Grand total", "value": "AED 13,125.00"}, invoice["detail"])
		receipt = items["pe:FPS/PR/2610/034"]
		self.assertEqual((receipt["title"], receipt["tag"], receipt["amount_display"]),
		                 (DESERT, "Received", "AED 15.8K"))
		self.assertEqual(receipt["subtitle"], "FPS/PR/2610/034 · Bank Transfer · Ref\u00a0TT-88412")
		self.assertEqual((invoice["title"], invoice["tag"]), (HARBOUR, "Invoice"))
		self.assertEqual(invoice["subtitle"], "FPS/INV/2610/071 · FPS/JO/2609/041 · due 12 Nov")
		# Most overdue customers, net of their credits (Harbour's 9K on account).
		customers = [i for i in self.acc["items"] if i["kind"] == "overdue_customer"]
		self.assertEqual([(c["title"], c["amount"]) for c in customers],
		                 [(HARBOUR, 33000.0), (DESERT, 18350.5), (GULF, 9800.0), (OLDPORT, 4250.0)])
		# One severity per list: every party listed is past due (AED 4,250 too).
		self.assertEqual({c["severity"] for c in customers}, {"warning"})
		self.assertEqual(customers[0]["records"][0]["name"], "FPS/INV/2609/066")
		# A party is NEW when what it owes changes, not because a day passed.
		tomorrow = build_sample_snapshot(now=NOW + timedelta(days=1))
		later = {i["key"]: i for i in sections(tomorrow)["acc"]["items"] if i["kind"] == "overdue_customer"}
		self.assertNotEqual(later[customers[0]["key"]]["subtitle"], customers[0]["subtitle"])
		self.assertEqual(later[customers[0]["key"]]["fingerprint"], customers[0]["fingerprint"])
		self.assertEqual(items["cash:statement_gap"]["subtitle"], "Books above statements AED 11K")
		suppliers = [i for i in self.acc["items"] if i["kind"] == "supplier_due"]
		self.assertEqual([s["title"] for s in suppliers], [HAULIER, AGENT])
		self.assertEqual(suppliers[0]["doctype"], "Purchase Invoice")
		self.assertNotIn("name", suppliers[0])                           # a list route

	def test_accounts_chips(self):
		chips = chips_by_key(self.acc)
		self.assertEqual(chips["cash"]["tone"], "critical")
		self.assertTrue(chips["cash"]["sub"].startswith("Books above statements"))
		self.assertEqual(chips["vat"]["label"], "VAT Jul–Sep 2026")
		self.assertEqual((chips["vat"]["tone"], chips["vat"]["sub"]), ("warning", "Due 28 Oct 2026 · 14 days"))
		self.assertEqual(chips["receivables"]["sub"], "AED 65.4K overdue")
		self.assertEqual(chips["receivables"]["doctype"], "Sales Invoice")
		self.assertEqual(chips["invoiced_7d"]["value"], 27500.0)
		self.assertEqual(chips["collected_7d"]["display"], "AED 15.8K")

	def test_one_customers_new_jobs_are_one_card(self):
		recent = recent_rows()
		jobs = {j["name"]: j for j in ops_raw()["Job Order"]}
		recent["Job Order"].append(dict(jobs["FPS/JO/2610/058"], name="FPS/JO/2610/059",
		                                client_reference_no="PO# 82467", creation="2026-10-14 11:30:00.000000"))
		ops, acc_data = payloads()
		snap = feed.build_snapshot(now=NOW, ops=ops, acc_data=acc_data, recent=recent,
		                           since=feed.recent_since(NOW, "2026-10-14 08:00:04"))
		items = items_by_key(sections(snap)["ops"])
		self.assertNotIn("jo:FPS/JO/2610/058", items)
		group = items["jos:" + HARBOUR]
		self.assertEqual((group["kind"], group["title"], group["tag"], group["at"]),
		                 ("job", HARBOUR, "2 new jobs", "2026-10-14 11:30:00"))
		self.assertEqual(group["subtitle"], "FPS/JO/2610/058, 059 · Freight forwarding")
		self.assertEqual([r["name"] for r in group["records"]], ["FPS/JO/2610/059", "FPS/JO/2610/058"])
		self.assertIn("PO#\u00a082467", group["records"][0]["subtitle"])
		self.assertTrue(group["route"].startswith("/app/job-order?name="))
		self.assertIn("jo:FPS/JO/2610/057", items)                      # another customer: its own card
		# The section cap and "more" count jobs, not cards.
		self.assertEqual(feed.job_count(group), 2)

	def test_counts_leave_out_the_standing_lists(self):
		for sec in self.snap["sections"]:
			listed = [i for i in sec["items"] if i["kind"] not in feed.PARTY_KINDS]
			self.assertEqual(sec["counts"]["warning"], sum(1 for i in listed if i["severity"] == "warning"))
		self.assertTrue([i for i in self.acc["items"] if i["kind"] in feed.PARTY_KINDS])

	def test_events_row_counts_only_the_window(self):
		rows = {r["label"]: r["value"] for r in self.ops["detail"]}
		events = [i for i in self.ops["items"] if i["kind"] in feed.EVENT_KINDS]
		inside = [i for i in events if feed.in_window(i, self.snap["since"])]
		self.assertEqual(rows["Events since 12:00 yesterday"], str(len(inside)))
		# u-0095 (13 Oct, 11:10) is one of the newest updates but older than the window.
		self.assertEqual(rows["Earlier job updates shown"], str(len(events) - len(inside)))
		self.assertGreater(len(events), len(inside))
		self.assertTrue(feed.in_window({"at": "2026-10-13"}, "2026-10-13 12:00:05"))
		self.assertFalse(feed.in_window({"at": "2026-10-13 11:10:00"}, "2026-10-13 12:00:05"))

	def test_customs_records_are_grouped(self):
		items = items_by_key(self.ops)
		self.assertEqual([r["group"] for r in items["ins:ops:customs_docs"]["records"]], ["Past deadline"])
		self.assertEqual([r["group"] for r in items["ins:ops:customs_mofa"]["records"]], ["Due soon"])

	def test_paid_invoice_and_the_invoiced_sheet(self):
		recent = recent_rows()
		paid = {r["name"]: r for r in acc_raw()["Sales Invoice"]}["FPS/INV/2610/069"]
		recent["Sales Invoice"].append(dict(paid, submitted_at="2026-10-14 10:02:00.000000"))
		ops, acc_data = payloads()
		snap = feed.build_snapshot(now=NOW, ops=ops, acc_data=acc_data, recent=recent,
		                           since=feed.recent_since(NOW, "2026-10-14 08:00:04"))
		acc_ = sections(snap)["acc"]
		# Settled: its status, not a due date that has passed.
		self.assertEqual(items_by_key(acc_)["si:FPS/INV/2610/069"]["subtitle"], "FPS/INV/2610/069 · Paid")
		rows = {r["label"]: r["value"] for r in chips_by_key(acc_)["invoiced_7d"]["detail"]}
		self.assertEqual(rows["Submitted since 12:00 yesterday"], "2 · AED 28.9K with VAT · 1 back-dated")
		self.assertEqual(rows["Latest posting date"], "13 Oct")
		self.assertNotIn("Last submitted", rows)

	def test_overdue_above_the_total_is_set_against_what_is_owed(self):
		a_raw = acc_raw()
		# A customer with only money on account: the total drops, the overdue does not.
		a_raw["Payment Entry"].append({
			"name": "FPS/PR/2610/040", "docstatus": 1, "payment_type": "Receive", "posting_date": "2026-10-12",
			"base_received_amount": 60000, "unallocated_amount": 60000, "party_type": "Customer",
			"party": "Prepaid Buyer (sample)", "party_name": "Prepaid Buyer (sample)"})
		payload = acc.build_dashboard(period="7d", as_of=AS_OF, generated_at=cc.timestamp(NOW),
		                              viewer={"full_name": "FPS Live Feed"}, raw=a_raw, company=COMPANY,
		                              creatable=())
		chip = {c["key"]: c for c in feed.acc_chips(payload, raw=a_raw, as_of=AS_OF)}["receivables"]
		self.assertLess(chip["value"], 65400)
		self.assertEqual(chip["sub"], "AED 65.4K overdue of AED 78.5K owed")
		rows = {r["label"]: r["value"] for r in chip["detail"]}
		self.assertEqual(rows["Customers in credit"], "AED 60K · 1")
		self.assertEqual(rows["Owed by the customers who owe"], "AED 78,525.50")
		# Not above the total: the plain line, as before.
		self.assertEqual(chips_by_key(self.acc)["receivables"]["sub"], "AED 65.4K overdue")

	def test_recent_reads_failing_leave_a_notice(self):
		ops, acc_data = payloads()
		s = feed.build_snapshot(now=NOW, ops=ops, acc_data=acc_data, recent={},
		                        errors={"recent": "Recent documents could not be read at 12:00."})
		ops_s, acc_s = sections(s)["ops"], sections(s)["acc"]
		self.assertEqual(ops_s["notice"], "The jobs opened since 12:00 yesterday could not be read at 12:00.")
		self.assertEqual(acc_s["notice"],
		                 "The invoices and receipts since 12:00 yesterday could not be read at 12:00.")
		self.assertEqual(list(ops_s), [k for k in feed.SectionKeys if k in ops_s])
		self.assertTrue(ops_s["items"] and acc_s["items"])
		self.assertNotIn("notice", sections(self.snap)["ops"])

	def test_reference_prefixes_stay_with_their_numbers(self):
		self.assertEqual(feed.nb("PO# 82467"), "PO#\u00a082467")
		self.assertEqual(feed.nb("PO 4410 and BOE 1010180"), "PO\u00a04410 and BOE\u00a01010180")
		self.assertEqual(feed.nb("Ref TT-88412"), "Ref\u00a0TT-88412")
		self.assertEqual(feed.nb("POD date 5"), "POD date 5")
		self.assertEqual(feed.nb("Report 5"), "Report 5")

	def test_window_reaches_back_to_the_previous_build(self):
		# The previous build was three days back (a stopped scheduler): the window
		# reaches back to it, so nothing that happened in between is skipped.
		later = build_sample_snapshot(now=datetime(2026, 10, 15, 20, 0, 2),
		                              previous_generated_at="2026-10-12 20:00:00")
		self.assertEqual((later["since"], later["since_label"]), ("2026-10-12 20:00:00", "since 12 Oct"))
		ops = items_by_key(sections(later)["ops"])
		self.assertIn("ct:FPS/CT/2610/052:cleared", ops)
		self.assertIn("pod:FPS/POD/2610/021", ops)
		self.assertNotIn("pod:FPS/POD/2610/020", ops)                  # 10 Oct: before the window
		self.assertIn("jo:FPS/JO/2610/058", ops)

	def test_error_sections(self):
		ops, acc_data = payloads()
		s = feed.build_snapshot(now=NOW, ops=None, acc_data=acc_data, recent=recent_rows(),
		                        errors={"ops": "Operations data could not be read at 12:00."})
		ops_section = sections(s)["ops"]
		self.assertEqual((ops_section["error"], ops_section["items"], ops_section["chips"]),
		                 ("Operations data could not be read at 12:00.", [], []))
		self.assertTrue(sections(s)["acc"]["items"])

	def test_json_round_trip(self):
		text = feed.dumps(self.snap)
		self.assertEqual(feed.loads(text), self.snap)
		self.assertIsNone(feed.loads(""))
		self.assertIsNone(feed.loads("{not json"))
		self.assertIsNone(feed.loads("[1, 2]"))
		self.assertEqual(feed.loads({"a": 1}), {"a": 1})

	def test_script_json_cannot_close_the_script(self):
		snap = mini_snapshot([item("x", "Evil </script><script>alert(1)</script> & co ")])
		text = feed.script_json(snap)
		for bad in ("</", "<script", "&", " "):
			self.assertNotIn(bad, text)
		self.assertEqual(json.loads(text), json.loads(feed.dumps(snap)))


# --------------------------------------------------------------------------
# Money, gate, can_open
# --------------------------------------------------------------------------

class TestMoney(unittest.TestCase):
	def test_compact_on_the_item_full_in_the_sheet(self):
		i = item("m", kind="invoice", severity="positive", amount=615028.22,
		         detail=[feed.row("Grand total", feed.money_full(615028.22))])
		self.assertEqual((i["amount"], i["amount_display"]), (615028.22, "AED 615K"))
		self.assertEqual(i["detail"], [{"label": "Grand total", "value": "AED 615,028.22"}])
		self.assertEqual(feed.money_compact(1474740.78), "AED 1.5M")
		self.assertEqual(feed.money_compact(-700), "−AED 700")
		self.assertEqual(feed.money_full(-1050), "−AED 1,050.00")
		self.assertEqual(feed.money_compact(999960), "AED 1M")

	def test_empty_rows_are_dropped(self):
		self.assertEqual(feed._rows([feed.row("A", ""), feed.row("B", None), feed.row("C", 0), feed.row("D", "x")]),
		                 [{"label": "C", "value": "0"}, {"label": "D", "value": "x"}])

	def test_pct_and_delta(self):
		self.assertEqual((feed.pct_text(12.5), feed.pct_text(-20.0), feed.pct_text(0.0)), ("+12.5%", "−20%", "0%"))
		kpi = {"value": 4, "previous": 0, "delta_pct": None, "unit": "count", "good_direction": "up"}
		self.assertEqual((feed.kpi_delta(kpi)["text"], feed.kpi_delta(kpi)["tone"]), ("new", "neutral"))
		kpi.update(previous=8, delta_pct=-50.0)
		self.assertEqual(feed.kpi_delta(kpi)["tone"], "warning")
		self.assertEqual(feed.kpi_delta(kpi, caveat=True)["tone"], "neutral")
		self.assertIsNone(feed.kpi_delta(dict(kpi, previous=None)))
		money = {"value": 27500, "previous": 15000, "delta_pct": 83.3, "unit": "currency", "good_direction": "up"}
		self.assertEqual((feed.kpi_delta(money)["previous_display"], feed.kpi_delta(money)["tone"]),
		                 ("AED 15K", "positive"))


class TestGateLogic(unittest.TestCase):
	USERS = ("Administrator", "agam@fastplanet.ae", "hello@fastplanet.ae")

	def test_gate(self):
		for user in ("Administrator", "agam@fastplanet.ae", "Agam@FastPlanet.ae", "hello@fastplanet.ae"):
			self.assertEqual(feed.gate(user, self.USERS), "allowed", user)
		for user in ("Guest", None, ""):
			self.assertEqual(feed.gate(user, self.USERS), "guest", user)
		for user in ("ops@fastplanet.ae", "abhishek@fastplanet.ae", "administrator2"):
			self.assertEqual(feed.gate(user, self.USERS), "refused", user)

	def test_feed_users_constant(self):
		with open(os.path.join(ROOT, "fps_erpnext", "api", "feed.py"), encoding="utf-8") as fh:
			tree = ast.parse(fh.read())
		value = next(ast.literal_eval(n.value) for n in tree.body
		             if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "FEED_USERS")
		self.assertEqual(value, self.USERS)


class TestCanOpen(unittest.TestCase):
	def test_routes_kept_only_where_the_viewer_can_read(self):
		snap = mini_snapshot(
			[item("form", doctype="Sales Invoice", name="S1"),
			 item("list", kind="overdue_customer", doctype="Sales Invoice", route="/app/sales-invoice?customer=C"),
			 item("job", doctype="Job Order", name="J1",
			      records=[feed.record("Doc", "Customs Tracker", "CT1"), feed.record("Gone", "Customs Tracker", "CT9")]),
			 item("no-doctype", route="/app/somewhere")],
			[feed.make_chip("vat", "VAT", 1, "AED 1", doctype="GL Entry", route="/app/query-report/General%20Ledger")])
		calls = []

		def can_read(doctype, name=None):
			calls.append((doctype, name))
			return doctype in ("Job Order", "Customs Tracker") and name != "CT9"

		feed.apply_can_open(snap, can_read)
		items = {i["key"]: i for i in snap["sections"][0]["items"]}
		self.assertEqual({k: i["can_open"] for k, i in items.items()},
		                 {"form": False, "list": False, "job": True, "no-doctype": False})
		self.assertNotIn("route", items["form"])
		self.assertNotIn("route", items["list"])
		self.assertEqual(items["job"]["route"], "/app/job-order/J1")
		recs = items["job"]["records"]
		self.assertEqual([(r["can_open"], "route" in r) for r in recs], [(True, True), (False, False)])
		chip = snap["sections"][0]["chips"][0]
		self.assertEqual((chip["can_open"], "route" in chip), (False, False))
		self.assertIn(("Sales Invoice", "S1"), calls)
		self.assertIn(("Sales Invoice", None), calls)             # a list route: doctype read only


	def test_report_routes_need_the_report_too(self):
		chip = feed.make_chip("vat", "VAT", 1, "AED 1", doctype="GL Entry",
		                      route="/app/query-report/General%20Ledger?company=X")
		self.assertEqual(feed.report_name(chip["route"]), "General Ledger")
		self.assertIsNone(feed.report_name("/app/sales-invoice"))
		for report_ok in (True, False):
			snap = mini_snapshot([], [dict(chip)])
			feed.apply_can_open(snap, lambda doctype, name=None: report_ok if doctype == "Report" else True)
			self.assertIs(snap["sections"][0]["chips"][0]["can_open"], report_ok)


# --------------------------------------------------------------------------
# fps_erpnext/api/feed.py with the stand-in frappe
# --------------------------------------------------------------------------

class TestFeedApi(unittest.TestCase):
	def setUp(self):
		from fps_erpnext.tests import fake_frappe
		if fake_frappe.REAL_FRAPPE:
			self.skipTest("a real frappe is importable; covered by the bench test run")
		self.ff = fake_frappe

	def fake(self, user="agam@fastplanet.ae", stored=None, **kw):
		o_raw, a_raw = ops_raw(), acc_raw()
		rows = {dt_: o_raw[dt_] for dt_ in ("FPS Enquiry", "Quotation", "Customs Tracker", "Proof of Delivery",
		                                     "Job Order", "FPS Job Update")}
		for dt_ in ("Sales Invoice", "Payment Entry", "Purchase Invoice", "FPS Bank Statement"):
			rows[dt_] = a_raw[dt_]
		rows["Supplier"] = [{"name": k, "supplier_group": v} for k, v in a_raw["Supplier"].items()]
		rows["Account"] = [{"name": r["account"], "account_name": r["account_name"],
		                    "account_type": r["account_type"]} for r in a_raw["GL"]["cash"]]
		singles = {"FPS Feed Snapshot": stored} if stored is not None else {}
		return self.ff.FakeFrappe(user=user, rows=rows, today=AS_OF.isoformat(), company=COMPANY,
		                          singles=singles,
		                          accounts={"VAT 5%": "VAT 5% - SC",
		                                    "Sales Taxes Receivables": "Sales Taxes Receivables - SC",
		                                    "Qashio Card Liability": "Qashio Card Liability - SC"}, **kw)

	@staticmethod
	def stub_reads(mods):
		"""The two SQL-builder reads (GL sums, recent vouchers) the stand-in cannot run."""
		def gl_sums(company, accounts, to_date, from_date=None, by_voucher_type=False):
			out = {a: {"debit": 100, "credit": 0} for a in accounts}
			if by_voucher_type:
				for s in out.values():
					s["voucher_types"] = {"Sales Invoice": {"debit": 0, "credit": 100}}
			return out

		mods["acc_dashboard"]._gl_sums = gl_sums
		mods["acc_dashboard"]._purchase_totals = lambda company, from_date, to_date: {"count": 1, "net": 10, "tax": 1}
		mods["feed"]._read_recent = lambda since: recent_rows()

	def stored_sample(self):
		snap = build_sample_snapshot()
		return {"generated_at": snap["generated_at"], "slot": snap["slot"],
		        "snapshot": feed.dumps(snap), "previous": feed.dumps(sample_previous(snap))}

	def test_guest_is_sent_to_login(self):
		fake = self.fake(user="Guest")
		with fake.installed() as mods:
			with self.assertRaises(self.ff.Redirect):
				mods["feed"].check_page_access()
			self.assertEqual(sys.modules["frappe"].local.flags.redirect_location, "/login?redirect-to=/fps-feed")
		self.assertEqual(fake.calls, [])

	def test_others_get_the_private_page_and_no_data(self):
		for user in ("ops@fastplanet.ae", "abhishek@fastplanet.ae"):
			fake = self.fake(user=user, stored=self.stored_sample())
			with fake.installed() as mods:
				api = mods["feed"]
				self.assertIs(api.check_page_access(), False)
				page = api.get_feed_for_page()
				with self.assertRaises(self.ff.PermissionError):
					api.get_feed_meta()
			self.assertEqual(page["state"], "private")
			self.assertNotIn("snapshot", page)
			self.assertEqual(fake.calls, [], user)       # nothing read, not even the Single

	def test_allowed_page(self):
		fake = self.fake(user="hello@fastplanet.ae", stored=self.stored_sample(),
		                 now="2026-10-14 12:37:00",
		                 readable={"Job Order", "Customs Tracker", "Proof of Delivery", "FPS Enquiry",
		                           "Quotation"},
		                 denied_docs={("Job Order", "FPS/JO/2610/057")})
		with fake.installed() as mods:
			api = mods["feed"]
			self.assertIs(api.check_page_access(), True)
			page = api.get_feed_for_page()
			meta = api.get_feed_meta()
		self.assertEqual(page["state"], "ready")
		self.assertEqual(page["meta"]["updated_label"], "12:00")
		self.assertEqual(page["meta"]["next_slot"], "16:00")
		self.assertEqual(meta, {"generated_at": "2026-10-14 12:00:05", "slot": "12:00",
		                        "slot_id": "2026-10-14 12:00", "building": False})
		ops, acc_ = sections(page["snapshot"])["ops"], sections(page["snapshot"])["acc"]
		items = items_by_key(ops)
		self.assertTrue(items["jo:FPS/JO/2610/058"]["is_new"])
		self.assertFalse(items["jo:FPS/JO/2610/057"]["is_new"])
		self.assertTrue(items["ins:ops:customs_mofa"]["is_new"])
		self.assertTrue(items["jo:FPS/JO/2610/058"]["can_open"])
		self.assertFalse(items["jo:FPS/JO/2610/057"]["can_open"])      # a User Permission, say
		self.assertNotIn("route", items["jo:FPS/JO/2610/057"])
		# hello@ reads no accounting doctype: every Accounts item is shown, none opens.
		self.assertTrue(acc_["items"])
		self.assertFalse([i["key"] for i in acc_["items"] if i["can_open"] or "route" in i])
		self.assertEqual(chips_by_key(ops)["open_jobs"]["since_previous"], 1)
		self.assertEqual(json.loads(page["feed_json"])["snapshot"], page["snapshot"])
		self.assertEqual(page["poll"]["meta_method"], "fps_erpnext.api.feed.get_feed_meta")
		self.assertNotIn(("set_single_value", "FPS Feed Snapshot"), fake.calls)   # the page never writes

	def test_first_visit_enqueues_one_build(self):
		fake = self.fake()
		with fake.installed() as mods:
			api = mods["feed"]
			page = api.get_feed_for_page()
			meta = api.get_feed_meta()
		self.assertEqual((page["state"], page["snapshot"]), ("building", None))
		self.assertIn(("enqueue", "fps_erpnext.api.feed.build_snapshot", "fps_feed_first_snapshot"), fake.calls)
		self.assertEqual(json.loads(page["feed_json"]), {"meta": page["meta"], "snapshot": None})
		self.assertIsNone(meta["generated_at"])
		self.assertNotIn(("set_single_value", "FPS Feed Snapshot"), fake.calls)

	def test_an_older_contract_is_rebuilt_not_rendered(self):
		stored = self.stored_sample()
		stored["snapshot"] = json.dumps(dict(json.loads(stored["snapshot"]), version=0))
		fake = self.fake(stored=stored)
		with fake.installed() as mods:
			self.assertEqual(mods["feed"].get_feed_for_page()["state"], "building")

	def test_build_refused_in_a_web_request(self):
		fake = self.fake(user="agam@fastplanet.ae", in_request=True)
		with fake.installed() as mods:
			with self.assertRaises(self.ff.PermissionError):
				mods["feed"].build_snapshot()
		self.assertEqual(fake.read_doctypes(), [])
		self.assertEqual(fake.singles, {})

	def test_build_in_a_background_job_runs_as_administrator(self):
		fake = self.fake(user="hello@fastplanet.ae", in_job=True, now="2026-10-14 12:00:05")
		with fake.installed() as mods:
			self.stub_reads(mods)
			result = mods["feed"].build_snapshot()
		self.assertEqual(fake.calls[0], ("set_user", "Administrator"))
		self.assertEqual(result["slot"], "12:00")
		self.assertIn("FPS Feed Snapshot", fake.singles)

	def test_build_as_administrator_stores_and_chains_previous(self):
		fake = self.fake(user="Administrator", now="2026-10-14 08:00:04")
		with fake.installed() as mods:
			self.stub_reads(mods)
			api = mods["feed"]
			first = api.build_snapshot()
			stored = dict(fake.singles["FPS Feed Snapshot"])
			fake.now = "2026-10-14 12:00:05"
			api.build_snapshot()
			at_12 = dict(fake.singles["FPS Feed Snapshot"])
			fake.now = "2026-10-14 12:06:00"                  # a manual re-run in the same slot
			api.build_snapshot()
			again = dict(fake.singles["FPS Feed Snapshot"])
		self.assertEqual(first["errors"], [])
		self.assertEqual((stored["slot"], stored["generated_at"]), ("08:00", "2026-10-14 08:00:04"))
		self.assertIsNone(stored["previous"])                 # the first snapshot compares with nothing
		snap = feed.loads(stored["snapshot"])
		self.assertEqual([s["key"] for s in snap["sections"]], ["ops", "acc"])
		self.assertFalse([s for s in snap["sections"] if s.get("error")])
		prev_12 = feed.loads(at_12["previous"])
		self.assertEqual(prev_12["slot_id"], "2026-10-14 08:00")
		self.assertEqual(prev_12, feed.fingerprints_of(snap))
		self.assertEqual(feed.loads(again["previous"]), prev_12)     # still compared with 08:00
		self.assertEqual(again["slot"], "12:00")
		# Built from the dashboards' own readers, Administrator rights, no money in OPS.
		read = fake.read_doctypes()
		for doctype in ("FPS Enquiry", "Quotation", "Customs Tracker", "Proof of Delivery", "Job Order",
		                "FPS Job Update", "Sales Invoice", "Payment Entry", "Purchase Invoice",
		                "FPS Bank Statement"):
			self.assertIn(doctype, read)
		self.assertNotIn(("set_user", "Administrator"), fake.calls)

	def test_failures_are_logged_so_a_rollback_keeps_them(self):
		fake = self.fake(user="Administrator", now="2026-10-14 16:00:03")
		with fake.installed() as mods:
			self.stub_reads(mods)
			api = mods["feed"]

			def boom(*a, **k):
				raise RuntimeError("read failed")

			api._read_recent = boom
			result = api.build_snapshot()
			snap = feed.loads(fake.singles["FPS Feed Snapshot"]["snapshot"])
			sys.modules["frappe"].enqueue = boom
			fake.singles.clear()
			page = api.get_feed_for_page()
		# The recent reads failing never fail the build: both sections, with a notice.
		self.assertEqual(result["errors"], ["recent"])
		self.assertTrue(all(s.get("notice") and s["items"] for s in snap["sections"]))
		self.assertIn(("log_error_deferred", "FPS Live Feed: recent documents could not be read"), fake.calls)
		# The page's GET is rolled back: the enqueue failure is logged deferred too.
		self.assertEqual(page["state"], "building")
		self.assertIn(("log_error_deferred", "FPS Live Feed: could not enqueue the first snapshot"), fake.calls)
		self.assertFalse([c for c in fake.calls if c[0] == "log_error"
		                  and ("log_error_deferred", c[1]) not in fake.calls])

	def test_report_routes_follow_the_reports_roles(self):
		reports = {"FPS Customer Receivables": {"ref_doctype": "Sales Invoice", "roles": ["Accounts Manager"]},
		           "Accounts Payable": {"ref_doctype": "Purchase Invoice", "roles": []},
		           "General Ledger": {"ref_doctype": "GL Entry", "roles": ["Accounts User"], "disabled": 1}}
		for roles, expected in ((["Accounts User"], (False, True, False)),
		                        (["Accounts Manager"], (True, True, False))):
			fake = self.fake(user="agam@fastplanet.ae", stored=self.stored_sample(), roles=roles,
			                 reports=reports)
			with fake.installed() as mods:
				page = mods["feed"].get_feed_for_page()
			chips = chips_by_key(sections(page["snapshot"])["acc"])
			self.assertEqual((chips["receivables"]["can_open"], chips["payables"]["can_open"],
			                  chips["cash"]["can_open"]), expected, roles)
			self.assertTrue(chips["invoiced_7d"]["can_open"])              # a list route, no report

	def test_one_failing_section_does_not_stop_the_feed(self):
		fake = self.fake(user="Administrator", now="2026-10-14 16:00:03")
		with fake.installed() as mods:
			self.stub_reads(mods)
			api = mods["feed"]

			def boom(*a, **k):
				raise RuntimeError("read failed")

			api._ops_data = boom
			result = api.build_snapshot()
			snap = feed.loads(fake.singles["FPS Feed Snapshot"]["snapshot"])
			api._acc_data = boom
			stored_before = dict(fake.singles["FPS Feed Snapshot"])
			fake.now = "2026-10-14 20:00:03"
			with self.assertRaises(self.ff.ValidationError):
				api.build_snapshot()
		self.assertEqual(result["errors"], ["ops"])
		self.assertEqual(sections(snap)["ops"]["error"], "Operations data could not be read at 16:00.")
		self.assertTrue(sections(snap)["acc"]["items"])
		self.assertIn(("log_error_deferred", "FPS Live Feed: Operations section failed"), fake.calls)
		self.assertEqual(fake.singles["FPS Feed Snapshot"], stored_before)    # both failed: kept


# --------------------------------------------------------------------------
# Drift: the doctype, the schema doc and the repo sample
# --------------------------------------------------------------------------

class TestDrift(unittest.TestCase):
	def test_doctype(self):
		path = os.path.join(ROOT, "fps_erpnext", "fps", "doctype", "fps_feed_snapshot", "fps_feed_snapshot.json")
		with open(path, encoding="utf-8") as fh:
			d = json.load(fh)
		self.assertEqual((d["name"], d["module"], d["issingle"], d["track_changes"]),
		                 ("FPS Feed Snapshot", "FPS", 1, 0))
		self.assertEqual({f["fieldname"]: f["fieldtype"] for f in d["fields"]},
		                 {"generated_at": "Datetime", "slot": "Data", "snapshot": "Long Text",
		                  "previous": "Long Text"})
		self.assertEqual(d["permissions"], [{"read": 1, "role": "System Manager"}])

	def test_schema_documents_every_key(self):
		if not os.path.exists(SCHEMA_PATH):
			self.skipTest("docs/live_feed/snapshot.schema.md not present")
		with open(SCHEMA_PATH, encoding="utf-8") as fh:
			text = fh.read()
		for keys in (feed.SnapshotKeys, feed.SectionKeys, feed.ItemKeys, feed.RecordKeys, feed.ChipKeys):
			for key in keys:
				self.assertIn("`%s`" % key, text, key)
		for key in ("is_new", "can_open", "changed", "since_previous", "since_previous_display",
		            "compared_with", "feed_json", "updated_label", "next_at", "late"):
			self.assertIn("`%s`" % key, text, key)

	def test_sample_fixture_matches_the_logic(self):
		if not os.path.exists(SAMPLE_PATH):
			self.skipTest("docs/live_feed/sample_snapshot.json not present")
		with open(SAMPLE_PATH, encoding="utf-8") as fh:
			sample = json.load(fh)
		self.assertEqual(sample, json.loads(json.dumps(build_sample_page(), ensure_ascii=False)),
		                 "regenerate: python -m fps_erpnext.tests.test_feed_logic --write-sample")
		# Fictional parties only.
		for s in sample["snapshot"]["sections"]:
			for i in s["items"]:
				if i["kind"] in ("overdue_customer", "supplier_due"):
					self.assertTrue(i["title"].endswith("(sample)"), i["title"])
				if i["kind"] in ("job", "invoice", "receipt", "customs", "delivery"):
					self.assertTrue(i["title"].endswith("(sample)"), i["title"])


def write_sample():
	os.makedirs(os.path.dirname(SAMPLE_PATH), exist_ok=True)
	with open(SAMPLE_PATH, "w", encoding="utf-8", newline="\n") as fh:
		json.dump(build_sample_page(), fh, indent=1, ensure_ascii=False)
		fh.write("\n")
	print("wrote", SAMPLE_PATH)


if __name__ == "__main__":
	if "--write-sample" in sys.argv:
		write_sample()
	else:
		unittest.main()
