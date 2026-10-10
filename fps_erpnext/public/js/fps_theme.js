// FPS theme -- decides when the FPS desk theme is on, and in which palette.
//
// It sets html[data-fps-theme] while the viewer is "under the FPS app tile"
// and removes it everywhere else; css/fps_theme.css scopes every rule under
// that attribute. That is ALL this file does: no frappe.call, no frappe.db,
// no writes of any kind, nothing sent anywhere.
//
// WHICH PALETTE. The value follows the user's own Frappe theme, resolved on
// html[data-theme]: "light" -> "pearl", "dark" -> "black" (Matte Black).
// Users switch it in Frappe's Toggle Theme dialog (avatar menu, Ctrl+Shift+G,
// or the Command Center's sun/moon button); Frappe saves that on their own
// profile and rewrites html[data-theme], which this file watches, so the
// palette changes on the spot. "Automatic" follows the computer because
// Frappe resolves it to light/dark on the same attribute.
//
// WHAT COUNTS AS "UNDER THE FPS TILE". The ACTIVE SIDEBAR, not the URL. A Job
// Order opened from the FPS sidebar is FPS; the same Job Order reached from
// the Selling sidebar is not, and the URL is identical in both cases. Frappe
// v16 keeps the sidebar's title on .body-sidebar[data-title]
// (ui/sidebar/sidebar.js setup()). It reads "FPS" for everyone -- for
// ops@fastplanet.ae the per-user override is swapped in under the key "fps"
// and titled "FPS" -- but a viewer can still land on the per-user sidebar's
// own name, "FPS-ops@fastplanet.ae", hence the pattern below. The FPS
// workspace routes themselves count as FPS whatever the sidebar says
// (Payment Receipts lives under FPS Accounts but is its own workspace).
//
// TIMING. This file is an app_include_js, so it runs before frappe.start_app():
// no sidebar and no router events exist yet. Sidebar.setup() fires
// "sidebar_setup" BEFORE it assigns the new title, and "sidebar-expand" after;
// the router's "change" fires after the page has rendered. So the decision is
// never taken synchronously inside one of those handlers: a MutationObserver
// on the sidebar's data-title and on body[data-route] does the real work, and
// every trigger is coalesced into a single queueMicrotask(), which runs after
// the synchronous setup() has finished and before the next paint -- no flash
// between two half-applied states.
//
// ANTI-FLASH ON RELOAD. Until the sidebar exists the attribute cannot be
// decided, which would paint one light frame on every reload of an FPS page.
// The last decision is kept in sessionStorage together with the URL it was
// taken for, and re-applied at load only for that same URL. Any other URL
// waits for the real decision (a wrong guess would flash the other way).

(function () {
	"use strict";

	var ATTR = "data-fps-theme";
	// Named after the file, not the palette: the stored value is only
	// {url, on}; the palette itself is re-read from html[data-theme], which the
	// server already renders on the first paint, so a stale palette is never
	// replayed.
	var STORE_KEY = "fps_theme_last";

	// "FPS", or a per-user copy such as "FPS-ops@fastplanet.ae".
	var FPS_SIDEBAR = /^fps(-[^\s@]+@\S+)?$/i;

	var root = document.documentElement;
	var observed = null; // the .body-sidebar currently being watched
	var scheduled = false;

	function here() {
		return window.location.pathname + window.location.search;
	}

	function remember(on) {
		try {
			window.sessionStorage.setItem(STORE_KEY, JSON.stringify({ url: here(), on: on }));
		} catch (e) {
			// Private mode or storage disabled: the anti-flash is a nicety only.
		}
	}

	function recall() {
		try {
			var saved = JSON.parse(window.sessionStorage.getItem(STORE_KEY) || "null");
			return saved && saved.url === here() ? !!saved.on : null;
		} catch (e) {
			return null;
		}
	}

	// The VALUE names the palette css/fps_theme.css carries a section for. A new
	// palette is a new value plus a new section there, never an edit to the
	// user's own Frappe theme.
	function palette() {
		return root.getAttribute("data-theme") === "dark" ? "black" : "pearl";
	}

	function setTheme(on) {
		if (on) {
			var value = palette();
			if (root.getAttribute(ATTR) !== value) root.setAttribute(ATTR, value);
		} else if (root.hasAttribute(ATTR)) {
			root.removeAttribute(ATTR);
		}
	}

	// body[data-route] (views/container.js) rather than frappe.get_route_str():
	// it is only set once a page has actually rendered, and it is the same
	// attribute the stylesheet's workspace rules key on, so the two agree.
	function currentRoute() {
		return (document.body && document.body.getAttribute("data-route")) || "";
	}

	function isFpsWorkspaceRoute(route) {
		return (
			route === "Workspaces/FPS" ||
			route.indexOf("Workspaces/FPS ") === 0 ||
			route === "Workspaces/Payment Receipts"
		);
	}

	function sidebarTitle() {
		var el = document.querySelector(".body-sidebar[data-title]");
		if (el) return el.getAttribute("data-title") || "";
		// frappe.app is only assigned once the Application constructor returns,
		// so this fallback can be undefined during startup.
		var app = window.frappe && frappe.app;
		return (app && app.sidebar && app.sidebar.sidebar_title) || "";
	}

	// true / false, or null while the desk has not rendered a page AND has not
	// titled the sidebar yet -- during startup there is nothing to decide from,
	// and answering "false" there would undo the anti-flash guess.
	function decide() {
		var route = currentRoute();
		if (isFpsWorkspaceRoute(route)) return true;
		var title = String(sidebarTitle()).trim();
		if (!title && !route) return null;
		return FPS_SIDEBAR.test(title);
	}

	function apply() {
		scheduled = false;
		watchSidebar();
		var on = decide();
		if (on === null) return;
		setTheme(on);
		remember(on);
	}

	function schedule() {
		if (scheduled) return;
		scheduled = true;
		var run = typeof queueMicrotask === "function" ? queueMicrotask : function (fn) {
			Promise.resolve().then(fn);
		};
		run(apply);
	}

	var observer =
		typeof MutationObserver === "function" ? new MutationObserver(schedule) : null;

	// The sidebar is built inside the Application constructor, after this file
	// has run. Attach the moment it exists, and re-attach if Frappe ever
	// rebuilds it.
	function watchSidebar() {
		if (!observer) return;
		var el = document.querySelector(".body-sidebar");
		if (!el || el === observed) return;
		observer.observe(el, { attributes: true, attributeFilter: ["data-title"] });
		observed = el;
	}

	// container.js sets body[data-route] on every page change.
	function watchRoute() {
		if (observer && document.body) {
			observer.observe(document.body, { attributes: true, attributeFilter: ["data-route"] });
		}
	}

	// frappe.ui.set_theme() rewrites html[data-theme] when the user picks a
	// theme (or the computer flips under "Automatic"); follow it.
	function watchFrappeTheme() {
		if (observer) observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
	}

	// Anti-flash: same URL as the last decision in this tab -> reuse it now.
	if (recall() === true) setTheme(true);

	watchFrappeTheme();
	if (document.body) watchRoute();

	var $ = window.jQuery;
	if ($) {
		// Registered inside app_ready so the router listener runs after the
		// sidebar's own (which the Application constructor registered earlier).
		$(document).on("app_ready", function () {
			watchRoute();
			if (window.frappe && frappe.router && typeof frappe.router.on === "function") {
				frappe.router.on("change", schedule);
			}
			schedule();
		});
		// Fired BEFORE the title changes: the microtask lands after setup().
		$(document).on("sidebar_setup sidebar-expand", schedule);
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", function () {
			watchRoute();
			schedule();
		});
	} else {
		schedule();
	}
})();
