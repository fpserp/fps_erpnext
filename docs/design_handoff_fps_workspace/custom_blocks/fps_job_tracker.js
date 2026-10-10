// Job Tracker board -- one row per open job, colour-coded by customer.
//
// Colour is assigned from the SORTED customer list the server returns, so a
// given customer keeps the same colour across reloads. Deriving it from row
// order instead would reshuffle every time a job was touched.
//
// THEME. This block renders in a shadow root, which the desk stylesheets
// cannot reach -- only inherited CSS custom properties cross into it. So the
// colours below are var(--fps-*, <light colour>): under the FPS Midnight theme
// (public/css/fps_midnight.css) the --fps-* tokens supply dark-safe values;
// anywhere else the fallback is the block's original light colour.
//
// LIVE REFRESH. Polls every 30s -- see fps_overview.js for why the interval
// checks the block's own node is still attached before each tick rather than
// relying on any teardown hook, which these blocks do not get.

(function () {
	var scope =
		typeof root_element !== "undefined" && root_element ? root_element : document;

	var body = scope.querySelector('[data-fps="rows"]');
	var legend = scope.querySelector('[data-fps="legend"]');
	var meta = scope.querySelector('[data-fps="meta"]');
	if (!body) return;

	var REFRESH_MS = 30000;

	// Customer palette. Deliberately distinct from the status hues, which
	// carry fixed meanings -- customer identity and job status must not be
	// confusable for one another. Slot order is unchanged, so a customer keeps
	// its slot; the midnight values are the same hue families lifted to >= 5.8:1
	// on the dark card.
	var PALETTE = [
		"var(--fps-cust-1, #0B4FE0)", "var(--fps-cust-2, #22D3EE)",
		"var(--fps-cust-3, #8F4CFF)", "var(--fps-cust-4, #0EA5E9)",
		"var(--fps-cust-5, #14B8A6)", "var(--fps-cust-6, #F59E0B)",
		"var(--fps-cust-7, #EC4899)", "var(--fps-cust-8, #64748B)",
		"var(--fps-cust-9, #7C3AED)", "var(--fps-cust-10, #0891B2)",
		"var(--fps-cust-11, #A16207)", "var(--fps-cust-12, #BE185D)",
	];

	// Stage -> tone. The tone classes (fps_job_tracker.css) hold the colours,
	// so a theme can restyle them without touching this map.
	var STAGE = {
		New: "blue",
		"Docs received": "orange",
		"In Progress": "amber",
		"Cleared - Ready": "violet",
		Delivered: "green",
		Invoiced: "purple",
		"On Hold": "red",
		Closed: "gray",
	};

	function esc(v) {
		return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
			return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
		});
	}

	function render(data) {
		var jobs = (data && data.jobs) || [];
		var customers = (data && data.customers) || [];

		if (!jobs.length) {
			body.innerHTML =
				'<tr><td colspan="8" class="fps-jt-msg">No open jobs.</td></tr>';
			return;
		}

		var colourOf = {};
		customers.forEach(function (c, i) {
			colourOf[c] = PALETTE[i % PALETTE.length];
		});

		if (legend) {
			legend.innerHTML = customers
				.map(function (c) {
					return (
						'<span class="fps-jt-chip" style="--fps-cust-color: ' +
						colourOf[c] + '"><i></i><span>' + esc(c) + "</span></span>"
					);
				})
				.join("");
		}

		body.innerHTML = jobs
			.map(function (j) {
				var tone = STAGE[j.stage] || "gray";
				return (
					'<tr data-job="' + esc(j.name) + '" title="' + esc(j.name) + '">' +
					'<td class="fps-jt-status"><span class="fps-jt-pill fps-tone-' + tone + '">' +
					esc(j.stage || "—") + "</span></td>" +
					'<td class="fps-jt-cust" style="--fps-cust-color: ' +
					(colourOf[j.customer] || "transparent") + '">' +
					esc(j.customer || "—") + "</td>" +
					'<td class="fps-jt-jo">' + esc(j.name) + "</td>" +
					'<td class="fps-jt-ref">' + esc(j.reference || "—") + "</td>" +
					'<td class="fps-jt-sow" title="' + esc(j.sow) + '">' +
					esc(j.sow || "—") + "</td>" +
					'<td class="fps-jt-cons" title="' + esc(j.consignment) + '">' +
					esc(j.consignment || "—") + "</td>" +
					'<td class="fps-jt-route" title="' + esc(j.route) + '">' +
					esc(j.route || "—") + "</td>" +
					'<td class="fps-jt-eta">' + esc(j.eta || "—") + "</td>" +
					"</tr>"
				);
			})
			.join("");

		if (meta) {
			meta.textContent =
				jobs.length + " open jobs · " + customers.length + " customers";
		}
	}

	// Row click opens the job order itself -- its update log (what this board's
	// status column and every row here is built from) is a grid directly on
	// that form now, not a separate document to look up first. Delegated so it
	// survives every re-render, and routed through frappe.set_route rather than
	// an <a href> so the desk navigates in place instead of doing a full page
	// reload.
	body.addEventListener("click", function (e) {
		var row = e.target.closest("tr[data-job]");
		if (!row) return;
		frappe.set_route("Form", "Job Order", row.getAttribute("data-job"));
	});

	var loaded = false;
	function load() {
		frappe
			.call({ method: "fps_erpnext.api.pipeline.get_job_tracker" })
			.then(function (r) {
				loaded = true;
				render(r && r.message);
			})
			.catch(function () {
				// Only the first load's failure replaces the board with an error --
				// a later poll that briefly fails should leave the last good rows
				// on screen rather than blank them.
				if (!loaded) {
					body.innerHTML =
						'<tr><td colspan="8" class="fps-jt-msg">Could not load the job tracker.</td></tr>';
				}
			});
	}

	load();
	var timer = setInterval(function () {
		// KNOWN ISSUE (fix separately, needs its own OK): body is in a shadow root, so this contains() is always false and the refresh stops after one tick.
		if (!document.body.contains(body)) {
			clearInterval(timer);
			return;
		}
		load();
	}, REFRESH_MS);
})();
