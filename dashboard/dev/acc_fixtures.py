"""Dev fixtures for the FPS ACC Dashboard (dev/fixtures/acc.*.json).

Called by make_fixtures.py (build_all) with the synthetic site it builds; this
module writes nothing itself. Fictional, deterministic, and shaped exactly like
dashboard/src/types/acc.ts (AccPayload) and dashboard.ts (MetricDetail):

    acc.dashboard.<period>.json            the realistic page on 14 Oct 2026
    acc.dashboard.<period>.edge.json       a stress page (harness ?scenario=edge):
                                           empty payables, VAT past due, every
                                           bank behind or missing, cash overdrawn
    acc.metric_detail.<key>.<period>.json  the drawer for the 4 ACC KPIs
    acc.metric_detail.paid_out.30d.dimension.json   one dimension chip

What it reuses: fps_erpnext.api.command_center_logic for everything the two
dashboards share -- period windows, buckets, deltas, weekly totals, money
formatting, the invoiced / collected KPIs and drawers, and the money insight
rules -- so a number here is built the way the server builds it. What it does
NOT use: fps_erpnext.api.acc_dashboard_logic, which is written in parallel
(14 Oct 2026); the four new pieces (paid out, purchases, balances / ageing /
banks, the new insights) follow docs/acc_dashboard/SPEC.md §2.3 directly.
When acc_dashboard_logic lands, these fixtures can be rebuilt through it.

Review fixes of 14 Oct 2026 mirrored here (acc_dashboard_logic does the real
thing): receivables / payables are NET of payments not yet allocated (each a
negative document aged by its payment date, named in the ageing caveat); a
party's overdue is net of its own credits, oldest documents first; KPI
"paid_out" is labelled "Paid to suppliers" and a bill paid at booking reads
"ADCB (paid at booking)"; the cash card compares the books with the latest
bank statements (critical on the edge page); a bank behind carries
open_months ("Jul missing, Aug in progress").

Edge cases on purpose (default page): a receivables bucket that nets NEGATIVE
(an unapplied credit note larger than that bucket), a customer whose net
outstanding is negative, a bank account with a negative book balance, a debit
note making purchases negative on its day, a Missing bank (QGOV) and a bank a
month behind (WIO). The edge page adds an empty payables ageing, a past-due
VAT quarter (critical) and a negative cash total.

Party names are placeholders ("Key account (sample)", "Supplier A (sample)").
Never put a real customer or supplier name, or a real amount, in this file.
"""

import random
from datetime import date, timedelta

from fps_erpnext.api import command_center_logic as logic

ACC_AS_OF = date(2026, 10, 14)
ACC_GENERATED_AT = "2026-10-14 09:30:00"
SEED = 20261014
CURRENCY = logic.CURRENCY

ACC_KPI_ORDER = ("invoiced", "collected", "paid_out", "purchases")
BUCKETS = (
	("not_due", "Not due"), ("0_30", "0–30"), ("31_60", "31–60"), ("61_90", "61–90"),
	("91_180", "91–180"), ("181_365", "181–365"), ("over_365", "Over 365"),
)
CARD_SPEND = "ADCB (paid at booking)"

SUPPLIERS = {
	# supplier: (supplier group, weight)
	"Shipping line A (sample)": ("Freight & shipping lines", 14),
	"Shipping line B (sample)": ("Freight & shipping lines", 8),
	"Airline cargo (sample)": ("Freight & shipping lines", 4),
	"Transport sub-contractor (sample)": ("Transport", 12),
	"Trailer hire (sample)": ("Transport", 6),
	"Port charges (sample)": ("Customs & government", 10),
	"Government fees (sample)": ("Customs & government", 9),
	"Customs broker (sample)": ("Customs & government", 5),
	"Office services (sample)": ("Services", 3),
	"IT subscriptions (sample)": ("Services", 2),
}
CARD_MERCHANTS = ["Fuel station (sample)", "Online fees portal (sample)", "Stationery (sample)",
                  "Courier (sample)", "Software store (sample)"]

PE_PAY_ROUTE = logic.list_route("Payment Entry", {"payment_type": "Pay", "docstatus": 1})
PI_ROUTE = logic.list_route("Purchase Invoice", {"docstatus": 1})
CARD_ROUTE = logic.list_route("Purchase Invoice", {"is_paid": 1, "docstatus": 1})

ACC_METRICS = {
	"invoiced": logic.METRICS["invoiced"],
	"collected": logic.METRICS["collected"],
	"paid_out": {
		"label": "Paid to suppliers",
		"definition": "Supplier payments: submitted Payment Entries of type Pay plus "
		              "purchase invoices paid at booking, by posting date. Salaries, "
		              "partner drawings and other journal entries are not included.",
		"unit": "currency", "good_direction": "none", "finance": True,
		"doctype": "Payment Entry", "new_doctype": None, "route": PE_PAY_ROUTE,
		"dimension_label": "Paid via",
	},
	"purchases": {
		"label": "Purchases booked",
		"definition": "Net value (before VAT) of submitted purchase invoices, by posting "
		              "date. Debit notes count negative.",
		"unit": "currency", "good_direction": "none", "finance": True,
		"doctype": "Purchase Invoice", "new_doctype": None, "route": PI_ROUTE,
		"dimension_label": "Supplier group",
	},
}

# Rule priorities for the ACC banner (rank_insights: severity first, then these).
_ACC_RULE = {
	"vat_due": 1, "bank_statements_behind": 2, "duplicate_drafts": 3, "invoicing_stall": 4,
	"unallocated_receipts": 5, "supplier_overdue": 6, "delivered_not_invoiced": 8,
	"ar_ageing": 9, "sales_invoice_drafts": 10,
}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _namer(prefix):
	serial = [0]

	def name(day):
		serial[0] += 1
		return "FPS/%s/%s/%03d" % (prefix, day.strftime("%y%m"), serial[0])
	return name


def _between(rng, start, end):
	return start + timedelta(days=rng.randint(0, (end - start).days))


def _money(x):
	return logic.money(x)


def _compact(x):
	return logic.format_money_compact(x)


def _days(n):
	return "%d %s" % (n, "day" if n == 1 else "days")


def _ordered(d, keys):
	return {k: d[k] for k in keys if k in d}


def _supplier(rng):
	names = list(SUPPLIERS)
	return rng.choices(names, [SUPPLIERS[n][1] for n in names])[0]


# --------------------------------------------------------------------------
# Synthetic money-out rows (the OPS site has no supplier side)
# --------------------------------------------------------------------------

def make_purchases(rng):
	"""Submitted Purchase Invoices since March: bills on credit (outstanding
	until paid), card spends paid at booking (is_paid = 1) and two debit notes."""
	rows = []
	name = _namer("PI")
	start = date(2026, 3, 1)
	for _ in range(130):
		who = _supplier(rng)
		day = _between(rng, start, ACC_AS_OF)
		net = round(rng.uniform(250, 12000) * (1.8 if SUPPLIERS[who][0] == "Freight & shipping lines" else 1), 2)
		# Government fees and port charges are mostly outside the scope of VAT.
		vatable = SUPPLIERS[who][0] != "Customs & government" and rng.random() < 0.6
		vat = round(net * 0.05, 2) if vatable else 0.0
		due = day + timedelta(days=30)
		if due >= ACC_AS_OF:
			out = net + vat if rng.random() < 0.85 else 0.0
		else:
			out = net + vat if rng.random() < (0.3 if day >= date(2026, 8, 15) else 0.04) else 0.0
		rows.append({"posting_date": day, "supplier": who, "supplier_group": SUPPLIERS[who][0],
		             "base_net_total": net, "vat": vat, "base_grand_total": round(net + vat, 2),
		             "outstanding_amount": round(out, 2), "due_date": due, "is_paid": 0,
		             "is_return": 0, "docstatus": 1})
	for _ in range(70):
		who = rng.choice(CARD_MERCHANTS)
		day = _between(rng, start, ACC_AS_OF)
		net = round(rng.uniform(40, 3800), 2)
		vat = round(net * 0.05, 2)
		rows.append({"posting_date": day, "supplier": who, "supplier_group": "Card spends",
		             "base_net_total": net, "vat": vat, "base_grand_total": round(net + vat, 2),
		             "outstanding_amount": 0.0, "due_date": day, "is_paid": 1,
		             "is_return": 0, "docstatus": 1})
	# Debit notes: one inside every period window (12 Oct), one older.
	for day, who, net in ((date(2026, 10, 12), "Shipping line A (sample)", -6850.00),
	                      (date(2026, 8, 19), "Trailer hire (sample)", -2400.00)):
		rows.append({"posting_date": day, "supplier": who, "supplier_group": SUPPLIERS[who][0],
		             "base_net_total": net, "vat": round(net * 0.05, 2),
		             "base_grand_total": round(net * 1.05, 2),
		             "outstanding_amount": round(net * 1.05, 2) if day.month == 10 else 0.0,
		             "due_date": day + timedelta(days=30), "is_paid": 0, "is_return": 1,
		             "docstatus": 1})
	rows.sort(key=lambda r: (r["posting_date"], r["supplier"], r["base_net_total"]))
	for r in rows:
		r["name"] = name(r["posting_date"])
	return rows


def make_supplier_payments(rng, purchases):
	"""Payment Entries of type Pay: one per settled credit bill (paid 5-40 days after
	posting), plus a few advances that are still unallocated."""
	rows = []
	name = _namer("PV")
	modes = ["Bank Transfer", "Bank Transfer", "Bank Transfer", "Cheque", "DubaiPay", "Rosoom"]
	for pi in purchases:
		if pi["is_paid"] or pi["is_return"] or pi["outstanding_amount"]:
			continue
		day = min(pi["posting_date"] + timedelta(days=rng.randint(5, 40)), ACC_AS_OF)
		mode = rng.choice(modes)
		rows.append({"posting_date": day, "party": pi["supplier"], "base_paid_amount": pi["base_grand_total"],
		             "mode_of_payment": mode, "reference_no": "SAMPLE-%06d" % rng.randint(0, 999999),
		             "unallocated_amount": 0.0, "docstatus": 1})
	for day, who, amount in ((date(2026, 9, 29), "Shipping line B (sample)", 12500.00),
	                         (date(2026, 10, 9), "Customs broker (sample)", 4300.00)):
		rows.append({"posting_date": day, "party": who, "base_paid_amount": amount,
		             "mode_of_payment": "Bank Transfer", "reference_no": "SAMPLE-%06d" % rng.randint(0, 999999),
		             "unallocated_amount": amount, "docstatus": 1})
	rows.sort(key=lambda r: (r["posting_date"], r["party"]))
	for r in rows:
		r["name"] = name(r["posting_date"])
	return rows


# --------------------------------------------------------------------------
# Points (same shape as command_center_logic's)
# --------------------------------------------------------------------------

def points_paid_out(payments, purchases):
	out = []
	for r in payments:
		amount = _money(r["base_paid_amount"])
		dim = logic._dim(r["mode_of_payment"])
		p = logic._point(r, r["posting_date"], amount, dim, r["party"],
		                 logic._join(r["mode_of_payment"], "Ref " + r["reference_no"]), "", amount=amount)
		p["doctype"] = "Payment Entry"
		out.append(p)
	for r in purchases:
		if not r["is_paid"]:
			continue
		amount = _money(r["base_grand_total"])
		p = logic._point(r, r["posting_date"], amount, (CARD_SPEND, CARD_SPEND), r["supplier"],
		                 CARD_SPEND, "Paid", amount=amount)
		p["doctype"] = "Purchase Invoice"
		out.append(p)
	return out


def points_purchases(purchases):
	out = []
	for r in purchases:
		amount = _money(r["base_net_total"])
		status = "Debit Note" if r["is_return"] else ("Paid" if r["is_paid"] or not r["outstanding_amount"]
		                                               else ("Overdue" if r["due_date"] < ACC_AS_OF else "Unpaid"))
		p = logic._point(r, r["posting_date"], amount, logic._dim(r["supplier_group"]), r["supplier"],
		                 logic._join(r["supplier_group"], "Due " + logic.short_date(r["due_date"])),
		                 status, amount=amount)
		p["doctype"] = "Purchase Invoice"
		out.append(p)
	return out


# --------------------------------------------------------------------------
# KPIs, trend, drawers
# --------------------------------------------------------------------------

def acc_kpi(key, points, period, context, caveat):
	spec = ACC_METRICS[key]
	summary = logic.summarize(points, period, ACC_AS_OF, "currency",
	                          first_seen=logic.source_first_seen(key, points))
	kpi = {
		"key": key, "label": spec["label"], "definition": spec["definition"], "unit": "currency",
		"currency": CURRENCY, "value": summary["value"], "previous": summary["previous"],
		"delta_pct": summary["delta_pct"], "good_direction": spec["good_direction"],
		"granularity": summary["granularity"], "series": summary["series"], "context": context,
		"route": spec["route"], "finance": True,
	}
	if caveat:
		kpi["caveat"] = caveat
	if spec["new_doctype"]:
		kpi["new_doctype"] = spec["new_doctype"]
	return _ordered(kpi, logic.KpiKeys)


def acc_context(key, points, raw, period):
	if key in ("invoiced", "collected"):
		return logic.kpi_context(key, points=points, raw=raw, stages={"tiles": [], "footnotes": []},
		                         period=period, as_of=ACC_AS_OF, finance=True)
	current, _previous = logic.period_windows(period, ACC_AS_OF)
	window = [p for p in points if p["date"] in current]
	if key == "paid_out":
		pays = [p for p in window if p["doctype"] == "Payment Entry"]
		cards = [p for p in window if p["doctype"] == "Purchase Invoice"]
		return [
			{"label": "Supplier payments", "value": "%s · %s" % (logic.format_count(len(pays)),
			                                                      _compact(sum(p["value"] for p in pays)))},
			{"label": "Paid at booking", "value": "%s · %s" % (logic.format_count(len(cards)),
			                                                    _compact(sum(p["value"] for p in cards)))},
		]
	bills = [p for p in window if p["status"] != "Debit Note"]
	notes = [p for p in window if p["status"] == "Debit Note"]
	lines = [{"label": "Bills booked", "value": logic.format_count(len(bills))}]
	if notes:
		lines.append({"label": "Debit notes", "value": "%s · %s" % (
			logic.format_count(len(notes)), _compact(sum(p["value"] for p in notes)))})
	else:
		lines.append({"label": "Suppliers", "value": logic.format_count(len({p["title"] for p in window}))})
	return lines


def acc_trend(points_by_key, raw):
	caveat = logic.caveat_for("collected", raw, ACC_AS_OF)
	modes = []
	for mode_key, label, series in (
		("billing", "Billing", (("invoiced", "Invoiced (net)", 1), ("collected", "Collected", 2))),
		("cashflow", "Cash flow", (("collected", "Collected", 1), ("paid_out", "Paid to suppliers", 2))),
	):
		columns = {k: logic.weekly_totals(logic._pairs(points_by_key[k]), ACC_AS_OF) for k, _l, _s in series}
		points = []
		for i, week_start in enumerate(logic.trend_week_starts(ACC_AS_OF)):
			points.append({
				"week_start": week_start.isoformat(),
				"label": logic.short_date(week_start),
				"partial": week_start <= ACC_AS_OF <= week_start + timedelta(days=6),
				"values": {k: logic.as_unit(columns[k][i][1], "currency") for k, _l, _s in series},
			})
		mode = {"key": mode_key, "label": label, "unit": "currency", "currency": CURRENCY,
		        "series": [{"key": k, "label": l, "slot": s} for k, l, s in series],
		        "points": points, "finance": True}
		if caveat:
			mode["caveat"] = caveat
		modes.append(_ordered(mode, ("key", "label", "unit", "currency", "series", "points", "caveat", "finance")))
	return modes


def acc_detail(key, points, period, dimension=None):
	"""MetricDetail for paid_out / purchases (invoiced / collected use logic.build_metric_detail)."""
	spec = ACC_METRICS[key]
	current, _previous = logic.period_windows(period, ACC_AS_OF)
	in_window = [p for p in points if p["date"] in current]
	options = logic.dimension_options(in_window)
	if dimension is not None and dimension not in {o["key"] for o in options}:
		dimension = None
	chosen = points if dimension is None else [p for p in points if p["dim"] == dimension]
	chosen_window = [p for p in chosen if p["date"] in current]
	summary = logic.summarize(chosen, period, ACC_AS_OF, "currency",
	                          first_seen=logic.source_first_seen(key, points))
	totals = {}
	for p in chosen_window:
		label, v = totals.get(p["dim"], (p["dim_label"], 0))
		totals[p["dim"]] = (label, v + p["value"])
	rows = logic.top_n_with_other(totals, unit="currency")
	records = []
	for p in sorted(chosen_window, key=lambda p: (p["date"], p["seq"]), reverse=True)[:logic.RECORDS_CAP]:
		rec = {"name": p["name"], "title": p["title"], "date": p["date"].isoformat(),
		       "route": logic.form_route(p["doctype"], p["name"])}
		if p["subtitle"]:
			rec["subtitle"] = p["subtitle"]
		rec["value"] = p["amount"]
		if p["status"]:
			rec["status"] = p["status"]
		records.append(rec)
	actions = [{"key": "open_list", "label": "Open list", "kind": "route", "route": spec["route"]}]
	if key == "paid_out":
		actions.append({"key": "open_paid_bills", "label": "Open bills paid at booking", "kind": "route",
		                "route": CARD_ROUTE})
	detail = {
		"key": key, "label": spec["label"], "unit": "currency", "currency": CURRENCY,
		"period": period, "period_label": logic.PERIODS[period]["label"],
		"compare_label": logic.PERIODS[period]["compare"], "granularity": summary["granularity"],
		"value": summary["value"], "previous": summary["previous"], "delta_pct": summary["delta_pct"],
		"good_direction": spec["good_direction"], "series": summary["series"],
		"dimension_label": spec["dimension_label"], "dimension_options": options,
		"dimension": dimension,
		"breakdown": {"title": "By " + spec["dimension_label"].lower(), "rows": rows} if rows else None,
		"records": records, "actions": actions,
	}
	return _ordered(detail, logic.MetricDetailKeys)


# --------------------------------------------------------------------------
# Positions: balances, ageing, banks
# --------------------------------------------------------------------------

def bucket_of(due):
	days = (ACC_AS_OF - due).days
	if days <= 0:
		return "not_due"
	for limit, key in ((30, "0_30"), (60, "31_60"), (90, "61_90"), (180, "91_180"), (365, "181_365")):
		if days <= limit:
			return key
	return "over_365"


def party_positions(docs):
	"""{party: {label, value, overdue, oldest, count}}: a party's credits (negative
	documents, payments on account included) clear its past-due documents oldest
	first (acc_dashboard_logic.party_positions); count is invoices / bills only."""
	parties = {}
	for doc in docs:
		p = parties.setdefault(doc["party"], {"label": doc["label"], "value": 0.0, "credit": 0.0,
		                                      "past_due": [], "count": 0})
		p["value"] += doc["outstanding"]
		if not doc.get("payment"):
			p["count"] += 1
		days = (ACC_AS_OF - doc["due_date"]).days
		if doc["outstanding"] < 0:
			p["credit"] -= doc["outstanding"]
		elif days > 0:
			p["past_due"].append((days, doc["outstanding"]))
	for p in parties.values():
		credit, left = p.pop("credit"), []
		for days, amount in sorted(p.pop("past_due"), reverse=True):
			used = min(credit, amount)
			credit -= used
			if amount - used >= 0.005:
				left.append((days, amount - used))
		p["overdue"] = sum(a for _d, a in left)
		p["oldest"] = left[0][0] if left else 0
	return parties


def net_overdue(docs):
	return _money(sum(p["overdue"] for p in party_positions(docs).values()))


def build_ageing(key, label, docs, party_route, route, caveat=None):
	"""docs: [{party, label, outstanding, due_date, payment?}] (outstanding != 0)."""
	sums = {k: [0.0, 0] for k, _l in BUCKETS}
	for doc in docs:
		b = bucket_of(doc["due_date"])
		sums[b][0] += doc["outstanding"]
		sums[b][1] += 1
	parties = party_positions(docs)
	buckets = [{"key": k, "label": l, "value": _money(sums[k][0]), "count": sums[k][1]} for k, l in BUCKETS]
	ranked = sorted(((party, p) for party, p in parties.items() if _money(p["value"]) > 0),
	                key=lambda kv: (-kv[1]["value"], kv[1]["label"]))[:5]
	top = [{"party": party, "label": p["label"], "value": _money(p["value"]), "overdue": _money(p["overdue"]),
	        "oldest_days": p["oldest"], "count": p["count"], "route": party_route(party)}
	       for party, p in ranked]
	ageing = {"key": key, "label": label, "currency": CURRENCY,
	          "total": _money(sum(b["value"] for b in buckets)),
	          "overdue": net_overdue(docs),   # same per-party figure as the card
	          "buckets": buckets, "top": top, "route": route}
	if caveat:
		ageing["caveat"] = caveat
	return ageing


def receivable_docs(site):
	"""Open submitted Sales Invoices, plus one large unapplied credit note whose
	due date falls in 61-90 days and outweighs that bucket (it nets negative)."""
	rows = logic.open_receivables(site["Sales Invoice"])
	docs = [{"name": r["name"], "party": r["customer"], "label": r["customer_name"],
	         "outstanding": r["outstanding_amount"], "due_date": r["due_date"]} for r in rows]
	in_bucket = sum(d["outstanding"] for d in docs if bucket_of(d["due_date"]) == "61_90")
	credit = -round(in_bucket + 1250.00, 2)
	docs.append({"name": "FPS/INV/2607/CN1", "party": "Customer B", "label": "Customer B",
	             "outstanding": credit, "due_date": ACC_AS_OF - timedelta(days=75)})
	return docs


def payable_docs(purchases, payments=()):
	"""Open bills plus the supplier payments not yet allocated (negative, aged by
	their payment date)."""
	docs = [{"name": r["name"], "party": r["supplier"], "label": r["supplier"],
	         "outstanding": r["outstanding_amount"], "due_date": r["due_date"]}
	        for r in purchases if r["outstanding_amount"] != 0]
	docs += [{"name": r["name"], "party": r["party"], "label": r["party"], "outstanding": -r["unallocated_amount"],
	          "due_date": r["posting_date"], "payment": True}
	         for r in payments if r["unallocated_amount"] > 0]
	return docs


# Two fictional receipts paid ahead of their invoices (unallocated), aged by date.
AR_ON_ACCOUNT = ((date(2026, 9, 18), 12450.00), (date(2026, 10, 6), 6000.00))


def receipts_on_account(docs):
	"""Negative documents for AR_ON_ACCOUNT, on the customer with the largest
	not-yet-due balance (a customer paying ahead)."""
	not_due = {}
	for d in docs:
		if bucket_of(d["due_date"]) == "not_due" and d["outstanding"] > 0:
			not_due[(d["party"], d["label"])] = not_due.get((d["party"], d["label"]), 0) + d["outstanding"]
	party, label = max(sorted(not_due), key=lambda k: not_due[k])
	return [{"name": "FPS/PR/%s/9%02d" % (day.strftime("%y%m"), i), "party": party, "label": label,
	         "outstanding": -amount, "due_date": day, "payment": True}
	        for i, (day, amount) in enumerate(AR_ON_ACCOUNT, 1)]


def ar_party_route(party):
	return logic.list_route("Sales Invoice", {"customer": party, "docstatus": 1,
	                                          "outstanding_amount": ["!=", 0]})


def ap_party_route(party):
	return logic.list_route("Purchase Invoice", {"supplier": party, "docstatus": 1,
	                                             "outstanding_amount": ["!=", 0]})


AR_REPORT = "/app/query-report/FPS%20Customer%20Receivables"
AP_REPORT = "/app/query-report/Accounts%20Payable"
GL_ROUTE = "/app/query-report/General%20Ledger?group_by=Group%20by%20Account"


def balance_card(key, label, definition, value, context, route, severity=None, caveat=None):
	card = {"key": key, "label": label, "definition": definition, "currency": CURRENCY,
	        "value": _money(value), "context": context, "route": route}
	if severity:
		card["severity"] = severity
	if caveat:
		card["caveat"] = caveat
	return _ordered(card, ("key", "label", "definition", "currency", "value", "context",
	                       "severity", "caveat", "route"))


def line(label, value):
	return {"label": label, "value": value}


def receivables_card(docs, site, unallocated):
	total = sum(d["outstanding"] for d in docs)
	overdue = net_overdue(docs)
	n_drafts, drafts_value = logic.drafts_pending(site["Sales Invoice"])
	return balance_card(
		"receivables", "Receivables",
		"Outstanding on submitted sales invoices less customer receipts not yet allocated to an "
		"invoice, credit notes netted, carried-over invoices included. Overdue is net of each "
		"customer's own credits.",
		total,
		[line("Overdue", _compact(overdue)),
		 line("Open invoices", logic.format_count(sum(1 for d in docs if not d.get("payment")))),
		 line("Less unallocated receipts", _compact(unallocated)),
		 line("Drafts waiting", "%s · %s" % (logic.format_count(n_drafts), _compact(drafts_value)))],
		AR_REPORT, severity="warning" if total > 0 and overdue / total >= 0.5 else None)


def payables_card(docs, purchases, unallocated, drafts):
	total = sum(d["outstanding"] for d in docs)
	return balance_card(
		"payables", "Payables",
		"Outstanding on submitted purchase invoices less supplier payments not yet allocated to a "
		"bill, debit notes netted. Overdue is net of each supplier's own credits.",
		total,
		[line("Overdue", _compact(net_overdue(docs))),
		 line("Open bills", logic.format_count(sum(1 for d in docs if not d.get("payment")))),
		 line("Less unallocated payments", _compact(unallocated)),
		 line("Draft bills", logic.format_count(drafts))],
		AP_REPORT)


def cash_card(accounts, card_liability, statements=0.0, statement_day="30 Sep", gap=None):
	"""gap: (bank, book minus statement at the statement date, statement closing) when
	the books are off by more than 1 % -- the card is then critical."""
	total = sum(v for _n, v in accounts)
	top = sorted(accounts, key=lambda a: -abs(a[1]))[:3]
	context = [line(n, _compact(v)) for n, v in top[:1]]
	if statements:
		context.append(line("Bank statements, %s" % statement_day, _compact(statements)))
	if gap:
		context.append(line("Books %s statements" % ("above" if gap[1] >= 0 else "below"), _compact(abs(gap[1]))))
	if card_liability:
		context.append(line("Qashio card liability", _compact(card_liability)))
	context += [line(n, _compact(v)) for n, v in top[1:]]
	caveat = "Book balances from ERPNext, not bank statements."
	if gap:
		caveat = ("ERPNext's %s balance on %s is %s %s its bank statement (%s), so this figure is not "
		          "the bank position until the ledger is reconciled." % (
		              gap[0], statement_day, _compact(abs(gap[1])), "above" if gap[1] >= 0 else "below",
		              _compact(gap[2])))
	return balance_card(
		"cash", "Cash & bank",
		"General Ledger balance of every bank and cash account, up to today, checked against each "
		"bank's latest statement at its closing date.",
		total, context[:4], GL_ROUTE, severity="critical" if gap else None, caveat=caveat)


def vat_route(start, end):
	return ("/app/query-report/General%20Ledger?from_date=" + start.isoformat() + "&to_date=" + end.isoformat()
	        + "&account=%5B%22VAT%205%25%20-%20FPS%22%2C%22Sales%20Taxes%20Receivables%20-%20FPS%22%5D")


def vat_card(label, start, end, output, input_, due, severity):
	days = (due - ACC_AS_OF).days
	when = "%d %s %d" % (due.day, logic.MONTHS[due.month - 1], due.year)
	due_text = "%s · %s" % (when, _days(days) if days >= 0 else _days(-days) + " overdue")
	return balance_card(
		"vat", label,
		"Output VAT (sales invoices) less input VAT (purchase invoices) posted to the VAT accounts in "
		"the quarter; positive means payable. Journal and payment postings are left out.",
		output - input_,
		[line("Output VAT", _compact(output)), line("Input VAT", _compact(input_)), line("Due date", due_text)],
		vat_route(start, end), severity=severity,
		caveat="From ERPNext postings; the return filed on EmaraTax may differ.")


def quarter_vat(site, purchases, start, end):
	output = sum(r["base_grand_total"] - r["base_net_total"] for r in site["Sales Invoice"]
	             if r["docstatus"] == 1 and not r["fps_is_payment_request"]
	             and start <= r["posting_date"] <= end
	             and abs(r["base_grand_total"] - r["base_net_total"] * 1.05) < 0.02)
	input_ = sum(r["vat"] for r in purchases if start <= r["posting_date"] <= end)
	return _money(output), _money(input_)


BANK_LABELS = (("ADCB", "ADCB"), ("WIO", "WIO"), ("QGEN", "Qashio – General"), ("QGOV", "Qashio – Government"))


def bank_row(code, label, month, status, closing, behind, open_months=None):
	if month:
		route = logic.form_route("FPS Bank Statement", "FPS-BST-%s-%s" % (code, month.strftime("%y%m")))
		latest = "%s %d" % (logic.MONTHS[month.month - 1], month.year)
	else:
		route = logic.list_route("FPS Bank Statement", {"name": ["like", "FPS-BST-%s-%%" % code]})
		latest = None
	row = {"bank": code, "label": label, "latest_month": latest, "status": status,
	       "closing_balance": None if closing is None else _money(closing),
	       "months_behind": behind, "route": route}
	if behind:
		assert open_months, code
		row = dict(list(row.items())[:-1], open_months=open_months, route=route)
	return row


# --------------------------------------------------------------------------
# Insights (SPEC §2.3; the shared rules come from command_center_logic)
# --------------------------------------------------------------------------

def _acc_insight(id_, severity, title, detail, weight, metric_key=None, route=None):
	return logic._insight(id_, severity, title, detail, _ACC_RULE[id_], weight,
	                      metric_key=metric_key, route=route)


def _rerank(item, rule_id):
	if item:
		item["_rule"] = _ACC_RULE[rule_id]
	return item


def acc_insights(site, *, vat, banks, unallocated, ap_overdue, ap_overdue_suppliers, lookback):
	invoices = site["Sales Invoice"]
	n_drafts, drafts_value = logic.drafts_pending(invoices)
	items = [
		_rerank(logic.rule_duplicate_drafts(invoices), "duplicate_drafts"),
		_rerank(logic.rule_invoicing_stall(logic.last_submitted_invoice(invoices, ACC_AS_OF), ACC_AS_OF,
		                                   n_drafts, drafts_value, lookback), "invoicing_stall"),
		_rerank(logic.rule_ar_ageing(logic.open_receivables(invoices), ACC_AS_OF), "ar_ageing"),
		_rerank(logic.rule_delivered_not_invoiced(site["Job Order"]), "delivered_not_invoiced"),
	]
	label, due, days_left = vat
	if days_left < 0:
		items.append(_acc_insight("vat_due", "critical", "VAT return %s is %s past due" % (label, _days(-days_left)),
		                          "It was due on %s. File it on EmaraTax; figures here come from ERPNext postings."
		                          % due, -days_left, route=GL_ROUTE))
	elif days_left <= 14:
		items.append(_acc_insight("vat_due", "warning", "VAT return %s due in %s" % (label, _days(days_left)),
		                          "Due %s. Check output and input VAT in the General Ledger before filing "
		                          "on EmaraTax." % due, 14 - days_left, route=GL_ROUTE))
	behind = [b for b in banks if b["months_behind"] >= 1]
	if behind:
		names = [b["label"] for b in behind]
		items.append(_acc_insight(
			"bank_statements_behind", "warning",
			"Bank %s behind for %s" % ("statement" if len(behind) == 1 else "statements",
			                           names[0] if len(names) == 1 else
			                           ", ".join(names[:-1]) + " and " + names[-1]),
			"%s. Last month was Sep 2026." % "; ".join("%s: %s" % (b["label"], b["open_months"]) for b in behind),
			max(b["months_behind"] for b in behind), route="/app/fps-bank-statement"))
	if unallocated > 0:
		items.append(_acc_insight(
			"unallocated_receipts", "warning", "%s received but not matched to invoices" % _compact(unallocated),
			"Customer receipts with an unallocated amount; allocate them so receivables and statements agree.",
			unallocated, route=logic.list_route("Payment Entry", {"payment_type": "Receive", "docstatus": 1,
			                                                      "unallocated_amount": [">", 0]})))
	if ap_overdue > 0:
		items.append(_acc_insight(
			"supplier_overdue", "warning" if ap_overdue > 50000 else "info",
			"%s overdue to %d %s" % (_compact(ap_overdue), ap_overdue_suppliers,
			                         "supplier" if ap_overdue_suppliers == 1 else "suppliers"),
			"Purchase invoices past their due date and still unpaid.", ap_overdue,
			route=logic.list_route("Purchase Invoice", {"docstatus": 1, "status": "Overdue"})))
	drafts = [r for r in invoices if r["docstatus"] == 0]
	if drafts:
		oldest = min(r["posting_date"] for r in drafts)
		items.append(_acc_insight(
			"sales_invoice_drafts", "info",
			"%d draft invoices worth %s" % (len(drafts), _compact(drafts_value)),
			"Oldest draft is %s old. Submit or delete them so receivables are complete."
			% _days((ACC_AS_OF - oldest).days), len(drafts), metric_key="invoiced",
			route=logic.list_route("Sales Invoice", {"docstatus": 0})))
	return logic.rank_insights(items)


# --------------------------------------------------------------------------
# The files
# --------------------------------------------------------------------------

def build_acc_files(site):
	rng = random.Random(SEED)
	purchases = make_purchases(rng)
	payments = make_supplier_payments(rng, purchases)
	raw = {"Sales Invoice": site["Sales Invoice"], "Payment Entry": site["Payment Entry"]}

	points = {
		"invoiced": logic.points_invoiced(site["Sales Invoice"]),
		"collected": logic.points_collected(site["Payment Entry"]),
		"paid_out": points_paid_out(payments, purchases),
		"purchases": points_purchases(purchases),
	}
	trend = acc_trend(points, raw)

	ar_docs = receivable_docs(site)
	ar_docs += receipts_on_account(ar_docs)
	ar_unallocated = _money(sum(a for _d, a in AR_ON_ACCOUNT))   # two receipts paid ahead of their invoices
	ap_docs = payable_docs(purchases, payments)
	ap_unallocated = sum(p["unallocated_amount"] for p in payments)
	ap_positions = party_positions(ap_docs)
	ap_overdue = _money(sum(p["overdue"] for p in ap_positions.values()))
	ap_overdue_suppliers = sum(1 for p in ap_positions.values() if p["overdue"] > 0)

	q3_out, q3_in = quarter_vat(site, purchases, date(2026, 7, 1), date(2026, 9, 30))
	q3_due, q2_due = date(2026, 10, 28), date(2026, 7, 28)

	receivables = receivables_card(ar_docs, site, ar_unallocated)
	ar_ageing = build_ageing("receivables", "Receivables", ar_docs, ar_party_route, AR_REPORT,
	                         caveat="Net of %s received from customers but not yet allocated to invoices "
	                                "(2 payments), aged by payment date, as in the full report."
	                                % _compact(ar_unallocated))
	ap_caveat = ("Net of %s paid to suppliers but not yet allocated to bills (%d payments), aged by "
	             "payment date, as in the full report." % (
	                 _compact(ap_unallocated), sum(1 for p in payments if p["unallocated_amount"] > 0)))
	assert ar_ageing["total"] == receivables["value"]
	assert any(b["value"] < 0 for b in ar_ageing["buckets"]), "the credit-note bucket must net negative"

	scenarios = {
		"": {
			"balances": [
				receivables,
				payables_card(ap_docs, purchases, ap_unallocated, drafts=3),
				cash_card([("ADCB Current A/c", 409812.40), ("WIO Business", -13420.10),
				           ("Qashio Government wallet", 21905.55), ("Qashio General wallet", 8640.00),
				           ("Petty cash", 1870.25)], card_liability=6215.40,
				          statements=409812.40 + 4215.30, statement_day="30 Sep"),
				vat_card("VAT Jul–Sep 2026", date(2026, 7, 1), date(2026, 9, 30), q3_out, q3_in,
				         q3_due, "warning"),
			],
			"ageing": [ar_ageing, build_ageing("payables", "Payables", ap_docs, ap_party_route, AP_REPORT,
			                                   caveat=ap_caveat)],
			"banks": [bank_row("ADCB", "ADCB", date(2026, 9, 1), "Reconciled", 409812.40, 0),
			          bank_row("WIO", "WIO", date(2026, 8, 1), "Reconciled", 4215.30, 1, "Sep missing"),
			          bank_row("QGEN", "Qashio – General", date(2026, 9, 1), "In Progress", 9102.75, 0),
			          bank_row("QGOV", "Qashio – Government", None, "Missing", None, 4, "Jun–Sep missing")],
			"vat": ("Jul–Sep 2026", "28 Oct 2026", (q3_due - ACC_AS_OF).days),
			"ap": (ap_unallocated, ap_overdue, ap_overdue_suppliers),
			"ar_unallocated": ar_unallocated,
		},
		".edge": {
			"balances": [
				receivables,
				payables_card([], purchases, 0.0, drafts=0),
				# Books AED 176.6K below the bank's 31 Jul statement: critical.
				cash_card([("ADCB Current A/c", -25410.20), ("WIO Business", 3100.00), ("Petty cash", 420.00)],
				          card_liability=0, statements=151200.00, statement_day="31 Jul",
				          gap=("ADCB", -25410.20 - 151200.00, 151200.00)),
				# A past-due quarter reads naturally as money owed: fixed, fictional
				# payable figures (the synthetic Q2 nets to a small refund).
				vat_card("VAT Apr–Jun 2026", date(2026, 4, 1), date(2026, 6, 30), 41862.35, 17404.15,
				         q2_due, "critical"),
			],
			"ageing": [ar_ageing, build_ageing("payables", "Payables", [], ap_party_route, AP_REPORT)],
			"banks": [bank_row("ADCB", "ADCB", date(2026, 7, 1), "In Progress", 151200.00, 3,
			                   "Jul in progress, Aug–Sep missing"),
			          bank_row("WIO", "WIO", None, "Missing", None, 4, "Jun–Sep missing"),
			          bank_row("QGEN", "Qashio – General", None, "Missing", None, 4, "Jun–Sep missing"),
			          bank_row("QGOV", "Qashio – Government", None, "Missing", None, 4, "Jun–Sep missing")],
			"vat": ("Apr–Jun 2026", "28 Jul 2026", (q2_due - ACC_AS_OF).days),
			"ap": (0.0, 0.0, 0),
			"ar_unallocated": ar_unallocated,
		},
	}

	files = {}
	for period in logic.PERIODS:
		floor = logic.fetch_floor(period, ACC_AS_OF)
		kpis = []
		for key in ACC_KPI_ORDER:
			caveat = logic.caveat_for(key, raw, ACC_AS_OF) if key == "collected" else None
			kpis.append(acc_kpi(key, points[key], period, acc_context(key, points[key], raw, period), caveat))
		for suffix, sc in scenarios.items():
			ap_unalloc, ap_over, ap_over_n = sc["ap"]
			payload = {
				"as_of": ACC_AS_OF.isoformat(), "generated_at": ACC_GENERATED_AT, "period": period,
				"period_label": logic.PERIODS[period]["label"], "compare_label": logic.PERIODS[period]["compare"],
				"viewer": {"full_name": "Sample Finance User"},
				"kpis": kpis, "balances": sc["balances"], "ageing": sc["ageing"], "banks": sc["banks"],
				"trend": trend,
				"insights": acc_insights(site, vat=sc["vat"], banks=sc["banks"], unallocated=sc["ar_unallocated"],
				                         ap_overdue=ap_over, ap_overdue_suppliers=ap_over_n,
				                         lookback=(ACC_AS_OF - floor).days),
			}
			files["acc.dashboard.%s%s.json" % (period, suffix)] = payload
		for key in ACC_KPI_ORDER:
			if key in ("invoiced", "collected"):
				detail = logic.build_metric_detail(key, raw, period=period, as_of=ACC_AS_OF, finance=True,
				                                   can_create=True)
			else:
				detail = acc_detail(key, points[key], period)
			files["acc.metric_detail.%s.%s.json" % (key, period)] = detail
	files["acc.metric_detail.paid_out.30d.dimension.json"] = acc_detail(
		"paid_out", points["paid_out"], "30d", dimension=CARD_SPEND)
	return files
