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

ONE TRACKER PER JOB. Job Tracker used to be an event log with one DOCUMENT per
event, which is how 84 jobs grew 371 trackers. The events are now child rows in
`fps_updates` (FPS Job Update), and the tracker is the job. log_update() below
is the single supported way to add one from the interface.

The Job Tracker itself is still not created here: the "JO Emit Opened" server
script opens it on Job Order insert together with the OPENED milestone the
rollup keys off. A second creator would double every job.
"""

import frappe

JOB_TRACKER = "Job Tracker"
CUSTOMS_TRACKER = "Customs Tracker"
UPDATES = "fps_updates"

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


def get_tracker(job_order, create=True):
    """The ONE Job Tracker for a job. Opens it if it is somehow missing.

    The exact-name check comes first, and it is not just a shortcut. If two
    events for the same job ever race and both open a tracker, the autoname hook
    gives the second one "<canonical name>-2". Asking for the canonical name
    directly means every later caller converges on the SAME tracker, instead of
    splitting the job's history across two -- which a filter query, whose row
    order is not defined, could otherwise do.
    """
    canonical = tracker_name_for(JOB_TRACKER, job_order)
    if canonical and frappe.db.exists(JOB_TRACKER, canonical):
        return canonical

    name = frappe.db.get_value(
        JOB_TRACKER, {"job_order": job_order}, "name", order_by="creation asc"
    )
    if name or not create:
        return name

    job = frappe.db.get_value(
        "Job Order", job_order, ["customer", "jo_date"], as_dict=True
    ) or {}
    tracker = frappe.get_doc({
        "doctype": JOB_TRACKER,
        "job_order": job_order,
        "customer": job.get("customer"),
        "track_date": job.get("jo_date") or frappe.utils.today(),
    })
    tracker.insert(ignore_permissions=True)
    return tracker.name


@frappe.whitelist()
def log_update(job_order, track_date=None, milestone=None, note=None,
               evidence=None, next_action=None, follow_up_date=None,
               customer_visible=1, internal=None):
    """Add one dated update to a job's tracker. The only supported way in.

    Permission is the caller's own: this writes a Job Tracker, so whoever calls
    it needs write on Job Tracker. No ignore_permissions on the save.
    """
    if not job_order:
        frappe.throw(frappe._("A job order is required to log an update."))

    frappe.has_permission(JOB_TRACKER, "write", throw=True)

    name = get_tracker(job_order)
    tracker = frappe.get_doc(JOB_TRACKER, name)

    is_issue = milestone == "HOLD"
    track_date = track_date or frappe.utils.today()
    status_line = (note or "")[:140]

    tracker.append(UPDATES, {
        "update_date": track_date,
        "event_type": "Issue" if is_issue else ("Milestone" if milestone else "Note"),
        "milestone": milestone or None,
        "status_line": status_line,
        "notes": note,
        "issues": internal,
        "evidence_ref": evidence,
        "source": "Manual",
        "customer_visible": 0 if is_issue else frappe.utils.cint(customer_visible),
        "next_action": next_action,
        "follow_up_date": follow_up_date,
        "responsible": frappe.session.user,
        "leg": 1,
    })

    # The parent carries the LATEST update, so the list still reads as "where
    # has this job reached". progress_notes is left alone on purpose -- it holds
    # the job's original hand-written summary, which a one-line status must not
    # overwrite.
    tracker.track_date = track_date
    tracker.fps_event_type = "Issue" if is_issue else ("Milestone" if milestone else "Note")
    tracker.fps_milestone = milestone or None
    tracker.current_status = status_line
    tracker.fps_evidence_ref = evidence
    tracker.fps_source = "Manual"
    if next_action:
        tracker.next_action = next_action
    if follow_up_date:
        tracker.follow_up_date = follow_up_date

    # Saving is what triggers JT Rollup, which re-derives the Job Order's stage,
    # progress, next action and checklist from this update.
    tracker.save()
    return tracker.name


@frappe.whitelist()
def rebuild(job_order):
    """Re-derive a job from its documents, without logging anything.

    Saving the tracker is the trigger; JT Rollup does the work. The old
    "Rebuild checklist" button inserted a throwaway Job Tracker document to
    achieve this, and 174 of those rows had to be deleted afterwards.
    """
    if not job_order:
        frappe.throw(frappe._("A job order is required."))

    frappe.has_permission(JOB_TRACKER, "write", throw=True)

    name = get_tracker(job_order)
    frappe.get_doc(JOB_TRACKER, name).save()
    return name
