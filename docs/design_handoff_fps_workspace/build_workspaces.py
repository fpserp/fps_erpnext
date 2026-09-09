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
# Must be newer than the row already in the site DB or the importer skips the file.
STAMP = "2026-09-09 14:20:00.000000"
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
ACCOUNTS_ROLES = ["Accounts User", "Accounts Manager", "System Manager"]
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
    card("Sales", [
        doc("FPS Enquiry"),
        doc("Quotation"),
        doc("Customer"),
    ])
    + card("Operations", [
        doc("Job Order"),
        doc("Customs Tracker", label="Customs Tracker · Mirsal"),
        doc("Proof of Delivery"),
        doc("Job Update Log", label="Job update log"),
    ])
    + card("Accounts & reports", [
        doc("Payment Entry"),
        doc("UAE VAT 201", "Report", "VAT 5% return"),
        doc("FPS Profitability per Job Order", "Report", "Profitability per Job Order"),
        doc("FPS Open Jobs by SOW", "Report", "Open jobs by SOW"),
    ])
)

FPS_HOME_CONTENT = [
    header("Fast Planet Shipping", "fpshdr"),
    # Step 6 inserts the Custom HTML Block pipeline strip here.
    number_card_block("Open - Customs clearance", "fpstrkc4"),
    number_card_block("Open - Freight forwarding", "fpstrkc5"),
    number_card_block("Open - Land transport", "fpstrkc6"),
    number_card_block("Open - General jobs", "fpstrkc7"),
    number_card_block("On hold", "fpstrkc8"),
    number_card_block("Next action overdue", "fpstrkc9"),
    number_card_block("Cleared - delivery pending", "fpstrkc10"),
    number_card_block("Delivered - not invoiced", "fpstrkc11"),
    # The design's six shortcuts, one row: 6 x col 2 == 12.
    shortcut_block("New Enquiry", "fpssc1", col=2),
    shortcut_block("New Job Order", "fpssc2", col=2),
    shortcut_block("Customs Tracker", "fpssc3", col=2),
    shortcut_block("Proof of Delivery", "fpssc4", col=2),
    shortcut_block("Sales Invoice", "fpssc5", col=2),
    shortcut_block("Purchase Invoice", "fpssc6", col=2),
    # Step 4 inserts the Quick List + Dashboard Chart pair here.
    card_block("Sales", "fpscard1"),
    card_block("Operations", "fpscard2"),
    card_block("Accounts & reports", "fpscard3"),
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
    # 34 of 39. Terminal statuses (Converted/Lost/Cancelled) have zero records on
    # this site, so this only ever grows until enquiries start being closed out.
    shortcut("New Enquiry", "FPS Enquiry", "Cyan", doc_view="New",
             stats_filter=[["FPS Enquiry", "status", "=", "Open"]],
             fmt="{} open"),

    # 40 of 84. Drafts MUST count: 54 of 84 job orders are docstatus 0, and
    # restricting to submitted collapses the badge to 5 while hiding 35 live jobs.
    shortcut("New Job Order", "Job Order", "Blue", doc_view="New",
             stats_filter=[["Job Order", "fps_stage", "not in", ["Closed", "Invoiced"]],
                           ["Job Order", "docstatus", "!=", 2]],
             fmt="{} open"),

    # 1 of 46. The tracker is almost entirely historical -- 45 are already
    # Cleared. The literal status "Pending" has zero records (ops move straight to
    # In Process), so the naive status = "Pending" filter would read 0 forever.
    shortcut("Customs Tracker", "Customs Tracker", "Orange",
             stats_filter=[["Customs Tracker", "status", "not in", ["Cleared"]]],
             fmt="{} pending"),

    # 35 of 38. Drafts count: the workflow is create-as-draft, capture signature,
    # then submit, and 20 of 38 are still drafts. Only cancelled ones are excluded.
    shortcut("Proof of Delivery", "Proof of Delivery", "Green",
             stats_filter=[["Proof of Delivery", "docstatus", "!=", 2]],
             fmt="{} filed"),

    # 130 of 628. The design's "63 · 210k open" cannot be one shortcut: a badge
    # renders a COUNT only. The AED figure is a Number Card in step 3 (Sum over
    # outstanding_amount with these same filters).
    shortcut("Sales Invoice", "Sales Invoice", "Purple",
             stats_filter=[["Sales Invoice", "status", "in",
                            ["Unpaid", "Overdue", "Partly Paid"]],
                           ["Sales Invoice", "docstatus", "=", 1]],
             fmt="{} open"),

    # Deliberately no badge. "Booked = submitted" is well-formed but returns 0:
    # nobody has ever submitted a Purchase Invoice here, and all 53 drafts are
    # Qashio corporate-card overhead, not freight costs. A "0 booked" or
    # "53 draft" badge would both mislead, so this ships as a plain nav tile.
    shortcut("Purchase Invoice", "Purchase Invoice", "Grey"),
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

FPS_HOME_NUMBER_CARDS = [
    {"label": lbl, "number_card_name": lbl} for lbl in (
        "Open - Customs clearance",
        "Open - Freight forwarding",
        "Open - Land transport",
        "Open - General jobs",
        "On hold",
        "Next action overdue",
        "Cleared - delivery pending",
        "Delivered - not invoiced",
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


def child_content(title, blurb, cards, extra=None, shortcuts=()):
    blocks = [header(title, "hdr_" + title.lower().replace(" ", "_").replace("&", "n"))]
    if blurb:
        blocks.append(paragraph(blurb, "txt_" + title.lower().replace(" ", "_").replace("&", "n")))
    blocks.extend(extra or [])
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

def s_link(label, link_type, link_to, icon=None, url=None):
    return {
        "child": 0, "collapsible": 1, "icon": icon, "indent": 0,
        "keep_closed": 0, "label": label, "link_to": link_to,
        "link_type": link_type, "show_arrow": 0, "type": "Link", "url": url,
    }


def s_section(label, icon, keep_closed=0):
    return {
        "child": 0, "collapsible": 1, "icon": icon, "indent": 0,
        "keep_closed": keep_closed, "label": label, "link_to": None,
        "link_type": "DocType", "show_arrow": 0, "type": "Section Break", "url": None,
    }


SIDEBAR_ITEMS = [
    s_link("FPS Home", "Workspace", "FPS", icon="home"),

    s_section("Sales", "sell"),
    s_link("Sales overview", "Workspace", "FPS Sales"),
    s_link("FPS Enquiry", "DocType", "FPS Enquiry"),
    s_link("Quotation", "DocType", "Quotation"),
    s_link("Customer", "DocType", "Customer"),

    s_section("Operations", "organization"),
    s_link("Operations overview", "Workspace", "FPS Operations"),
    s_link("Job Order", "DocType", "Job Order"),
    # link_type URL always opens a new tab in v16; kept because a Kanban view
    # cannot be addressed by a DocType sidebar item.
    s_link("FPS Job Tracker (board)", "URL", None,
           url="/app/job-order/view/kanban/FPS%20Job%20Tracker"),
    s_link("Customs Tracker · Mirsal", "DocType", "Customs Tracker"),
    s_link("Proof of Delivery", "DocType", "Proof of Delivery"),
    s_link("Job update log", "DocType", "Job Update Log"),

    s_section("Accounts", "accounting"),
    s_link("Accounts overview", "Workspace", "FPS Accounts"),
    s_link("Payment Receipts", "Workspace", "Payment Receipts"),
    s_link("Sales Invoice", "DocType", "Sales Invoice"),
    s_link("Purchase Invoice", "DocType", "Purchase Invoice"),
    s_link("Customer Receipts", "DocType", "Payment Entry"),
    s_link("Payment Reconciliation", "DocType", "Payment Reconciliation"),
    s_link("Bank Reconciliation", "DocType", "FPS Bank Statement"),

    s_section("HR", "hr", keep_closed=1),
    s_link("HR overview", "Workspace", "FPS HR"),
    s_link("Employee", "DocType", "Employee"),
    s_link("Attendance", "DocType", "Attendance"),
    s_link("Leave Application", "DocType", "Leave Application"),

    s_section("Reports", "table", keep_closed=1),
    s_link("Reports overview", "Workspace", "FPS Reports"),
    s_link("Open jobs by SOW", "Report", "FPS Open Jobs by SOW"),
    s_link("Profitability per Job Order", "Report", "FPS Profitability per Job Order"),
    s_link("Monthly GP trend", "Report", "FPS Monthly GP Trend"),
    s_link("Accounts Receivable", "Report", "Accounts Receivable"),
    s_link("Accounts Receivable Summary", "Report", "Accounts Receivable Summary"),
    s_link("Customer Ledger Summary", "Report", "Customer Ledger Summary"),
    s_link("Payment Ledger", "Report", "Payment Ledger"),
    s_link("Payment Period Based On Invoice Date", "Report",
           "Payment Period Based On Invoice Date"),
    s_link("Bank Clearance Summary", "Report", "Bank Clearance Summary"),

    s_section("Masters & Setup", "setting", keep_closed=1),
    s_link("Masters overview", "Workspace", "FPS Masters & Setup"),
    s_link("FPS Outgoing Email", "DocType", "FPS Outgoing Email"),
    s_link("FPS Microsoft Settings", "DocType", "FPS Microsoft Settings"),
    s_link("Qashio Settings", "DocType", "Qashio Settings"),
]


SIDEBAR = {
    "app": APP,
    "creation": CREATED,
    "docstatus": 0,
    "doctype": "Workspace Sidebar",
    "for_user": None,
    "header_icon": "grid",
    "idx": 0,
    "items": [dict(it, filters=None, route_options=None, navigate_to_tab=None)
              for it in SIDEBAR_ITEMS],
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
        # Matches its parent so the nav does not offer a page whose contents
        # the viewer cannot read anyway.
        roles=ACCOUNTS_ROLES,
    )


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
                                  spec.get("extra"), spec.get("shortcuts") or ()),
            shortcuts=spec.get("shortcuts") or [],
        )))

    written.append(write("workspace", "payment_receipts", payment_receipts()))

    written.append(write("workspace_sidebar", "fps", SIDEBAR))

    for p in written:
        print(p.replace(os.sep, "/"))


if __name__ == "__main__":
    main()
