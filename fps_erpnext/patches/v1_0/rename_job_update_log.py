"""Rename the DocType "Job Update Log" to "Job Tracker".

The doctype is the per-job event log the whole tracker is built on; "Job Update
Log" was never the name anyone used for it out loud.

frappe.rename_doc on a DocType renames the table and repoints every Link field
that targets it, so the 629 records, their Custom DocPerm rows, the Client
Script's `dt` and the Server Scripts' `reference_doctype` all follow on their
own. NO RECORD IS DELETED and no field is cleared.

What rename_doc CANNOT follow is the doctype name written inside script bodies
as a plain string -- `frappe.get_all("Job Update Log", ...)` is just text to it.
Four of those exist and are fixed here by hand. Miss them and the rollup engine
raises on the next Job Update Log save, and the sweep on its */30 cron takes
every open job down with it.

Ordering matters: this runs AFTER match_tracker_numbers in patches.txt, so that
patch does its renumbering under the old name and this one moves the doctype
afterwards. Either order leaves the same result, but this way neither has to
know about the other.

Re-running is a no-op.
"""

import frappe

OLD = "Job Update Log"
NEW = "Job Tracker"

# Scripts that name the doctype as a string in their body.
SERVER_SCRIPTS = ("JT Rollup", "FPS Tracker Sweep", "JO Emit Opened",
                  "JT Fetch from Job Order")


def execute():
    _rename_doctype()
    _fix_script_bodies()
    frappe.clear_cache()


def _rename_doctype():
    if not frappe.db.exists("DocType", OLD):
        return
    if frappe.db.exists("DocType", NEW):
        # Already renamed, or something else claimed the name -- do not merge.
        return
    # Minimal kwargs on purpose -- see match_tracker_numbers for why.
    frappe.rename_doc("DocType", OLD, NEW, force=True)


def _fix_script_bodies():
    for name in SERVER_SCRIPTS:
        _replace("Server Script", name, "script")

    for name in frappe.get_all(
        "Client Script", filters={"script": ["like", "%" + OLD + "%"]}, pluck="name"
    ):
        _replace("Client Script", name, "script")


def _replace(doctype, name, field):
    if not frappe.db.exists(doctype, name):
        return
    value = frappe.db.get_value(doctype, name, field) or ""
    if OLD not in value:
        return
    frappe.db.set_value(
        doctype, name, field, value.replace(OLD, NEW), update_modified=False
    )
