// FPS compact desk -- sidebar controls on every desk page (all modules, all users).
//
// Left module sidebar (the FPS / Accounts / Selling list), Agam 28 Oct 2026:
// "keep the fps panel open ... make the minimise button up not bottom; if
// someone wants they can, else it will be open".
//   - Frappe's own collapse arrow is moved from the bottom of the sidebar to the
//     top (css/fps_compact.css). That arrow is the only way to fold it; Frappe
//     keeps the choice in this browser (localStorage desk-sidebar-collapsed).
//   - The sidebar never folds by itself: Frappe's fold_for_page() is turned off.
//   - Clicking the "FPS" header (logo / name) of a folded sidebar opens it again.
//   (The extra left button that used to sit in the page head is gone: one control.)
//
// Right form sidebar (Assign, Attachments, Tags, Share, Last Edited...):
//   [>] button in the page head hides / shows it. Done with
//   body.fps-form-sidebar-hidden + css/fps_compact.css; remembered in
//   localStorage (per browser). Shown only on pages that have one.
//
// No frappe.call, no writes of any kind. The button is re-added on every
// route change because Frappe rebuilds the page head per page.
(function () {
	const KEY = "fps_form_sidebar_hidden";
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
	function sidebar() {
		return window.frappe && frappe.app && frappe.app.sidebar;
	}
	// keep the left sidebar open unless the user folds it with the arrow
	function keep_left_open() {
		const sb = sidebar();
		if (!sb || sb.__fps_keep_open) return;
		sb.__fps_keep_open = true;
		if (typeof sb.fold_for_page === "function") sb.fold_for_page = function () {};
		if (sb.folded_for_page && typeof sb.unfold_after_leaving_page === "function") sb.unfold_after_leaving_page();
	}
	// a click on the "FPS" header of a folded sidebar opens it (and only that:
	// the header menu is held back so the first click does one thing)
	document.addEventListener("click", function (e) {
		const sb = sidebar();
		if (!sb || sb.sidebar_expanded || typeof sb.open !== "function") return;
		if (!e.target.closest || !e.target.closest(".body-sidebar .sidebar-header")) return;
		e.preventDefault();
		e.stopPropagation();
		sb.open();
	}, true);
	function toggle_right() {
		remember(!hidden());
		apply_right();
		fit_head_soon();
	}
	function add_buttons() {
		const page = document.querySelector(".page-container:not(.hide) .page-head, .page-head");
		if (!page) return;
		const actions = page.querySelector(".page-actions");
		if (!actions) return;
		// older build of this file put a left button here; drop it if a cached page still has one
		actions.querySelectorAll(".fps-side-toggle-left").forEach((b) => b.remove());
		if (actions.querySelector(".fps-side-toggle")) return;
		const mk = (cls, icon, title, fn) => {
			const b = document.createElement("button");
			b.type = "button";
			b.className = "btn-reset fps-side-toggle " + cls;
			b.title = title;
			b.innerHTML = icon;
			b.addEventListener("click", (e) => { e.preventDefault(); fn(); });
			return b;
		};
			// only this page's own right sidebar counts: Frappe keeps earlier pages in the DOM, hidden
		const container = page.closest(".page-container") || page.parentElement;
		if (container && container.querySelector(".layout-side-section.right .form-sidebar")) {
			actions.prepend(mk("fps-side-toggle-right", ICON_RIGHT, __("Hide / show the right sidebar"), toggle_right));
		}
	}
	// Page head on a narrow / portrait screen (Agam, 28 Oct 2026): when the full
	// title ("Job Order / FPS/JO/2610/101" + status) and the buttons do not fit on
	// one line, the head gets two rows -- title on top, buttons below on the
	// right -- instead of squeezing the title to a few letters. Decided from the
	// title's natural width, so it never flips back and forth.
	function fit_head() {
		const pc = document.querySelector(".page-container:not(.hide)");
		if (!pc) return;
		const head = pc.querySelector(".page-head .page-head-content");
		const title = pc.querySelector(".page-head .page-title .title-area");
		const actions = pc.querySelector(".page-head .standard-items-section");
		if (!head || !title || !actions || !head.clientWidth) return;
		const probe = title.cloneNode(true);
		probe.style.cssText = "position:absolute;visibility:hidden;left:-9999px;top:0;width:max-content;max-width:none";
		probe.querySelectorAll("*").forEach((e) => { e.style.maxWidth = "none"; e.style.overflow = "visible"; });
		document.body.appendChild(probe);
		const need = probe.getBoundingClientRect().width;
		probe.remove();
		pc.classList.toggle("fps-head-stacked", need + actions.scrollWidth + 40 > head.clientWidth);
	}
	let fit_timer = null;
	function fit_head_soon() {
		clearTimeout(fit_timer);
		fit_timer = setTimeout(fit_head, 120);
	}
	window.addEventListener("resize", fit_head_soon);
	$(document).on("sidebar-expand", fit_head_soon);

	function refresh() {
		keep_left_open();
		apply_right();
		// the page head is built after the route event; try now and again shortly after
		add_buttons();
		fit_head();
		setTimeout(() => { add_buttons(); fit_head(); }, 300);
		setTimeout(() => { add_buttons(); fit_head(); }, 1200);
	}
	$(document).on("page-change", refresh);
	$(document).on("form-refresh", refresh);
	if (window.frappe && frappe.router && frappe.router.on) frappe.router.on("change", refresh);
	$(refresh);
})();
