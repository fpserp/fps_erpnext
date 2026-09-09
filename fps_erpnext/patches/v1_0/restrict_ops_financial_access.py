"""Withhold receipts, bank reconciliation and outstanding totals from FPS Operations.

Owner's requirement (2026-09-09): ops@fastplanet.ae must not see bank
reconciliation, how much has been received from clients, or how much is
outstanding in total. Ops KEEPS everything else -- raising sales invoices,
booking supplier costs, job orders including their cost and margin fields, and
the Paid / Unpaid / Overdue status of an individual invoice.

Per-user effect. All five enabled System Users, verified 2026-09-09:

    agam@fastplanet.ae      unaffected -- System Manager + Accounts Manager +
                            Accounts User keep every grant zeroed here
    abhishek@fastplanet.ae  unaffected -- same roles
    ops@fastplanet.ae       the target. Employee + Desk User + FPS Operations
                            only, so loses receipts, bank and AR aggregation
    hello@fastplanet.ae     (FPS_AZEEM) Desk User + FPS Customs Access +
                            FPS Viewer + Employee. Holds no Accounts role and no
                            FPS Operations, so his ONLY route to Payment Entry is
                            the role "All" row -- which this zeroes. He loses
                            receipt visibility too. Intended for a customs/viewer
                            account, but it is a real change and is called out
                            here because the FPS Operations roster does not
                            mention him.
    Administrator           unaffected

WHY THIS ZEROES ROWS INSTEAD OF DELETING THEM
Custom DocPerm rows mask the standard DocPerm set only while at least one Custom
DocPerm row exists for that doctype. Deleting the last one makes Frappe fall back
to the standard rows, which can grant MORE than the custom set did -- on Bank
Account exactly that would happen, handing Accounts User and Accounts Manager full
CRUD including delete and export on IBANs, where today they hold nothing at all.
Zeroing every bit grants the same nothing, keeps the custom set non-empty so the
standard set stays masked, avoids the question of whether a standard DocPerm child
row survives the next migrate, shows up honestly in the Role Permissions Manager,
and is trivially reversible.

Rows are matched on (parent, role, permlevel) rather than by their hashed names,
so this is portable across sites and safe to re-run.
"""

import frappe

ALL_BITS = (
    "select", "read", "write", "create", "delete", "submit", "cancel", "amend",
    "report", "export", "import", "print", "email", "share",
)

# (doctype, role) whose permission row is stripped of every right.
ZERO_OUT = [
    # -- how much has been received ------------------------------------------
    # Payment Entry is granted TWICE; zeroing one alone would leave receipts
    # readable. The "All" row let every logged-in user read every receipt, and
    # the FPS Operations row also carried submit and amend.
    ("Payment Entry", "FPS Operations"),
    ("Payment Entry", "All"),

    # -- bank reconciliation --------------------------------------------------
    # The FPS Bank Statement row also carried write, create and delete, so ops
    # could ALTER or remove reconciliation data -- a control weakness beyond
    # disclosure. System Manager keeps its own row.
    ("FPS Bank Statement", "FPS Operations"),

    # Bank Account carries iban / account number / branch code. Zeroing this also
    # closes the "Account Balance" report, whose Has Role table is EMPTY so its
    # only gate is report permission on this ref_doctype.
    ("Bank Account", "FPS Operations"),
]

# (doctype, role, permlevel, bits) -> only these bits are cleared, row kept.
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
    # ref_doctype Bank Account -- which ZERO_OUT above removes. Belt and braces:
    # gate the report itself so it stays closed if Bank Account is ever regranted.
    ("Report", "Account Balance", ["Accounts User", "Accounts Manager", "System Manager"]),

    # is_public=1 with an empty roles table. It renders bank/cash balances over
    # time from GL Entry through the "Account Balance Timeline" chart source --
    # a path that never consults GL Entry permissions, which ops do not hold.
    ("Dashboard Chart", "Bank Balance", ["Accounts User", "Accounts Manager", "System Manager"]),
]


def _zero(table, name):
    frappe.db.set_value(table, name, {bit: 0 for bit in ALL_BITS}, update_modified=False)


def _gate(doctype, name, roles):
    """Insert Has Role child rows WITHOUT saving the parent.

    Both targets are standard records. Dashboard Chart.validate() throws
    "Cannot edit Standard charts" whenever developer_mode is off, and
    ignore_permissions does not suppress validate() -- so a doc.save() here
    raises, patch_handler rolls back and re-raises, and bench migrate aborts
    mid-deploy. Writing the child rows directly bypasses the parent's validate
    entirely, which is the whole point.
    """
    if not frappe.db.exists(doctype, name):
        return
    if frappe.get_all("Has Role", filters={"parent": name, "parenttype": doctype}, limit=1):
        # Already gated by someone; do not narrow or widen their choice.
        return

    for idx, role in enumerate(roles, start=1):
        if not frappe.db.exists("Role", role):
            continue
        frappe.get_doc({
            "doctype": "Has Role",
            "parent": name,
            "parenttype": doctype,
            "parentfield": "roles",
            "role": role,
            "idx": idx,
        }).db_insert()


def execute():
    for doctype, role in ZERO_OUT:
        for table in ("Custom DocPerm", "DocPerm"):
            for name in frappe.get_all(
                table, filters={"parent": doctype, "role": role}, pluck="name"
            ):
                _zero(table, name)

    for doctype, role, permlevel, bits in CLEAR_BITS:
        for table in ("Custom DocPerm", "DocPerm"):
            for name in frappe.get_all(
                table,
                filters={"parent": doctype, "role": role, "permlevel": permlevel},
                pluck="name",
            ):
                for bit in bits:
                    frappe.db.set_value(table, name, bit, 0, update_modified=False)

    # A cosmetic gate must never be able to abort a migrate. The permission work
    # above is the part that matters; if these two fail, log and carry on.
    for doctype, name, roles in GATE_BY_ROLE:
        try:
            _gate(doctype, name, roles)
        except Exception:
            frappe.log_error(
                title="restrict_ops_financial_access: could not gate %s %s" % (doctype, name),
                message=frappe.get_traceback(),
            )

    frappe.clear_cache()
