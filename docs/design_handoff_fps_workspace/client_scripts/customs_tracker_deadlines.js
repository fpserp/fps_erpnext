// Customs Tracker: colour the two chase clocks on the form.
//
// THE RULES ARE DEFINED IN fps_erpnext/api/customs_clock.py AND REPEATED HERE.
// That duplication is deliberate and is the only copy: a form has to recolour
// itself the instant someone changes a date or picks "Completed", and a server
// round trip on every keystroke to fetch a few constants would be a worse trade
// than repeating them in two files. If you change them, change both.
//
//   Doc submission   due declaration (BOE date) + 30   amber from day 15, red from day 25
//   MOFA attestation due clearance + 14                amber from day  9, red from day 12
//
// The doc deadline is Dubai Customs' fine start date (Agam, 16 Sep 2026): fines
// run from that day, included, at AED 5 a day, so the originals must be in the
// day before. A cleared declaration with no BOE date counts from clearance.
// Days are counted from the same date the deadline counts from, and only once a
// declaration has cleared (a clearance date, or status Cleared).
//
// The tracker's two dates belong to its Declarations rows, so the colour comes
// from the outstanding row whose clock started first -- the row the tracker's
// date came from. A tracker with no rows is its own declaration.

frappe.ui.form.on('Customs Tracker', {
  refresh: fps_paint_deadlines,
  ct_date: fps_paint_deadlines,
  clearance_date: fps_paint_deadlines,
  status: fps_paint_deadlines,
  fps_doc_submission: fps_paint_deadlines,
  fps_mofa_status: fps_paint_deadlines,
});

const FPS_DEADLINES = [
  { key: 'doc', date_field: 'fps_doc_deadline', status_field: 'fps_doc_submission',
    from: ['ct_date', 'clearance_date'], warn: 15, late: 25 },
  { key: 'mofa', date_field: 'fps_mofa_deadline', status_field: 'fps_mofa_status',
    from: ['clearance_date'], warn: 9, late: 12 },
];

// "Submitted" is the old wording for Completed on document submission. Kept so
// any row that missed the migration still reads as finished rather than overdue.
const FPS_DONE = ['completed', 'not applicable', 'n/a', 'submitted'];

function fps_is_done(value) {
  return FPS_DONE.includes((value || '').trim().toLowerCase());
}

// { date, field } this clock counts from on one declaration, or null.
function fps_clock_start(rec, spec) {
  const cleared = !!rec.clearance_date
    || (rec.status || '').trim().toLowerCase() === 'cleared';
  if (!cleared) return null;
  for (const field of spec.from) {
    if (rec[field]) return { date: rec[field], field: field };
  }
  return null;
}

function fps_tracker_start(frm, spec) {
  const rows = frm.doc.fps_declarations || [];
  if (!rows.length) return fps_clock_start(frm.doc, spec);
  let first = null;
  rows.forEach(row => {
    if (fps_is_done(row[spec.status_field])) return;
    const start = fps_clock_start(row, spec);
    if (start && (!first || start.date < first.date)) first = start;
  });
  return first;
}

function fps_paint_deadlines(frm) {
  FPS_DEADLINES.forEach(spec => {
    const field = frm.get_field(spec.date_field);
    if (!field || !field.$wrapper) return;

    const input = field.$wrapper.find('.control-value, input');
    input.css({ 'background-color': '', 'color': '', 'font-weight': '' });
    frm.set_df_property(spec.date_field, 'description', '');

    if (fps_is_done(frm.doc[spec.status_field])) {
      frm.set_df_property(spec.date_field, 'description', __('Done — nothing to chase.'));
      return;
    }
    const start = fps_tracker_start(frm, spec);
    if (!start) {
      frm.set_df_property(spec.date_field, 'description',
        __('No cleared declaration yet, so no deadline is running.'));
      return;
    }

    const today = frappe.datetime.get_today();
    const elapsed = frappe.datetime.get_day_diff(today, start.date);
    const left = frm.doc[spec.date_field]
      ? frappe.datetime.get_day_diff(frm.doc[spec.date_field], today)
      : null;

    let note = start.field === 'ct_date'
      ? __('Day {0} since declaration.', [elapsed])
      : __('Day {0} since clearance.', [elapsed]);
    if (left !== null) {
      if (spec.key === 'doc') {
        // The deadline is the first fine day, not the last free one.
        note += ' ' + (left <= 0
          ? __('Dubai Customs fines running: {0} day(s) at AED 5 a day.', [1 - left])
          : __('{0} day(s) left before fines start.', [left]));
      } else {
        note += ' ' + (left < 0
          ? __('{0} days OVERDUE.', [Math.abs(left)])
          : __('{0} days left.', [left]));
      }
    }

    if (elapsed >= spec.late) {
      input.css({ 'background-color': '#FEE2E2', 'color': '#B91C1C', 'font-weight': '700' });
    } else if (elapsed >= spec.warn) {
      input.css({ 'background-color': '#FEF3C7', 'color': '#92400E', 'font-weight': '600' });
    }
    frm.set_df_property(spec.date_field, 'description', note);
  });
}
