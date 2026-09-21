"""Restore the standard permission table of Sales Invoice (21 Sep 2026).

An earlier REST edit rewrote the DocType's own permission rows (four rows, one
"All @ level 1" with nothing set). Frappe validates that standard table on every
permission change, so the Role Permission Manager failed for Sales Invoice - in
the UI and through the API - until the definition is reloaded from ERPNext's
JSON. Custom DocPerm rows (the permissions actually in force), Custom Fields and
Property Setters are not touched by a reload.
"""

import frappe


def execute():
    frappe.reload_doc("accounts", "doctype", "sales_invoice", force=True, reset_permissions=True)
    frappe.clear_cache(doctype="Sales Invoice")
