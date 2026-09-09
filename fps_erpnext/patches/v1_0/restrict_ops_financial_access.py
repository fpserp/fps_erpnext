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

    # Sales Invoice has a permlevel-1 read row granted to "All", which defeats
    # any future attempt to protect a field by raising its permlevel.
    ("Sales Invoice", "All", 1, ["read"]),
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

    frappe.clear_cache()
