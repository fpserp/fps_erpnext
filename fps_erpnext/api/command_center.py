"""Read-only data for the FPS OPS Dashboard (the Command Center in the FPS Overview block).

Two whitelisted GET methods, both read-only, both permission-aware:

    get_dashboard(period)                    -> DashboardPayload
    get_metric_detail(key, period, dimension) -> MetricDetail

The payload contract is dashboard/src/types/dashboard.ts. This module only
decides WHO may see WHAT and reads the rows; every number, string and insight
is computed by fps_erpnext.api.command_center_logic (pure Python, unit-tested
without a bench). The pipeline strip is fps_erpnext.api.pipeline.get_overview,
called as-is.

NOTHING HERE WRITES. Reads go through frappe.get_list (permission-aware: role
permissions, User Permissions, permission query conditions, shares). The only
non-SQL side effect is a 60-second Redis cache entry per (user, period) for
get_dashboard -- never shared across users, never a database write.

THE TRAPS pipeline.py documents apply here too, and are handled the same way:
docstatus is always passed explicitly (most live Job Orders and every Proof of
Delivery since July are drafts), and every date filter carries its
["<field>", "is", "set"] guard. Aggregation is done in Python: v16's query
builder rejects string aggregates in `fields`, and one read per doctype then
serves the KPI, its sparkline, the 12-week trend and the insights.

NO MONEY ON THIS PAGE, FOR ANYONE (Agam, 14 Oct 2026: keep this dashboard as
the FPS OPS dashboard, open to all, without the invoices and collection
parts). The money moved to the FPS ACC Dashboard (fps_erpnext.api.
acc_dashboard, Accounts Manager only). So every viewer -- finance roles and
Administrator included -- is built as a non-finance viewer (OPS_FINANCE): no
Sales Invoice or Payment Entry read, no invoiced/collected KPI, no money trend,
no money insight (duplicate drafts, invoicing stall, AR ageing), no quotation
amount, viewer.finance always false, and get_metric_detail refuses the money
metrics. The "invoices" tile (open Sales Invoices) is dropped from the stage
strip here (logic.ops_stages), not in pipeline.TILES, which the classic strip
and other callers keep. The gate is server-side because FPS Operations can
read Sales Invoice and Payment Entry at permlevel 0 (checked 2026-10-10), so
hiding money client-side would be cosmetic; and logic.build_dashboard drops
money rows again for a non-finance viewer, so a caller mistake cannot leak
them either.

FIELD-LEVEL PERMISSIONS. The app's property setters put the Sales Invoice
amounts (base_net_total, base_grand_total, outstanding_amount, ...) at
permlevel 1, readable by the Accounts roles. In v16, frappe.get_list goes
through frappe/model/qb_query.py and frappe/database/query.py. There, a
SELECTED field the viewer cannot read is silently dropped
(Engine.apply_field_permissions). A FILTER or ORDER-BY field the viewer cannot
read raises frappe.PermissionError (Engine._check_field_permission).
_read_invoices filters on outstanding_amount, so Sales Invoice is only read
when the viewer holds permlevel-1 read (_can_read below). Otherwise it is left
out and the logic omits the money metrics, never "AED 0". (Since 14 Oct 2026
this page reads no Sales Invoice at all; the FPS ACC Dashboard reuses
_read_invoices and _can_read.)

FIELDS, VERIFIED READ-ONLY against the live site on 2026-10-10 (fps-erpnext MCP
get_doctype_info / list_documents; fps_job_order re-checked as a Link to Job
Order; permlevel 0 unless the paragraph above says otherwise):

    FPS Enquiry        enquiry_date (Date, reqd), status (Open/Quoted/Converted/
                       Lost/Cancelled), enquiry_source (Select), client_name
                       (Data, title field), movement_type. Not submittable.
    Quotation          transaction_date, status, docstatus, base_grand_total,
                       customer_name, party_name, quotation_to, valid_till.
    Job Order          jo_date (reqd), docstatus, fps_category, fps_stage, eta,
                       customer, customer_name, client_reference_no,
                       sales_invoice. Child table fps_updates -> FPS Job Update.
    FPS Job Update     (child of Job Order, parentfield fps_updates) update_date
                       (Date, reqd), milestone, status_line, event_type, source
                       (Manual/Claude/System/Backfill), parent, creation.
    Customs Tracker    ct_date, clearance_date, status, customer, job_order,
                       boe_number, fps_clearance_type, fps_doc_submission,
                       fps_doc_deadline, fps_mofa_status, fps_mofa_deadline.
                       Not submittable.
    Proof of Delivery  pod_date (reqd), docstatus, delivery_status (Pending/
                       Delivered/Failed/Returned), customer, job_order,
                       movement_type, client_reference_no.
    Sales Invoice      posting_date, docstatus, status, base_net_total,
                       base_grand_total, outstanding_amount, due_date, customer,
                       customer_name, fps_job_order, is_return,
                       fps_is_payment_request. (The fps_* GP fields are
                       permlevel 1 and deliberately not read.)
    Payment Entry      posting_date, payment_type, base_received_amount, party,
                       party_name, mode_of_payment, reference_no, creation.
"""

import frappe
from frappe import _
from frappe.utils import get_fullname, getdate, now_datetime, today

from fps_erpnext.api import command_center_logic as logic
from fps_erpnext.api import pipeline

# The OPS page is built as a non-finance viewer for EVERYONE (see the module
# docstring). One constant, so no call site can pass True by accident.
OPS_FINANCE = False

# Polled every 60 s by the dashboard; the cache makes a poll from a second tab
# (or a quick period toggle back) free. Versioned so a deploy that changes the
# payload shape never serves the old one.
CACHE_TTL = 60
# v3: money-free for everyone (14 Oct 2026). The bump also makes sure no v2
# payload -- which carried money for finance viewers -- is served after deploy.
CACHE_KEY = "fps_command_center:v3:dashboard:%s"

MAX_DIMENSION_LENGTH = 140


@frappe.whitelist(methods=["GET"])
def get_dashboard(period: str = "7d"):
	"""Operations KPIs, pipeline strip, weekly trend and insights. Read-only, no money."""
	period = _check_period(period)
	user = frappe.session.user
	key = CACHE_KEY % period

	# user= scopes the key to this user ("user:<user>:..."), so one viewer's
	# numbers (permission-dependent) can never be served to another.
	cached = frappe.cache().get_value(key, user=user, expires=True)
	if cached is not None:
		return cached

	payload = _dashboard(period, user)
	frappe.cache().set_value(key, payload, user=user, expires_in_sec=CACHE_TTL)
	return payload


@frappe.whitelist(methods=["GET"])
def get_metric_detail(key: str, period: str = "30d", dimension: str | None = None):
	"""One KPI's drawer: series, breakdown, latest records, quick actions. Read-only.

	The money metrics (invoiced, collected) are refused for EVERY viewer here,
	Administrator included: they live on the FPS ACC Dashboard now
	(fps_erpnext.api.acc_dashboard.get_metric_detail).
	"""
	period = _check_period(period)
	if not isinstance(key, str) or key not in logic.METRICS:
		frappe.throw(_("Unknown metric"), frappe.ValidationError)
	spec = logic.METRICS[key]

	if spec["finance"] or not _can_read(spec["doctype"]):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	dimension = _check_dimension(dimension)
	as_of = getdate(today())
	raw = _read_rows(logic.fetch_floor(period, as_of), finance=OPS_FINANCE, keys=(key,))
	can_create = bool(spec["new_doctype"]) and frappe.has_permission(spec["new_doctype"], "create")
	return logic.build_metric_detail(
		key, raw, period=period, as_of=as_of, dimension=dimension,
		finance=OPS_FINANCE, can_create=can_create)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def _dashboard(period, user):
	as_of = getdate(today())
	raw = _read_rows(logic.fetch_floor(period, as_of), finance=OPS_FINANCE, keys=logic.KPI_ORDER)
	return logic.build_dashboard(
		period=period,
		as_of=as_of,
		generated_at=logic.timestamp(now_datetime()),
		viewer={"finance": OPS_FINANCE, "full_name": get_fullname(user)},
		raw=raw,
		# The open-invoices tile belongs to the FPS ACC Dashboard.
		stages=logic.ops_stages(pipeline.get_overview()),
		creatable=_creatable(),
	)


def _can_read(doctype):
	"""Readable at permlevel 0 and, for Sales Invoice, also at permlevel 1:
	_read_invoices filters on outstanding_amount (permlevel 1), and a v16 filter
	on a field the viewer cannot read throws PermissionError."""
	if not frappe.has_permission(doctype, "read"):
		return False
	if doctype == "Sales Invoice":
		return 1 in frappe.get_meta(doctype).get_permlevel_access("read")
	return True


def _creatable():
	"""DocTypes the viewer may open a blank "new" form for (the drawer's quick action).
	Only the operations metrics' doctypes: this page has no money metric."""
	doctypes = {m["new_doctype"] for m in logic.METRICS.values()
	            if m["new_doctype"] and not m["finance"]}
	return {dt for dt in doctypes if frappe.has_permission(dt, "create")}


def _check_period(period):
	if not isinstance(period, str) or period not in logic.PERIODS:
		frappe.throw(_("Period must be one of {0}").format(", ".join(logic.PERIODS)),
		             frappe.ValidationError)
	return period


def _check_dimension(dimension):
	"""A plain string or None. Whether it matches an option is decided against
	the rows actually read (logic.build_metric_detail falls back to "All")."""
	if dimension is None:
		return None
	if not isinstance(dimension, str) or len(dimension) > MAX_DIMENSION_LENGTH:
		frappe.throw(_("Invalid dimension"), frappe.ValidationError)
	dimension = dimension.strip()
	return dimension or None


# --------------------------------------------------------------------------
# Reads -- one per doctype, bounded by the earliest date the call needs
# --------------------------------------------------------------------------

def _read_rows(floor, *, finance, keys):
	"""{doctype: rows} for the metrics in `keys`.

	A doctype the viewer cannot read is left out of the dict entirely, and the
	logic module then omits its metrics rather than reporting a zero -- the same
	rule as pipeline.get_overview, so nothing confirms records the viewer has no
	rights to. Money doctypes are not even read for a non-finance viewer, which
	on this page is everyone (OPS_FINANCE).
	"""
	keys = [k for k in keys if finance or not logic.METRICS[k]["finance"]]
	need = {logic.METRIC_SOURCE[k] for k in keys}
	floor = floor.isoformat()

	raw = {}
	for doctype, reader in READERS.items():
		if doctype in need and _can_read(doctype):
			raw[doctype] = reader(floor)

	if need & {"Job Order", "FPS Job Update"} and frappe.has_permission("Job Order", "read"):
		raw.update(_read_jobs(floor, with_updates="FPS Job Update" in need))
	return raw


def _read_enquiries(floor):
	dt = "FPS Enquiry"
	return frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		filters=[
			# Not submittable (always 0), but passed explicitly all the same.
			[dt, "docstatus", "<", 2],
			[dt, "enquiry_date", "is", "set"],
			[dt, "enquiry_date", ">=", floor],
			# The bot line's duplicates are cancelled, not deleted (10 of them
			# on 06-08 Oct); counting them would nearly double that week.
			[dt, "status", "!=", "Cancelled"],
		],
		order_by="enquiry_date desc, name desc",
		limit_page_length=0,
	)


def _read_quotations(floor):
	dt = "Quotation"
	return frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		filters=[
			# Drafts count: bot-line quotes wait as drafts for Agam's "ok".
			[dt, "docstatus", "in", [0, 1]],
			[dt, "transaction_date", "is", "set"],
			[dt, "transaction_date", ">=", floor],
		],
		order_by="transaction_date desc, name desc",
		limit_page_length=0,
	)


def _read_customs(floor):
	dt = "Customs Tracker"
	return frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		# Not submittable (always 0), but passed explicitly all the same.
		filters=[[dt, "docstatus", "<", 2]],
		# Recent trackers for the cleared count, PLUS every tracker still
		# waiting on originals or MOFA however old -- the overdue insights must
		# not lose a tracker just because it was declared before the floor.
		or_filters=[
			[dt, "clearance_date", ">=", floor],
			[dt, "ct_date", ">=", floor],
			[dt, "fps_doc_submission", "in", list(logic.CUSTOMS_OPEN_DOC)],
			[dt, "fps_mofa_status", "in", list(logic.CUSTOMS_OPEN_MOFA)],
		],
		order_by="ct_date desc, name desc",
		limit_page_length=0,
	)


def _read_deliveries(floor):
	dt = "Proof of Delivery"
	return frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		filters=[
			# Only 2 PODs have been submitted since late June; docstatus=1 alone
			# would report no deliveries at all.
			[dt, "docstatus", "in", [0, 1]],
			[dt, "pod_date", "is", "set"],
			[dt, "pod_date", ">=", floor],
		],
		order_by="pod_date desc, name desc",
		limit_page_length=0,
	)


def _read_invoices(floor):
	"""Sales Invoices for the money KPIs and insights. Not read by this page any
	more (OPS_FINANCE); fps_erpnext.api.acc_dashboard calls it for the ACC page.

	Read: everything posted since the floor, everything still outstanding
	however old (the AR figures include the legacy 2023-2025 book by design),
	and EVERY draft however old (drafts waiting is a stock, not a flow). Then a
	second, narrow read for the duplicate-draft insight: the submitted invoices
	on the drafts' Job Orders that the first read did not reach (an older, fully
	paid invoice is outside both of its windows).
	"""
	dt = "Sales Invoice"
	rows = frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		# Drafts are read only for "drafts waiting" and the invoicing insights;
		# the invoiced KPI itself counts submitted invoices (logic.points_invoiced).
		filters=[[dt, "docstatus", "in", [0, 1]]],
		or_filters=[
			[dt, "posting_date", ">=", floor],
			[dt, "outstanding_amount", "!=", 0],
			[dt, "docstatus", "=", 0],
		],
		order_by="posting_date desc, name desc",
		limit_page_length=0,
	)
	draft_jobs = sorted({r.fps_job_order for r in rows if r.docstatus == 0 and r.fps_job_order})
	if draft_jobs:
		seen = {r.name for r in rows}
		older = frappe.get_list(
			dt,
			fields=logic.FIELDS[dt],
			filters=[
				[dt, "docstatus", "=", 1],
				[dt, "fps_job_order", "in", draft_jobs],
				[dt, "posting_date", "<", floor],
			],
			order_by="posting_date desc, name desc",
			limit_page_length=0,
		)
		rows += [r for r in older if r.name not in seen]
	return rows


def _read_receipts(floor):
	dt = "Payment Entry"
	return frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		filters=[
			[dt, "docstatus", "=", 1],
			[dt, "payment_type", "=", "Receive"],
			[dt, "posting_date", "is", "set"],
			[dt, "posting_date", ">=", floor],
		],
		order_by="posting_date desc, name desc",
		limit_page_length=0,
	)


READERS = {
	"FPS Enquiry": _read_enquiries,
	"Quotation": _read_quotations,
	"Customs Tracker": _read_customs,
	"Proof of Delivery": _read_deliveries,
	"Sales Invoice": _read_invoices,
	"Payment Entry": _read_receipts,
}


def _read_jobs(floor, *, with_updates):
	"""Job Orders, and (optionally) their update rows restricted to readable parents.

	WHY get_all FOR THE UPDATE ROWS. FPS Job Update is a child table: its rows
	have no permissions of their own, they inherit the Job Order's. A plain list
	query on the child doctype returns blank fields on this site (checked
	2026-10-10), so the rows are read with frappe.get_all -- which skips
	permission checks -- and ONLY after the caller has confirmed
	has_permission("Job Order", "read"). That alone would still count updates on
	jobs a User Permission hides, so the parents are then read through the
	permission-aware get_list below, and an update whose parent did not come
	back is dropped. The same read supplies each update's customer and stage.

	One Job Order read serves the jobs KPI (jo_date in range), the past-ETA
	insight (every open job, however old -- same rule as pipeline.OPEN_JOB)
	and the update parents.
	"""
	updates = []
	if with_updates:
		updates = frappe.get_all(
			"FPS Job Update",
			fields=logic.FIELDS["FPS Job Update"],
			filters=[
				["FPS Job Update", "parenttype", "=", "Job Order"],
				["FPS Job Update", "parentfield", "=", "fps_updates"],
				["FPS Job Update", "update_date", "is", "set"],
				["FPS Job Update", "update_date", ">=", floor],
				# The 10-11 Sep go-live backfill wrote hundreds of rows with
				# historical dates; counted, July would dwarf every live week.
				["FPS Job Update", "source", "!=", "Backfill"],
			],
			order_by="update_date desc, creation desc",
			limit_page_length=0,
		)

	dt = "Job Order"
	or_filters = [
		[dt, "jo_date", ">=", floor],
		[dt, "fps_stage", "not in", list(logic.CLOSED_JOB_STAGES)],
	]
	parents = sorted({u.parent for u in updates if u.parent})
	if parents:
		or_filters.append([dt, "name", "in", parents])

	jobs = frappe.get_list(
		dt,
		fields=logic.FIELDS[dt],
		filters=[[dt, "docstatus", "<", 2]],
		or_filters=or_filters,
		order_by="jo_date desc, name desc",
		limit_page_length=0,
	)
	if not with_updates:
		return {"Job Order": jobs}

	by_name = {j.name: j for j in jobs}
	kept = []
	for u in updates:
		job = by_name.get(u.parent)
		if not job:
			# Parent not readable for this viewer, or cancelled: not counted.
			continue
		u["job_customer"] = job.customer_name or job.customer
		u["job_stage"] = job.fps_stage
		kept.append(u)
	return {"Job Order": jobs, "FPS Job Update": kept}
