// Customs Tracker: colour the two chase clocks on the form.
//
// THE THRESHOLDS ARE DEFINED IN fps_erpnext/api/customs.py AND REPEATED HERE.
// That duplication is deliberate and is the only copy: a form has to recolour
// itself the instant someone changes the clearance date or picks "Completed",
// and a server round trip on every keystroke to fetch four constants would be a
// worse trade than four numbers in two files. If you change them, change both.
//
//   Doc submission   due clearance + 30    amber from day 15, red from day 25
//   MOFA attestation due clearance + 14    amber from day  9, red from day 12

frappe.ui.form.on('Customs Tracker', {
  refresh: fps_paint_deadlines,
  clearance_date: fps_paint_deadlines,
  fps_doc_submission: fps_paint_deadlines,
  fps_mofa_status: fps_paint_deadlines,
});

const FPS_DEADLINES = [
  { date_field: 'fps_doc_deadline', status_field: 'fps_doc_submission', warn: 15, late: 25 },
  { date_field: 'fps_mofa_deadline', status_field: 'fps_mofa_status', warn: 9, late: 12 },
];

// "Submitted" is the old wording for Completed on document submission. Kept so
// any row that missed the migration still reads as finished rather than overdue.
const FPS_DONE = ['completed', 'not applicable', 'n/a', 'submitted'];

function fps_paint_deadlines(frm) {
  FPS_DEADLINES.forEach(spec => {
    const field = frm.get_field(spec.date_field);
    if (!field || !field.$wrapper) return;

    const input = field.$wrapper.find('.control-value, input');
    input.css({ 'background-color': '', 'color': '', 'font-weight': '' });
    frm.set_df_property(spec.date_field, 'description', '');

    const status = (frm.doc[spec.status_field] || '').trim().toLowerCase();
    if (FPS_DONE.includes(status)) {
      frm.set_df_property(spec.date_field, 'description', __('Done — nothing to chase.'));
      return;
    }
    if (!frm.doc.clearance_date) {
      frm.set_df_property(spec.date_field, 'description',
        __('No clearance date yet, so no deadline is running.'));
      return;
    }

    const elapsed = frappe.datetime.get_day_diff(
      frappe.datetime.get_today(), frm.doc.clearance_date);
    const left = frm.doc[spec.date_field]
      ? frappe.datetime.get_day_diff(frm.doc[spec.date_field], frappe.datetime.get_today())
      : null;

    let note = __('Day {0} since clearance.', [elapsed]);
    if (left !== null) {
      note += ' ' + (left < 0
        ? __('{0} days OVERDUE.', [Math.abs(left)])
        : __('{0} days left.', [left]));
    }

    if (elapsed >= spec.late) {
      input.css({ 'background-color': '#FEE2E2', 'color': '#B91C1C', 'font-weight': '700' });
    } else if (elapsed >= spec.warn) {
      input.css({ 'background-color': '#FEF3C7', 'color': '#92400E', 'font-weight': '600' });
    }
    frm.set_df_property(spec.date_field, 'description', note);
  });
}
