"""Read-only data for the FPS ACC Dashboard (accounting), the "FPS ACC Overview" block.

Agam, 14 Oct 2026: a separate accounting dashboard that only Administrator,
agam@ and abhishek@ can open. Two whitelisted GET methods:

    get_dashboard(period)                     -> AccPayload
    get_metric_detail(key, period, dimension) -> MetricDetail

The payload contract is dashboard/src/types/acc.ts. This module only checks
the role, reads the rows and caches the answer; every number, string and
insight is computed by fps_erpnext.api.acc_dashboard_logic (pure Python,
unit-tested without a bench).

THE GATE. Both methods start with frappe.only_for("Accounts Manager") --
nothing is read, not even the cache, before it. Administrator passes (only_for
returns early for it). On 14 Oct 2026 Accounts Manager is held by exactly
Administrator, agam@ and abhishek@. Anyone else gets frappe.PermissionError,
which the page shows as "You do not have access to the FPS ACC Dashboard".
The Workspace "FPS ACC" carries the same role, so Frappe hides the page
itself from everyone else; this gate is what keeps the numbers private even
for a user who calls the method directly.

NOTHING HERE WRITES. Document reads go through frappe.get_list (permission-
aware), with docstatus always explicit and date filters guarded the way
command_center documents. General Ledger sums are aggregated in SQL with
frappe.qb functions (v16 rejects string aggregates like "sum(debit)") and are
only run after the gate. The only side effect is a 60-second Redis cache entry
per (user, period), scoped to the user.

FIELDS, VERIFIED READ-ONLY against the live site on 2026-10-14 (REST meta and
rows; Frappe 16.51.0, ERPNext 16.50.0):

    Sales Invoice      as command_center (outstanding_amount at permlevel 1,
                       which Accounts Manager reads).
    Payment Entry      payment_type (Receive / Pay / Internal Transfer),
                       base_paid_amount, base_received_amount,
                       unallocated_amount, mode_of_payment, party_type, party,
                       party_name, reference_no, posting_date, creation.
    Purchase Invoice   is_paid, is_return, base_net_total, base_grand_total,
                       outstanding_amount (party currency; every bill is AED),
                       due_date, supplier, supplier_name, mode_of_payment,
                       cash_bank_account (the account a paid-at-booking bill
                       was paid from: ADCB for all 318 on 14 Oct 2026),
                       bill_no, status, posting_date; base_total_taxes_and_charges
                       and company for the quarter's purchase totals.
    Supplier           supplier_group.
    FPS Bank Statement bank_code (ADCB / WIO / QGEN / QGOV), month_code (YYMM),
                       statement_month, status (In Progress / Reconciled),
                       closing_balance, to_date. Named FPS-BST-<CODE>-<YYMM>.
                       Readable by System Manager (and the n8n writer) only.
    GL Entry           account, debit, credit (company currency), is_cancelled,
                       posting_date, company, voucher_type (the VAT split).
    Account            account_type Bank / Cash leaves; "VAT 5%" (output VAT),
                       "Sales Taxes Receivables" (input VAT, no account_type),
                       "Qashio Card Liability" (Payable) by account_name.
"""

import frappe
from frappe import _
from frappe.utils import get_fullname, getdate, now_datetime, today

from fps_erpnext.api import acc_dashboard_logic as logic
from fps_erpnext.api import command_center as cc_api
from fps_erpnext.api import command_center_logic as cc

GATE_ROLE = "Accounts Manager"

CACHE_TTL = 60
CACHE_KEY = "fps_acc_dashboard:v1:dashboard:%s"


@frappe.whitelist(methods=["GET"])
def get_dashboard(period: str = "7d"):
	"""KPIs, balances, ageing, bank statements, trend and insights. Read-only."""
	frappe.only_for(GATE_ROLE)
	period = _check_period(period)
	user = frappe.session.user
	key = CACHE_KEY % period

	# user= scopes the key to this user ("user:<user>:..."): one viewer's
	# numbers are never served to another, even among the three who may look.
	cached = frappe.cache().get_value(key, user=user, expires=True)
	if cached is not None:
		return cached

	payload = _dashboard(period, user)
	frappe.cache().set_value(key, payload, user=user, expires_in_sec=CACHE_TTL)
	return payload


@frappe.whitelist(methods=["GET"])
def get_metric_detail(key: str, period: str = "30d", dimension: str | None = None):
	"""One ACC KPI's drawer: series, breakdown, latest records, actions. Read-only."""
	frappe.only_for(GATE_ROLE)
	period = _check_period(period)
	if not isinstance(key, str) or key not in logic.KPI_ORDER:
		frappe.throw(_("Unknown metric"), frappe.ValidationError)
	dimension = cc_api._check_dimension(dimension)
	as_of = getdate(today())
	floor = cc.fetch_floor(period, as_of).isoformat()
	raw = _read(floor, as_of, _company(), need=_NEEDS[key])
	if logic.metric_points(key, raw) is None:
		# A source the metric needs is not readable for this viewer.
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	can_create = key == "invoiced" and frappe.has_permission("Sales Invoice", "create")
	return logic.build_metric_detail(key, raw, period=period, as_of=as_of,
	                                 dimension=dimension, can_create=can_create)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

# What each call reads. The dashboard reads everything; a drawer only what its
# metric (and its caveat) needs.
_ALL = ("Sales Invoice", "Payment Entry", "Purchase Invoice", "Job Order",
        "FPS Bank Statement", "GL")
_NEEDS = {
	"invoiced": ("Sales Invoice",),
	"collected": ("Payment Entry",),
	"paid_out": ("Payment Entry", "Purchase Invoice", "FPS Bank Statement"),
	"purchases": ("Purchase Invoice",),
}


def _dashboard(period, user):
	as_of = getdate(today())
	company = _company()
	raw = _read(cc.fetch_floor(period, as_of).isoformat(), as_of, company, need=_ALL)
	return logic.build_dashboard(
		period=period,
		as_of=as_of,
		generated_at=cc.timestamp(now_datetime()),
		viewer={"full_name": get_fullname(user)},
		raw=raw,
		company=company,
		creatable={"Sales Invoice"} if frappe.has_permission("Sales Invoice", "create") else set(),
	)


def _check_period(period):
	if not isinstance(period, str) or period not in cc.PERIODS:
		frappe.throw(_("Period must be one of {0}").format(", ".join(cc.PERIODS)),
		             frappe.ValidationError)
	return period


def _company():
	"""The default company (the site has one: FAST PLANET SHIPPING LLC)."""
	return (frappe.defaults.get_user_default("Company")
	        or frappe.defaults.get_global_default("company")
	        or frappe.db.get_value("Company", {}, "name"))


# --------------------------------------------------------------------------
# Reads -- each bounded by the period floor, open documents or the quarter
# --------------------------------------------------------------------------

def _read(floor, as_of, company, *, need):
	"""{source: rows} for acc_dashboard_logic. A source the viewer cannot read
	is left out, and the logic omits what is built on it -- never a zero."""
	raw = {}
	if "Sales Invoice" in need and cc_api._can_read("Sales Invoice"):
		# The OPS reader, unchanged: posted since the floor, every open invoice
		# however old, every draft, plus the older invoices the drafts' Job
		# Orders need for the duplicate-draft insight.
		raw["Sales Invoice"] = cc_api._read_invoices(floor)
	if "Payment Entry" in need and frappe.has_permission("Payment Entry", "read"):
		raw["Payment Entry"] = _read_payments(floor)
	if "Purchase Invoice" in need and frappe.has_permission("Purchase Invoice", "read"):
		raw["Purchase Invoice"] = _read_purchases(floor)
		raw["Supplier"] = _read_supplier_groups(raw["Purchase Invoice"])
	if "Job Order" in need and frappe.has_permission("Job Order", "read"):
		raw["Job Order"] = _read_delivered_jobs()
	if "FPS Bank Statement" in need and frappe.has_permission("FPS Bank Statement", "read"):
		raw["FPS Bank Statement"] = _read_bank_statements()
	if ("GL" in need and company and frappe.has_permission("GL Entry", "read")
	        and frappe.has_permission("Account", "read")):
		raw["GL"] = _read_gl(company, as_of, statements=raw.get("FPS Bank Statement"))
	return raw


def _read_payments(floor):
	"""Submitted receipts and supplier payments since the floor, plus every one
	still carrying an unallocated amount however old (a stock, not a flow)."""
	dt = "Payment Entry"
	return frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		filters=[
			[dt, "docstatus", "=", 1],
			[dt, "payment_type", "in", ["Receive", "Pay"]],
		],
		or_filters=[
			[dt, "posting_date", ">=", floor],
			[dt, "unallocated_amount", ">", 0],
		],
		order_by="posting_date desc, name desc",
		limit_page_length=0,
	)


def _read_purchases(floor):
	"""Purchase invoices: posted since the floor, every open one however old,
	and every draft (draft bills waiting is a stock)."""
	dt = "Purchase Invoice"
	return frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		filters=[[dt, "docstatus", "in", [0, 1]]],
		or_filters=[
			[dt, "posting_date", ">=", floor],
			[dt, "outstanding_amount", "!=", 0],
			[dt, "docstatus", "=", 0],
		],
		order_by="posting_date desc, name desc",
		limit_page_length=0,
	)


def _read_supplier_groups(bills):
	"""{supplier: supplier_group} for the suppliers on these bills."""
	suppliers = sorted({b.get("supplier") for b in bills if b.get("supplier")})
	if not suppliers or not frappe.has_permission("Supplier", "read"):
		return {}
	rows = frappe.get_list(
		"Supplier",
		fields=logic.FIELDS["Supplier"],
		filters=[["Supplier", "name", "in", suppliers]],
		limit_page_length=0,
	)
	return {r.get("name"): r.get("supplier_group") for r in rows}


def _read_delivered_jobs():
	"""Jobs at stage Delivered, not cancelled (delivered_not_invoiced)."""
	dt = "Job Order"
	return frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		filters=[[dt, "docstatus", "<", 2], [dt, "fps_stage", "=", "Delivered"]],
		order_by="jo_date asc, name asc",
		limit_page_length=0,
	)


def _read_bank_statements():
	dt = "FPS Bank Statement"
	return frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		filters=[[dt, "name", "like", "FPS-BST-%"]],
		order_by="name asc",
		limit_page_length=0,
	)


def _read_gl(company, as_of, statements=None):
	"""General Ledger sums for the cash card, the Qashio line and the VAT card.

	Accounts are resolved at run time: every leaf Bank / Cash account of the
	company, and the three named accounts by account_name. One that does not
	exist is left out (None), never a failure of the whole payload.

	Also (review 14 Oct 2026): each bank account's balance at its latest
	statement's closing date (logic.statement_checks; `statements` are the FPS
	Bank Statement rows, None when unreadable), the VAT postings by voucher type,
	and the count / value of the quarter's purchase bills (the input VAT check)."""
	accounts = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0,
		         "account_type": ["in", list(logic.CASH_ACCOUNT_TYPES)]},
		fields=["name", "account_name", "account_type"],
		order_by="name asc",
	)
	named = {key: frappe.db.get_value("Account", {"company": company, "is_group": 0,
	                                               "account_name": account_name}, "name")
	         for key, account_name in logic.NAMED_ACCOUNTS.items()}

	to_date = getdate(as_of)
	stock = _gl_sums(company, [a.get("name") for a in accounts] + [n for n in [named["qashio"]] if n],
	                 to_date=to_date)
	quarter = logic.vat_quarter(to_date)
	vat_accounts = [n for n in (named["vat_output"], named["vat_input"]) if n]
	flow = _gl_sums(company, vat_accounts, from_date=quarter.start, to_date=quarter.window_end,
	                by_voucher_type=True)

	checks = logic.statement_checks(accounts, statements) if statements is not None else []
	for check in checks:
		if check["account"]:
			# Bounded by as_of too: a statement dated after today is compared at today.
			at = min(getdate(check["to_date"]), to_date)
			sums = _gl_sums(company, [check["account"]], to_date=at).get(check["account"]) or {}
			check.update(debit=sums.get("debit") or 0, credit=sums.get("credit") or 0)

	def row(account, sums):
		if not account:
			return None
		s = sums.get(account) or {}
		out = {"account": account, "debit": s.get("debit") or 0, "credit": s.get("credit") or 0}
		if "voucher_types" in s:
			out["voucher_types"] = s["voucher_types"]
		return out

	return {
		"cash": [dict(row(a.get("name"), stock), account_name=a.get("account_name"),
		              account_type=a.get("account_type"))
		         for a in accounts],
		"qashio": row(named["qashio"], stock),
		"vat_output": row(named["vat_output"], flow),
		"vat_input": row(named["vat_input"], flow),
		"statements": checks,
		"vat_purchases": (_purchase_totals(company, quarter.start, quarter.window_end)
		                  if frappe.has_permission("Purchase Invoice", "read") else None),
	}


def _gl_sums(company, accounts, *, to_date, from_date=None, by_voucher_type=False):
	"""{account: {"debit", "credit"}} from GL Entry, cancelled entries excluded.
	by_voucher_type adds "voucher_types": {voucher_type: {"debit", "credit"}}."""
	if not accounts:
		return {}
	from frappe.query_builder.functions import Sum

	gle = frappe.qb.DocType("GL Entry")
	columns = [gle.account] + ([gle.voucher_type] if by_voucher_type else [])
	query = (
		frappe.qb.from_(gle)
		.select(*columns, Sum(gle.debit).as_("debit"), Sum(gle.credit).as_("credit"))
		.where(gle.company == company)
		.where(gle.is_cancelled == 0)
		.where(gle.account.isin(accounts))
		.where(gle.posting_date <= to_date)
	)
	if from_date:
		query = query.where(gle.posting_date >= from_date)
	out = {}
	for r in query.groupby(*columns).run(as_dict=True):
		s = out.setdefault(r.get("account"), {"debit": 0, "credit": 0})
		s["debit"] += r.get("debit") or 0
		s["credit"] += r.get("credit") or 0
		if by_voucher_type:
			s.setdefault("voucher_types", {})[r.get("voucher_type") or ""] = {
				"debit": r.get("debit") or 0, "credit": r.get("credit") or 0}
	return out


def _purchase_totals(company, from_date, to_date):
	"""{count, net, tax} of submitted purchase invoices posted in the window."""
	from frappe.query_builder.functions import Count, Sum

	pi = frappe.qb.DocType("Purchase Invoice")
	rows = (
		frappe.qb.from_(pi)
		.select(Count(pi.name).as_("count"), Sum(pi.base_net_total).as_("net"),
		        Sum(pi.base_total_taxes_and_charges).as_("tax"))
		.where(pi.company == company)
		.where(pi.docstatus == 1)
		.where(pi.posting_date >= from_date)
		.where(pi.posting_date <= to_date)
	).run(as_dict=True)
	r = rows[0] if rows else {}
	return {"count": int(r.get("count") or 0), "net": r.get("net") or 0, "tax": r.get("tax") or 0}
