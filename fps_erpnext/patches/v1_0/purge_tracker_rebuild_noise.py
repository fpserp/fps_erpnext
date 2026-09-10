"""Delete the tracker rows that record nothing but a rebuild of the tracker.

The go-live on 2026-09-09 left 258 of the 629 tracker rows carrying no history
at all -- 174 stamped ":rebuild:" and 84 ":tracker-enabled". They say "Checklist
rebuilt", carry no milestone, and exist only because the derivation engine was
re-run three times that morning. FPS/JO/2607/018 has four of them.

These are safe to remove because the engine ALREADY discards them. In the rollup
body:

    real_evs = [e for e in evs if not (
        (e.fps_evidence_ref or "").endswith(":tracker-enabled")
        or ":rebuild:" in (e.fps_evidence_ref or ""))]

and they carry an empty fps_milestone, so they contribute nothing to the
milestone map either. Deleting them changes no derived stage, progress, next
action or last update.

WHAT IS DELIBERATELY KEPT
Everything with real content. The remaining 371 rows are distinct facts -- one
job's log holds "Job opened", "Vehicle 1222-KSA-XBA assigned" and "Invoice
FPS/INV/2607/031 issued" as three separate entries, each with its own evidence
reference. There is no single row that carries all of a job's information, so
collapsing to one row per job would throw history away. The rolled-up single
view already exists on the Job Order itself: fps_stage, fps_progress,
fps_milestone_state and fps_last_update.

Rows go through frappe.delete_doc, so each is archived to Deleted Document and
can be restored. Nothing is force-deleted.

Job Tracker naming is NOT done here. The one-tracker-per-job restructure
collapses these rows into a single parent per job, and names them then -- one
clean name each, no suffixes.
"""

import frappe

DOCTYPES = ("Job Tracker", "Job Update Log")  # renamed part-way through this series

NOISE = (
    ("fps_evidence_ref", "like", "%:rebuild:%"),
    ("fps_evidence_ref", "like", "%:tracker-enabled"),
)


def execute():
    doctype = next((d for d in DOCTYPES if frappe.db.exists("DocType", d)), None)
    if not doctype:
        return

    deleted = 0
    for field, op, pattern in NOISE:
        for name in frappe.get_all(doctype, filters={field: [op, pattern]}, pluck="name"):
            try:
                # No force, no delete_permanently: each row lands in Deleted
                # Document so it can be restored if this was ever wrong.
                frappe.delete_doc(doctype, name, ignore_permissions=True,
                                  ignore_missing=True)
                deleted += 1
            except Exception:
                frappe.log_error(title="FPS: could not purge tracker row %s" % name)

    if deleted:
        frappe.db.commit()

    # No renumbering pass here. Job Tracker naming is deferred to the
    # one-tracker-per-job restructure, which collapses these rows into one parent
    # per job and names them cleanly in a single sweep.
    frappe.clear_cache()
