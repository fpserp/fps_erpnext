"""Read-only data for the FPS workspace blocks: the overview strip and the job tracker.

Two whitelisted methods, both read-only, both permission-aware. They back the two
Custom HTML Blocks on the FPS home page.

Two traps this module deliberately avoids, both verified on this site 2026-09-09:

1. Frappe wraps a date comparison as ifnull(field, '') and '' sorts below any
   date, so `<` on a sparse date column silently matches every UNPOPULATED row.
   `eta < today` returns 38 of 84; with an is-set guard the true answer is 2.
   Every date comparison here carries its ["<field>", "is", "set"] guard.

2. Never rely on a default docstatus. Counts here pass docstatus explicitly, so a
   submittable doctype cannot quietly report only its submitted rows.

A tile whose doctype the caller cannot read is omitted rather than returned as a
zero, so neither block leaks the existence of records the viewer has no rights to.
"""

import frappe
from frappe.utils import today

from fps_erpnext.api import customs

OPEN_JOB = [
    ["Job Order", "fps_stage", "not in", ["Closed", "Invoiced"]],
    ["Job Order", "docstatus", "<", 2],
]

# key, label, note, doctype, filters, route
# THE RULE FOR EVERY TILE: it counts what is still OPEN and needs someone to act.
# A record that has been submitted, completed, invoiced, cleared, closed or
# cancelled drops out of its tile. No tile is ever a lifetime total -- that is
# what the list views behind them are for.
TILES = [
    ("enquiry", "Enquiry", "open", "FPS Enquiry",
     [["FPS Enquiry", "status", "=", "Open"]],
     "/app/fps-enquiry?status=Open"),

    ("quotation", "Quotation", "open", "Quotation",
     [["Quotation", "status", "=", "Open"], ["Quotation", "docstatus", "<", 2]],
     "/app/quotation?status=Open"),

    ("job_order", "Job Order", "open", "Job Order",
     OPEN_JOB,
     "/app/job-order?fps_stage=%5B%22not%20in%22%2C%5B%22Closed%22%2C%22Invoiced%22%5D%5D"),

    # Distinct from Job Order on purpose: this is what is still MOVING. A job
    # sitting at Delivered is open but no longer in motion -- it is waiting on
    # invoicing, and it has its own tile.
    ("job_tracker", "Job Tracker", "in motion", "Job Order",
     [["Job Order", "fps_stage", "in", ["New", "Docs received", "In Progress", "Cleared - Ready"]],
      ["Job Order", "docstatus", "<", 2]],
     "/app/job-order/view/kanban/FPS%20Job%20Tracker"),

    ("customs", "Customs Tracker", "not cleared", "Customs Tracker",
     [["Customs Tracker", "status", "not in", ["Cleared"]]],
     "/app/customs-tracker"),

    ("in_progress", "In Progress", "jobs", "Job Order",
     [["Job Order", "fps_stage", "=", "In Progress"], ["Job Order", "docstatus", "<", 2]],
     "/app/job-order?fps_stage=In%20Progress"),

    # Delivered but not yet invoiced. Once it moves to Invoiced it leaves here
    # and appears under Invoices instead.
    ("delivered", "Delivered", "awaiting invoice", "Job Order",
     [["Job Order", "fps_stage", "=", "Delivered"], ["Job Order", "docstatus", "<", 2]],
     "/app/job-order?fps_stage=Delivered"),

    ("invoices", "Invoices", "open", "Sales Invoice",
     [["Sales Invoice", "status", "in", ["Unpaid", "Overdue", "Partly Paid"]],
      ["Sales Invoice", "docstatus", "=", 1]],
     "/app/sales-invoice?status=%5B%22in%22%2C%5B%22Unpaid%22%2C%22Overdue%22%2C%22Partly%20Paid%22%5D%5D"),
]

# fps_category codes are stored with their prefix, e.g. "CC - Customs Clearance".
# The strip and tracker want the short form.
SOW_SHORT = {
    "CC - Customs Clearance": "Customs clearance",
    "FF - Freight Forwarding": "Freight forwarding",
    "LT - Local Land Transport": "Local transport",
    "XB - Cross-Border Land Transport": "Cross-border",
    "GJ - General Job": "General job",
}


@frappe.whitelist()
def get_overview():
    """Tile counts for the FPS Overview strip. Read-only."""
    tiles = []
    for key, label, note, doctype, filters, route in TILES:
        if not frappe.has_permission(doctype, "read"):
            # Omit rather than zero: a zero still confirms the tile exists.
            continue
        tiles.append({
            "key": key,
            "label": label,
            "note": note,
            "count": frappe.db.count(doctype, filters=filters),
            "route": route,
        })

    return {"tiles": tiles, "footnotes": _footnotes()}


def _footnotes():
    """Honest replacements for the design's sub-lines.

    The handoff asked for "4 unanswered", "3 past deadline" and "2 delivering
    today". None has a populated backing field -- fps_next_due and
    fps_service_date are empty on all 84 job orders, and Customs Tracker's two
    date candidates are empty on all 46 rows. These are what the data supports.
    """
    notes = []
    if frappe.has_permission("Job Order", "read"):
        # The is-set guard is load-bearing: without it this counts every job
        # that has no ETA at all.
        overdue = frappe.db.count("Job Order", filters=OPEN_JOB + [
            ["Job Order", "eta", "is", "set"],
            ["Job Order", "eta", "<", today()],
        ])
        no_eta = frappe.db.count("Job Order", filters=OPEN_JOB + [
            ["Job Order", "eta", "is", "not set"],
        ])
        notes.append("%d past ETA" % overdue)
        if no_eta:
            notes.append("%d with no ETA" % no_eta)
    if frappe.has_permission("Proof of Delivery", "read"):
        notes.append("%d PODs on file" % frappe.db.count(
            "Proof of Delivery", filters=[["Proof of Delivery", "docstatus", "!=", 2]]))
    return notes


@frappe.whitelist()
def get_job_tracker(limit=60):
    """Live job rows for the tracker board, grouped by customer. Read-only.

    One row per open Job Order: who it is for, the customer's own reference, what
    FPS is actually doing on it, the consignment, and where it has reached.
    """
    if not frappe.has_permission("Job Order", "read"):
        return {"jobs": [], "customers": []}

    rows = frappe.get_all(
        "Job Order",
        filters=OPEN_JOB,
        fields=[
            "name", "customer", "customer_name", "client_reference_no",
            "fps_stage", "fps_category", "fps_subcategory",
            "movement_type", "direction", "container_type", "no_of_packages",
            "package_type", "cargo_description", "pol", "pod",
            "awb_bl_no", "boe_no", "eta",
        ],
        order_by="modified desc",
        limit_page_length=frappe.utils.cint(limit) or 60,
    )

    jobs = []
    for r in rows:
        jobs.append({
            "name": r.name,
            "customer": r.customer_name or r.customer or "",
            "reference": r.client_reference_no or "",
            "stage": r.fps_stage or "",
            "sow": r.fps_subcategory or SOW_SHORT.get(r.fps_category, r.fps_category or ""),
            "consignment": _consignment(r),
            "route": _route(r),
            "eta": frappe.utils.formatdate(r.eta, "d MMM") if r.eta else "",
            "doc_route": "/app/job-order/" + r.name,
        })

    # Stable customer order so the colour assignment does not shuffle between loads.
    customers = sorted({j["customer"] for j in jobs if j["customer"]})
    return {"jobs": jobs, "customers": customers}


def _consignment(r):
    """A one-line cargo summary from whichever fields are populated."""
    bits = []
    if r.container_type:
        bits.append(r.container_type)
    elif r.no_of_packages:
        bits.append("%s %s" % (r.no_of_packages, r.package_type or "pkgs"))
    if r.movement_type:
        bits.append(r.movement_type)
    if r.awb_bl_no:
        bits.append(r.awb_bl_no)
    elif r.boe_no:
        bits.append("BOE " + r.boe_no)
    if not bits and r.cargo_description:
        bits.append(r.cargo_description[:40])
    return " · ".join(bits)


def _route(r):
    if r.pol and r.pod:
        return "%s → %s" % (r.pol, r.pod)
    return r.pol or r.pod or ""


# --------------------------------------------------------------------------
# Customs board
#
# Every customs entry in one filterable grid, spreadsheet style: one dropdown
# per column, listing only the values that actually occur, combining with AND.
#
# WHICH COLUMNS, AND WHY THESE ONES. Checked against all 46 rows on 2026-09-10:
#   status              46/46   45 Cleared, 1 In Process
#   customer            46/46   8 distinct
#   job_order           46/46
#   ct_date             46/46
#   fps_clearance_type  46/46   the real discriminator (FZ / ROW / transit)
#   boe_number          46/46
#   fps_mofa_status     28/46   Completed / Pending / N/A
#   fps_doc_submission  38/46   Pending / Submitted
#   fps_deposit_status  46/46   after customs_tracker_sheet_columns backfills it
#   fps_deposit_claim   46/46   likewise
#
# Deposit and Claim read "Not Applicable" on all 46 today. That is NOT the same
# as empty: it is the answer, it comes from the workbook, and it turns into real
# information the first time a job carries a customs deposit. An empty column
# would have been left out -- a uniform one is kept.
#
# Deliberately NOT shown:
#   fps_do_status        0/46   empty on every row -- and dropped from the list
#                               view in the same commit
#   fps_leg              4 rows carry leg 2; it lives on the form
#   fps_clearance_location  1/46  one row in Khorfakkan, nothing else. Add it
#                               back the day it is being filled in; it is one
#                               entry in COLUMNS below.
#   fps_approval_required  "N/A" on all 46, and free text rather than a Select,
#                               so it filters to nothing useful. On the form.
# --------------------------------------------------------------------------

# (key, label, fieldname, filterable)
#
# COLUMNS AND HEADINGS COME FROM THE OPERATIONS WORKBOOK, "Daily Operation's &
# Quotes MAY 2026.xlsx" -- same order, same words (Job No., Client, BOE, Type,
# Date, MOFA, Doc Sub, Deposit, Claim), so the board reads like the sheet it
# replaces. ERPNext's own Status leads, because it carries the colour pill.
#
# declaration_type is NOT here. It is populated on all 46 rows and is still on
# the form and in the list filters, but the workbook has no such column and
# "Type" already answers the same question in the words operations use.
CUSTOMS_COLUMNS = [
    ("status", "Status", "status", True),
    ("customer", "Client", "customer", True),
    ("job_order", "Job No.", "job_order", True),
    ("boe", "BOE", "boe_number", False),
    ("clearance_type", "Type", "fps_clearance_type", True),
    ("date", "Date", "ct_date", False),
    ("mofa", "MOFA", "fps_mofa_status", True),
    ("mofa_due", "MOFA due", "fps_mofa_deadline", False),
    ("doc_sub", "Doc Sub", "fps_doc_submission", True),
    ("doc_due", "Doc due", "fps_doc_deadline", False),
    ("deposit", "Deposit", "fps_deposit_status", True),
    ("claim", "Claim", "fps_deposit_claim", True),
]

# key -> the deadline spec that colours it, from fps_erpnext.api.customs.
# The board does NOT recompute the thresholds; it asks customs.deadline_state,
# so amber means the same thing here, on the form and in the stored dates.
DEADLINE_COLUMNS = {
    "doc_due": "doc",
    "mofa_due": "mofa",
}


@frappe.whitelist()
def get_customs_tracker(limit=400):
    """Every customs entry, plus the distinct value list for each filterable
    column. Read-only.

    The filter options come from the ROWS THAT WERE RETURNED, not from the field
    definition, so a dropdown never offers a value that would filter to nothing
    -- and never offers a value from a record the caller cannot read.
    """
    if not frappe.has_permission("Customs Tracker", "read"):
        return {"columns": [], "rows": [], "options": {}}

    # clearance_date is fetched but never shown: it is what both deadline
    # colours are measured from.
    fields = ["name", "clearance_date"] + [f for _k, _l, f, _fl in CUSTOMS_COLUMNS]

    records = frappe.get_all(
        "Customs Tracker",
        fields=fields,
        order_by="ct_date desc, name desc",
        limit_page_length=frappe.utils.cint(limit) or 400,
    )

    specs = {spec["key"]: spec for spec in customs.DEADLINES}
    as_of = frappe.utils.today()

    rows = []
    for r in records:
        row = {"name": r.name}
        for key, _label, field, _filterable in CUSTOMS_COLUMNS:
            value = r.get(field)
            if field == "ct_date":
                value = frappe.utils.formatdate(value, "dd-MM-yyyy") if value else ""
                row["sort_date"] = str(r.get(field) or "")
            elif key in DEADLINE_COLUMNS:
                value = frappe.utils.formatdate(value, "dd-MM-yyyy") if value else ""
            row[key] = value or ""

        # One state per deadline column, computed HERE so the board, the form
        # and the stored dates cannot disagree about what amber means.
        for key, spec_key in DEADLINE_COLUMNS.items():
            spec = specs[spec_key]
            row[key + "_state"] = customs.deadline_state(
                r.get("clearance_date"), r.get(spec["status_field"]), spec, as_of
            )
        rows.append(row)

    options = {}
    for key, _label, _field, filterable in CUSTOMS_COLUMNS:
        if not filterable:
            continue
        options[key] = sorted({r[key] for r in rows if r[key]})

    return {
        "columns": [{"key": k, "label": l, "filterable": f}
                    for k, l, _field, f in CUSTOMS_COLUMNS],
        "rows": rows,
        "options": options,
    }
