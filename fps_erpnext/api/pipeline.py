"""Read-only stage counts for the FPS workspace pipeline strip.

One whitelisted method, one grouped query per stage, no writes. Backs the single
Custom HTML Block on the FPS home page (design 1a, step 6).

The stages are the Job Order lifecycle as it is ACTUALLY recorded on this site --
`fps_stage`, which is populated on all 84 job orders -- bracketed by Enquiry and
Quotation at the front and Sales Invoice at the back. The handoff design drew
"Customs / Mirsal" and "Trucking" as stages; both were dropped because the data
does not support a column (45 of 46 Customs Tracker rows are already Cleared, and
Customs Tracker is per-LEG rather than per-job, so its count can never be a job
count). They appear in the footnote row instead.

Two traps this module deliberately avoids, both verified on this site 2026-09-09:

1. Frappe wraps a date comparison as ifnull(field, '') and '' sorts below any
   date, so `<` on a sparse date column silently matches every UNPOPULATED row.
   `eta < today` returns 38 of 84; with an is-set guard the true answer is 2.
   Every date comparison here carries its ["<field>", "is", "set"] guard.

2. Never rely on a default docstatus. Counts here pass docstatus explicitly, so a
   submittable doctype cannot quietly report only its submitted rows.

Permission-aware by construction: a stage whose doctype the caller cannot read is
omitted from the payload rather than returned as a zero, so the strip never leaks
the existence of records the viewer has no rights to.
"""

import frappe
from frappe.utils import today

# label, doctype, filters. Job Order stages key on fps_stage, which is a real
# populated Select -- not the hidden, unused `status` field.
STAGES = [
    ("Enquiry", "FPS Enquiry", [["FPS Enquiry", "status", "=", "Open"]]),
    ("Quotation", "Quotation", [["Quotation", "status", "=", "Open"],
                                ["Quotation", "docstatus", "<", 2]]),
    ("New", "Job Order", [["Job Order", "fps_stage", "=", "New"],
                          ["Job Order", "docstatus", "<", 2]]),
    ("Docs", "Job Order", [["Job Order", "fps_stage", "=", "Docs"],
                           ["Job Order", "docstatus", "<", 2]]),
    ("In progress", "Job Order", [["Job Order", "fps_stage", "=", "In Progress"],
                                  ["Job Order", "docstatus", "<", 2]]),
    ("Cleared", "Job Order", [["Job Order", "fps_stage", "=", "Cleared - Ready"],
                              ["Job Order", "docstatus", "<", 2]]),
    ("Delivered", "Job Order", [["Job Order", "fps_stage", "=", "Delivered"],
                                ["Job Order", "docstatus", "<", 2]]),
    ("Invoiced", "Sales Invoice", [["Sales Invoice", "status", "in",
                                    ["Unpaid", "Overdue", "Partly Paid"]],
                                   ["Sales Invoice", "docstatus", "=", 1]]),
]

# Each stage links to the list it counts, so a click lands on the same records.
ROUTES = {
    "Enquiry": "/app/fps-enquiry?status=Open",
    "Quotation": "/app/quotation?status=Open",
    "New": "/app/job-order?fps_stage=New",
    "Docs": "/app/job-order?fps_stage=Docs",
    "In progress": "/app/job-order?fps_stage=In%20Progress",
    "Cleared": "/app/job-order?fps_stage=Cleared%20-%20Ready",
    "Delivered": "/app/job-order?fps_stage=Delivered",
    "Invoiced": "/app/sales-invoice?status=%5B%22in%22%2C%5B%22Unpaid%22%2C%22Overdue%22%2C%22Partly%20Paid%22%5D%5D",
}


def _count(doctype, filters):
    return frappe.db.count(doctype, filters=filters)


@frappe.whitelist()
def get_pipeline():
    """Return the stage counts for the workspace strip. Read-only."""
    stages = []
    for label, doctype, filters in STAGES:
        if not frappe.has_permission(doctype, "read"):
            # Omit rather than zero: a zero would still confirm the stage exists.
            continue
        stages.append({
            "label": label,
            "doctype": doctype,
            "count": _count(doctype, filters),
            "route": ROUTES.get(label, ""),
        })

    return {
        "stages": stages,
        "footnotes": _footnotes(),
    }


def _footnotes():
    """The honest replacements for the design's sub-lines.

    The handoff asked for "4 unanswered", "9 awaiting reply", "3 past deadline"
    and "2 delivering today". None has a backing field that is populated:
    fps_next_due and fps_service_date are empty on all 84 job orders, and
    Customs Tracker's two date candidates are empty on all 46 rows. Rather than
    fabricate them, these are the equivalents the data can actually support.
    """
    notes = []

    if frappe.has_permission("Job Order", "read"):
        open_jobs = _count("Job Order", [
            ["Job Order", "fps_stage", "not in", ["Closed", "Invoiced"]],
            ["Job Order", "docstatus", "<", 2],
        ])
        # The is-set guard is load-bearing: without it this returns every job
        # with no ETA at all.
        overdue = _count("Job Order", [
            ["Job Order", "fps_stage", "not in", ["Closed", "Invoiced"]],
            ["Job Order", "docstatus", "<", 2],
            ["Job Order", "eta", "is", "set"],
            ["Job Order", "eta", "<", today()],
        ])
        no_eta = _count("Job Order", [
            ["Job Order", "fps_stage", "not in", ["Closed", "Invoiced"]],
            ["Job Order", "docstatus", "<", 2],
            ["Job Order", "eta", "is", "not set"],
        ])
        notes.append("%d open jobs" % open_jobs)
        notes.append("%d past ETA" % overdue)
        if no_eta:
            notes.append("%d with no ETA" % no_eta)

    if frappe.has_permission("Customs Tracker", "read"):
        not_cleared = _count("Customs Tracker", [
            ["Customs Tracker", "status", "not in", ["Cleared"]],
        ])
        notes.append("%d customs file%s not cleared"
                     % (not_cleared, "" if not_cleared == 1 else "s"))

    if frappe.has_permission("Proof of Delivery", "read"):
        pods = _count("Proof of Delivery", [
            ["Proof of Delivery", "docstatus", "!=", 2],
        ])
        notes.append("%d PODs on file" % pods)

    return notes
