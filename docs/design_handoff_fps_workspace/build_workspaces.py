#!/usr/bin/env python3
"""
Generate the FPS workspace fixtures for design 1a (step 1 of the handoff README).

Emits app-shipped JSON under fps_erpnext/fps/workspace/<slug>/<slug>.json and
fps_erpnext/fps/workspace_sidebar/fps/fps.json. Both `workspace` and
`workspace_sidebar` are in Frappe v16's IMPORTABLE_DOCTYPES, so `bench migrate`
imports these on deploy -- the layout lives in the app, not the site DB.

Run:  python docs/design_handoff_fps_workspace/build_workspaces.py
"""

import json
import os

APP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MODULE_PATH = os.path.join(APP_ROOT, "fps_erpnext", "fps")

MODULE = "FPS"
APP = "fps_erpnext"
OWNER = "Administrator"
# Must be newer than the row already in the site DB or the importer SILENTLY skips
# the file -- frappe/modules/import_file.py compares this against the DB `modified`
# and `continue`s with no error and no warning. The content-hash rescue there is
# guarded by `if doc['doctype'] == 'DocType'`, so workspaces and client scripts get
# no second chance. BUMP THIS ON EVERY CONTENT CHANGE, and do not edit these
# workspaces in the desk UI between generating and deploying -- a desk save sets
# `modified` to now(), which would out-race the stamp and drop the whole import.
STAMP = "2026-09-10 21:10:00.000000"
CREATED = "2026-09-09 13:30:00.000000"


# --------------------------------------------------------------------------
# link / content helpers
# --------------------------------------------------------------------------

def card(label, links):
    """A Card Break plus its Link rows, as Frappe's exporter writes them."""
    rows = [{
        "hidden": 0,
        "is_query_report": 0,
        "label": label,
        "link_count": len(links),
        "onboard": 0,
        "type": "Card Break",
    }]
    for link in links:
        target, link_type, text = link
        rows.append({
            "dependencies": "",
            "hidden": 0,
            "is_query_report": 1 if link_type == "Report" else 0,
            "label": text,
            "link_count": 0,
            "link_to": target,
            "link_type": link_type,
            "onboard": 0,
            "type": "Link",
        })
    return rows


def doc(name, link_type="DocType", label=None):
    return (name, link_type, label or name)


def block(btype, data):
    return {"id": data.pop("id"), "type": btype, "data": data}


def header(text, bid, size="h4"):
    return block("header", {
        "id": bid,
        "text": '<span class="%s"><b>%s</b></span>' % (size, text),
        "col": 12,
    })


def paragraph(text, bid):
    return block("paragraph", {"id": bid, "text": text, "col": 12})


def card_block(card_name, bid, col=4):
    return block("card", {"id": bid, "card_name": card_name, "col": col})


def shortcut_block(shortcut_name, bid, col=3):
    return block("shortcut", {"id": bid, "shortcut_name": shortcut_name, "col": col})


def number_card_block(number_card_name, bid, col=3):
    return block("number_card", {"id": bid, "number_card_name": number_card_name, "col": col})


def shortcut(label, link_to, color, doc_view="List", stats_filter=None,
             fmt=None, stype="DocType", kanban_board=None, icon=None):
    """A Workspace Shortcut row.

    stats_filter is stored as a JSON *string* of 4-element rows
    [doctype, fieldname, operator, value]; a 5-element row makes v16's
    frappe.utils.cleanup_filters silently drop the last filter. `fmt` is the
    badge template, e.g. "{} open". Colours are Frappe's Title-case palette
    names (Red / Orange / Yellow / Blue / Cyan / Green / Purple / Pink / Grey).
    """
    row = {
        "color": color,
        "doc_view": doc_view,
        "format": fmt,
        "icon": icon,
        "kanban_board": kanban_board,
        "label": label,
        "link_to": link_to,
        "restrict_to_domain": None,
        "stats_filter": json.dumps(stats_filter, separators=(",", ":")) if stats_filter else None,
        "type": stype,
        "url": None,
    }
    return row


def quick_list(label, document_type, quick_list_filter=None):
    return {
        "document_type": document_type,
        "label": label,
        "quick_list_filter": (json.dumps(quick_list_filter, separators=(",", ":"))
                              if quick_list_filter else None),
    }


def custom_block_block(block_name, bid, col=12):
    return block("custom_block", {"id": bid, "custom_block_name": block_name, "col": col})


def quick_list_block(quick_list_name, bid, col=12):
    return block("quick_list", {"id": bid, "quick_list_name": quick_list_name, "col": col})


def chart_block(chart_name, bid, col=12):
    return block("chart", {"id": bid, "chart_name": chart_name, "col": col})


def workspace(name, title, sequence_id, icon, content, links,
              parent_page="", roles=None, indicator_color="",
              shortcuts=None, number_cards=None, charts=None,
              quick_lists=None, custom_blocks=None, idx=0):
    return {
        "app": APP,
        "charts": charts or [],
        "content": json.dumps(content, separators=(",", ":")),
        "creation": CREATED,
        "custom_blocks": custom_blocks or [],
        "docstatus": 0,
        "doctype": "Workspace",
        "for_user": "",
        "hide_custom": 0,
        "icon": icon,
        "idx": idx,
        "indicator_color": indicator_color,
        "is_hidden": 0,
        "label": name,
        "links": links,
        "modified": STAMP,
        "modified_by": OWNER,
        "module": MODULE,
        "name": name,
        "number_cards": number_cards or [],
        "owner": OWNER,
        "parent_page": parent_page,
        "public": 1,
        "quick_lists": quick_lists or [],
        "restrict_to_domain": "",
        "roles": [{"role": r} for r in (roles or [])],
        "sequence_id": float(sequence_id),
        "shortcuts": shortcuts or [],
        "title": title,
        "type": "Workspace",
    }


# --------------------------------------------------------------------------
# Roles
#
# Verified against the live site 2026-09-09: agam@ and abhishek@ hold System
# Manager + Accounts Manager + HR Manager + FPS Operations; ops@ holds only
# Employee / Desk User / FPS Operations; hello@ holds FPS Viewer.
# Empty roles == visible to everyone, which is today's behaviour for "FPS".
# --------------------------------------------------------------------------

OPS_ROLES = ["FPS Operations", "System Manager"]
SALES_ROLES = ["FPS Operations", "Sales User", "Sales Manager", "System Manager"]
# Ops raise invoices and book supplier costs, so they need the Accounts page.
# What they must NOT see -- receipts, bank reconciliation, outstanding totals --
# is withheld by DOCUMENT permissions, not by hiding this page: Frappe hides each
# workspace link, sidebar item and report the viewer cannot open, and hides a card
# once all its links are hidden. Layout follows permissions, never the reverse.
ACCOUNTS_ROLES = ["FPS Operations", "Accounts User", "Accounts Manager",
                  "System Manager"]
# The receipts sub-tab stays finance-only.
RECEIPTS_ROLES = ["Accounts User", "Accounts Manager", "System Manager"]
HR_ROLES = ["HR User", "HR Manager", "System Manager"]
SETUP_ROLES = ["System Manager"]


# ==========================================================================
# 1. FPS  (the home page -- design 1a)
#
# The record keeps the name "FPS" so /app/fps, hooks.py add_to_apps_screen,
# the sidebar's Home item and Payment Receipts' parent_page all stay valid.
# The sidebar shows it as "FPS Home".
#
# Step 1 owns the information architecture only: the ten link cards that used
# to crowd this page move out to the six children, and the three design link
# cards take their place. The existing shortcuts and number cards stay put so
# the page keeps working until steps 2-4 restyle them.
# ==========================================================================

FPS_HOME_LINKS = (
    # The Sales / Operations / Accounts link cards that used to sit at the bottom
    # of this page are gone: the left sidebar now carries that navigation, so
    # repeating it here was two places to maintain and one to forget.
    []
)

FPS_HOME_CONTENT = [
    header("Fast Planet Shipping", "fpshdr"),
    custom_block_block("FPS Overview", "fpsoverview"),
    custom_block_block("FPS Job Tracker", "fpsjobtracker"),
    # Deliberately last on the page: it is the "what do I pick up now" list, read
    # after the overview and the tracker rather than before them.
    quick_list_block("Jobs needing action", "fpsql1"),
]

# --------------------------------------------------------------------------
# Step 2 -- the six design shortcuts.
#
# Every filter below was probed and then adversarially re-verified against live
# data on 2026-09-09: each one is accepted by the site, every row is 4 elements,
# and the returned count matched. Counts shown are what the badge reads TODAY --
# the design's numbers (4 / 22 / 14 / 29 / 63 / 53) are illustrative placeholders
# and no filter was bent to reach them.
#
# These ten legacy shortcuts are replaced: FPS Job Tracker, Open jobs by SOW,
# Job Order, Customs Tracker, FPS Enquiry, Proof of Delivery, Quotation, Sales
# Invoice, Payment Entry, Bank Reconciliation. Every target survives on a child
# workspace's link cards, in the sidebar, or on Payment Receipts.
# --------------------------------------------------------------------------

FPS_HOME_SHORTCUTS = [
    # The six shortcut tiles are gone. Every one duplicated a tile in the FPS
    # Overview strip, which links to the same lists and also carries a count.
]

# Two README IA members that had no primitive in step 1 and are expressible as
# filtered shortcuts. They live on FPS Operations rather than the home page, so
# the design's six-tile single row stays intact.
OPERATIONS_SHORTCUTS = [
    # Mirrors the Kanban board's own filter (docstatus < 2), so board and badge
    # can never disagree.
    shortcut("Daily Job Tracker", "Job Order", "Blue", doc_view="Kanban",
             kanban_board="FPS Job Tracker",
             stats_filter=[["Job Order", "fps_stage", "not in", ["Closed", "Invoiced"]],
                           ["Job Order", "docstatus", "<", 2]],
             fmt="{} open"),

    # 26 of 84, and named "Local" on purpose. A stats_filter ANDs every row and
    # cannot express OR, so this cannot be "transport OR cross-border" (31 jobs) --
    # adding the second row would give the intersection, which is 1.
    shortcut("Local trucking & delivery", "Job Order", "Orange",
             stats_filter=[["Job Order", "fps_svc_transport", "=", 1]],
             fmt="{} jobs"),
]

FPS_HOME_NUMBER_CARDS = []

# The SOW breakdown built in the desk on 2026-09-09 is preserved, but moved off
# the home page to Operations where a per-service split belongs. "Next action
# overdue" is deliberately NOT carried over: fps_next_due is empty on all 84 job
# orders, and Frappe's ifnull() coercion makes its "<" comparison match every
# unpopulated row, so it renders 40 when the true answer is 0.
OPERATIONS_NUMBER_CARDS = [
    {"label": lbl, "number_card_name": lbl} for lbl in (
        # The four from step 3, moved off the home page at the owner's request.
        "FPS Jobs past ETA",
        "FPS Clearance in progress",
        "FPS Delivered not invoiced",
        "FPS Cleared ready to deliver",
        # The SOW split built in the desk on 2026-09-09, preserved.
        "Open - Customs clearance",
        "Open - Freight forwarding",
        "Open - Land transport",
        "Open - General jobs",
        "On hold",
    )
]


# ==========================================================================
# 2-7. the six child workspaces
# ==========================================================================

SALES_LINKS = (
    card("Sales", [
        doc("FPS Enquiry"),
        doc("Quotation"),
        doc("Sales Order"),
        doc("Customer"),
    ])
    + card("CRM", [
        doc("Lead"),
        doc("Opportunity"),
        doc("Contact"),
    ])
)

OPERATIONS_LINKS = (
    card("Jobs", [
        doc("Job Order"),
        doc("Job Update Log", label="Job update log (history)"),
        doc("FPS Enquiry"),
    ])
    + card("Customs", [
        doc("Customs Tracker", label="Customs Tracker · Mirsal"),
    ])
    + card("Trucking & delivery", [
        doc("Delivery Note"),
        doc("Proof of Delivery"),
    ])
)

ACCOUNTS_LINKS = (
    card("Billing", [
        doc("Sales Invoice"),
        doc("Purchase Invoice"),
        doc("Payment Entry"),
        doc("Journal Entry"),
    ])
    + card("Buying", [
        doc("Material Request"),
        doc("Purchase Order"),
        doc("Supplier"),
    ])
    + card("Bank & reconciliation", [
        doc("FPS Bank Statement", label="Bank statements"),
        doc("Payment Reconciliation"),
        doc("Account", label="Chart of Accounts"),
    ])
    + card("Receivables & payables", [
        doc("Accounts Receivable", "Report"),
        doc("Accounts Payable", "Report"),
        doc("Customer Ledger Summary", "Report"),
    ])
    + card("Tax", [
        doc("UAE VAT 201", "Report", "VAT 5% return"),
        doc("VAT Audit Report", "Report"),
    ])
)

HR_LINKS = (
    card("People", [
        doc("Employee"),
        doc("Attendance"),
        doc("Shift Assignment"),
    ])
    + card("Leave & claims", [
        doc("Leave Application"),
        doc("Expense Claim"),
    ])
    + card("Payroll", [
        doc("Payroll Entry"),
        doc("Salary Slip"),
    ])
)

REPORTS_LINKS = (
    card("FPS reports", [
        doc("FPS Open Jobs by SOW", "Report"),
        doc("FPS Profitability per Job Order", "Report"),
        doc("FPS Monthly GP Trend", "Report"),
    ])
    + card("Accounting reports", [
        doc("General Ledger", "Report"),
        doc("Accounts Receivable", "Report"),
        doc("Accounts Payable", "Report"),
        doc("Sales Register", "Report"),
        doc("Trial Balance", "Report"),
    ])
)

MASTERS_LINKS = (
    card("Masters", [
        doc("Customer"),
        doc("Supplier"),
        doc("Item", label="Charge items"),
        doc("Item Group"),
        doc("Cost Center"),
    ])
    + card("Stock", [
        doc("Stock Entry"),
        doc("Warehouse"),
    ])
    + card("Users & roles", [
        doc("User"),
        doc("Role"),
    ])
    + card("Integrations", [
        doc("FPS Outgoing Email"),
        doc("FPS Microsoft Settings"),
        doc("Qashio Settings"),
        doc("Qashio Sync Log"),
    ])
)


def child_content(title, blurb, cards, extra=None, shortcuts=(),
                  number_cards=(), charts=()):
    blocks = [header(title, "hdr_" + title.lower().replace(" ", "_").replace("&", "n"))]
    if blurb:
        blocks.append(paragraph(blurb, "txt_" + title.lower().replace(" ", "_").replace("&", "n")))
    blocks.extend(extra or [])
    for i, nc in enumerate(number_cards):
        blocks.append(number_card_block(nc["number_card_name"], "n%d_%s" % (
            i, title.lower().replace(" ", "_").replace("&", "n"))))
    for i, ch in enumerate(charts):
        blocks.append(chart_block(ch["chart_name"], "g%d_%s" % (
            i, title.lower().replace(" ", "_").replace("&", "n"))))
    for i, sc in enumerate(shortcuts):
        blocks.append(shortcut_block(sc["label"], "s%d_%s" % (
            i, title.lower().replace(" ", "_").replace("&", "n")), col=3))
    for i, name in enumerate(cards):
        blocks.append(card_block(name, "c%d_%s" % (i, title.lower().replace(" ", "_").replace("&", "n"))))
    return blocks


CHILDREN = [
    dict(
        name="FPS Sales", title="FPS Sales", sequence_id=1, icon="sell",
        roles=SALES_ROLES, links=SALES_LINKS,
        blurb="Enquiries, quotations and the customer book.",
        cards=["Sales", "CRM"],
    ),
    dict(
        name="FPS Operations", title="FPS Operations", sequence_id=2, icon="organization",
        roles=OPS_ROLES, links=OPERATIONS_LINKS,
        blurb="Jobs from booking to delivery — job orders, customs and proof of delivery.",
        shortcuts=OPERATIONS_SHORTCUTS,
        number_cards=OPERATIONS_NUMBER_CARDS,
        cards=["Jobs", "Customs", "Trucking & delivery"],
    ),
    dict(
        name="FPS Accounts", title="FPS Accounts", sequence_id=3, icon="accounting",
        roles=ACCOUNTS_ROLES, links=ACCOUNTS_LINKS,
        blurb="Invoicing, payments, bank reconciliation and VAT.",
        extra=[paragraph(
            '<a href="/desk/payment-receipts"><b>Payment Receipts</b> &rarr; '
            'receipts dashboard, customer receipts, unpaid invoices</a>',
            "acc_payrcpt")],
        cards=["Billing", "Buying", "Bank & reconciliation", "Receivables & payables", "Tax"],
    ),
    dict(
        name="FPS HR", title="FPS HR", sequence_id=4, icon="hr",
        roles=HR_ROLES, links=HR_LINKS,
        blurb="Stock ERPNext HR doctypes — permissions, workflows and reports are ERPNext's own.",
        cards=["People", "Leave & claims", "Payroll"],
    ),
    dict(
        name="FPS Reports", title="FPS Reports", sequence_id=5, icon="table",
        roles=OPS_ROLES, links=REPORTS_LINKS,
        blurb="Job tracking and profitability reporting.",
        charts=[{"chart_name": "FPS Gross Profit by Month",
                 "label": "FPS Gross Profit by Month"}],
        cards=["FPS reports", "Accounting reports"],
    ),
    dict(
        name="FPS Masters & Setup", title="FPS Masters & Setup", sequence_id=6, icon="setting",
        roles=SETUP_ROLES, links=MASTERS_LINKS,
        blurb="Reference data, users and integrations. Changes here affect every job.",
        cards=["Masters", "Stock", "Users & roles", "Integrations"],
    ),
]


# ==========================================================================
# The v16 sidebar
#
# In Frappe v16 the left sidebar under the FPS tile is a Workspace Sidebar
# doc, NOT the parent_page tree the README assumes (that is v15 behaviour).
# The doc must stay named "FPS" to match Module Def "FPS", otherwise Frappe
# auto-generates one over the top of it.
# ==========================================================================

def s_link(label, link_type, link_to, icon=None, url=None, child=1,
           route_options=None):
    """A sidebar row. child=1 nests it under the Section Break above it.

    route_options carries list-view filters. Its values must be JSON *strings* --
    the list view JSON.parses any value that starts with "[" -- which is how a
    non-equality filter is expressed without falling back to link_type URL.
    """
    return {
        "child": child, "collapsible": 1, "icon": icon, "indent": 0,
        "keep_closed": 0, "label": label, "link_to": link_to,
        "link_type": link_type,
        # MUST be serialised. route_options is a Code/JSON field, i.e. a longtext
        # column: handing Frappe a dict makes the child-row INSERT fail because
        # MySQLdb cannot bind one, which aborts sync_fixtures and rolls the whole
        # migrate back. That is what turned three deploys into "Recovered".
        "route_options": (json.dumps(route_options, separators=(",", ":"))
                          if isinstance(route_options, dict) else route_options),
        "show_arrow": 0, "type": "Link", "url": url,
    }


def s_group(label, icon, keep_closed=0):
    """A collapsible category header.

    Copied field-for-field from ERPNext's own shipped "Stock" sidebar, which is
    the only reliable source for this: a group is type "Section Break" with
    child=0 and **indent=1**, and its members are type "Link" with **child=1**.

    Two earlier attempts got this wrong. Section Break with indent=0 and child=0
    members renders as one flat list -- the section is just a divider and nothing
    nests under it. Type "Sidebar Item Group" is not used anywhere in ERPNext and
    renders nothing at all, blanking the sidebar. indent + child is the pair that
    actually does the work.
    """
    return {
        "child": 0, "collapsible": 1, "icon": icon, "indent": 1,
        "keep_closed": keep_closed, "label": label, "link_to": None,
        "link_type": "DocType", "show_arrow": 0, "type": "Section Break",
        "url": None,
    }


# Six categories, every item nested under one of them. Only FPS Home sits loose.
#
# NOTHING here uses link_type "URL". In v16 a URL item always renders
# target="_blank", so it opens a new tab, does a full page reload, and lands the
# user under whichever sidebar that doctype belongs to -- which is exactly the
# "the left panel disappears" behaviour. DocType items navigate in place and keep
# this sidebar, and route_options carries any filtering the old URL encoded.
#
# The per-category "overview" rows are gone too. Each opened a child workspace
# that duplicated what the category already lists, so they were a row of pure
# indirection. The child workspaces still exist and open from the workspace
# switcher.
SIDEBAR_ITEMS = [
    s_link("FPS Home", "Workspace", "FPS", icon="home", child=0),

    s_group("Sales", "sell"),
    s_link("Enquiry", "DocType", "FPS Enquiry"),
    s_link("Quotation", "DocType", "Quotation"),
    s_link("Customer", "DocType", "Customer"),

    s_group("Operations", "organization"),
    s_link("Job Order", "DocType", "Job Order"),
    # Was the Kanban board behind a URL item. Now a plain Job Order list filtered
    # to the open stages, so it stays inside this sidebar. Distinct from the row
    # above, which is every job order regardless of stage.
    s_link("Job Tracker", "DocType", "Job Order",
           route_options={"fps_stage": '[\"not in\",[\"Closed\",\"Invoiced\"]]'}),
    s_link("Customs Tracker", "DocType", "Customs Tracker"),
    s_link("Proof of Delivery", "DocType", "Proof of Delivery"),

    s_group("Accounts", "accounting"),
    s_link("Sales Invoice", "DocType", "Sales Invoice"),
    s_link("Purchase Invoice", "DocType", "Purchase Invoice"),
    # The receipts themselves, not the dashboard workspace of the same name.
    s_link("Payment Receipts", "DocType", "Payment Entry",
           route_options={"payment_type": "Receive"}),
    s_link("Bank Reconciliation", "DocType", "FPS Bank Statement"),

    s_group("HR", "hr", keep_closed=1),
    s_link("Employee", "DocType", "Employee"),
    s_link("Attendance", "DocType", "Attendance"),
    s_link("Leave Application", "DocType", "Leave Application"),
    s_link("Expense Claim", "DocType", "Expense Claim"),

    s_group("Reports", "table", keep_closed=1),
    s_link("Profitability per Job Order", "Report", "FPS Profitability per Job Order"),
    s_link("Monthly GP trend", "Report", "FPS Monthly GP Trend"),
    s_link("Accounts Receivable", "Report", "Accounts Receivable"),
    s_link("Accounts Receivable Summary", "Report", "Accounts Receivable Summary"),
    # ERPNext's own SOA generator, not a report: pick customers (or a customer
    # group), set the period and ageing buckets, and it renders a statement PDF
    # per customer and can email them straight out. That is what credit-terms
    # customers need, and no report produces a sendable document.
    s_link("Statement of Accounts", "DocType", "Process Statement Of Accounts"),

    s_group("Masters", "setting", keep_closed=1),
    s_link("Supplier", "DocType", "Supplier"),
    s_link("Charge items", "DocType", "Item"),
    s_link("Item Group", "DocType", "Item Group"),
    s_link("Cost Center", "DocType", "Cost Center"),
]


SIDEBAR = {
    "app": APP,
    "creation": CREATED,
    "docstatus": 0,
    "doctype": "Workspace Sidebar",
    "for_user": None,
    "header_icon": "grid",
    "idx": 0,
    "items": [dict({"filters": None, "route_options": None,
                    "navigate_to_tab": None}, **it) for it in SIDEBAR_ITEMS],
    "modified": STAMP,
    "modified_by": OWNER,
    "module": MODULE,
    "module_onboarding": None,
    "name": "FPS",
    "owner": OWNER,
    "standard": 0,
    "title": "FPS",
}


# --------------------------------------------------------------------------

# ==========================================================================
# Payment Receipts -- adopted, not authored
#
# This workspace was built in the site DB on 2026-09-05 and existed only there,
# so a fresh install would not have had it at all. It is pulled into the app
# verbatim from `adopted/payment_receipts.source.json` (a cleaned copy of the
# live record) and re-parented from FPS to FPS Accounts, which is where it
# belongs: it is the receipts sub-tab of Accounts, not a seventh category.
#
# To refresh the source after editing the page in the desk UI, re-fetch
# /api/resource/Workspace/Payment%20Receipts and strip the volatile fields
# (name, owner, creation, modified, modified_by, docstatus, idx, parent,
# parentfield, parenttype, doctype) from the doc and every child row.
# ==========================================================================

ADOPTED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adopted")


def payment_receipts():
    with open(os.path.join(ADOPTED_DIR, "payment_receipts.source.json"),
              encoding="utf-8") as fh:
        src = json.load(fh)

    return workspace(
        name="Payment Receipts",
        title=src.get("title", "Payment Receipts"),
        sequence_id=1,
        icon=src.get("icon") or "receipt-text",
        indicator_color=src.get("indicator_color") or "",
        content=json.loads(src["content"]),
        links=src.get("links") or [],
        shortcuts=src.get("shortcuts") or [],
        number_cards=src.get("number_cards") or [],
        charts=src.get("charts") or [],
        quick_lists=src.get("quick_lists") or [],
        custom_blocks=src.get("custom_blocks") or [],
        # Re-parented: a sub-tab of Accounts rather than a sibling of it.
        parent_page="FPS Accounts",
        # Deliberately NOT its parent's roles: Accounts is open to ops so they
        # can invoice, but receipts are not.
        roles=RECEIPTS_ROLES,
    )


# ==========================================================================
# Client Scripts
#
# `client_script` is also in IMPORTABLE_DOCTYPES, so these ship with the app
# rather than living only in the site DB (where all 13 existing FPS client
# scripts currently sit, with module = null -- a fresh install would have none
# of them). The JS lives beside this file as real .js so it stays reviewable
# and syntax-highlighted; only the generated fixture carries it as a string.
# ==========================================================================

CLIENT_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "client_scripts")

CLIENT_SCRIPTS = [
    {
        "name": "FPS Customer Billing Indicators",
        "source": "fps_customer_billing_indicators.js",
        "dt": "Customer",
        "view": "Form",
    },
]


def client_script(spec):
    with open(os.path.join(CLIENT_SCRIPTS_DIR, spec["source"]), encoding="utf-8") as fh:
        source = fh.read()

    return {
        "creation": CREATED,
        "docstatus": 0,
        "doctype": "Client Script",
        "dt": spec["dt"],
        "enabled": 1,
        "idx": 0,
        "modified": STAMP,
        "modified_by": OWNER,
        "module": MODULE,
        "name": spec["name"],
        "owner": OWNER,
        "script": source,
        "view": spec["view"],
    }


# ==========================================================================
# Fixtures
#
# Number Card, Dashboard Chart and Custom HTML Block are NOT in v16's
# IMPORTABLE_DOCTYPES, so unlike the workspaces they cannot ship as module JSON.
# They go through the `fixtures` hook instead, which imports <app>/fixtures/*.json
# on migrate. Hand-authored here rather than produced by `bench export-fixtures`,
# which needs bench access this project does not have.
#
# Every filter row is 4 elements. Every count below was probed against live data
# and then adversarially re-verified on 2026-09-09.
# ==========================================================================

BLOCKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_blocks")

# Site convention, taken from the cards already present.
RED, ORANGE, PURPLE, GREEN = "#C93A3A", "#B86E00", "#8F4CFF", "#10B981"


def number_card(name, label, doctype, filters, color, function="Count",
                based_on=None, dynamic_filters=None):
    return {
        "aggregate_function_based_on": based_on,
        "color": color,
        "creation": CREATED,
        "docstatus": 0,
        "doctype": "Number Card",
        "document_type": doctype,
        "dynamic_filters_json": (json.dumps(dynamic_filters, separators=(",", ":"))
                                 if dynamic_filters else None),
        "filters_json": json.dumps(filters, separators=(",", ":")),
        "function": function,
        "idx": 0,
        "is_public": 1,
        "is_standard": 0,
        "label": label,
        "modified": STAMP,
        "modified_by": OWNER,
        "module": MODULE,
        "name": name,
        "owner": OWNER,
        "show_percentage_stats": 0,
        "stats_time_interval": "Daily",
        "type": "Document Type",
    }


NUMBER_CARDS = [
    # 2 live. The ["eta","is","set"] guard is load-bearing: without it Frappe's
    # ifnull() coercion matches all 36 open jobs that have no ETA and this reads
    # 38. The date itself goes in dynamic_filters_json, the framework-canonical
    # form (the shipped "Employees on Leave (Today)" card uses exactly this).
    number_card("FPS Jobs past ETA", "Jobs past ETA", "Job Order",
                [["Job Order", "fps_stage", "not in", ["Closed", "Invoiced"]],
                 ["Job Order", "docstatus", "<", 2],
                 ["Job Order", "eta", "is", "set"]],
                RED,
                dynamic_filters=[["Job Order", "eta", "<",
                                  "frappe.datetime.get_today()"]]),

    # 21 live. Named for what it measures. The design asked for Customs Tracker
    # status "Submitted", which is not one of its statuses, and that doctype is
    # per-LEG not per-job so its count could never be a job count.
    number_card("FPS Clearance in progress", "Clearance in progress", "Job Order",
                [["Job Order", "fps_svc_clearance", "=", 1],
                 ["Job Order", "fps_stage", "in", ["New", "Docs", "In Progress"]],
                 ["Job Order", "docstatus", "<", 2]],
                ORANGE),

    # 2 live. Job Order expresses this directly -- fps_stage plus the
    # sales_invoice Link -- without needing to join through POD.
    number_card("FPS Delivered not invoiced", "Delivered, not invoiced", "Job Order",
                [["Job Order", "fps_stage", "=", "Delivered"],
                 ["Job Order", "sales_invoice", "is", "not set"],
                 ["Job Order", "docstatus", "<", 2]],
                PURPLE),

    # 9 live. Replaces the design's "GP this month", which would read AED 0.00:
    # gross_profit is populated on only 6 of 84 job orders, all in June, netting
    # -112,888.90. A Number Card also cannot be role-gated (no roles table), so a
    # money card cannot live on a page ops can see. This is real and operational.
    number_card("FPS Cleared ready to deliver", "Cleared, ready to deliver", "Job Order",
                [["Job Order", "fps_stage", "=", "Cleared - Ready"],
                 ["Job Order", "docstatus", "<", 2]],
                GREEN),
]

# Dashboard Chart DOES have a roles table (Number Card does not), so the money
# chart is gated here AND kept off the home page.
DASHBOARD_CHARTS = [{
    "based_on": "jo_date",
    "chart_name": "FPS Gross Profit by Month",
    "chart_type": "Sum",
    "creation": CREATED,
    "docstatus": 0,
    "doctype": "Dashboard Chart",
    "document_type": "Job Order",
    "dynamic_filters_json": None,
    "filters_json": json.dumps([["Job Order", "docstatus", "<", 2]],
                               separators=(",", ":")),
    "idx": 0,
    "is_public": 1,
    "is_standard": 0,
    "modified": STAMP,
    "modified_by": OWNER,
    "module": MODULE,
    "name": "FPS Gross Profit by Month",
    "owner": OWNER,
    "roles": [{"role": r} for r in
              ("Accounts User", "Accounts Manager", "System Manager")],
    "time_interval": "Monthly",
    # Frappe has no "Last 6 Months"; the options are Last Year / Last Quarter /
    # Last Month / Last Week / Select Date Range. Last Year rolls forward on its
    # own, where a Select Date Range would freeze and need hand-editing.
    "timespan": "Last Year",
    "type": "Bar",
    "value_based_on": "gross_profit",
}]


def custom_html_blocks():
    def read(stem, ext):
        with open(os.path.join(BLOCKS_DIR, stem + "." + ext), encoding="utf-8") as fh:
            return fh.read()

    def block(name, stem):
        return {
            "creation": CREATED,
            "docstatus": 0,
            "doctype": "Custom HTML Block",
            "html": read(stem, "html"),
            "idx": 0,
            "modified": STAMP,
            "modified_by": OWNER,
            "name": name,
            "owner": OWNER,
            # Left ungated on purpose: the gate is inside the API methods, which
            # omit any tile or row whose doctype the caller cannot read. That
            # degrades per viewer instead of hiding the whole block.
            "private": 0,
            "roles": [],
            "script": read(stem, "js"),
            "style": read(stem, "css"),
        }

    return [
        block("FPS Overview", "fps_overview"),
        block("FPS Job Tracker", "fps_job_tracker"),
    ]


def write_fixtures():
    out = os.path.join(APP_ROOT, "fps_erpnext", "fixtures")
    os.makedirs(out, exist_ok=True)
    written = []
    for fname, payload in (
        ("number_card.json", NUMBER_CARDS),
        ("dashboard_chart.json", DASHBOARD_CHARTS),
        ("custom_html_block.json", custom_html_blocks()),
    ):
        target = os.path.join(out, fname)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        written.append(os.path.relpath(target, APP_ROOT))
    return written


def write(rel_dir, slug, payload):
    path = os.path.join(MODULE_PATH, rel_dir, slug)
    os.makedirs(path, exist_ok=True)
    target = os.path.join(path, slug + ".json")
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    return os.path.relpath(target, APP_ROOT)


def main():
    written = []

    written.append(write("workspace", "fps", workspace(
        name="FPS", title="FPS", sequence_id=0, icon="grid",
        indicator_color="cyan",
        content=FPS_HOME_CONTENT, links=FPS_HOME_LINKS,
        shortcuts=FPS_HOME_SHORTCUTS, number_cards=FPS_HOME_NUMBER_CARDS,
        quick_lists=[quick_list(
            "Jobs needing action", "Job Order",
            [["Job Order", "fps_stage", "not in", ["Closed", "Invoiced"]],
             ["Job Order", "docstatus", "<", 2]])],
        custom_blocks=[
            {"custom_block_name": "FPS Overview", "label": "FPS Overview"},
            {"custom_block_name": "FPS Job Tracker", "label": "FPS Job Tracker"},
        ],
    )))

    for spec in CHILDREN:
        slug = (spec["name"].lower()
                .replace(" & ", " and ")
                .replace(" ", "_"))
        written.append(write("workspace", slug, workspace(
            name=spec["name"], title=spec["title"],
            sequence_id=spec["sequence_id"], icon=spec["icon"],
            parent_page="FPS", roles=spec["roles"], links=spec["links"],
            content=child_content(spec["title"], spec["blurb"], spec["cards"],
                                  spec.get("extra"), spec.get("shortcuts") or (),
                                  spec.get("number_cards") or (),
                                  spec.get("charts") or ()),
            shortcuts=spec.get("shortcuts") or [],
            number_cards=spec.get("number_cards") or [],
            charts=spec.get("charts") or [],
        )))

    written.append(write("workspace", "payment_receipts", payment_receipts()))

    written.append(write("workspace_sidebar", "fps", SIDEBAR))

    written.extend(write_fixtures())

    for spec in CLIENT_SCRIPTS:
        slug = spec["name"].lower().replace(" ", "_")
        written.append(write("client_script", slug, client_script(spec)))

    for p in written:
        print(p.replace(os.sep, "/"))


if __name__ == "__main__":
    main()
