"""Two permission gaps that would have made "Payment Voucher" (2026-09-12)
unusable for the team that actually needs it, found before shipping the
feature rather than after someone hit a Permission Denied.

PAYMENT ENTRY: FPS Operations had zero access at all (read=0, write=0,
create=0) -- only Accounts User / Accounts Manager could even open one.
Confirmed with the user before changing this: FPS Operations should be able
to draft a Payment Voucher (create + edit), but NOT submit or cancel one --
the actual booking of money leaving the company stays with an accounts
role. This mirrors Purchase Invoice's own FPS Operations row exactly, which
already has this same split (create + write, no submit) -- nothing new was
invented here, just extended to Payment Entry to match its natural pairing.

ACCOUNTS PAYABLE REPORT: its own role list (Accounts User, Purchase User,
Accounts Manager, Auditor) did not include FPS Operations either, so even
with the Payment Entry permission fixed, the report itself would still have
refused to run for them. Same class of gap as the one already found and
fixed in FPS Open Jobs by SOW / FPS Profitability per Job Order
(2026-09-11) -- a report can be perfectly correct and still be invisible to
the people who need it if its own role list was never updated to match.

Read-only: FPS Operations gets to VIEW Accounts Payable, not edit anything
about the report itself.

Safe to re-run: both checks are no-ops once already in place.
"""

import frappe

ROLE = "FPS Operations"


def execute():
	_allow_payment_entry_draft()
	_allow_accounts_payable_report()


def _allow_payment_entry_draft():
	if not frappe.db.exists("DocType", "Payment Entry"):
		return
	name = frappe.db.get_value("Custom DocPerm", {"parent": "Payment Entry", "role": ROLE, "permlevel": 0})
	if not name:
		frappe.log_error(title="FPS: no Payment Entry DocPerm row for %s, not updated" % ROLE)
		return
	frappe.db.set_value("Custom DocPerm", name, {
		"read": 1, "write": 1, "create": 1,
		"report": 1, "export": 1, "share": 1, "print": 1, "email": 1,
	}, update_modified=False)
	frappe.clear_cache(doctype="Payment Entry")


def _allow_accounts_payable_report():
	if not frappe.db.exists("Report", "Accounts Payable"):
		return
	if frappe.db.exists("Has Role", {"parent": "Accounts Payable", "role": ROLE}):
		return
	frappe.get_doc({
		"doctype": "Has Role",
		"parent": "Accounts Payable", "parenttype": "Report", "parentfield": "roles",
		"role": ROLE,
	}).insert(ignore_permissions=True)
