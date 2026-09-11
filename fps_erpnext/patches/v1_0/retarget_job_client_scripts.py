"""Point the two Job Order client scripts at fps_erpnext.api.jobs, and drop the
now-redundant "Update history" / "Job Tracker" buttons.

Both changes were verified against the live script text before this was
written -- see build_job_emitters.py's sibling transform for the client
scripts, applied with the same assert-before-replace discipline and re-checked
with `node --check`.

  Job Order - SOW Tracker UI
    "Log update"        now calls fps_erpnext.api.jobs.log_update
    "Rebuild checklist" now calls fps_erpnext.api.jobs.rebuild
    "Update history"     REMOVED -- the update log this button used to open on
                          a separate Job Tracker document is now the Updates
                          grid directly below the checklist on this same page.
    fps_open_tracker()   REMOVED -- its only caller was the button above.

  Job Order - Create Buttons
    "Job Tracker" (View) REMOVED, same reasoning.
    fps_open_tracker()   REMOVED, same reasoning.

Everything else in both scripts -- render_header, render_checklist, relabel,
the Log update dialog's fields, Create Customs Tracker / POD / Sales Invoice,
the View buttons for POD / Customs Tracker / Invoices -- is untouched.

Safe to re-run: a script whose body already matches is skipped.
"""

import frappe

SCRIPTS = {
	'Job Order - SOW Tracker UI': """\
// Job Order - SOW Tracker UI (Form). Status header + stepper at the top of the form, detailed checklist, "Log update" dialog.
frappe.ui.form.on('Job Order', {
  refresh(frm) {
    render_header(frm);
    render_checklist(frm);
    relabel(frm);
    if (frm.doc.__islocal) return;
    frm.add_custom_button(__('Log update'), () => log_update_dialog(frm)).addClass('btn-primary');
    frm.add_custom_button(__('Rebuild checklist'), () => {
      // Was: insert a throwaway Job Tracker document purely to trigger the
      // rollup. 174 of those had to be deleted afterwards. This re-derives
      // from the documents and records nothing.
      frappe.call({ method: 'fps_erpnext.api.jobs.rebuild', args: { job_order: frm.doc.name } }).then(() => frm.reload_doc());
    }, __('Tracker'));
    frm.add_custom_button(__('Job board'), () => frappe.set_route('job-order', 'view', 'kanban', 'FPS Job Tracker'), __('Tracker'));
    if (frm.doc.fps_stage) {
      frm.page.set_indicator(__(frm.doc.fps_stage) + (frm.doc.fps_progress ? ' · ' + frm.doc.fps_progress : ''), stage_color(frm.doc.fps_stage));
    }
  },
  fps_svc_freight(frm) { relabel(frm); }, fps_svc_transport(frm) { relabel(frm); }, fps_svc_crossborder(frm) { relabel(frm); }, fps_svc_clearance(frm) { relabel(frm); },
});

const ACTIVITY = {
  docs: { name: 'Documents & freight', bg: '#E4EEFB', fg: '#1B4FA8', border: '#B9D0F2' },
  customs: { name: 'Customs', bg: '#FCF1DA', fg: '#7D5200', border: '#F0D49A' },
  transport: { name: 'Transport & delivery', bg: '#DDF4EE', fg: '#0F6B5C', border: '#A9DFD1' },
  general: { name: 'General job', bg: '#ECE8F8', fg: '#4A3A9A', border: '#CFC5EF' },
  billing: { name: 'Billing & closure', bg: '#EBEEF2', fg: '#3B4453', border: '#CAD1DB' },
};
function activity_group(code) {
  if (['BOOKED', 'DOCS', 'DEPARTED', 'ARRIVED'].includes(code)) return ACTIVITY.docs;
  if (['FZ_BOE', 'FZ_CLEARED', 'OMAN_BOE', 'OMAN_CLEARED', 'MOFA', 'BOE', 'DO', 'DUTY', 'CLEARED'].includes(code)) return ACTIVITY.customs;
  if (['VEHICLE', 'PICKED_UP', 'TRUCKS_DEPARTED', 'BORDER', 'DELIVERED'].includes(code)) return ACTIVITY.transport;
  if (['DOCS_IN', 'SUBMITTED', 'COMPLETED'].includes(code)) return ACTIVITY.general;
  return ACTIVITY.billing;
}
function stage_color(stage) {
  return { 'New': 'gray', 'Docs': 'orange', 'In Progress': 'blue', 'Cleared - Ready': 'cyan', 'Delivered': 'green', 'Invoiced': 'darkgrey', 'Closed': 'light-gray', 'On Hold': 'red' }[stage] || 'gray';
}
function stage_words(stage) {
  return { 'New': 'New job, nothing filed yet', 'Docs': 'Waiting for shipping documents', 'In Progress': 'In progress', 'Cleared - Ready': 'Customs released, delivery pending', 'Delivered': 'Delivered, to be invoiced', 'Invoiced': 'Invoiced, awaiting closure', 'Closed': 'Closed', 'On Hold': 'On hold' }[stage] || stage;
}
function parse_state(frm) { try { return JSON.parse(frm.doc.fps_milestone_state || '[]'); } catch (e) { return []; } }
function relabel(frm) {
  const transport_only = (frm.doc.fps_svc_transport || frm.doc.fps_svc_crossborder) && !frm.doc.fps_svc_freight && !frm.doc.fps_svc_clearance;
  frm.set_df_property('pol', 'label', transport_only ? 'Pickup from' : 'Origin / POL');
  frm.set_df_property('pod', 'label', transport_only ? 'Deliver to' : 'Destination');
}

function render_header(frm) {
  if (!frm.dashboard || !frm.dashboard.wrapper) return;
  frm.dashboard.wrapper.find('.fps-status').remove();
  if (frm.doc.__islocal) return;
  const esc = frappe.utils.escape_html;
  const rows = parse_state(frm);
  const total = rows.filter(r => r[2] !== 'na').length, done = rows.filter(r => r[2] === 'done').length;
  const pct = total ? Math.round(done / total * 100) : 0;
  const stage = frm.doc.fps_stage || 'New';
  const pill = '<span class="indicator-pill ' + stage_color(stage) + '" style="font-size:13px;padding:4px 12px">' + esc(stage) + '</span>';
  let html = '<div class="fps-status" style="padding:6px 0 4px">';
  if (frm.doc.fps_hold_reason) html += '<div class="alert alert-danger" style="padding:6px 10px;margin:0 0 10px"><b>On hold:</b> ' + esc(frm.doc.fps_hold_reason) + '</div>';
  html += '<div style="display:flex;flex-wrap:wrap;gap:18px 28px;align-items:center;margin-bottom:10px">'
    + '<div>' + pill + ' <span class="text-muted" style="margin-left:6px">' + esc(stage_words(stage)) + '</span></div>'
    + '<div style="min-width:220px"><div style="display:flex;justify-content:space-between;font-size:12px;color:#6c757d"><span>' + esc(frm.doc.fps_subcategory || '') + '</span><span>' + done + ' / ' + total + '</span></div><div style="height:8px;background:#e6e9f0;border-radius:4px;overflow:hidden"><div style="height:100%;width:' + pct + '%;background:#0B4FE0"></div></div></div>'
    + '<div><div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6c757d">Next action</div><div style="font-weight:600">' + esc(frm.doc.fps_next_action || '—') + (frm.doc.fps_next_due ? ' <span class="text-muted">· due ' + frappe.datetime.str_to_user(frm.doc.fps_next_due) + '</span>' : '') + '</div></div>'
    + '<div><div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6c757d">Owner</div><div>' + esc((frm.doc.fps_owner || '').split('@')[0] || '—') + '</div></div>'
    + '<div style="flex:1;min-width:240px"><div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6c757d">Last update</div><div>' + esc(frm.doc.fps_last_update || '—') + '</div></div>'
    + '</div>';
  if (rows.length) {
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px">';
    rows.filter(r => r[0] !== 'OPENED').forEach(r => {
      const [code, label, status, date, note] = r;
      const g = activity_group(code);
      const bg = status === 'done' ? g.bg : status === 'na' ? '#F3F4F7' : '#FFFFFF';
      const fg = status === 'na' ? '#9AA3B5' : g.fg;
      const mark = status === 'done' ? '&#10003; ' : status === 'unconfirmed' ? '? ' : status === 'na' ? '&ndash; ' : '&#9675; ';
      const title = (status === 'done' ? 'Done' : status === 'unconfirmed' ? 'Unconfirmed' : status === 'na' ? 'Not applicable' : 'Pending') + (date ? ' · ' + frappe.datetime.str_to_user(date) : '') + (note ? ' · ' + note : '');
      html += '<span title="' + esc(title) + '" style="font-size:12px;padding:3px 9px;border-radius:12px;border:1px solid ' + (status === 'na' ? '#d8deea' : g.border) + ';background:' + bg + ';color:' + fg + (status === 'na' ? ';text-decoration:line-through' : '') + (status === 'unconfirmed' ? ';border-style:dashed' : '') + '">' + mark + esc(label) + (date && status === 'done' ? ' <span style="opacity:.7">' + frappe.datetime.str_to_user(date).slice(0, 5) + '</span>' : '') + '</span>';
    });
    html += '</div>';
    html += '<div style="margin-top:8px;font-size:11.5px;color:#6c757d;display:flex;flex-wrap:wrap;gap:12px">' + Object.values(ACTIVITY).map(a => '<span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:' + a.bg + ';border:1px solid ' + a.border + ';margin-right:4px;vertical-align:-1px"></i>' + a.name + '</span>').join('') + '<span>&#10003; done &nbsp; &#9675; pending &nbsp; ? unconfirmed &nbsp; &ndash; not needed</span></div>';
  }
  html += '</div>';
  const section = frm.dashboard.add_section(html, __('Job status'));
  if (section && section.addClass) section.addClass('fps-status');
  frm.dashboard.show();
}

function render_checklist(frm) {
  const wrapper = frm.get_field('fps_checklist_html') && frm.get_field('fps_checklist_html').$wrapper;
  if (!wrapper) return;
  const rows = parse_state(frm);
  if (!rows.length) { wrapper.html('<div class="text-muted small">The checklist appears after the first save. It is built from the service lines ticked above and from the customs entries, PODs and invoices on this job.</div>'); return; }
  const icon = { done: '<span style="color:#1A8F5C;font-weight:600">&#10003;</span>', na: '<span style="color:#98A3B8">&ndash;</span>', unconfirmed: '<span style="color:#B86E00;font-weight:600">?</span>', pending: '<span style="color:#B9C3D6">&#9675;</span>' };
  let html = '<table class="table table-sm" style="margin:0;font-size:12.5px"><thead><tr><th style="width:26px"></th><th>Milestone</th><th style="width:110px">Date</th><th>Proof / note</th></tr></thead><tbody>';
  rows.forEach(r => {
    const [code, label, status, date, note] = r;
    const dim = status === 'na' ? ' style="color:#98A3B8"' : '';
    const g = activity_group(code);
    html += '<tr' + dim + '><td>' + (icon[status] || icon.pending) + '</td><td><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + g.bg + ';border:1px solid ' + g.border + ';margin-right:7px;vertical-align:0"></span>' + frappe.utils.escape_html(label) + (status === 'unconfirmed' ? ' <span class="text-muted">(unconfirmed)</span>' : '') + '</td><td>' + (date ? frappe.datetime.str_to_user(date) : '') + '</td><td class="text-muted">' + frappe.utils.escape_html(note || '') + '</td></tr>';
  });
  html += '</tbody></table><div class="text-muted small" style="margin-top:6px">&#10003; proven by a document or logged update · ? a draft POD exists · &ndash; not needed on this job · &#9675; still pending</div>';
  wrapper.html(html);
}

function log_update_dialog(frm) {
  const rows = parse_state(frm);
  const pending = rows.filter(r => r[2] !== 'done' && r[2] !== 'na' && r[0] !== 'CLOSED');
  const options = [{ label: __('Just a note (no milestone)'), value: '' }]
    .concat(pending.map(r => ({ label: r[1], value: r[0] })))
    .concat([{ label: __('Put job on hold (issue)'), value: 'HOLD' }, { label: __('Lift hold / resume'), value: 'RESUME' }, { label: __('Close job'), value: 'CLOSED' }]);
  const d = new frappe.ui.Dialog({
    title: __('Log update - {0}', [frm.doc.client_reference_no || frm.doc.name]),
    fields: [
      { fieldname: 'milestone', label: __('This update proves'), fieldtype: 'Select', options: options, default: pending.length ? pending[0][0] : '' },
      { fieldname: 'track_date', label: __('Date'), fieldtype: 'Date', default: frappe.datetime.get_today(), reqd: 1 },
      { fieldname: 'note', label: __('What happened (customer will read this if visible)'), fieldtype: 'Small Text', reqd: 1 },
      { fieldname: 'evidence', label: __('Reference (BOE / DO / vehicle / document no.)'), fieldtype: 'Data' },
      { fieldname: 'cb', fieldtype: 'Column Break' },
      { fieldname: 'next_action', label: __('Next action'), fieldtype: 'Data' },
      { fieldname: 'follow_up', label: __('Next action due'), fieldtype: 'Date' },
      { fieldname: 'visible', label: __('Show on customer status sheet'), fieldtype: 'Check', default: 1 },
      { fieldname: 'internal', label: __('Internal note (never shown to customer)'), fieldtype: 'Small Text' },
    ],
    primary_action_label: __('Save update'),
    primary_action(values) {
      const is_issue = values.milestone === 'HOLD';
      frappe.call({
        method: 'fps_erpnext.api.jobs.log_update',
        args: {
          job_order: frm.doc.name, track_date: values.track_date,
          milestone: values.milestone || null, note: values.note,
          evidence: values.evidence || null, next_action: values.next_action || null,
          follow_up_date: values.follow_up || null,
          customer_visible: is_issue ? 0 : (values.visible ? 1 : 0),
          internal: values.internal || null,
        },
      }).then(() => { d.hide(); frappe.show_alert({ message: __('Update logged'), indicator: 'green' }); frm.reload_doc(); });
    },
  });
  d.show();
}

""",
	'Job Order - Create Buttons': """\
frappe.ui.form.on('Job Order', {
  refresh: function(frm) {
    if (frm.doc.docstatus === 0) {
      frm.add_custom_button(__('Save as Draft'), function() {
        frm.save().then(() => frappe.show_alert({message: __('Saved as draft - review then click Submit when ready'), indicator: 'blue'}, 6));
      });
    }
    if (frm.doc.__islocal || frm.doc.docstatus === 2) return;
    frm.add_custom_button(__('Customs Tracker'), function() { create_ct_from_jo(frm); }, __('Create'));
    // 'Job tracker note' removed: it created a SECOND Job Tracker document for
    // the job, which is exactly what the one-tracker-per-job change undoes. The
    // 'Log update' button on this same form is the way in.
    frm.add_custom_button(__('Proof of Delivery'), function() { create_pod_from_jo(frm); }, __('Create'));
    frm.add_custom_button(__('Sales Invoice'), function() { create_si_from_jo(frm); }, __('Create'));
    if (frm.doc.quotation_ref) {
      frm.add_custom_button(__('Source Quotation'), function() { frappe.set_route('Form', 'Quotation', frm.doc.quotation_ref); }, __('View'));
    }
    frm.add_custom_button(__('Linked POD'), function() { frappe.set_route('List', 'Proof of Delivery', {'job_order': frm.doc.name}); }, __('View'));
    frm.add_custom_button(__('Linked Customs Tracker'), function() { frappe.set_route('List', 'Customs Tracker', {'job_order': frm.doc.name}); }, __('View'));
    // 'Job Tracker' view button removed: there is no separate tracker to
    // open any more -- its update log lives directly on this form's own
    // Updates grid, below the checklist.
    frm.add_custom_button(__('Linked Invoices'), function() { frappe.set_route('List', 'Sales Invoice', {'fps_job_order': frm.doc.name}); }, __('View'));
  }
});
function create_doc_from_jo(frm, doctype, extra) {
  frappe.model.with_doctype(doctype, function() {
    const d = frappe.model.get_new_doc(doctype);
    d.job_order = frm.doc.name; d.customer = frm.doc.customer;
    if (extra) Object.keys(extra).forEach(k => d[k] = extra[k]);
    frappe.set_route('Form', doctype, d.name);
  });
}
function create_ct_from_jo(frm) {
  // ONE Customs Tracker per job. A second BOE is a row inside it, not a second
  // document -- so this opens the existing tracker rather than making another.
  frappe.db.get_value('Customs Tracker', { job_order: frm.doc.name }, 'name').then(r => {
    const existing = r && r.message && r.message.name;
    if (existing) {
      frappe.set_route('Form', 'Customs Tracker', existing);
      frappe.show_alert({ message: __('Add the next BOE as a row under Declarations.'), indicator: 'blue' }, 7);
      return;
    }
    create_doc_from_jo(frm, 'Customs Tracker', {ct_date: frappe.datetime.get_today(), status: 'Pending', fps_leg: 1, fps_clearance_location: frm.doc.fps_clearance_location, fps_clearance_type: frm.doc.fps_clearance_type});
  });
}
function create_pod_from_jo(frm) {
  frappe.db.count('Proof of Delivery', {filters: {job_order: frm.doc.name, docstatus: ['<', 2]}}).then(n => {
    frappe.model.with_doctype('Proof of Delivery', function() {
      const d = frappe.model.get_new_doc('Proof of Delivery');
      d.job_order = frm.doc.name; d.customer = frm.doc.customer;
      d.pod_date = frappe.datetime.get_today(); d.delivery_status = 'Pending';
      d.client_reference_no = frm.doc.client_reference_no;
      d.movement_type = frm.doc.movement_type; d.pol = frm.doc.pol; d.destination = frm.doc.pod;
      d.carrier = frm.doc.carrier; d.awb_bl_no = frm.doc.awb_bl_no; d.container_nos = frm.doc.container_nos;
      d.cargo_description = frm.doc.cargo_description; d.no_of_packages = frm.doc.no_of_packages;
      d.gross_weight = frm.doc.gross_weight; d.load = frm.doc.load;
      d.fps_leg = (n || 0) + 1; d.fps_final_delivery = 1; d.fps_vehicle_type = frm.doc.fps_vehicle_type;
      frappe.set_route('Form', 'Proof of Delivery', d.name);
    });
  });
}
function create_si_from_jo(frm) {
  frappe.model.with_doctype('Sales Invoice', function() {
    const d = frappe.model.get_new_doc('Sales Invoice');
    d.fps_job_order = frm.doc.name; d.customer = frm.doc.customer; d.customer_name = frm.doc.customer_name;
    d.posting_date = frappe.datetime.get_today(); d.due_date = frappe.datetime.add_days(frappe.datetime.get_today(), 30);
    d.fps_client_reference_no = frm.doc.client_reference_no;
    d.fps_movement_type = frm.doc.movement_type; d.fps_pol = frm.doc.pol; d.fps_pod = frm.doc.pod;
    d.fps_carrier = frm.doc.carrier; d.fps_awb_bl_no = frm.doc.awb_bl_no;
    d.fps_cargo_description = frm.doc.cargo_description; d.fps_no_of_packages = frm.doc.no_of_packages;
    d.fps_gross_weight = frm.doc.gross_weight; d.fps_load = frm.doc.load;
    if (frm.doc.ar_charges && frm.doc.ar_charges.length) {
      frm.doc.ar_charges.forEach(row => {
        const item = frappe.model.add_child(d, 'items');
        item.item_code = row.service_item; item.description = row.description;
        item.qty = row.qty || 1; item.rate = row.rate; item.amount = row.amount; item.uom = row.unit;
      });
    }
    frappe.set_route('Form', 'Sales Invoice', d.name);
  });
}
""",
}


def execute():
	changed = 0
	for name, script in SCRIPTS.items():
		if not frappe.db.exists("Client Script", name):
			frappe.log_error(title="FPS: Client Script %s missing, not retargeted" % name)
			continue
		current = frappe.db.get_value("Client Script", name, "script") or ""
		if current == script:
			continue
		frappe.db.set_value("Client Script", name, "script", script, update_modified=False)
		changed += 1

	if changed:
		frappe.db.commit()
	frappe.clear_cache()
	frappe.logger().info("FPS: retargeted %d Job Order client scripts" % changed)

