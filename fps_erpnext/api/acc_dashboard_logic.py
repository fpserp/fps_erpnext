"""Arithmetic, copy and payload assembly for the FPS ACC Dashboard. Pure Python.

No frappe import, standard library only (plus the two pure modules it builds
on: command_center_logic and customs_clock). Like command_center_logic, it
takes plain values or dict-like rows and returns plain dicts, lists, strings
and numbers, so the whole accounting page can be built and checked with a bare
`python` and no bench:

    fps_erpnext/tests/test_acc_dashboard_logic.py    the rules, unit-tested

fps_erpnext.api.acc_dashboard does the role gate and the database reads, then
hands the raw rows to build_dashboard / build_metric_detail here. The payload
shape is dashboard/src/types/acc.ts; change both together.

READ-ONLY BY CONSTRUCTION. Nothing in this module can reach the database.

WHAT IT REUSES. The period windows, buckets, deltas, sparklines, weekly trend,
money formatting, routes, the invoiced / collected KPIs and drawers, the money
insights (duplicate drafts, invoicing stall, AR ageing) and delivered-not-
invoiced all come from command_center_logic unchanged, so the two pages can
never disagree on what "Invoiced (net)" or "AED 1.5M" means.

RAW ROWS. build_dashboard takes `raw`, a dict by source. A source that is
absent (or None) was not readable and everything built on it is left out --
never reported as zero, the same rule as the OPS page:

    "Sales Invoice"       command_center._read_invoices rows (submitted since
                          the floor, every open one however old, every draft)
    "Payment Entry"       submitted Receive and Pay entries since the floor,
                          plus every one with an unallocated amount
    "Purchase Invoice"    submitted since the floor, every open one, every draft
    "Supplier"            {supplier: supplier_group}
    "Job Order"           jobs at stage Delivered (delivered_not_invoiced)
    "FPS Bank Statement"  every statement (FPS-BST-<CODE>-<YYMM>)
    "GL"                  General Ledger sums, see build_balances:
                          {"cash": [{account, account_name, account_type,
                                     debit, credit}],
                           "qashio": {account, debit, credit} | None,
                           "vat_output": {account, debit, credit,
                                          voucher_types: {type: {debit, credit}}} | None,
                           "vat_input": (the same) | None,
                           "statements": [statement_checks() rows + debit, credit
                                          up to the statement's to_date],
                           "vat_purchases": {count, net, tax} | None}
                          The VAT sums cover vat_quarter(as_of).

THE CHOICES THAT ARE NOT OBVIOUS (review fixes of 14 Oct 2026 marked *):

* Ageing is by DUE date (not_due = due_date >= as_of), as the spec says. The
  "FPS Customer Receivables" report puts a document due TODAY in 0-30; here it
  is not due yet, the same as the "Overdue" line (due_date < as_of).
* A negative outstanding (credit / debit note, overpayment) is netted into its
  party and into the bucket of its own due date, so a bucket can be negative.
* (*) A payment not yet allocated to an invoice (Receive from a Customer, Pay
  to a Supplier, unallocated_amount > 0) is a negative open document too,
  aged by its posting date -- what the native Accounts Receivable / Payable
  reports and FPS Customer Receivables do. Receivables and payables (card
  value and ageing total) are therefore NET of money on account, and match the
  report each card opens. On 14 Oct 2026 AED 109,950 of Green Team receipts
  sat unallocated against AED 92,928 of its "overdue" invoices.
* (*) "Overdue" (card line, top-party overdue, supplier_overdue) is netted per
  party: the party's credits (notes and unallocated payments, whatever their
  date) clear its past-due documents oldest first. So a party's overdue never
  exceeds what it owes, and a debit note reversing an overdue bill clears it.
  Ageing.overdue is the same per-party figure, so card and panel agree; the
  buckets still place each credit in its own bucket, so the past-due buckets
  need not add up to it.
* Paid to suppliers (KPI key paid_out) = submitted Pay entries
  (base_paid_amount) + submitted purchase invoices paid at booking (is_paid =
  1, base_grand_total). Each document is counted once: a paid-at-booking bill
  has no outstanding, so no Pay entry can settle it as well. (*) Journal-entry
  outflows (salaries, partner drawings) are NOT in it, hence the name.
* VAT is UAE Stagger 3 (calendar quarters), due the 28th of the month after
  the quarter. The last completed quarter is shown up to and including its due
  date, then the running quarter to date. (*) Output and input VAT come from
  the voucher type of each posting on the two VAT accounts (sales invoices =
  output, purchase invoices = input), not from the account alone: on 14 Oct
  2026 the one input VAT posting of the quarter sat on the output account.
  Journal and payment postings (e.g. settling an earlier return) are left out
  of the net and shown on their own line.
* (*) Cash & bank stays the book balance (spec), but each bank account is
  compared with its latest statement's closing balance AT THE STATEMENT DATE;
  a gap over 1 % makes the card critical with a caveat naming it.
* (*) Bank statements: months_behind counts the months from go-live to last
  month with no reconciled statement (a missing month in the middle counts;
  last month still In Progress does not), and open_months names them.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import NamedTuple
from urllib.parse import quote

from fps_erpnext.api import command_center_logic as cc
from fps_erpnext.api.customs_clock import to_date

CURRENCY = cc.CURRENCY

KPI_ORDER = ("invoiced", "collected", "paid_out", "purchases")
BALANCE_ORDER = ("receivables", "payables", "cash", "vat")

# Fields each read selects. acc_dashboard passes these to frappe.get_list.
FIELDS = {
	"Sales Invoice": cc.FIELDS["Sales Invoice"],
	"Payment Entry": cc.FIELDS["Payment Entry"] + [
		"docstatus", "base_paid_amount", "unallocated_amount", "party_type"],
	"Purchase Invoice": ["name", "posting_date", "docstatus", "status", "is_paid", "is_return",
	                     "base_net_total", "base_grand_total", "outstanding_amount", "due_date",
	                     "supplier", "supplier_name", "mode_of_payment", "cash_bank_account",
	                     "bill_no"],
	"Supplier": ["name", "supplier_group"],
	"Job Order": ["name", "jo_date", "docstatus", "fps_stage"],
	"FPS Bank Statement": ["name", "bank_code", "month_code", "statement_month", "status",
	                       "closing_balance", "to_date"],
}

# Accounts resolved by account_name (company suffix added by the API). A missing
# one leaves its part of the payload out.
NAMED_ACCOUNTS = {
	"vat_output": "VAT 5%",                    # output VAT (Tax, liability)
	"vat_input": "Sales Taxes Receivables",    # input VAT (asset)
	"qashio": "Qashio Card Liability",         # Qashio card liability (payable)
}
CASH_ACCOUNT_TYPES = ("Bank", "Cash")

ROUTES = {
	"receivables": "/app/query-report/FPS%20Customer%20Receivables",
	"payables": "/app/query-report/Accounts%20Payable",
	"general_ledger": "/app/query-report/General%20Ledger",
}

# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------

# "Paid via" for a bill paid at booking with no mode of payment and no paying
# account recorded. With an account it reads "<bank> (paid at booking)": on
# 14 Oct 2026 every one of the 318 such bills was paid from ADCB, not a card.
PAID_AT_BOOKING_KEY = "__paid_at_booking__"
PAID_AT_BOOKING_LABEL = "Paid at booking"

METRICS = {
	"invoiced": cc.METRICS["invoiced"],
	"collected": cc.METRICS["collected"],
	"paid_out": {
		# Review 14 Oct 2026: "Paid out" read as every outflow, but journal
		# entries (salaries, partner drawings -- about a fifth of ADCB's
		# outflows over 90 days) are not in it. The key stays paid_out.
		"label": "Paid to suppliers",
		"definition": "Supplier payments: submitted Payment Entries of type Pay plus "
		              "purchase invoices paid at booking, by posting date. Salaries, "
		              "partner drawings and other journal entries are not included.",
		"unit": "currency", "good_direction": "none", "finance": True,
		# No "New" action: payments are booked from bank statements.
		"doctype": "Payment Entry", "new_doctype": None,
		"route": cc.list_route("Payment Entry", {"payment_type": "Pay", "docstatus": 1}),
		"dimension_label": "Paid via",
	},
	"purchases": {
		"label": "Purchases booked",
		"definition": "Net value (before VAT) of submitted purchase invoices, by posting "
		              "date, debit notes included.",
		"unit": "currency", "good_direction": "none", "finance": True,
		"doctype": "Purchase Invoice", "new_doctype": None,
		"route": cc.list_route("Purchase Invoice", {"docstatus": 1}),
		"dimension_label": "Supplier group",
	},
}

# Breakdown title in the drawer, per metric.
BREAKDOWN_TITLE = {
	"invoiced": "Top customers",
	"collected": "Top customers",
	"paid_out": "Top payees",
	"purchases": "Top suppliers",
}


def _text(value):
	return str(value).strip() if value is not None else ""


def _num(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _flag(value):
	return int(_num(value)) == 1


def _submitted(row):
	"""docstatus 1; a row read with a docstatus filter may not carry the field."""
	return int(_num(row.get("docstatus", 1))) == 1


def _signed(amount, is_return):
	"""A return (credit / debit note) is negative whatever sign it was stored with."""
	amount = cc.money(amount)
	return -abs(amount) if is_return else amount


def _point(row, d, value, dim, title, subtitle="", status="", doctype=None):
	p = cc._point(row, d, value, dim, title, subtitle, status, amount=value)
	p["doctype"] = doctype
	return p


def receipts_of(payment_rows):
	"""Customer receipts (Receive) among the payment rows -- what the OPS money
	functions (points_collected, receipt_lag_days) expect to be given."""
	return [r for r in payment_rows or []
	        if _submitted(r) and _text(r.get("payment_type")) == "Receive"]


def payments_out(payment_rows):
	return [r for r in payment_rows or []
	        if _submitted(r) and _text(r.get("payment_type")) == "Pay"]


def account_short(account):
	""""ADCB - Current Account - FPS" -> "ADCB": the first part of an account name."""
	account = _text(account)
	return account.split(" - ")[0].strip() or account


def paid_at_booking_dim(row):
	"""(key, label) of how a paid-at-booking bill was paid: its mode of payment,
	else the account it was paid from ("ADCB (paid at booking)")."""
	mode = _text(row.get("mode_of_payment"))
	if mode:
		return mode, mode
	account = _text(row.get("cash_bank_account"))
	if account:
		return account, "%s (paid at booking)" % account_short(account)
	return PAID_AT_BOOKING_KEY, PAID_AT_BOOKING_LABEL


def points_paid_out(payment_rows, purchase_rows):
	"""Pay entries (base_paid_amount) + paid-at-booking purchase invoices
	(base_grand_total), each document once. Dimension: how it was paid."""
	out = []
	seen = set()
	for r in payments_out(payment_rows):
		d = to_date(r.get("posting_date"))
		key = ("Payment Entry", _text(r.get("name")))
		if not d or key in seen:
			continue
		seen.add(key)
		amount = cc.money(_num(r.get("base_paid_amount")))
		ref = _text(r.get("reference_no"))
		out.append(_point(r, d, amount, cc._dim(r.get("mode_of_payment")),
		                  r.get("party_name") or r.get("party"),
		                  cc._join(r.get("mode_of_payment"), ("Ref " + ref) if ref else ""),
		                  "", doctype="Payment Entry"))
	for r in purchase_rows or []:
		d = to_date(r.get("posting_date"))
		key = ("Purchase Invoice", _text(r.get("name")))
		if not d or not _submitted(r) or not _flag(r.get("is_paid")) or key in seen:
			continue
		seen.add(key)
		is_return = _flag(r.get("is_return"))
		amount = _signed(_num(r.get("base_grand_total")), is_return)
		dim = paid_at_booking_dim(r)
		bill = _text(r.get("bill_no"))
		out.append(_point(r, d, amount, dim, r.get("supplier_name") or r.get("supplier"),
		                  cc._join(dim[1], "Debit note" if is_return else "",
		                           ("Bill " + bill) if bill else ""),
		                  r.get("status"), doctype="Purchase Invoice"))
	return out


def points_purchases(purchase_rows, supplier_groups=None):
	"""Submitted purchase invoices by posting date, value base_net_total, debit
	notes negative. Dimension: the supplier's group."""
	groups = supplier_groups or {}
	out = []
	for r in purchase_rows or []:
		d = to_date(r.get("posting_date"))
		if not d or not _submitted(r):
			continue
		is_return = _flag(r.get("is_return"))
		amount = _signed(_num(r.get("base_net_total")), is_return)
		bill = _text(r.get("bill_no"))
		out.append(_point(r, d, amount, cc._dim(groups.get(_text(r.get("supplier")))),
		                  r.get("supplier_name") or r.get("supplier"),
		                  cc._join("Debit note" if is_return else "",
		                           "Paid at booking" if _flag(r.get("is_paid")) else "",
		                           ("Bill " + bill) if bill else ""),
		                  r.get("status"), doctype="Purchase Invoice"))
	return out


def _supplier_groups(raw):
	groups = raw.get("Supplier")
	if isinstance(groups, dict):
		return groups
	return {_text(r.get("name")): r.get("supplier_group") for r in groups or []}


def metric_points(key, raw):
	"""Points for one ACC KPI, or None when a source it needs was not readable."""
	invoices = raw.get("Sales Invoice")
	payments = raw.get("Payment Entry")
	purchases = raw.get("Purchase Invoice")
	if key == "invoiced":
		return None if invoices is None else cc.points_invoiced(invoices)
	if key == "collected":
		return None if payments is None else cc.points_collected(receipts_of(payments))
	if key == "paid_out":
		if payments is None or purchases is None:
			return None   # half the money that left is not "paid out"
		return points_paid_out(payments, purchases)
	if key == "purchases":
		return None if purchases is None else points_purchases(purchases, _supplier_groups(raw))
	raise KeyError(key)


def _cc_raw(raw):
	"""The raw dict the OPS money helpers expect: receipts only under Payment Entry."""
	out = {}
	if raw.get("Sales Invoice") is not None:
		out["Sales Invoice"] = raw["Sales Invoice"]
	if raw.get("Payment Entry") is not None:
		out["Payment Entry"] = receipts_of(raw["Payment Entry"])
	return out


def drafts_waiting(rows):
	"""(count, grand total) of draft documents."""
	drafts = [r for r in rows or [] if int(_num(r.get("docstatus"))) == 0]
	return len(drafts), cc.money(sum(_num(r.get("base_grand_total")) for r in drafts))


def sales_drafts_line(invoice_rows):
	"""The "Drafts waiting" line for sales invoices, the duplicate drafts left out
	(review 14 Oct 2026: two drafts repeating paid invoices made AED 631.4K of the
	AED 1.8M). The label says how many were left out; duplicate_drafts names them."""
	duplicates = {_text(r.get("name")) for r in cc.duplicate_drafts(invoice_rows)}
	drafts = [r for r in invoice_rows or []
	          if int(_num(r.get("docstatus"))) == 0 and _text(r.get("name")) not in duplicates]
	n, value = drafts_waiting(drafts)
	label = ("Drafts excl. %d %s" % (len(duplicates), cc.plural(len(duplicates), "duplicate", "duplicates"))
	         if duplicates else "Drafts waiting")
	return _count_money_line(label, n, value)


def kpi_context(key, points, raw, *, period, as_of):
	"""Up to two pre-formatted facts under an ACC KPI value."""
	as_of = to_date(as_of)
	if key in ("invoiced", "collected"):
		lines = cc.kpi_context(key, points=points, raw=_cc_raw(raw), stages=None,
		                       period=period, as_of=as_of, finance=True)
		invoices = raw.get("Sales Invoice")
		out = []
		for line in lines:
			if line["label"] == "Drafts waiting" and invoices is not None:
				line = sales_drafts_line(invoices)
			elif line["label"] == "Outstanding AR" and invoices is not None:
				# The receivables card's figure: net of receipts on account.
				line = _money_line("Outstanding AR", receivables_total(invoices, raw.get("Payment Entry")))
			out.append(line)
		return out
	current, _previous = cc.period_windows(period, as_of)
	in_window = [p for p in points if p["date"] in current]
	if key == "paid_out":
		paid = sum(p["value"] for p in in_window if p["doctype"] == "Payment Entry")
		card = sum(p["value"] for p in in_window if p["doctype"] == "Purchase Invoice")
		return [cc._line("Supplier payments", cc.format_money_compact(paid)),
		        cc._line("Paid at booking", cc.format_money_compact(card))]
	if key == "purchases":
		bills = sum(1 for p in in_window if p["value"] >= 0)
		n, value = drafts_waiting(raw.get("Purchase Invoice"))
		return [cc._line("Bills", cc.format_count(bills)),
		        cc._line("Drafts waiting", "%s · %s" % (cc.format_count(n),
		                                                cc.format_money_compact(value)))]
	return []


def caveat_for(key, raw, as_of):
	"""The honest caveat a KPI, trend mode or drawer carries, or None."""
	as_of = to_date(as_of)
	if key == "collected":
		return cc.caveat_for("collected", _cc_raw(raw), as_of)
	if key == "paid_out" and raw.get("FPS Bank Statement") is not None:
		open_banks = [b for b in bank_statuses(raw["FPS Bank Statement"], as_of)
		              if b["months_behind"] > 0 or b["status"] != "Reconciled"]
		if open_banks:
			return ("Payments are booked as bank statements are reconciled, and %s %s not "
			        "reconciled up to %s yet, so recent weeks fill in later."
			        % (_and([b["label"] for b in open_banks]),
			           cc.plural(len(open_banks), "is", "are"),
			           month_label(last_month_start(as_of))))
	return None


def build_kpi(key, points, *, period, as_of, raw, creatable=()):
	spec = METRICS[key]
	summary = cc.summarize(points, period, as_of, spec["unit"], first_seen=cc._first_seen(points))
	kpi = {
		"key": key,
		"label": spec["label"],
		"definition": spec["definition"],
		"unit": spec["unit"],
		"currency": CURRENCY,
		"value": summary["value"],
		"previous": summary["previous"],
		"delta_pct": summary["delta_pct"],
		"good_direction": spec["good_direction"],
		"granularity": summary["granularity"],
		"series": summary["series"],
		"context": kpi_context(key, points, raw, period=period, as_of=as_of),
		"route": spec["route"],
		"finance": True,
	}
	caveat = caveat_for(key, raw, as_of)
	if caveat:
		kpi["caveat"] = caveat
	if spec["new_doctype"] and spec["new_doctype"] in set(creatable or ()):
		kpi["new_doctype"] = spec["new_doctype"]
	return cc._ordered(kpi, cc.KpiKeys)


# --------------------------------------------------------------------------
# Ageing
# --------------------------------------------------------------------------

AGEING_BUCKETS = (
	("not_due", "Not due"),
	("0_30", "0–30"),
	("31_60", "31–60"),
	("61_90", "61–90"),
	("91_180", "91–180"),
	("181_365", "181–365"),
	("over_365", "Over 365"),
)
TOP_PARTIES = 5


def days_past_due(row, as_of):
	"""as_of - due_date in days (posting_date when there is no due date); None
	when the row has neither. 0 or less means not due yet."""
	due = to_date(row.get("due_date")) or to_date(row.get("posting_date"))
	if not due:
		return None
	return (to_date(as_of) - due).days


def bucket_key(days):
	"""Ageing bucket for a days-past-due figure (None: not due)."""
	if days is None or days <= 0:
		return "not_due"
	if days <= 30:
		return "0_30"
	if days <= 60:
		return "31_60"
	if days <= 90:
		return "61_90"
	if days <= 180:
		return "91_180"
	if days <= 365:
		return "181_365"
	return "over_365"


def open_documents(rows):
	"""Submitted documents that still carry an outstanding amount (either sign)."""
	return [r for r in rows or []
	        if int(_num(r.get("docstatus"))) == 1 and abs(_num(r.get("outstanding_amount"))) >= 0.005]


AGEING_SPEC = {
	"receivables": {"label": "Receivables", "party": "customer", "party_name": "customer_name",
	                "doctype": "Sales Invoice", "route": ROUTES["receivables"],
	                "payment_type": "Receive", "party_type": "Customer"},
	"payables": {"label": "Payables", "party": "supplier", "party_name": "supplier_name",
	             "doctype": "Purchase Invoice", "route": ROUTES["payables"],
	             "payment_type": "Pay", "party_type": "Supplier"},
}


def unallocated(payment_rows, payment_type):
	"""(amount, rows) of submitted entries of this type with an unallocated amount
	-- receipts from customers (Receive) or payments to suppliers (Pay). A row read
	without party_type is taken as the usual party for its type."""
	party_type = {"Receive": "Customer", "Pay": "Supplier"}.get(payment_type)
	hits = [r for r in payment_rows or []
	        if _submitted(r) and _text(r.get("payment_type")) == payment_type
	        and _num(r.get("unallocated_amount")) > 0
	        and _text(r.get("party_type")) in ("", party_type)]
	return cc.money(sum(_num(r.get("unallocated_amount")) for r in hits)), hits


def payment_documents(kind, payment_rows):
	"""Payments not yet allocated, as open documents with a NEGATIVE outstanding,
	dated (and due) on their posting date -- how the native Accounts Receivable /
	Payable reports age them. Marked "_payment" so counts of invoices skip them."""
	spec = AGEING_SPEC[kind]
	_total, hits = unallocated(payment_rows, spec["payment_type"])
	return [{
		"name": _text(r.get("name")),
		"docstatus": 1,
		"posting_date": r.get("posting_date"),
		"due_date": r.get("posting_date"),
		"outstanding_amount": -cc.money(_num(r.get("unallocated_amount"))),
		spec["party"]: _text(r.get("party")),
		spec["party_name"]: _text(r.get("party_name")) or _text(r.get("party")),
		"_payment": True,
	} for r in hits]


def ageing_documents(kind, rows, payment_rows=None):
	"""Open invoices / bills plus the matching payments on account."""
	return open_documents(rows) + payment_documents(kind, payment_rows)


def party_positions(kind, docs, as_of):
	"""{party: position} for open documents (ageing_documents).

	position: party, label, value (net outstanding), count (open invoices or bills,
	payments on account not counted), overdue, oldest_days and overdue_docs. The
	party's credits -- every negative document, notes and payments on account,
	whatever their date -- clear its past-due documents oldest first; overdue is
	what is left, oldest_days the days past due of the oldest document still open
	after that (0 when nothing is), overdue_docs those documents."""
	spec = AGEING_SPEC[kind]
	as_of = to_date(as_of)
	parties = {}
	for r in docs:
		amount = _num(r.get("outstanding_amount"))
		party = _text(r.get(spec["party"])) or cc.NO_PARTY
		p = parties.setdefault(party, {"party": party,
		                               "label": _text(r.get(spec["party_name"])) or party,
		                               "value": 0.0, "count": 0, "credit": 0.0, "past_due": []})
		p["value"] += amount
		if not r.get("_payment"):
			p["count"] += 1
		days = days_past_due(r, as_of)
		if amount < 0:
			p["credit"] -= amount
		elif days is not None and days > 0:
			p["past_due"].append((days, _text(r.get("name")), amount, r))
	for p in parties.values():
		credit = p.pop("credit")
		left = []
		for days, name, amount, r in sorted(p.pop("past_due"), key=lambda x: (-x[0], x[1])):
			used = min(credit, amount)
			credit -= used
			if amount - used >= 0.005:
				left.append((days, name, amount - used, r))
		p["value"] = cc.money(p["value"])
		p["overdue"] = cc.money(sum(x[2] for x in left))
		p["oldest_days"] = left[0][0] if left else 0
		p["overdue_docs"] = left
	return parties


def overdue_net(kind, docs, as_of):
	"""(amount, positions): the parties' overdue after their credits (party_positions),
	only the parties that still have some."""
	hits = [p for p in party_positions(kind, docs, as_of).values() if p["overdue"] > 0]
	return cc.money(sum(p["overdue"] for p in hits)), hits


def _ageing_caveat(kind, payment_rows):
	spec = AGEING_SPEC[kind]
	total, hits = unallocated(payment_rows, spec["payment_type"])
	if total <= 0:
		return None
	what = ("received from customers" if kind == "receivables" else "paid to suppliers")
	return ("Net of %s %s but not yet allocated to %s (%d %s), aged by payment date, as in "
	        "the full report." % (cc.format_money_compact(total), what,
	                              "invoices" if kind == "receivables" else "bills",
	                              len(hits), cc.plural(len(hits), "payment", "payments")))


def build_ageing(kind, rows, as_of, payment_rows=None):
	"""Ageing for "receivables" (Sales Invoice rows) or "payables" (Purchase Invoice
	rows), net of the payments on account among payment_rows (Payment Entry rows)."""
	spec = AGEING_SPEC[kind]
	as_of = to_date(as_of)
	docs = ageing_documents(kind, rows, payment_rows)
	sums = {k: 0.0 for k, _label in AGEING_BUCKETS}
	counts = {k: 0 for k, _label in AGEING_BUCKETS}
	for r in docs:
		b = bucket_key(days_past_due(r, as_of))
		sums[b] += _num(r.get("outstanding_amount"))
		counts[b] += 1
	buckets = [{"key": k, "label": label, "value": cc.money(sums[k]), "count": counts[k]}
	           for k, label in AGEING_BUCKETS]
	ranked = sorted((p for p in party_positions(kind, docs, as_of).values() if p["value"] > 0),
	                key=lambda p: (-p["value"], p["label"], p["party"]))
	top = []
	for p in ranked[:TOP_PARTIES]:
		top.append({
			"party": p["party"],
			"label": p["label"],
			"value": p["value"],
			"overdue": p["overdue"],
			"oldest_days": int(p["oldest_days"]),
			"count": p["count"],
			"route": cc.list_route(spec["doctype"], {
				spec["party"]: p["party"], "docstatus": 1, "outstanding_amount": ["!=", 0]}),
		})
	ageing = {
		"key": kind,
		"label": spec["label"],
		"currency": CURRENCY,
		"total": _net_total(docs),   # the balance card's value, computed the same way
		# Same figure as the balance card's "Overdue" line (per party, net of its
		# credits), so the page shows one overdue number per side (Agam's review,
		# 14 Oct 2026: 617.5K on the card vs 600.5K on the panel read as an error).
		"overdue": overdue_net(kind, docs, as_of)[0],
		"buckets": buckets,
		"top": top,
		"route": spec["route"],
	}
	caveat = _ageing_caveat(kind, payment_rows)
	if caveat:
		ageing["caveat"] = caveat
	return ageing


# --------------------------------------------------------------------------
# Balances (as of today)
# --------------------------------------------------------------------------

BalanceKeys = ("key", "label", "definition", "currency", "value", "context", "severity",
               "caveat", "route")
OVERDUE_SHARE_WARNING = 0.5
VAT_WARNING_DAYS = 14


def _money_line(label, value):
	return cc._line(label, cc.format_money_compact(value))


def _count_money_line(label, n, value):
	return cc._line(label, "%s · %s" % (cc.format_count(n), cc.format_money_compact(value)))


def _net_total(docs):
	return cc.money(sum(_num(r.get("outstanding_amount")) for r in docs))


def receivables_total(invoices, payments=None):
	"""Outstanding on submitted sales invoices less receipts on account -- the
	receivables card value and the receivables ageing total."""
	return _net_total(ageing_documents("receivables", invoices, payments))


def balance_receivables(invoices, payments, as_of):
	docs = ageing_documents("receivables", invoices, payments)
	total = _net_total(docs)
	overdue, _parties = overdue_net("receivables", docs, as_of)
	context = [_money_line("Overdue", overdue),
	           cc._line("Open invoices", cc.format_count(len(open_documents(invoices))))]
	if payments is not None:
		context.append(_money_line("Less unallocated receipts", unallocated(payments, "Receive")[0]))
	context.append(sales_drafts_line(invoices))
	card = {
		"key": "receivables",
		"label": "Receivables",
		"definition": "Outstanding on submitted sales invoices less customer receipts not yet "
		              "allocated to an invoice, credit notes netted, the invoices carried over "
		              "from Fresa included. Overdue is net of each customer's own credits, so it "
		              "can exceed the total when some customers are in credit.",
		"currency": CURRENCY,
		"value": total,
		"context": context[:4],
		"route": ROUTES["receivables"],
	}
	if total > 0 and overdue / total >= OVERDUE_SHARE_WARNING:
		card["severity"] = "warning"
	return cc._ordered(card, BalanceKeys)


def balance_payables(bills, payments, as_of):
	docs = ageing_documents("payables", bills, payments)
	total = _net_total(docs)
	overdue, _parties = overdue_net("payables", docs, as_of)
	context = [_money_line("Overdue", overdue),
	           cc._line("Open bills", cc.format_count(len(open_documents(bills))))]
	if payments is not None:
		context.append(_money_line("Less unallocated payments", unallocated(payments, "Pay")[0]))
	context.append(cc._line("Draft bills", cc.format_count(drafts_waiting(bills)[0])))
	return cc._ordered({
		"key": "payables",
		"label": "Payables",
		"definition": "Outstanding on submitted purchase invoices less supplier payments not "
		              "yet allocated to a bill, debit notes netted. Overdue is net of each "
		              "supplier's own debit notes and payments on account, so it can exceed the "
		              "total when some suppliers are in credit.",
		"currency": CURRENCY,
		"value": total,
		"context": context[:4],
		"route": ROUTES["payables"],
	}, BalanceKeys)


def _balance(row, credit_side=False):
	"""debit - credit (credit - debit for a credit-side account), each side
	rounded to fils first so float noise cannot move the last fils."""
	if not row:
		return 0.0
	value = cc.money(_num(row.get("debit"))) - cc.money(_num(row.get("credit")))
	return cc.money(-value if credit_side else value)


def report_route(base, filters):
	"""Query-report URL; list values go as JSON (query_report.js parses a value
	starting with "[" as a multi-select)."""
	parts = []
	for field, value in filters.items():
		if value is None:
			continue
		if isinstance(value, list | tuple):
			value = json.dumps(list(value), separators=(",", ":"))
		parts.append("%s=%s" % (field, quote(str(value), safe="")))
	return base + ("?" + "&".join(parts) if parts else "")


# Bank accounts whose latest statement is compared with the ledger (QGEN / QGOV
# are Qashio card statements; the card has no Bank-type account).
STATEMENT_BANKS = ("ADCB", "WIO")
# A book balance more than this far from the statement (at the statement date)
# makes the cash card critical: 1 % of the statement, at least AED 100.
STATEMENT_GAP_SHARE = 0.01
STATEMENT_GAP_MIN = 100.0
CASH_CAVEAT = "Book balances from ERPNext, not bank statements."


def statement_checks(account_rows, statement_rows):
	"""What to compare the cash card with: for each STATEMENT_BANKS bank whose
	latest statement has a closing balance, {bank, label, statement, to_date
	(yyyy-mm-dd), closing_balance, account}. account is the one Bank / Cash
	account whose name carries the bank code as a word ("ADCB - Current Account
	- FPS"), or None when there is none. A bank matching two accounts is left out
	(which account the statement belongs to is not known)."""
	latest = _latest_statements(statement_rows)
	out = []
	for code, label in BANKS:
		if code not in STATEMENT_BANKS or code not in latest:
			continue
		(month, name), r = latest[code]
		if r.get("closing_balance") is None:
			continue
		word = re.compile(r"\b%s\b" % re.escape(code), re.I)
		matches = sorted({_text(a.get("name") or a.get("account")) for a in account_rows or []
		                  if word.search(_text(a.get("account_name")) or _text(a.get("name") or a.get("account")))})
		if len(matches) > 1:
			continue
		end = to_date(r.get("to_date")) or (_add_months(month, 1) - timedelta(days=1))
		out.append({"bank": code, "label": label, "statement": name, "to_date": end.isoformat(),
		            "closing_balance": cc.money(_num(r.get("closing_balance"))),
		            "account": matches[0] if matches else None})
	return out


def _short_day(d):
	d = to_date(d)
	return "%d %s" % (d.day, cc.MONTHS[d.month - 1])


def cash_statement_gaps(gl):
	"""(gaps, unbooked, statements) from gl["statements"]: gaps = [(row, book, gap)]
	where the ledger at the statement date is off by more than the tolerance;
	unbooked = statements of banks with no ledger account."""
	statements = [s for s in (gl or {}).get("statements") or [] if s]
	gaps, unbooked = [], []
	for s in statements:
		closing = cc.money(_num(s.get("closing_balance")))
		if not s.get("account"):
			unbooked.append(s)
			continue
		book = _balance(s)
		gap = cc.money(book - closing)
		if abs(gap) > max(STATEMENT_GAP_SHARE * abs(closing), STATEMENT_GAP_MIN):
			gaps.append((s, book, gap))
	return gaps, unbooked, statements


def _cash_caveat(gaps, unbooked):
	parts = []
	for s, _book, gap in gaps:
		parts.append("ERPNext's %s balance on %s is %s %s its bank statement (%s)" % (
			s["label"], _short_day(s["to_date"]), cc.format_money_compact(abs(gap)),
			"above" if gap > 0 else "below", cc.format_money_compact(s["closing_balance"])))
	text = ""
	if parts:
		text = ("; ".join(parts) + ", so this figure is not the bank position until the ledger "
		        "is reconciled.")
	else:
		text = CASH_CAVEAT
	if unbooked:
		text += " %s %s no ledger account, so %s not in this figure." % (
			_and("%s (statement %s)" % (s["label"], cc.format_money_compact(s["closing_balance"]))
			     for s in unbooked),
			cc.plural(len(unbooked), "has", "have"), cc.plural(len(unbooked), "it is", "they are"))
	return text


def balance_cash(gl, company, as_of):
	"""Book balance of every Bank / Cash account, or None when not readable.

	Context, most useful first, up to four: the largest account; the latest bank
	statements' closing balances; the gap between the books and those statements
	(at the statement date) when it is over the tolerance; the Qashio card
	account; the next largest accounts. A gap makes the card critical."""
	rows = (gl or {}).get("cash")
	if rows is None:
		return None
	balances = [(_text(r.get("account_name")) or _text(r.get("account")), _balance(r)) for r in rows]
	total = cc.money(sum(v for _label, v in balances))
	top = sorted((b for b in balances if b[1] != 0), key=lambda b: (-abs(b[1]), b[0]))[:3]
	gaps, unbooked, statements = cash_statement_gaps(gl)

	context = [_money_line(label, value) for label, value in top[:1]]
	if statements:
		days = sorted({s["to_date"] for s in statements})
		label = ("Bank statements, %s" % _short_day(days[0])) if len(days) == 1 else "Latest bank statements"
		context.append(_money_line(label, sum(s["closing_balance"] for s in statements)))
	if gaps:
		gap = cc.money(sum(g for _s, _b, g in gaps))
		context.append(_money_line("Books %s statements" % ("above" if gap >= 0 else "below"), abs(gap)))
	qashio = (gl or {}).get("qashio")
	if qashio:
		liability = _balance(qashio, credit_side=True)
		if liability > 0:
			context.append(_money_line("Qashio card liability", liability))
		elif liability < 0:
			# A debit balance: more was topped up than card bills booked against it
			# (on 14 Oct 2026 AED 38.3K of it is supplier payments on account,
			# which the payables card already nets).
			context.append(_money_line("Qashio top-ups unmatched", -liability))
	context += [_money_line(label, value) for label, value in top[1:]]

	card = {
		"key": "cash",
		"label": "Cash & bank",
		"definition": "General Ledger balance of every bank and cash account, up to today, "
		              "checked against each bank's latest statement at its closing date.",
		"currency": CURRENCY,
		"value": total,
		"context": context[:4],
		"caveat": _cash_caveat(gaps, unbooked),
		"route": report_route(ROUTES["general_ledger"], {
			"company": company,
			"to_date": to_date(as_of).isoformat(),
			"account": sorted(_text(r.get("account")) for r in rows) or None,
			"group_by": "Group by Account",
		}),
	}
	if gaps:
		card["severity"] = "critical"
	return cc._ordered(card, BalanceKeys)


class Quarter(NamedTuple):
	start: date
	end: date          # last day of the quarter
	due: date          # the return's due date
	completed: bool    # the quarter has ended
	window_end: date   # last day the figures cover (end, or as_of when running)

	@property
	def label(self):
		return "%s–%s %d" % (cc.MONTHS[self.start.month - 1], cc.MONTHS[self.end.month - 1],
		                     self.end.year)


def _quarter_start(d):
	return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _add_months(d, n):
	months = d.year * 12 + (d.month - 1) + n
	return date(months // 12, months % 12 + 1, 1)


def vat_due_date(quarter_end):
	"""UAE VAT: the 28th of the month after the period ends."""
	return _add_months(quarter_end, 1).replace(day=28)


def vat_quarter(as_of):
	"""The quarter the VAT card shows on as_of (Stagger 3 = calendar quarters).

	The last completed quarter while its due date has not passed (the due day
	itself included), otherwise the running quarter to date."""
	as_of = to_date(as_of)
	current = _quarter_start(as_of)
	prev_end = current - timedelta(days=1)
	prev_start = _quarter_start(prev_end)
	prev_due = vat_due_date(prev_end)
	if as_of <= prev_due:
		return Quarter(prev_start, prev_end, prev_due, True, prev_end)
	end = _add_months(current, 3) - timedelta(days=1)
	return Quarter(current, end, vat_due_date(end), False, as_of)


def full_date(d):
	d = to_date(d)
	return "%d %s %d" % (d.day, cc.MONTHS[d.month - 1], d.year)


def days_phrase(days):
	if days == 0:
		return "today"
	if days < 0:
		return "%d %s late" % (-days, cc.plural(-days, "day", "days"))
	return "%d %s" % (days, cc.plural(days, "day", "days"))


OUTPUT_VAT_VOUCHERS = ("Sales Invoice", "POS Invoice")
INPUT_VAT_VOUCHERS = ("Purchase Invoice",)
# Input VAT below this share of the quarter's purchases (before VAT) is called out.
INPUT_VAT_LOW_SHARE = 0.01
VAT_CAVEAT = "From ERPNext postings; the return filed on EmaraTax may differ."


class VatFigures(NamedTuple):
	output: float | None   # None: the output VAT account does not exist
	input: float | None    # None: no VAT account to read it from
	other: float           # journal / payment postings, credit - debit, left out of the net

	@property
	def net(self):
		return cc.money((self.output or 0) - (self.input or 0))


def vat_figures(gl):
	"""VatFigures for the quarter, or None when neither VAT account exists.

	With the per-voucher-type sums the API reads (row["voucher_types"]), the
	split is by what posted: sales invoices are output VAT (credit - debit, so
	credit notes net), purchase invoices input VAT (debit - credit), on either
	account -- on 14 Oct 2026 the quarter's one input VAT posting (AED 99) sat on
	"VAT 5%". Anything else (journal entries settling an earlier return, payments
	to the FTA) is `other`, kept out of the net. Rows without the split fall back
	to the account: output = VAT 5% credit - debit, input = Sales Taxes
	Receivables debit - credit."""
	gl = gl or {}
	out_row, in_row = gl.get("vat_output"), gl.get("vat_input")
	if not out_row and not in_row:
		return None
	rows = [r for r in (out_row, in_row) if r]
	if all(isinstance(r.get("voucher_types"), dict) for r in rows):
		output = input_ = other = 0.0
		for r in rows:
			for vtype, s in r["voucher_types"].items():
				debit, credit = cc.money(_num(s.get("debit"))), cc.money(_num(s.get("credit")))
				if vtype in OUTPUT_VAT_VOUCHERS:
					output += credit - debit
				elif vtype in INPUT_VAT_VOUCHERS:
					input_ += debit - credit
				else:
					other += credit - debit
		return VatFigures(cc.money(output) if out_row else None, cc.money(input_), cc.money(other))
	output = _balance(out_row, credit_side=True) if out_row else None
	input_ = _balance(in_row) if in_row else None
	return VatFigures(output, input_, 0.0)


def vat_input_low(figures, purchases):
	"""True when the quarter has purchase bills but almost no input VAT is posted
	(under INPUT_VAT_LOW_SHARE of their value before VAT)."""
	if not purchases or not int(_num(purchases.get("count"))):
		return False
	net = _num(purchases.get("net"))
	return net > 0 and (figures.input or 0) < INPUT_VAT_LOW_SHARE * net


def vat_caveat(figures, purchases, quarter):
	"""The VAT card's caveat: specific when input VAT looks missing."""
	if not vat_input_low(figures, purchases):
		return VAT_CAVEAT
	n = int(_num(purchases.get("count")))
	posted = ("No input VAT is" if not figures.input
	          else "Only %s of input VAT is" % cc.format_money_compact(figures.input))
	return ("%s posted in ERPNext for %s, on %d purchase %s worth %s before VAT, so the net is "
	        "close to output VAT alone. Check reclaimable input VAT before filing; the return "
	        "filed on EmaraTax may differ." % (posted, quarter.label, n, cc.plural(n, "bill", "bills"),
	                                            cc.format_money_compact(_num(purchases.get("net")))))


def vat_severity(days_left):
	if days_left < 0:
		return "critical"
	if days_left <= VAT_WARNING_DAYS:
		return "warning"
	return None


def vat_route(gl, company, quarter):
	accounts = [row["account"] for row in (gl.get("vat_output"), gl.get("vat_input")) if row]
	return report_route(ROUTES["general_ledger"], {
		"company": company,
		"from_date": quarter.start.isoformat(),
		"to_date": quarter.window_end.isoformat(),
		"account": accounts,
		"group_by": "Group by Account",
	})


def balance_vat(gl, company, as_of):
	"""Net VAT for vat_quarter(as_of), or None when neither VAT account exists."""
	if gl is None:
		return None
	figures = vat_figures(gl)
	if figures is None:
		return None
	as_of = to_date(as_of)
	q = vat_quarter(as_of)
	days_left = (q.due - as_of).days
	context = []
	if figures.output is not None:
		context.append(_money_line("Output VAT", figures.output))
	if figures.input is not None:
		context.append(_money_line("Input VAT", figures.input))
	context.append(cc._line("Due date", "%s · %s" % (full_date(q.due), days_phrase(days_left))))
	if figures.other:
		context.append(_money_line("Other postings, left out", figures.other))
	card = {
		"key": "vat",
		"label": "VAT " + q.label,
		"definition": ("Output VAT (sales invoices) less input VAT (purchase invoices) posted to "
		               "the VAT accounts in the quarter%s; positive means payable. Journal and "
		               "payment postings are left out. UAE VAT Stagger 3, return due on the 28th "
		               "of the month after the quarter." % ("" if q.completed else " so far")),
		"currency": CURRENCY,
		"value": figures.net,
		"context": context[:4],
		"caveat": vat_caveat(figures, gl.get("vat_purchases"), q),
		"route": vat_route(gl, company, q),
	}
	severity = vat_severity(days_left)
	if severity:
		card["severity"] = severity
	return cc._ordered(card, BalanceKeys)


def build_balances(raw, company, as_of):
	cards = []
	invoices, bills = raw.get("Sales Invoice"), raw.get("Purchase Invoice")
	payments = raw.get("Payment Entry")
	if invoices is not None:
		cards.append(balance_receivables(invoices, payments, as_of))
	if bills is not None:
		cards.append(balance_payables(bills, payments, as_of))
	for card in (balance_cash(raw.get("GL"), company, as_of),
	             balance_vat(raw.get("GL"), company, as_of)):
		if card:
			cards.append(card)
	return cards


# --------------------------------------------------------------------------
# Bank statements
# --------------------------------------------------------------------------

BANKS = (("ADCB", "ADCB"), ("WIO", "WIO"),
         ("QGEN", "Qashio – General"), ("QGOV", "Qashio – Government"))
# First statement month on the site (FPS-BST-*-2606). A bank with no statement
# at all is behind by every month from here to last month.
BANK_GO_LIVE = date(2026, 6, 1)
BANK_STATUSES = ("Reconciled", "In Progress")
BankStatusKeys = ("bank", "label", "latest_month", "status", "closing_balance",
                  "months_behind", "open_months", "route")


def last_month_start(as_of):
	return _add_months(to_date(as_of).replace(day=1), -1)


def months_between(a, b):
	"""Whole calendar months from a's month to b's month."""
	return (b.year - a.year) * 12 + (b.month - a.month)


def month_label(d):
	return "%s %d" % (cc.MONTHS[d.month - 1], d.year)


def statement_month(row):
	"""First day of a statement's month from month_code (YYMM) or the name's
	-<YYMM> suffix; None when neither parses."""
	for code in (_text(row.get("month_code")), _text(row.get("name")).rsplit("-", 1)[-1]):
		if len(code) == 4 and code.isdigit() and 1 <= int(code[2:]) <= 12:
			return date(2000 + int(code[:2]), int(code[2:]), 1)
	return None


def statement_bank(row):
	code = _text(row.get("bank_code"))
	if code:
		return code.upper()
	parts = _text(row.get("name")).split("-")
	return parts[2].upper() if len(parts) >= 4 and parts[0] == "FPS" and parts[1] == "BST" else ""


def _statements_by_month(rows):
	"""{code: {first day of month: (name, row)}}, one statement per bank and month:
	a month with two statements (a mid-month file and the full month) keeps the
	higher name."""
	out = {}
	for r in rows or []:
		code, month = statement_bank(r), statement_month(r)
		if not code or not month:
			continue
		name = _text(r.get("name"))
		months = out.setdefault(code, {})
		if month not in months or name > months[month][0]:
			months[month] = (name, r)
	return out


def _latest_statements(rows):
	"""{code: ((month, name), row)}: each bank's latest statement (highest YYMM)."""
	latest = {}
	for code, months in _statements_by_month(rows).items():
		month = max(months)
		name, r = months[month]
		latest[code] = ((month, name), r)
	return latest


def _status(row):
	status = _text(row.get("status"))
	return status if status in BANK_STATUSES else "In Progress"


def open_months(by_month, as_of):
	"""[(month, "missing" | "in progress")]: the months from go-live to LAST month
	with no reconciled statement. Last month's statement still In Progress is not
	open -- it is reconciled during the running month -- but a missing one is.
	Review 14 Oct 2026: ADCB had no July statement and read "0 months behind"
	because only its latest month (Sep) was looked at."""
	last = last_month_start(as_of)
	out = []
	month = BANK_GO_LIVE
	while month <= last:
		entry = (by_month or {}).get(month)
		if entry is None:
			out.append((month, "missing"))
		elif _status(entry[1]) != "Reconciled" and month < last:
			out.append((month, "in progress"))
		month = _add_months(month, 1)
	return out


def open_months_text(months, as_of):
	""""Jul missing, Aug–Sep in progress": runs of consecutive months in the same
	state. The year is named only when it is not as_of's."""
	year = to_date(as_of).year

	def name(m):
		return cc.MONTHS[m.month - 1] + ("" if m.year == year else " %d" % m.year)

	runs = []
	for month, state in months:
		if runs and runs[-1][2] == state and _add_months(runs[-1][1], 1) == month:
			runs[-1][1] = month
		else:
			runs.append([month, month, state])
	return ", ".join("%s %s" % (name(a) if a == b else "%s–%s" % (name(a), name(b)), state)
	                 for a, b, state in runs)


def _bank_rows(rows, as_of):
	"""BankStatus dicts, ADCB, WIO, QGEN, QGOV in that order. latest_month, status
	and closing_balance are the latest statement's (highest YYMM); months_behind
	and open_months come from every month since go-live (open_months)."""
	by_bank = _statements_by_month(rows)
	out = []
	for code, label in BANKS:
		months = by_bank.get(code) or {}
		gaps = open_months(months, as_of)
		row = {"bank": code, "label": label, "months_behind": len(gaps)}
		if gaps:
			row["open_months"] = open_months_text(gaps, as_of)
		if months:
			month = max(months)
			name, r = months[month]
			row.update({
				"latest_month": month_label(month),
				"status": _status(r),
				"closing_balance": (cc.money(_num(r.get("closing_balance")))
				                    if r.get("closing_balance") is not None else None),
				"route": cc.form_route("FPS Bank Statement", name),
			})
		else:
			row.update({"latest_month": None, "status": "Missing", "closing_balance": None,
			            "route": cc.list_route("FPS Bank Statement", {"bank_code": code})})
		out.append(cc._ordered(row, BankStatusKeys))
	return out


def bank_statuses(rows, as_of):
	"""BankStatus list (acc.ts), ADCB, WIO, QGEN, QGOV in that order."""
	return _bank_rows(rows, as_of)


def banks_behind(rows, as_of):
	"""BankStatus dicts of the banks with a month since go-live, up to last month,
	that is not reconciled (months_behind >= 1). `rows` are FPS Bank Statement rows."""
	return [b for b in _bank_rows(rows, as_of) if b["months_behind"] >= 1]


# --------------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------------

TREND_MODES = (
	("billing", "Billing", (("invoiced", "Invoiced (net)", 1), ("collected", "Collected", 2))),
	("cashflow", "Cash flow", (("collected", "Collected", 1),
	                           ("paid_out", METRICS["paid_out"]["label"], 2))),
)


def build_trend(points_by_key, raw, as_of):
	"""TrendMode list. A series is shown only when its KPI could be computed."""
	as_of = to_date(as_of)
	modes = []
	weeks = cc.trend_week_starts(as_of)
	for mode_key, label, series_spec in TREND_MODES:
		series = [(k, l, slot) for k, l, slot in series_spec if k in points_by_key]
		if not series:
			continue
		columns = {k: cc.weekly_totals(cc._pairs(points_by_key[k]), as_of) for k, _l, _s in series}
		points = [{
			"week_start": w.isoformat(),
			"label": cc.short_date(w),
			"partial": w <= as_of <= w + timedelta(days=6),
			"values": {k: cc.money(columns[k][i][1]) for k, _l, _s in series},
		} for i, w in enumerate(weeks)]
		mode = {
			"key": mode_key, "label": label, "unit": "currency", "currency": CURRENCY,
			"series": [{"key": k, "label": l, "slot": slot} for k, l, slot in series],
			"points": points, "finance": True,
		}
		if "collected" in points_by_key:
			caveat = caveat_for("collected", raw, as_of)
			if caveat:
				mode["caveat"] = caveat
		modes.append(cc._ordered(mode, ("key", "label", "unit", "currency", "series",
		                                "points", "caveat", "finance")))
	return modes


# --------------------------------------------------------------------------
# Insights
#
#   id                      severity              what
#   vat_due                 critical | warning    VAT return due within 14 days / late
#   duplicate_drafts        warning               (OPS R3) a draft repeats a submitted invoice
#   invoicing_stall         warning               (OPS R2) no invoice for 10+ days, drafts waiting
#   unallocated_receipts    warning               receipts not matched to invoices
#   supplier_overdue        warning | info        past-due payables (warning over AED 50K)
#   bank_statements_behind  warning               statements not reconciled up to last month
#   ar_ageing               info                  (OPS R7) 40%+ of AR over 90 days past due
#   delivered_not_invoiced  info                  (OPS R6) jobs at stage Delivered
#   sales_invoice_drafts    info                  draft sales invoices waiting
#
# Ranked by command_center_logic.rank_insights (severity, then this table's
# order, then magnitude) and capped at 6.
# --------------------------------------------------------------------------

_RULE = {
	"vat_due": 1, "duplicate_drafts": 2, "invoicing_stall": 3, "unallocated_receipts": 4,
	"supplier_overdue": 5, "bank_statements_behind": 6, "ar_ageing": 7,
	"delivered_not_invoiced": 8, "sales_invoice_drafts": 9,
}
SUPPLIER_OVERDUE_WARNING = 50000


def _ranked(item):
	"""Re-rank an insight built by an OPS rule into this page's table."""
	if item:
		item["_rule"] = _RULE[item["id"]]
	return item


def _and(names):
	names = list(names)
	if len(names) <= 1:
		return "".join(names)
	return ", ".join(names[:-1]) + " and " + names[-1]


def rule_vat_due(gl, as_of, company=None):
	"""VAT return due within VAT_WARNING_DAYS days (warning) or late (critical)."""
	if gl is None:
		return None
	figures = vat_figures(gl)
	if figures is None:
		return None
	as_of = to_date(as_of)
	q = vat_quarter(as_of)
	days_left = (q.due - as_of).days
	severity = vat_severity(days_left)
	if not severity:
		return None
	if days_left < 0:
		when = "is %s" % days_phrase(days_left)
	elif days_left == 0:
		when = "is due today"
	else:
		when = "due in %s" % days_phrase(days_left)
	parts = []
	if figures.output is not None:
		parts.append("output %s" % cc.format_money_compact(figures.output))
	if figures.input is not None:
		parts.append("input %s" % cc.format_money_compact(figures.input))
	if vat_input_low(figures, gl.get("vat_purchases")):
		tail = "Input VAT looks incomplete; check it before filing on EmaraTax."
	else:
		tail = "File and pay on EmaraTax; the return filed there may differ."
	detail = "Net VAT %s from ERPNext postings (%s), due %s. %s" % (
		cc.format_money_compact(figures.net), ", ".join(parts), full_date(q.due), tail)
	return cc._insight("vat_due", severity, "VAT return %s %s" % (q.label, when), detail,
	                   _RULE["vat_due"], -days_left, route=vat_route(gl, company, q))


def rule_unallocated_receipts(payment_rows):
	"""Receipts with an unallocated amount: money in that no invoice shows yet."""
	total, hits = unallocated(payment_rows, "Receive")
	if total <= 0:
		return None
	n = len(hits)
	top = max(hits, key=lambda r: (_num(r.get("unallocated_amount")), _text(r.get("name"))))
	who = _text(top.get("party_name")) or _text(top.get("party")) or cc.NO_PARTY
	if n == 1:
		detail = ("1 customer receipt carries an unallocated amount (%s, %s). Until it is "
		          "allocated, the invoices it pays still read as outstanding."
		          % (who, _text(top.get("name"))))
	else:
		detail = ("%d customer receipts carry an unallocated amount; the largest is %s from "
		          "%s (%s). Until they are allocated, the invoices they pay still read as "
		          "outstanding." % (n, cc.format_money_compact(_num(top.get("unallocated_amount"))),
		                            who, _text(top.get("name"))))
	return cc._insight(
		"unallocated_receipts", "warning",
		"%s received but not matched to invoices" % cc.format_money_compact(total),
		detail, _RULE["unallocated_receipts"], total,
		route=cc.list_route("Payment Entry", {"payment_type": "Receive", "docstatus": 1,
		                                      "unallocated_amount": [">", 0]}))


def rule_supplier_overdue(bill_rows, as_of, payment_rows=None):
	"""Past-due payables, net per supplier of its debit notes and payments on
	account (party_positions). Review 14 Oct 2026: counted gross it read AED
	110.1K owed to 26 suppliers, more than the payables total, because debit
	notes reversing the same suppliers' overdue bills were ignored."""
	as_of = to_date(as_of)
	docs = ageing_documents("payables", bill_rows, payment_rows)
	total, parties = overdue_net("payables", docs, as_of)
	if total <= 0:
		return None
	n = len(parties)
	bills = [(r, amount) for p in parties for _days, _name, amount, r in p["overdue_docs"]]
	oldest = min((r for r, _a in bills),
	             key=lambda r: (to_date(r.get("due_date")) or to_date(r.get("posting_date")) or date.max,
	                            _text(r.get("name"))))
	oldest_due = to_date(oldest.get("due_date")) or to_date(oldest.get("posting_date"))
	big = max(parties, key=lambda p: (p["overdue"], p["label"]))
	detail = "%d %s; the oldest was due %s (%s)." % (
		len(bills), cc.plural(len(bills), "bill", "bills"), full_date(oldest_due),
		_text(oldest.get("name")))
	if n > 1:
		detail += " Largest: %s, %s." % (big["label"], cc.format_money_compact(big["overdue"]))
	gross = cc.money(sum(_num(r.get("outstanding_amount")) for r in open_documents(bill_rows)
	                     if _num(r.get("outstanding_amount")) > 0 and (days_past_due(r, as_of) or 0) > 0))
	if gross > total:
		detail += " Net of debit notes and payments on account."
	return cc._insight(
		"supplier_overdue", "warning" if total > SUPPLIER_OVERDUE_WARNING else "info",
		"%s owed to %d %s is past due" % (cc.format_money_compact(total), n,
		                                  cc.plural(n, "supplier", "suppliers")),
		detail, _RULE["supplier_overdue"], total,
		route=cc.list_route("Purchase Invoice", {
			"docstatus": 1, "outstanding_amount": [">", 0],
			# 'between' skips the list view's IFNULL wrapping of '<' on a Date.
			"due_date": ["between", ["2000-01-01", (as_of - timedelta(days=1)).isoformat()]],
		}))


def rule_bank_statements_behind(statement_rows, as_of):
	"""Statements not reconciled up to last month, naming the banks. `statement_rows`
	are FPS Bank Statement rows."""
	hits = banks_behind(statement_rows, as_of)
	if not hits:
		return None
	last = month_label(last_month_start(as_of))
	# "ADCB: Jul missing, Aug in progress" -- every open month, not only the latest.
	notes = ["%s: %s" % (b["label"], b["open_months"]) for b in hits]
	return cc._insight(
		"bank_statements_behind", "warning",
		"Bank %s behind for %s" % (cc.plural(len(hits), "statement", "statements"),
		                           _and(b["label"] for b in hits)),
		"%s. Last month was %s." % ("; ".join(notes), last),
		_RULE["bank_statements_behind"], max(b["months_behind"] for b in hits),
		route="/app/fps-bank-statement")


def rule_sales_invoice_drafts(invoice_rows, as_of, *, stall_fired=False):
	"""Draft sales invoices waiting. Skipped when invoicing_stall fired (it states
	the same drafts) or when every draft is already a duplicate_drafts hit."""
	drafts = [r for r in invoice_rows or [] if int(_num(r.get("docstatus"))) == 0]
	if not drafts or stall_fired:
		return None
	duplicates = {_text(r.get("name")) for r in cc.duplicate_drafts(invoice_rows)}
	if all(_text(r.get("name")) in duplicates for r in drafts):
		return None
	as_of = to_date(as_of)
	n, value = drafts_waiting(drafts)
	dated = sorted((to_date(r.get("posting_date")), _text(r.get("name"))) for r in drafts
	               if to_date(r.get("posting_date")))
	detail = ""
	if dated:
		oldest, name = dated[0]
		age = max((as_of - oldest).days, 0)
		detail = "The oldest, %s, is dated %s (%d %s ago). " % (
			name, cc.short_date(oldest), age, cc.plural(age, "day", "days"))
	detail += "Drafts are not in receivables or VAT until they are submitted."
	dup = sum(1 for r in drafts if _text(r.get("name")) in duplicates)
	if dup:
		detail += " %d of them %s a submitted invoice." % (dup, cc.plural(dup, "repeats", "repeat"))
	return cc._insight(
		"sales_invoice_drafts", "info",
		"%d sales %s in draft, worth %s" % (n, cc.plural(n, "invoice", "invoices"),
		                                    cc.format_money_compact(value)),
		detail, _RULE["sales_invoice_drafts"], value,
		route=cc.list_route("Sales Invoice", {"docstatus": 0}))


def ar_ageing_rows(invoices, payments, as_of):
	"""The rows OPS rule_ar_ageing reads (outstanding_amount, due_date,
	posting_date), net of each customer's credits: the past-due invoices still
	open after party_positions (with what is left on each), plus one undated row
	carrying the rest, so the rule's total is the receivables card value and its
	"over 90 days" share counts only what customers still owe. Review 14 Oct
	2026: a customer whose receipts on account exceed its overdue invoices was
	counted as AED 92.9K, 240 days overdue."""
	docs = ageing_documents("receivables", invoices, payments)
	rows = [dict(r, outstanding_amount=amount)
	        for p in party_positions("receivables", docs, as_of).values()
	        for _days, _name, amount, r in p["overdue_docs"]]
	rest = cc.money(_net_total(docs) - sum(r["outstanding_amount"] for r in rows))
	if rest:
		rows.append({"name": "", "outstanding_amount": rest})
	return rows


def build_insights(raw, *, as_of, lookback, company=None):
	as_of = to_date(as_of)
	items = []
	invoices = raw.get("Sales Invoice")
	payments = raw.get("Payment Entry")
	bills = raw.get("Purchase Invoice")
	items.append(rule_vat_due(raw.get("GL"), as_of, company))
	stall = None
	if invoices is not None:
		n_drafts, drafts_value = cc.drafts_pending(invoices)
		stall = cc.rule_invoicing_stall(cc.last_submitted_invoice(invoices, as_of), as_of,
		                                n_drafts, drafts_value, lookback)
		items += [_ranked(cc.rule_duplicate_drafts(invoices)), _ranked(stall),
		          _ranked(cc.rule_ar_ageing(ar_ageing_rows(invoices, payments, as_of), as_of)),
		          rule_sales_invoice_drafts(invoices, as_of, stall_fired=stall is not None)]
	if payments is not None:
		items.append(rule_unallocated_receipts(payments))
	if bills is not None:
		items.append(rule_supplier_overdue(bills, as_of, payments))
	if raw.get("FPS Bank Statement") is not None:
		items.append(rule_bank_statements_behind(raw["FPS Bank Statement"], as_of))
	if raw.get("Job Order") is not None:
		items.append(_ranked(cc.rule_delivered_not_invoiced(raw["Job Order"])))
	return cc.rank_insights(items)


# --------------------------------------------------------------------------
# The payload
# --------------------------------------------------------------------------

AccPayloadKeys = ("as_of", "generated_at", "period", "period_label", "compare_label", "viewer",
                  "kpis", "balances", "ageing", "banks", "trend", "insights")


def build_dashboard(*, period, as_of, generated_at, viewer, raw, company=None, creatable=()):
	"""AccPayload (dashboard/src/types/acc.ts)."""
	cc.check_period(period)
	as_of = to_date(as_of)
	raw = raw or {}
	lookback = (as_of - cc.fetch_floor(period, as_of)).days

	points_by_key = {}
	for key in KPI_ORDER:
		points = metric_points(key, raw)
		if points is not None:
			points_by_key[key] = points
	kpis = [build_kpi(key, points_by_key[key], period=period, as_of=as_of, raw=raw,
	                  creatable=creatable)
	        for key in KPI_ORDER if key in points_by_key]

	ageing = []
	if raw.get("Sales Invoice") is not None:
		ageing.append(build_ageing("receivables", raw["Sales Invoice"], as_of, raw.get("Payment Entry")))
	if raw.get("Purchase Invoice") is not None:
		ageing.append(build_ageing("payables", raw["Purchase Invoice"], as_of, raw.get("Payment Entry")))

	banks = (bank_statuses(raw["FPS Bank Statement"], as_of)
	         if raw.get("FPS Bank Statement") is not None else [])

	viewer_out = {}
	if (viewer or {}).get("full_name"):
		viewer_out["full_name"] = viewer["full_name"]

	return {
		"as_of": as_of.isoformat(),
		"generated_at": generated_at,
		"period": period,
		"period_label": cc.PERIODS[period]["label"],
		"compare_label": cc.PERIODS[period]["compare"],
		"viewer": viewer_out,
		"kpis": kpis,
		"balances": build_balances(raw, company, as_of),
		"ageing": ageing,
		"banks": banks,
		"trend": build_trend(points_by_key, raw, as_of),
		"insights": build_insights(raw, as_of=as_of, lookback=lookback, company=company),
	}


# --------------------------------------------------------------------------
# The drawer
# --------------------------------------------------------------------------

def latest_records(points, cap=cc.RECORDS_CAP):
	"""DrillRecord list, newest first; each record opens its own doctype."""
	ordered = sorted(points, key=lambda p: (p["date"], p["seq"]), reverse=True)
	records = []
	for p in ordered[:cap]:
		rec = {"name": p["name"], "title": p["title"], "date": p["date"].isoformat(),
		       "route": cc.form_route(p["doctype"], p["name"])}
		if p["subtitle"]:
			rec["subtitle"] = p["subtitle"]
		rec["value"] = p["amount"]
		if p["status"]:
			rec["status"] = p["status"]
		records.append(rec)
	return records


def drill_actions(key):
	spec = METRICS[key]
	actions = [{"key": "open_list", "label": "Open list", "kind": "route", "route": spec["route"]}]
	if key == "paid_out":
		actions.append({"key": "open_paid_bills", "label": "Open bills paid at booking",
		                "kind": "route",
		                "route": cc.list_route("Purchase Invoice", {"docstatus": 1, "is_paid": 1})})
	if key == "purchases":
		actions.append({"key": "open_report", "label": "Open report", "kind": "route",
		                "route": ROUTES["payables"]})
	return actions


def build_metric_detail(key, raw, *, period, as_of, dimension=None, can_create=False):
	"""MetricDetail for one ACC KPI. invoiced / collected are the OPS drawers as
	finance viewers saw them; paid_out / purchases are built the same way, with
	each record opening its own doctype."""
	if key not in KPI_ORDER:
		raise KeyError(key)
	as_of = to_date(as_of)
	raw = raw or {}
	if key in ("invoiced", "collected"):
		detail = cc.build_metric_detail(key, _cc_raw(raw), period=period, as_of=as_of,
		                                dimension=dimension, finance=True, can_create=can_create)
		detail["currency"] = CURRENCY
		return cc._ordered(detail, cc.MetricDetailKeys)

	spec = METRICS[key]
	points = metric_points(key, raw) or []
	current, _previous = cc.period_windows(period, as_of)
	in_window = [p for p in points if p["date"] in current]
	options = cc.dimension_options(in_window)
	if dimension is not None and dimension not in {o["key"] for o in options}:
		dimension = None
	chosen = points if dimension is None else [p for p in points if p["dim"] == dimension]
	chosen_window = [p for p in chosen if p["date"] in current]
	summary = cc.summarize(chosen, period, as_of, "currency", first_seen=cc._first_seen(points))
	totals = {}
	for p in chosen_window:
		label, v = totals.get(p["title"], (p["title"], 0))
		totals[p["title"]] = (label, v + p["value"])
	rows = cc.top_n_with_other(totals, unit="currency")
	detail = {
		"key": key,
		"label": spec["label"],
		"unit": "currency",
		"currency": CURRENCY,
		"period": period,
		"period_label": cc.PERIODS[period]["label"],
		"compare_label": cc.PERIODS[period]["compare"],
		"granularity": summary["granularity"],
		"value": summary["value"],
		"previous": summary["previous"],
		"delta_pct": summary["delta_pct"],
		"good_direction": spec["good_direction"],
		"series": summary["series"],
		"dimension_label": spec["dimension_label"],
		"dimension_options": options,
		"dimension": dimension,
		"breakdown": {"title": BREAKDOWN_TITLE[key], "rows": rows} if rows else None,
		"records": latest_records(chosen_window),
		"actions": drill_actions(key),
	}
	caveat = caveat_for(key, raw, as_of)
	if caveat:
		detail["caveat"] = caveat
	return cc._ordered(detail, cc.MetricDetailKeys)
