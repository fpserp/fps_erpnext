"""Let the finance roles read the Sales Invoice totals that just moved to permlevel 1.

THE FIELD SIDE of this change ships as Property Setters: fifteen server-computed
money fields on Sales Invoice -- total, net_total, the tax totals, grand_total,
rounded_total, in_words, outstanding_amount, total_advance, paid_amount and
their base_* twins -- move from permlevel 0 to permlevel 1. THIS patch is the
permission side.

WHY PERMLEVEL AT ALL. Ops was given report=0 on Sales Invoice on the assumption
that it stopped them totalling invoices up. It does not. In the code this site
actually serves, `report` gates saved Query Reports and export only; the Report
VIEW, Group By -> SUM and Show Totals all run on plain `read`, and
can_get_report appears zero times in the deployed list bundle. Permlevel is the
mechanism that works: reportview.validate_fields() strips fields the caller
cannot read at their permlevel, so they cannot be picked as a column, grouped
by, or summed.

WHAT EXISTS ALREADY on Sales Invoice at permlevel 1: Accounts Manager (read,
write) and All (nothing). Until now that gated nothing at all, because no Sales
Invoice field was above permlevel 0 -- which is also why the earlier attempt to
close this off by clearing "read on Sales Invoice / All / permlevel 1" changed
nothing.

WHAT THIS ADDS: read at permlevel 1 for Accounts User and System Manager, so
the people who run the books keep seeing every figure.

WHO ENDS UP BLOCKED, checked against live roles on 2026-09-10:
  agam@      Accounts Manager + Accounts User + System Manager  -> sees totals
  abhishek@  Accounts Manager + Accounts User + System Manager  -> sees totals
  ops@       Employee + Desk User + FPS Operations              -> BLOCKED
  hello@     Desk User + FPS Viewer + Employee + Customs Access -> blocked
Adding System Manager is safe precisely because ops does not hold it.

WHAT THIS DOES NOT HIDE, and nobody should think it does:
  * The line items. Ops types the rates, so they can always add up one invoice.
  * The printed invoice. Print rendering is not permlevel-filtered, so a PDF
    ops generates still shows its own total. It has to -- that is the document
    they send the customer.
The point is CROSS-INVOICE totals: "how much have we invoiced", "how much is
outstanding". Those are now unreachable in the list, the report view and the
group-by sidebar.

Safe to re-run: a row that already exists is left alone.
"""

import frappe

DOCTYPE = "Sales Invoice"
PERMLEVEL = 1

# Roles that keep full sight of the money. Deliberately NOT FPS Operations.
FINANCE_ROLES = ("Accounts User", "System Manager")


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    added = 0
    for role in FINANCE_ROLES:
        if not frappe.db.exists("Role", role):
            frappe.log_error(title="FPS: role %s missing, permlevel not granted" % role)
            continue

        existing = frappe.db.get_value(
            "Custom DocPerm",
            {"parent": DOCTYPE, "role": role, "permlevel": PERMLEVEL},
            "name",
        )
        if existing:
            # Make sure it actually grants read -- a row that exists with read 0
            # would silently keep finance locked out of their own figures.
            if not frappe.db.get_value("Custom DocPerm", existing, "read"):
                frappe.db.set_value("Custom DocPerm", existing, "read", 1)
            continue

        try:
            frappe.get_doc({
                "doctype": "Custom DocPerm",
                "parent": DOCTYPE,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": role,
                "permlevel": PERMLEVEL,
                "read": 1,
                "write": 0,
            }).insert(ignore_permissions=True)
            added += 1
        except Exception:
            frappe.log_error(title="FPS: could not grant %s permlevel 1 on %s" % (role, DOCTYPE))

    if added:
        frappe.db.commit()

    frappe.clear_cache(doctype=DOCTYPE)
