// Shipment pipeline strip -- design 1a, step 6.
//
// One frappe.call to one whitelisted read-only method. The method omits any
// stage whose doctype the caller cannot read, so this renders whatever the
// viewer is entitled to see and never reveals the existence of the rest.
//
// Frappe hands a Custom HTML Block's script the block element as `root_element`.
// Fall back to a document lookup so the block still renders if that changes.

(function () {
	var scope =
		typeof root_element !== "undefined" && root_element
			? root_element
			: document;

	var grid = scope.querySelector('[data-fps="grid"]');
	var foot = scope.querySelector('[data-fps="foot"]');
	var meta = scope.querySelector('[data-fps="meta"]');
	if (!grid) return;

	// Stage identity colours, in workflow order. The handoff's oklch() values are
	// the intent; used verbatim here because inside a Custom HTML Block we own
	// the CSS, unlike shortcuts and cards which are limited to Frappe's palette.
	var COLOURS = {
		Enquiry: "oklch(0.68 0.1 220)",
		Quotation: "oklch(0.66 0.11 205)",
		New: "oklch(0.64 0.115 200)",
		Docs: "oklch(0.62 0.12 195)",
		"In progress": "oklch(0.65 0.14 75)",
		Cleared: "oklch(0.66 0.1 265)",
		Delivered: "oklch(0.62 0.12 150)",
		Invoiced: "oklch(0.55 0.12 300)",
	};

	function esc(value) {
		return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
			return {
				"&": "&amp;",
				"<": "&lt;",
				">": "&gt;",
				'"': "&quot;",
				"'": "&#39;",
			}[c];
		});
	}

	function render(data) {
		var stages = (data && data.stages) || [];
		if (!stages.length) {
			grid.innerHTML =
				'<div class="fps-pipeline-error">No pipeline stages are visible to you.</div>';
			return;
		}

		grid.innerHTML = stages
			.map(function (stage) {
				var colour = COLOURS[stage.label] || "#94a3b8";
				var tag = stage.route ? "a" : "div";
				var href = stage.route
					? ' href="' + esc(stage.route) + '"'
					: "";
				return (
					"<" + tag + ' class="fps-pipeline-cell"' + href +
					' style="--fps-stage-color: ' + colour + '">' +
					'<span class="fps-pipeline-label">' + esc(stage.label) + "</span>" +
					'<span class="fps-pipeline-count">' + esc(stage.count) + "</span>" +
					"</" + tag + ">"
				);
			})
			.join("");

		var total = stages.reduce(function (sum, stage) {
			return sum + (Number(stage.count) || 0);
		}, 0);
		if (meta) meta.textContent = total + " records across " + stages.length + " stages";

		if (foot) {
			foot.innerHTML = ((data && data.footnotes) || [])
				.map(function (note) {
					return "<span>" + esc(note) + "</span>";
				})
				.join("");
		}
	}

	frappe
		.call({ method: "fps_erpnext.api.pipeline.get_pipeline" })
		.then(function (r) {
			render(r && r.message);
		})
		.catch(function () {
			grid.innerHTML =
				'<div class="fps-pipeline-error">Could not load the pipeline.</div>';
		});
})();
