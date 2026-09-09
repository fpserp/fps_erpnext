// FPS Overview strip -- design 1a, step 6.
//
// One frappe.call to one whitelisted read-only method. The method omits any tile
// whose doctype the caller cannot read, so this renders what the viewer is
// entitled to see and never reveals the existence of the rest.

(function () {
	var scope =
		typeof root_element !== "undefined" && root_element ? root_element : document;

	var grid = scope.querySelector('[data-fps="grid"]');
	var foot = scope.querySelector('[data-fps="foot"]');
	var meta = scope.querySelector('[data-fps="meta"]');
	if (!grid) return;

	// Tile identity colours, in workflow order. The handoff's oklch() values are
	// the intent, used verbatim here because inside a Custom HTML Block we own the
	// CSS -- unlike shortcuts and cards, which are limited to Frappe's palette.
	var COLOURS = {
		enquiry: "oklch(0.68 0.1 220)",
		quotation: "oklch(0.66 0.11 205)",
		job_order: "oklch(0.62 0.12 195)",
		job_tracker: "oklch(0.66 0.1 265)",
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
		var tiles = (data && data.tiles) || [];
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

	frappe
		.call({ method: "fps_erpnext.api.pipeline.get_overview" })
		.then(function (r) {
			render(r && r.message);
		})
		.catch(function () {
			grid.innerHTML = '<div class="fps-ov-msg">Could not load the overview.</div>';
		});
})();
