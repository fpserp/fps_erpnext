"""Rename every tracker so its number matches the Job Order it belongs to.

    FPS/JO/2607/018  ->  FPS/JT/2607/018   (job tracker)
                     ->  FPS/CT/2607/018   (customs tracker)

NO DATA IS DELETED. frappe.rename_doc moves the record and repoints every link,
comment, version and attachment; nothing is dropped and no field is cleared.

WHY SOME NAMES CARRY A SUFFIX
A job legitimately has MANY tracker rows -- Job Update Log is an event log, and
FPS/JO/2607/018 alone has seven. Seven records cannot share one name, so the
oldest takes the clean number and the rest are suffixed in creation order:

    FPS/JT/2607/018, FPS/JT/2607/018-2 ... -7

Customs Tracker is per-LEG, and four jobs have two legs (2607/020, 2607/025,
2607/027, 2608/065), so those get -2 the same way. Everything stays readable as
"this belongs to job 2607/018", which is the point.

TWO PHASES, BECAUSE THE TARGETS ARE OCCUPIED
Current numbering is genuinely out of step -- FPS/CT/2607/023 belongs to
FPS/JO/2606/009 -- so a target name is often already taken by a DIFFERENT
record. Renaming in place would collide part-way through and leave the data
half-migrated. Every record that needs to move goes to a temporary name first,
then to its final one, so no two records ever contend for a name.

Re-running is safe: anything already at its target is skipped.

KEEP THE rename_doc CALLS MINIMAL. The deployed Frappe (16.24.1) does not accept
ignore_permissions on rename_doc -- passing it raised
"TypeError: rename_doc() got an unexpected keyword argument 'ignore_permissions'"
and took the whole migrate down. The version-16 branch does accept it, so the
branch source is NOT a safe guide to what is running. Only `force` is passed
here; patches already run as Administrator, so there is no permission to bypass.
"""

import frappe

# Customs Tracker ONLY for now.
#
# Job Tracker is deliberately left alone: the one-tracker-per-job restructure
# collapses its ~371 rows into ~84 parents, so renumbering them here would hand
# out -2 .. -7 suffixes that the very next deploy deletes again. Once there is
# exactly one tracker per job the naming is clean with no suffix at all
# (FPS/JO/2607/018 -> FPS/JT/2607/018), and that restructure does it in one pass.
#
# Customs Tracker is genuinely per customs leg, so its numbering is unaffected by
# that work and is wanted now. Four jobs have two legs and take -2.
TRACKERS = (
    # (doctype, prefix, link fieldname, ordering for the suffix sequence)
    ("Customs Tracker", "FPS/CT/", "job_order", "fps_leg asc, creation asc"),
)


def execute():
    for doctype, prefix, link_field, order_by in TRACKERS:
        if not frappe.db.exists("DocType", doctype):
            continue
        _renumber(doctype, prefix, link_field, order_by)
    frappe.clear_cache()


def _tail(job_order):
    """FPS/JO/2607/018 -> 2607/018 . Returns None if the name is not that shape."""
    parts = (job_order or "").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else None


def _renumber(doctype, prefix, link_field, order_by):
    rows = frappe.get_all(
        doctype,
        fields=["name", link_field],
        filters={link_field: ["is", "set"]},
        order_by=order_by,
        limit_page_length=0,
    )

    # Build the target for every row first, so the suffix sequence is decided
    # before anything moves.
    targets = {}
    seen = {}
    for row in rows:
        tail = _tail(row.get(link_field))
        if not tail:
            continue
        seen[tail] = seen.get(tail, 0) + 1
        n = seen[tail]
        targets[row["name"]] = prefix + tail + ("" if n == 1 else "-%d" % n)

    moving = {old: new for old, new in targets.items() if old != new}
    if not moving:
        return

    # Phase 1 -- park every mover on a name nothing can want.
    parked = {}
    for i, old in enumerate(sorted(moving), start=1):
        tmp = "%sTMP-%d" % (prefix, i)
        while frappe.db.exists(doctype, tmp):
            i += 1
            tmp = "%sTMP-%d" % (prefix, i)
        frappe.rename_doc(doctype, old, tmp, force=True)
        parked[tmp] = moving[old]

    # Phase 2 -- every target is free now.
    for tmp, final in parked.items():
        frappe.rename_doc(doctype, tmp, final, force=True)
