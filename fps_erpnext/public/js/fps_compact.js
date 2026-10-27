// FPS compact desk -- two sidebar toggle buttons in the page head of every desk
// page (all modules). Agam, 27 Oct 2026: "give an option to minimize the left
// hand side panel and also the right hand side panel if any".
//
//   [<]  left  : collapses / expands the module sidebar (the Accounts / FPS /
//                Selling list on the left) to the icon rail. This is Frappe
//                16's own frappe.app.sidebar.toggle_width(); Frappe saves the
//                state on the user's profile, so it stays collapsed across
//                pages and reloads until opened again.
//   [>]  right : hides / shows the right-hand form sidebar (Assign, Attachments,
//                Tags, Share, Last Edited...). Shown only on pages that have one.
//                Done with body.fps-form-sidebar-hidden + css/fps_compact.css;
//                remembered in localStorage (per browser).
//
// No frappe.call, no writes of any kind. The buttons are re-added on every
// route change because Frappe rebuilds the page head per page.
(function () {
	const KEY = "fps_form_sidebar_hidden";
	const ICON_LEFT = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M6 3v10"/><path d="M11 6.5 9.5 8 11 9.5"/></svg>';
	const ICON_RIGHT = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M10 3v10"/><path d="M5 6.5 6.5 8 5 9.5"/></svg>';

	function hidden() {
		try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; }
	}
	function remember(v) {
		try { localStorage.setItem(KEY, v ? "1" : "0"); } catch (e) { /* private window */ }
	}
	function apply_right() {
		document.body.classList.toggle("fps-form-sidebar-hidden", hidden());
	}
	function toggle_left() {
		const sb = frappe.app && frappe.app.sidebar;
		if (sb && typeof sb.toggle_width === "function") sb.toggle_width();
	}
	function toggle_right() {
		remember(!hidden());
		apply_right();
	}
	function add_buttons() {
		const page = document.querySelector(".page-container:not(.hide) .page-head, .page-head");
		if (!page) return;
		const actions = page.querySelector(".page-actions");
		if (!actions || actions.querySelector(".fps-side-toggle")) return;
		const mk = (cls, icon, title, fn) => {
			const b = document.createElement("button");
			b.type = "button";
			b.className = "btn-reset fps-side-toggle " + cls;
			b.title = title;
			b.innerHTML = icon;
			b.addEventListener("click", (e) => { e.preventDefault(); fn(); });
			return b;
		};
		actions.prepend(mk("fps-side-toggle-left", ICON_LEFT, __("Collapse / expand the left sidebar"), toggle_left));
		// only this page's own right sidebar counts: Frappe keeps earlier pages in the DOM, hidden
		const container = page.closest(".page-container") || page.parentElement;
		if (container && container.querySelector(".layout-side-section.right .form-sidebar")) {
			actions.prepend(mk("fps-side-toggle-right", ICON_RIGHT, __("Hide / show the right sidebar"), toggle_right));
		}
	}
	function refresh() {
		apply_right();
		// the page head is built after the route event; try now and again shortly after
		add_buttons();
		setTimeout(add_buttons, 300);
		setTimeout(add_buttons, 1200);
	}
	$(document).on("page-change", refresh);
	$(document).on("form-refresh", refresh);
	if (window.frappe && frappe.router && frappe.router.on) frappe.router.on("change", refresh);
	$(refresh);
})();
