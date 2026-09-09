// Job Tracker board -- one row per open job, colour-coded by customer.
//
// Colour is assigned from the SORTED customer list the server returns, so a
// given customer keeps the same colour across reloads. Deriving it from row
// order instead would reshuffle every time a job was touched.

(function () {
	var scope =
		typeof root_element !== "undefined" && root_element ? root_element : document;

	var body = scope.querySelector('[data-fps="rows"]');
	var legend = scope.querySelector('[data-fps="legend"]');
	var meta = scope.querySelector('[data-fps="meta"]');
	if (!body) return;

	// Customer palette. Deliberately distinct from the five status hues, which
	// carry fixed meanings -- customer identity and job status must not be
	// confusable for one another.
	var PALETTE = [
		"#0B4FE0", "#22D3EE", "#8F4CFF", "#0EA5E9", "#14B8A6",
		"#F59E0B", "#EC4899", "#64748B", "#7C3AED", "#0891B2",
		"#A16207", "#BE185D",
	];

	var STAGE = {
		New: ["#eff6ff", "#1d4ed8"],
		Docs: ["#fff7ed", "#b45309"],
		"In Progress": ["#fef3c7", "#92400e"],
		"Cleared - Ready": ["#ede9fe", "#6d28d9"],
		Delivered: ["#dcfce7", "#15803d"],
		Invoiced: ["#f3e8ff", "#7e22ce"],
		"On Hold": ["#fee2e2", "#b91c1c"],
		Closed: ["#f1f5f9", "#475569"],
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
				var pill = STAGE[j.stage] || ["#f1f5f9", "#475569"];
				return (
					'<tr data-job="' + esc(j.name) + '" title="' + esc(j.name) + '">' +
					'<td class="fps-jt-status"><span class="fps-jt-pill" style="--fps-stage-bg: ' +
					pill[0] + "; --fps-stage-fg: " + pill[1] + '">' +
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

	// Row click opens the Job Order. Delegated so it survives every re-render,
	// and routed through frappe.set_route rather than an <a href> so the desk
	// navigates in place instead of doing a full page reload.
	body.addEventListener("click", function (e) {
		var row = e.target.closest("tr[data-job]");
		if (!row) return;
		frappe.set_route("Form", "Job Order", row.getAttribute("data-job"));
	});

	frappe
		.call({ method: "fps_erpnext.api.pipeline.get_job_tracker" })
		.then(function (r) {
			render(r && r.message);
		})
		.catch(function () {
			body.innerHTML =
				'<tr><td colspan="8" class="fps-jt-msg">Could not load the job tracker.</td></tr>';
		});
})();
