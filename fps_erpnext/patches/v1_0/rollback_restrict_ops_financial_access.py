"""Undo restrict_ops_financial_access. NOT listed in patches.txt -- run by hand.

    bench --site fastplanet.u.frappe.cloud execute \
        fps_erpnext.patches.v1_0.rollback_restrict_ops_financial_access.execute

Frappe records a patch in the Patch Log and never re-runs it, so redeploying does
not undo the forward patch. This restores every permission bit to the value it
held on 2026-09-09 before the change, captured live from the site rather than
reconstructed from memory, and clears the Patch Log entry so the forward patch
can run again after it is corrected.

Restoring is possible at all only because the forward patch ZEROES rows instead
of deleting them -- the rows are still there, just emptied.
"""

import frappe

FORWARD_PATCH = "fps_erpnext.patches.v1_0.restrict_ops_financial_access"

# (table, parent, role, permlevel, bits-that-were-set). Everything not listed was
# 0 before the change and stays 0. Captured live 2026-09-09.
RESTORE = [
    ("Custom DocPerm", "Payment Entry", "All", 0,
     ["read", "report", "print", "email"]),

    ("Custom DocPerm", "Payment Entry", "FPS Operations", 0,
     ["read", "write", "create", "submit", "amend", "report", "export",
      "print", "email", "share"]),

    ("Custom DocPerm", "Bank Account", "FPS Operations", 0,
     ["read", "report", "print"]),

    ("DocPerm", "FPS Bank Statement", "FPS Operations", 0,
     ["read", "write", "create", "delete", "report", "export",
      "print", "email", "share"]),

    # CLEAR_BITS targets -- only the single bit the forward patch cleared.
    ("Custom DocPerm", "Sales Invoice", "FPS Operations", 0, ["report"]),
    ("Custom DocPerm", "Sales Invoice", "All", 1, ["read"]),
]

# Roles the forward patch inserted where the roles table had been empty. Only
# these exact roles are removed, so a gate someone tightened by hand survives.
UNGATE = [
    ("Report", "Account Balance", ["Accounts User", "Accounts Manager", "System Manager"]),
    ("Dashboard Chart", "Bank Balance", ["Accounts User", "Accounts Manager", "System Manager"]),
]


def execute():
    for table, parent, role, permlevel, bits in RESTORE:
        names = frappe.get_all(
            table,
            filters={"parent": parent, "role": role, "permlevel": permlevel},
            pluck="name",
        )
        if not names:
            frappe.log_error(
                title="rollback_restrict_ops_financial_access: row missing",
                message="No %s row for %s / %s / permlevel %s" % (table, parent, role, permlevel),
            )
            continue
        for name in names:
            frappe.db.set_value(table, name, {bit: 1 for bit in bits}, update_modified=False)

    for doctype, name, roles in UNGATE:
        for row in frappe.get_all(
            "Has Role",
            filters={"parent": name, "parenttype": doctype, "role": ["in", roles]},
            pluck="name",
        ):
            frappe.db.delete("Has Role", {"name": row})

    # Let the forward patch run again once it has been corrected.
    frappe.db.delete("Patch Log", {"patch": FORWARD_PATCH})

    frappe.db.commit()
    frappe.clear_cache()
