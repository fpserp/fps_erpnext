// Customer form: hide the "Annual Billing" and "Total Unpaid" header indicators
// from anyone outside finance.
//
// ERPNext's customer.js refresh() reads frm.doc.__onload.dashboard_info and calls
// frm.dashboard.add_indicator() once per figure. Client Scripts are appended after
// the app's own form script, so removing the payload in onload() means refresh()
// finds nothing left to draw. The refresh() pass is belt-and-braces for the
// multi-company branch, which builds its row through erpnext.utils.setup_dashboard_info
// instead, and for any later repaint.
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

	var money = /annual billing|total unpaid|outstanding|billing this year/i;

	dashboard.stats_area_row.find(".indicator, .indicator-pill").each(function () {
		var $pill = $(this);
		if (!money.test($pill.text())) return;
		var $cell = $pill.closest("[class*='col-']");
		($cell.length ? $cell : $pill).remove();
	});

	if (dashboard.stats_area && !dashboard.stats_area_row.children().length) {
		dashboard.stats_area.addClass("hidden");
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
		// The multi-company branch appends asynchronously; sweep again next tick.
		setTimeout(function () {
			fps_strip_billing_indicators(frm);
		}, 0);
	},
});
