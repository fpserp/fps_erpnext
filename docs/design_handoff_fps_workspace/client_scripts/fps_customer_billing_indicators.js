// Customer form: hide the receivables figures in the form header from anyone
// outside finance.
//
// ERPNext's customer.js refresh() reads frm.doc.__onload.dashboard_info and calls
// frm.dashboard.add_indicator() once per figure. Client Scripts are appended after
// the app's own form script, so removing the payload in onload() means refresh()
// finds nothing left to draw. The sweep in refresh() then covers the reload path,
// where the server re-populates __onload after the form is already open.
//
// SCOPE: this hides the DISPLAY, not the data. dashboard_info is computed
// server-side in Customer.onload and still reaches the browser, so the figures
// remain readable in devtools. Sealing that needs a server-side override of the
// Customer class (override_doctype_class in hooks.py) rather than a client script.

function fps_can_see_receivables() {
	var allowed = [
		"Accounts User",
		"Accounts Manager",
		"System Manager",
		"Administrator",
		"Auditor",
	];
	return (frappe.user_roles || []).some(function (role) {
		return allowed.indexOf(role) !== -1;
	});
}

function fps_strip_billing_indicators(frm) {
	var dashboard = frm.dashboard;
	if (!dashboard || !dashboard.stats_area_row) return;

	// Empty the row wholesale rather than matching rendered label text. ERPNext
	// also renders "Total Advance Paid" and "Total Advance Received", which carry
	// the same balance, and every label is built through __() so a translated UI
	// would defeat a pattern. Nothing else appends to this row on Customer.
	dashboard.stats_area_row.empty();

	// stats_area is a frappe.ui.form.Section, NOT a jQuery object -- it has
	// hide()/show(), and no addClass(). Calling addClass() here throws a
	// TypeError inside refresh() and aborts the rest of the form render.
	if (dashboard.stats_area && typeof dashboard.stats_area.hide === "function") {
		dashboard.stats_area.hide();
	}
}

frappe.ui.form.on("Customer", {
	onload: function (frm) {
		if (fps_can_see_receivables()) return;
		if (frm.doc.__onload) delete frm.doc.__onload.dashboard_info;
	},

	refresh: function (frm) {
		if (fps_can_see_receivables()) return;
		if (frm.doc.__onload) delete frm.doc.__onload.dashboard_info;
		fps_strip_billing_indicators(frm);

		// ERPNext adds these two View-menu buttons unconditionally. Both route to
		// query reports whose Has Role tables already exclude non-finance users,
		// so for this viewer they only ever raise a permission error. Best effort:
		// remove_custom_button is a no-op when the button is not present.
		frm.remove_custom_button("Accounts Receivable", "View");
		frm.remove_custom_button("Accounting Ledger", "View");
	},
});
