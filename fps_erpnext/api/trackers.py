"""Tracker naming, creation and updates, all driven off the Job Order.

NAMING. A tracker carries its OWN prefix and its job order's number:

    Job Order       FPS/JO/2607/018
    Job Tracker     FPS/JT/2607/018      <- same tail, its own prefix
    Customs Tracker FPS/CT/2607/018      <- likewise

Only the prefix differs. The year-month and the serial are the job order's, so
a tracker and its job always share a tail and reading one tells you the other.

This briefly went the other way. On 2026-09-10 the trackers were renamed to the
job order's name outright, on the reasoning that the job number is the only
number anyone says out loud. Seeing it live, the prefix was wanted back: with
three doctypes sharing one string, a bare "2607/018" no longer said WHICH record
was meant in an email or over the phone. The prefix does that job for free, and
it costs nothing, because the tail still matches.

Job Tracker is exactly one per job, so it never needs a suffix. Customs Tracker
is per customs LEG and four jobs clear in two legs, so those take -2. That is
honest: they really are two declarations.

JOB TRACKER ITSELF IS RETIRED, NOT DELETED. It used to be an event log with one
DOCUMENT per event (84 jobs grew 371 trackers), then briefly one document per
job with its events as child rows. Both stages are done: the update log is now
`fps_updates`, a Table field directly on JOB ORDER, and the derivation that
reads it lives in fps_erpnext.api.jobs (rollup(), log_update(), rebuild()) --
see that module for why the trigger had to be the child table's own
after_insert rather than anything on Job Order's own save. The 90 Job Tracker
documents that existed when this changed are left exactly as they are, a frozen
historical record; nothing here creates a new one.

This module now only does what genuinely differs by doctype: tracker NAMING
(still used by Customs Tracker, and left in place for Job Tracker in case one
is ever created by hand) and raising the Customs Tracker automatically.
"""

import frappe

JOB_TRACKER = "Job Tracker"
CUSTOMS_TRACKER = "Customs Tracker"

TRACKERS = (JOB_TRACKER, CUSTOMS_TRACKER)

# Prefix per tracker doctype. The rest of the name is the job order's tail.
SERIES = {
    JOB_TRACKER: "FPS/JT/",
    CUSTOMS_TRACKER: "FPS/CT/",
}

# The scopes of work that mean this job is tracked. General-job-only work is the
# one case with nothing to follow.
TRACKED_SOW = (
    "fps_svc_freight",
    "fps_svc_clearance",
    "fps_svc_transport",
    "fps_svc_crossborder",
)


def tracker_name_for(doctype, job_order):
    """FPS/JO/2607/018 -> FPS/JT/2607/018 (or FPS/CT/...). None if not derivable.

    Only the PREFIX differs from the job order; the year-month and the serial are
    the job order's own, so a tracker and its job always carry the same tail.
    """
    prefix = SERIES.get(doctype)
    parts = (job_order or "").split("/")
    if not prefix or len(parts) < 2:
        return None
    return prefix + "/".join(parts[-2:])


def name_from_job_order(doc, method=None):
    """autoname hook: the tracker is numbered after its job order, under its own prefix.

    Setting flags.name_set tells Frappe the name is decided, so the naming
    series is left alone rather than burning a counter it will never use.

    THIS HOOK ONLY RUNS IF NO DOCUMENT NAMING RULE CLAIMS THE DOCTYPE FIRST.
    Frappe's set_new_name() calls set_naming_from_document_naming_rule(doc)
    BEFORE doc.run_method("autoname"), and only reaches the autoname event
    `if not doc.name`. The site had enabled rules for both trackers, which is
    why this hook silently never fired between 2026-09-10 and the deploy that
    added name_trackers_after_job_order -- that patch disables them. If a
    tracker ever starts coming out as FPS/JT/#### again, look for a re-enabled
    Document Naming Rule before looking at this function.
    """
    if doc.doctype not in TRACKERS:
        return

    base = tracker_name_for(doc.doctype, doc.get("job_order"))
    if not base:
        # Nothing to derive from -- let the naming series do its usual job
        # rather than inventing something.
        return

    name = base
    n = 1
    while frappe.db.exists(doc.doctype, name):
        n += 1
        name = "%s-%d" % (base, n)

    doc.name = name
    doc.flags.name_set = True


def on_job_order_created(doc, method=None):
    """Raise the Customs Tracker when the job includes customs clearance."""
    if not doc.get("fps_svc_clearance"):
        return
    if frappe.db.exists(CUSTOMS_TRACKER, {"job_order": doc.name}):
        return

    try:
        tracker = frappe.get_doc({
            "doctype": CUSTOMS_TRACKER,
            "job_order": doc.name,
            "customer": doc.get("customer"),
            "ct_date": doc.get("jo_date") or frappe.utils.today(),
            "status": "Pending",
            "fps_leg": 1,
            "fps_clearance_location": doc.get("fps_clearance_location"),
            "fps_clearance_type": doc.get("fps_clearance_type"),
        })
        tracker.insert(ignore_permissions=True)
    except Exception:
        # A tracker that fails to open must never block the job order itself.
        frappe.log_error(title="FPS: auto Customs Tracker for %s" % doc.name)


def is_tracked(doc):
    """True when any scope of work on this job is one we follow."""
    return any(doc.get(f) for f in TRACKED_SOW)


# get_tracker() / log_update() / rebuild() used to live here, operating on a
# separate Job Tracker document. Their replacements -- log_update() and
# rebuild(), now writing directly onto Job Order.fps_updates -- are in
# fps_erpnext.api.jobs, alongside the derivation (rollup()) that reads what
# they write. Nothing in the app calls the versions that were here; the "Log
# update" / "Rebuild checklist" buttons on the Job Order form call the jobs.py
# ones directly.
