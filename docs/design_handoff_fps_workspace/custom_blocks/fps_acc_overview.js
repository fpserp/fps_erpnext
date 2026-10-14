var FPS_CC_VERSION = "48c98f51aec0";
// ^ Rewritten with the bundle's content hash by dashboard/scripts/sync-block.mjs
//   after every build (it matches that exact line, here and in fps_overview.js).
//   Keep it the only line of its kind in this file.
//
// FPS ACC Overview -- loader for the FPS ACC Dashboard (accounting).
//
// The SAME prebuilt bundle as the FPS Overview block (the FPS OPS Dashboard),
// mounted with variant "acc". /assets is cached "max-age=31536000, immutable",
// so the URL carries the bundle hash as ?v=; a new build that kept the old URL
// would never reach a browser that already has the old file.
//
// This script runs inside Frappe's wrapper for Custom HTML Blocks -- a classic
// inline <script>, `root_element` is the block's shadow root -- so a static
// `import` is a syntax error here but dynamic import() works. The bundle's
// mount() swaps the placeholder's contents for its own element (which keeps the
// dashboard in a nested shadow root of its own) and puts it back on unmount.
//
// ACCESS. The workspace "FPS ACC" is limited to Accounts Manager, and every
// method the dashboard calls (fps_erpnext.api.acc_dashboard) checks that role
// again before reading anything. This block holds no data of its own.
//
// FALLBACK. If the bundle cannot be fetched or mount() throws, the mount point
// shows one line asking for a reload. Unlike FPS Overview there is no classic
// strip to fall back to.
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
		m.mount(scope, { mountPoint: mountPoint, variant: "acc" });
	})
	.catch(function (err) {
		console.error(
			"FPS ACC Overview: the dashboard bundle did not load (" + SRC + ").",
			err
		);
		renderFallback();
	});

function renderFallback() {
	if (!mountPoint) return;

	// A mount() that failed half-way may have left its element in the
	// placeholder; the innerHTML below removes it (its disconnectedCallback
	// tears the React root down).
	mountPoint.hidden = false;
	mountPoint.style.removeProperty("display");
	mountPoint.innerHTML =
		'<div class="fps-acc-msg" role="alert">' +
		"The FPS ACC Dashboard could not load &mdash; reload the page." +
		"</div>";
}
