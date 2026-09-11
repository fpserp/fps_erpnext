// Customs board -- a spreadsheet filter view over every customs entry.
//
// Each filterable column carries its own dropdown. The dropdowns CASCADE, the
// way an autofilter does: the options offered for a column are the values still
// reachable given every OTHER column's filter. Offering the full value list
// instead would let you pick a combination that returns nothing, which is the
// usual way these grids waste your time.
//
// A column's own selection is never removed from its own list, so you can always
// undo a choice that has narrowed everything else to nothing.
//
// LIVE REFRESH. Polls every 30s for new/changed rows -- see fps_overview.js
// for why the interval checks the block's own node is still attached before
// each tick. Only the ROWS are re-fetched and re-rendered; the header (and
// its filter dropdowns' change listener) is built exactly once, and whatever
// the viewer has chosen in `chosen` / typed into `term` carries across every
// poll untouched -- a background refresh must never reset someone's filters
// out from under them mid-review.

(function () {
	var scope =
		typeof root_element !== "undefined" && root_element ? root_element : document;

	var labelRow = scope.querySelector('[data-fps="labels"]');
	var filterRow = scope.querySelector('[data-fps="filters"]');
	var body = scope.querySelector('[data-fps="rows"]');
	var meta = scope.querySelector('[data-fps="meta"]');
	var search = scope.querySelector('[data-fps="search"]');
	var clear = scope.querySelector('[data-fps="clear"]');
	if (!body) return;

	var REFRESH_MS = 30000;

	var STATUS = {
		Pending: ["#fff7ed", "#b45309"],
		"In Process": ["#fef3c7", "#92400e"],
		Cleared: ["#dcfce7", "#15803d"],
		"On Hold": ["#fee2e2", "#b91c1c"],
		Delayed: ["#fee2e2", "#b91c1c"],
	};

	var columns = [];
	var rows = [];
	var chosen = {}; // column key -> selected value ("" means no filter)
	var term = "";

	function esc(v) {
		return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
			return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
		});
	}

	function matches(row, skipKey) {
		for (var key in chosen) {
			if (key === skipKey || !chosen[key]) continue;
			if (row[key] !== chosen[key]) return false;
		}
		if (term) {
			var hay = columns
				.map(function (c) {
					return row[c.key];
				})
				.join(" ")
				.toLowerCase();
			if (hay.indexOf(term) === -1) return false;
		}
		return true;
	}

	function visible() {
		return rows.filter(function (r) {
			return matches(r, null);
		});
	}

	function buildHeader() {
		labelRow.innerHTML = columns
			.map(function (c) {
				return "<th>" + esc(c.label) + "</th>";
			})
			.join("");

		filterRow.innerHTML = columns
			.map(function (c) {
				if (!c.filterable) return "<th></th>";
				return (
					'<th><select class="fps-ct-select" data-col="' +
					esc(c.key) +
					'" aria-label="Filter by ' + esc(c.label) + '"></select></th>'
				);
			})
			.join("");

		filterRow.addEventListener("change", function (e) {
			var sel = e.target.closest("select[data-col]");
			if (!sel) return;
			chosen[sel.getAttribute("data-col")] = sel.value;
			refresh();
		});
	}

	function refreshOptions() {
		columns.forEach(function (c) {
			if (!c.filterable) return;
			var sel = filterRow.querySelector('select[data-col="' + c.key + '"]');
			if (!sel) return;

			// Reachable given every filter EXCEPT this column's own.
			var reachable = {};
			rows.forEach(function (r) {
				if (r[c.key] && matches(r, c.key)) reachable[r[c.key]] = 1;
			});
			var values = Object.keys(reachable).sort();
			var current = chosen[c.key] || "";
			if (current && values.indexOf(current) === -1) values.push(current);

			sel.innerHTML =
				'<option value="">All</option>' +
				values
					.map(function (v) {
						return (
							'<option value="' + esc(v) + '"' +
							(v === current ? " selected" : "") + ">" + esc(v) + "</option>"
						);
					})
					.join("");
			sel.value = current;
			sel.classList.toggle("is-active", !!current);
		});
	}

	function cell(c, row) {
		// Deadline columns carry a state the SERVER worked out -- '', 'ok',
		// 'warn', 'late' or 'done'. The thresholds are not repeated here; see
		// fps_erpnext/api/customs.py. 'done' means the status column next to it
		// says Completed (or Not Applicable), so there is nothing left to chase.
		if (row[c.key + "_state"] !== undefined) {
			var state = row[c.key + "_state"] || "none";
			return (
				'<td class="fps-ct-due fps-ct-due-' + state + '">' +
				esc(row[c.key] || "—") + "</td>"
			);
		}
		if (c.key === "status") {
			var pill = STATUS[row.status] || ["#f1f5f9", "#475569"];
			return (
				'<td><span class="fps-ct-pill" style="--fps-ct-bg: ' + pill[0] +
				"; --fps-ct-fg: " + pill[1] + '">' + esc(row.status || "—") + "</span></td>"
			);
		}
		var cls = { customer: "fps-ct-cust", job_order: "fps-ct-jo",
		            boe: "fps-ct-boe", date: "fps-ct-date" }[c.key] || "";
		var v = row[c.key] || "—";
		return (
			'<td class="' + cls + '" title="' + esc(row[c.key] || "") + '">' +
			esc(v) + "</td>"
		);
	}

	function refresh() {
		refreshOptions();

		var shown = visible();
		var active = columns.filter(function (c) {
			return chosen[c.key];
		}).length + (term ? 1 : 0);

		if (clear) clear.hidden = !active;

		if (!shown.length) {
			body.innerHTML =
				'<tr><td class="fps-ct-msg" colspan="' + columns.length +
				'">Nothing matches these filters.</td></tr>';
		} else {
			body.innerHTML = shown
				.map(function (r) {
					return (
						'<tr data-ct="' + esc(r.name) + '">' +
						columns.map(function (c) { return cell(c, r); }).join("") +
						"</tr>"
					);
				})
				.join("");
		}

		if (meta) {
			meta.textContent =
				shown.length === rows.length
					? rows.length + " declarations"
					: shown.length + " of " + rows.length + " declarations";
		}
	}

	function reset() {
		chosen = {};
		term = "";
		if (search) search.value = "";
		refresh();
	}

	// Delegated so it survives every re-render, and routed through
	// frappe.set_route rather than an <a href> so the desk navigates in place.
	body.addEventListener("click", function (e) {
		var row = e.target.closest("tr[data-ct]");
		if (!row) return;
		frappe.set_route("Form", "Customs Tracker", row.getAttribute("data-ct"));
	});

	if (search) {
		search.addEventListener("input", function () {
			term = (search.value || "").trim().toLowerCase();
			refresh();
		});
	}
	if (clear) clear.addEventListener("click", reset);

	var headerBuilt = false;
	var loaded = false;

	function load() {
		frappe
			.call({ method: "fps_erpnext.api.pipeline.get_customs_tracker" })
			.then(function (r) {
				var data = (r && r.message) || {};
				columns = data.columns || [];
				rows = data.rows || [];
				var firstLoad = !loaded;
				loaded = true;

				if (!columns.length) {
					body.innerHTML =
						'<tr><td class="fps-ct-msg">No access to the customs tracker.</td></tr>';
					return;
				}
				if (!headerBuilt) {
					buildHeader();
					headerBuilt = true;
				}
				if (!rows.length && firstLoad) {
					body.innerHTML =
						'<tr><td class="fps-ct-msg" colspan="' + columns.length +
						'">No customs entries yet.</td></tr>';
					if (meta) meta.textContent = "";
					return;
				}
				refresh();
			})
			.catch(function () {
				// Only the first load's failure replaces the grid with an error --
				// a later poll that briefly fails should leave the last good rows
				// (and whatever the viewer has filtered to) on screen.
				if (!loaded) {
					body.innerHTML =
						'<tr><td class="fps-ct-msg">Could not load the customs tracker.</td></tr>';
				}
			});
	}

	load();
	var timer = setInterval(function () {
		if (!document.body.contains(body)) {
			clearInterval(timer);
			return;
		}
		load();
	}, REFRESH_MS);
})();
