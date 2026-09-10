"""Tracker creation and numbering, driven off the Job Order.

Two jobs, wired through doc_events in hooks.py:

1. NUMBERING -- an `autoname` hook on both tracker doctypes. Whatever creates a
   tracker (the JO Emit Opened server script, this module, or a user clicking
   New), it is numbered after the job order it belongs to:

       FPS/JO/2607/018  ->  FPS/JT/2607/018  /  FPS/CT/2607/018

   A job legitimately has more than one tracker -- Job Tracker is an event log,
   and Customs Tracker is per customs leg -- so the second and later rows take
   -2, -3 and so on. Numbering here rather than in the creating code means every
   route in gets the same names, including manual entry.

2. CREATION -- the Customs Tracker is raised automatically when the job order
   says customs clearance is in scope.

   The Job Tracker is deliberately NOT created here. The existing "JO Emit
   Opened" server script already opens one on every Job Order insert, with the
   OPENED milestone that the rollup engine keys off. Adding a second creator
   would double every job.
"""

import frappe

JOB_TRACKER = "Job Tracker"
CUSTOMS_TRACKER = "Customs Tracker"

SERIES = {
    JOB_TRACKER: "FPS/JT/",
    CUSTOMS_TRACKER: "FPS/CT/",
}

NAMING_SERIES = {
    JOB_TRACKER: "FPS/JT/.YY..MM./.###",
    CUSTOMS_TRACKER: "FPS/CT/.YY..MM./.###",
}

# The scopes of work that mean this job is tracked. General-job-only work is the
# one case with nothing to follow.
TRACKED_SOW = (
    "fps_svc_freight",
    "fps_svc_clearance",
    "fps_svc_transport",
    "fps_svc_crossborder",
)


def job_order_tail(job_order):
    """FPS/JO/2607/018 -> 2607/018 . None if the name is not that shape."""
    parts = (job_order or "").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else None


def name_from_job_order(doc, method=None):
    """autoname hook: number a tracker after its job order.

    Setting flags.name_set tells Frappe the name is decided, so the naming
    series is left alone rather than burning a counter it will never use.
    """
    prefix = SERIES.get(doc.doctype)
    if not prefix:
        return

    tail = job_order_tail(doc.get("job_order"))
    if not tail:
        # No job order to derive from -- let the naming series do its usual job.
        return

    base = prefix + tail
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
            "naming_series": NAMING_SERIES[CUSTOMS_TRACKER],
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
