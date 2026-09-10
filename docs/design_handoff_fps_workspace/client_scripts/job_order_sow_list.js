// Job Order - SOW List (List view): colour by tracker stage, red OVERDUE when the next action date has passed.
frappe.listview_settings['Job Order'] = Object.assign(frappe.listview_settings['Job Order'] || {}, {
  has_indicator_for_draft: true,
  // ONLY what get_indicator below actually reads.
  //
  // Every fieldname listed here is fetched with the list, and the REPORT view
  // turns each fetched field into a column -- which is how an empty
  // "Next action due" column ended up sitting next to "Next action", and a
  // stray "On hold reason" next to it. Neither was ever asked for.
  //
  // fps_next_due is empty on all 84 job orders, so the overdue branch below is
  // inert today. Put 'fps_next_due' back in this list on the day something
  // starts writing it -- and accept the extra column that comes with it.
  add_fields: ['fps_stage', 'docstatus'],
  get_indicator(doc) {
    const colors = { 'New': 'gray', 'Docs received': 'orange', 'In Progress': 'blue', 'Cleared - Ready': 'cyan', 'Delivered': 'green', 'Invoiced': 'darkgrey', 'Closed': 'light-gray', 'On Hold': 'red' };
    if (doc.docstatus === 2) return [__('Cancelled'), 'red', 'docstatus,=,2'];
    const stage = doc.fps_stage || 'New';
    const overdue = doc.fps_next_due && frappe.datetime.get_diff(frappe.datetime.get_today(), doc.fps_next_due) > 0 && !['Closed', 'Invoiced'].includes(stage);
    if (overdue) return [__('OVERDUE · ') + __(stage), 'red', 'fps_stage,=,' + stage];
    return [__(stage), colors[stage] || 'gray', 'fps_stage,=,' + stage];
  },
});
