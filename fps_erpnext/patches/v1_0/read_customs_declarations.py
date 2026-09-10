"""Point the derivation engine and the Create button at declarations, not sibling trackers.

customs_declarations moves every BOE into a row inside its job's Customs
Tracker. Two things still assume a job's declarations are separate DOCUMENTS,
and both change here in the same migration -- leave either behind and the four
merged jobs derive from one declaration instead of two.

1. JT Rollup and FPS Tracker Sweep

   Both fetch `cts` and then read c.status, c.boe_number, c.fps_clearance_type,
   c.fps_mofa_status and the rest to work out the FZ / Oman / final legs and the
   BOE, MOFA, DO, DUTY and CLEARED milestones. That body needs NO change,
   because the child fieldnames were chosen to match the tracker's exactly. Only
   the query moves -- from sibling Customs Trackers to the declaration rows of
   this job's tracker, which is what the engine always meant by "a declaration".

   frappe.get_all on a child doctype with a parenttype filter was PROVED to work
   in this site's own safe_exec sandbox before this was written.

2. Job Order - Create Buttons

   "Create -> Customs Tracker" counted the job's trackers and made another one at
   fps_leg = n + 1. That is precisely the behaviour being removed. It now opens
   the job's existing tracker, where the second BOE is a new row, and only
   creates one if the job has none.

Each replacement asserts on the exact text it expects. A script that has been
edited since is skipped and logged rather than half-rewritten.

Safe to re-run: once replaced, the old text is not there to match.
"""

import frappe

OLD_CTS = (
	'    cts = frappe.get_all("Customs Tracker", filters={"job_order": jo_name}, '
	'fields=["name", "status", "boe_number", "fps_leg", "fps_clearance_type", '
	'"fps_clearance_location", "fps_mofa_status", "fps_do_status", '
	'"fps_duty_paid_on", "clearance_date", "ct_date", "modified", "remarks"], '
	'order_by="ct_date asc, creation asc")'
)

NEW_CTS = (
	'    # One tracker per job; each BOE is a row in it. The field names match the\n'
	'    # tracker\'s, so everything below that reads c.status / c.boe_number /\n'
	'    # c.fps_clearance_type keeps working untouched.\n'
	'    ct_names = [c.name for c in frappe.get_all("Customs Tracker", '
	'filters={"job_order": jo_name}, fields=["name"])]\n'
	'    cts = frappe.get_all("FPS Customs Declaration", '
	'filters={"parenttype": "Customs Tracker", "parent": ["in", ct_names]}, '
	'fields=["name", "status", "boe_number", "fps_leg", "fps_clearance_type", '
	'"fps_clearance_location", "fps_mofa_status", "fps_do_status", '
	'"fps_duty_paid_on", "clearance_date", "ct_date", "modified", "remarks"], '
	'order_by="ct_date asc, idx asc") if ct_names else []'
)

ROLLUP_SCRIPTS = ("JT Rollup", "FPS Tracker Sweep")

OLD_CREATE_CT = """function create_ct_from_jo(frm) {
  frappe.db.count('Customs Tracker', {filters: {job_order: frm.doc.name}}).then(n => {
    create_doc_from_jo(frm, 'Customs Tracker', {ct_date: frappe.datetime.get_today(), status: 'Pending', fps_leg: (n || 0) + 1, fps_clearance_location: frm.doc.fps_clearance_location, fps_clearance_type: (n || 0) === 0 ? frm.doc.fps_clearance_type : null});
  });
}"""

NEW_CREATE_CT = """function create_ct_from_jo(frm) {
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
}"""

CREATE_BUTTONS = "Job Order - Create Buttons"


def execute():
	for name in ROLLUP_SCRIPTS:
		_replace("Server Script", name, OLD_CTS, NEW_CTS)
	_replace("Client Script", CREATE_BUTTONS, OLD_CREATE_CT, NEW_CREATE_CT)
	frappe.clear_cache()


def _replace(doctype, name, old, new):
	if not frappe.db.exists(doctype, name):
		frappe.log_error(title="FPS: %s %s missing, not repointed" % (doctype, name))
		return

	script = frappe.db.get_value(doctype, name, "script") or ""
	if new in script:
		return
	if old not in script:
		# Edited since, or already changed another way. Do not guess at it.
		frappe.log_error(
			title="FPS: %s %s does not match, not repointed" % (doctype, name)
		)
		return

	frappe.db.set_value(doctype, name, "script", script.replace(old, new),
	                    update_modified=False)
