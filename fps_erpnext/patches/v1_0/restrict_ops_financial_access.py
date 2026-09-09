"""Withhold receipts, bank reconciliation and outstanding totals from FPS Operations.

Owner's requirement (2026-09-09): ops@fastplanet.ae must not see bank
reconciliation, how much has been received from clients, or how much is
outstanding in total. Ops KEEPS everything else -- raising sales invoices,
booking supplier costs, job orders including their cost and margin fields, and
the Paid / Unpaid / Overdue status of an individual invoice.

Blast radius, verified 2026-09-09: FPS Operations is held by agam@, abhishek@
and ops@. agam@ and abhishek@ also hold Accounts User, Accounts Manager and
System Manager, so every grant removed here they keep by another route. ops@
holds only Employee, Desk User and FPS Operations.

Rows are matched on (parent, role, permlevel) rather than by their hashed names,
so this is portable across sites and safe to re-run.
"""

import frappe

# (doctype, role) whose permission row is removed outright.
REVOKE = [
    # -- how much has been received ------------------------------------------
    # Payment Entry is granted TWICE; removing one alone would leave receipts
    # readable. The "All" row let every logged-in user read every receipt.
    ("Payment Entry", "FPS Operations"),
    ("Payment Entry", "All"),

    # -- bank reconciliation --------------------------------------------------
    # Also removes write/create: ops could previously ALTER reconciliation data,
    # which is a control weakness beyond confidentiality. System Manager keeps a
    # row, so agam@ and abhishek@ are unaffected.
    ("FPS Bank Statement", "FPS Operations"),

    # Bank Account carries iban / account number / branch code. Removing this
    # also closes the "Account Balance" report, whose Has Role table is EMPTY --
    # its only gate is report permission on its ref_doctype, which is this row.
    ("Bank Account", "FPS Operations"),
]

# (doctype, role, permlevel) -> permission bits forced to 0, the row itself kept.
CLEAR_BITS = [
    # Ops keep read/write/create/submit on Sales Invoice -- they raise invoices.
    # `report` is what powers the Report Builder view, where outstanding_amount
    # can be added as a column, grouped by customer and totalled. That total is
    # exactly "how much is pending", so the aggregation goes while the ability to
    # open, create and edit an invoice stays.
    ("Sales Invoice", "FPS Operations", 0, ["report"]),

    # Sales Invoice carries a deliberate permlevel-1 block of eleven Custom
    # Fields -- "AP Costs & Profitability (Admin Only)", including
    # fps_gross_profit and fps_total_cost. Custom DocPerm row `csm72v3srk`
    # (role All, permlevel 1, read=1) silently defeats it: every logged-in user
    # can read the whole panel today. Clearing read restores the protection that
    # was already intended. The permlevel-1 grant that should remain is
    # `csm1k27e0t` (Accounts Manager), which this does not touch.
    ("Sales Invoice", "All", 1, ["read"]),
]

# (doctype, name, roles) -> add a roles gate when the record has none at all.
# An empty roles table means "everyone", which is how these two slipped through.
GATE_BY_ROLE = [
    # Zero Has Role rows, so its only gate was report permission on its
    # ref_doctype Bank Account -- which REVOKE above removes. Belt and braces:
    # gate the report itself so it stays closed if Bank Account is ever regranted.
    ("Report", "Account Balance", ["Accounts User", "Accounts Manager", "System Manager"]),

    # is_public=1 with an empty roles table. It renders bank/cash balances over
    # time from GL Entry through the "Account Balance Timeline" chart source --
    # a path that never consults GL Entry permissions, which ops do not hold.
    # Unlike Number Card, Dashboard Chart HAS a roles child table, so this is a
    # clean per-role fix rather than the blunt is_public=0.
    ("Dashboard Chart", "Bank Balance", ["Accounts User", "Accounts Manager", "System Manager"]),
]


def execute():
    for doctype, role in REVOKE:
        for table in ("Custom DocPerm", "DocPerm"):
            for name in frappe.get_all(
                table,
                filters={"parent": doctype, "role": role},
                pluck="name",
            ):
                frappe.delete_doc(table, name, ignore_permissions=True, force=True)

    for doctype, role, permlevel, bits in CLEAR_BITS:
        for table in ("Custom DocPerm", "DocPerm"):
            for name in frappe.get_all(
                table,
                filters={"parent": doctype, "role": role, "permlevel": permlevel},
                pluck="name",
            ):
                for bit in bits:
                    frappe.db.set_value(table, name, bit, 0)

    for doctype, name, roles in GATE_BY_ROLE:
        if not frappe.db.exists(doctype, name):
            continue
        if not frappe.get_meta(doctype).has_field("roles"):
            continue

        doc = frappe.get_doc(doctype, name)
        if doc.get("roles"):
            # Already gated by someone; do not narrow or widen their choice.
            continue

        for role in roles:
            if frappe.db.exists("Role", role):
                doc.append("roles", {"role": role})

        if doc.get("roles"):
            doc.save(ignore_permissions=True)

    frappe.clear_cache()
