var FPS_CC_VERSION = "48c98f51aec0";
// ^ Rewritten with the bundle's content hash by dashboard/scripts/sync-block.mjs
//   after every build (it matches that exact line). Keep it the only line of
//   its kind in this file.
//
// FPS Overview -- loader for the FPS Command Center.
//
// The dashboard is a prebuilt React bundle served from /assets. /assets is
// cached "max-age=31536000, immutable", so the URL carries the bundle hash as
// ?v=; a new build that kept the old URL would never reach a browser that
// already has the old file.
//
// This script runs inside Frappe's wrapper for Custom HTML Blocks -- a classic
// inline <script>, `root_element` is the block's shadow root -- so a static
// `import` is a syntax error here but dynamic import() works (the desk sends no
// Content-Security-Policy). The bundle's mount() swaps the placeholder's
// contents for its own <fps-command-center> element (which keeps the dashboard
// in a nested shadow root of its own) and puts the placeholder back on unmount.
//
// FALLBACK. If the bundle cannot be fetched or mount() throws, renderLegacy()
// draws the overview strip this block showed before the Command Center: the
// same read-only get_overview call, the same tiles, footnotes, messages and
// 30 s refresh. The page never ends up with less than it had.
//
// Presentation only: nothing here (or in the bundle) writes to ERPNext.

var SRC = "/assets/fps_erpnext/dashboard/fps-command-center.js?v=" + FPS_CC_VERSION;

var scope =
	typeof root_element !== "undefined" && root_element ? root_element : document;
var mountPoint = scope.querySelector('[data-fps="cc-root"]');

import(SRC)
	.then(function (m) {
		// mount() throws on anything but the block's shadow root, which lands
		// in the catch below like any other failure.
		m.mount(scope, { mountPoint: mountPoint });
	})
	.catch(function (err) {
		console.error(
			"FPS Overview: the Command Center bundle did not load (" + SRC +
			"); showing the classic overview strip instead.",
			err
		);
		renderLegacy();
	});

// The classic overview strip (design 1a, step 6), building its own DOM inside
// the mount point.
//
// One frappe.call to one whitelisted read-only method. The method omits any tile
// whose doctype the caller cannot read, so this renders what the viewer is
// entitled to see and never reveals the existence of the rest.
//
// LIVE REFRESH. Polls every 30s so counts move without a manual page reload.
// The interval checks the block's own DOM node is still attached before each
// tick and clears itself the moment it is not -- the block's container gets
// replaced wholesale on every workspace navigation, with no teardown hook of
// its own to unhook from, so this is what stops a poll loop for a page the
// viewer has since left from running forever in the background. A tick is
// also skipped (not cleared) while the tab is hidden or the page is not
// rendered, so a user working in forms all afternoon does not keep a hidden
// strip polling.
function renderLegacy() {
	if (!mountPoint) return;

	// A mount() that failed half-way may have left its element in the
	// placeholder; the innerHTML below removes it (its disconnectedCallback
	// tears the React root down). The two resets guard against an older
	// bundle that hid the placeholder instead of swapping its contents.
	mountPoint.hidden = false;
	mountPoint.style.removeProperty("display");

	mountPoint.innerHTML =
		'<div class="fps-ov">' +
		'<div class="fps-ov-head">' +
		'<span class="fps-ov-title">FPS Overview</span>' +
		'<span class="fps-ov-help">live count by stage &mdash; click a tile to open the list behind it</span>' +
		'<span class="fps-ov-meta" data-fps="meta"></span>' +
		"</div>" +
		'<div class="fps-ov-grid" data-fps="grid">' +
		'<div class="fps-ov-msg">Loading&hellip;</div>' +
		"</div>" +
		'<div class="fps-ov-foot" data-fps="foot"></div>' +
		"</div>";

	var grid = mountPoint.querySelector('[data-fps="grid"]');
	var foot = mountPoint.querySelector('[data-fps="foot"]');
	var meta = mountPoint.querySelector('[data-fps="meta"]');
	if (!grid) return;

	var REFRESH_MS = 30000;

	// Tile identity colours, in workflow order. The handoff's oklch() values are
	// the intent, used verbatim here because inside a Custom HTML Block we own the
	// CSS -- unlike shortcuts and cards, which are limited to Frappe's palette.
	// As 3px top edges they clear 3:1 on the dark plane as well as on white.
	var COLOURS = {
		enquiry: "oklch(0.68 0.1 220)",
		quotation: "oklch(0.66 0.11 205)",
		job_order: "oklch(0.62 0.12 195)",
		customs: "oklch(0.65 0.14 75)",
		in_progress: "oklch(0.64 0.13 55)",
		delivered: "oklch(0.62 0.12 150)",
		invoices: "oklch(0.55 0.12 300)",
	};

	function esc(v) {
		return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
			return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
		});
	}

	function render(data) {
		// The FPS OPS Dashboard carries no money (14 Oct 2026): the "invoices"
		// tile (open Sales Invoices) belongs to the FPS ACC Dashboard, so the
		// fallback strip drops it too (command_center_logic.OPS_HIDDEN_TILES;
		// pipeline.TILES keeps it for its other callers).
		var tiles = ((data && data.tiles) || []).filter(function (t) {
			return t && t.key !== "invoices";
		});
		if (!tiles.length) {
			grid.innerHTML = '<div class="fps-ov-msg">No stages are visible to you.</div>';
			return;
		}

		grid.innerHTML = tiles
			.map(function (t) {
				var colour = COLOURS[t.key] || "#94a3b8";
				var tag = t.route ? "a" : "div";
				var href = t.route ? ' href="' + esc(t.route) + '"' : "";
				return (
					"<" + tag + ' class="fps-ov-cell"' + href +
					' style="--fps-tile-color: ' + colour + '">' +
					'<span class="fps-ov-label">' + esc(t.label) + "</span>" +
					'<span class="fps-ov-count">' + esc(t.count) + "</span>" +
					'<span class="fps-ov-note">' + esc(t.note || "") + "</span>" +
					"</" + tag + ">"
				);
			})
			.join("");

		if (meta) meta.textContent = tiles.length + " stages";

		if (foot) {
			foot.innerHTML = ((data && data.footnotes) || [])
				.map(function (n) {
					return "<span>" + esc(n) + "</span>";
				})
				.join("");
		}
	}

	var loaded = false;
	function load() {
		frappe
			.call({ method: "fps_erpnext.api.pipeline.get_overview" })
			.then(function (r) {
				loaded = true;
				render(r && r.message);
			})
			.catch(function () {
				// Only the FIRST load's failure replaces the grid with an error --
				// a transient blip on a later poll should not blank out tiles that
				// were showing real counts a moment ago.
				if (!loaded) {
					grid.innerHTML = '<div class="fps-ov-msg">Could not load the overview.</div>';
				}
			});
	}

	load();
	var timer = setInterval(function () {
		// isConnected, not document.body.contains(): the grid lives in the
		// block's shadow root. isConnected follows the shadow host.
		if (!grid.isConnected) {
			clearInterval(timer);
			return;
		}
		// Frappe hides the Workspaces page (display:none) when a list or form
		// opens and does not rebuild it on return (Workspace.show() returns
		// early), so the block stays connected while hidden. Skip ticks while
		// the tab is in the background or the page is not rendered, the same
		// gate the React path uses (lib/shadow.tsx computeVisible).
		if (document.visibilityState !== "visible" || grid.getClientRects().length === 0) return;
		load();
	}, REFRESH_MS);
}
