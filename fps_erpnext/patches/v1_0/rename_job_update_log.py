"""Rename the DocType "Job Update Log" to "Job Tracker".

The doctype is the per-job event log the whole tracker is built on; "Job Update
Log" was never the name anyone used for it out loud.

frappe.rename_doc on a DocType renames the table and repoints every Link field
that targets it, so the 629 records, their Custom DocPerm rows, the Client
Script's `dt` and the Server Scripts' `reference_doctype` all follow on their
own. NO RECORD IS DELETED and no field is cleared.

What rename_doc CANNOT follow is the doctype name written inside a script body
as a plain string -- frappe.get_all("Job Update Log", ...) is just text to it.

EVERY SCRIPT IS FOUND BY SEARCHING, NEVER BY A HARD-CODED LIST.
An earlier version of this patch named four scripts by hand and got it badly
wrong. One of the four ("JT Fetch from Job Order") does not contain the string at
all, and SIX that do were missed: POD Events (Save), POD Events (Submit),
POD Events (Cancel), SI Events (Submit), SI Events (Cancel) and
CT BOE to Job Order. Each references the doctype twice -- once in a
frappe.db.exists() guard and once in the {"doctype": ...} insert.

That would have been silent and severe. frappe.db.exists() on a doctype that no
longer exists raises DoesNotExistError, and every one of those scripts wraps its
body in `except Exception: frappe.log_error(...)`. So after the rename they would
keep "succeeding" while recording nothing: VEHICLE, PICKED_UP, DELIVERED, HOLD,
INVOICED, BOE, MOFA, DO, DUTY, CLEARED and the rest would all stop being written,
leaving only OPENED. Worse, the aborts are partial -- CT BOE to Job Order has
already written boe_no, clearance_date and fps_svc_clearance onto the Job Order
before its first emit() throws, and POD Events has already set
fps_svc_transport=1 before the VEHICLE emit throws. Half-applied side effects,
no error surfaced, and the derived stage on every job quietly rotting from there.

Searching for the string cannot miss a script, and cannot go stale when someone
adds an eighth one.

Re-running is a no-op.
"""

import frappe

OLD = "Job Update Log"
NEW = "Job Tracker"

# Doctypes whose records embed the name as text rather than as a Link.
SCRIPT_DOCTYPES = ("Server Script", "Client Script")


def execute():
    _rename_doctype()
    _fix_script_bodies()
    _fix_reference_links()
    frappe.clear_cache()


def _rename_doctype():
    if not frappe.db.exists("DocType", OLD):
        return
    if frappe.db.exists("DocType", NEW):
        # Already renamed, or something else claimed the name -- do not merge.
        return
    # Minimal kwargs on purpose: the deployed Frappe (16.24.1) rejects
    # ignore_permissions/show_alert on rename_doc, and patches already run as
    # Administrator so there is nothing to bypass.
    frappe.rename_doc("DocType", OLD, NEW, force=True)


def _fix_script_bodies():
    """Repoint every script that names the doctype as a string. Search, do not list."""
    for doctype in SCRIPT_DOCTYPES:
        for name in frappe.get_all(
            doctype, filters={"script": ["like", "%" + OLD + "%"]}, pluck="name"
        ):
            script = frappe.db.get_value(doctype, name, "script") or ""
            if OLD not in script:
                continue
            frappe.db.set_value(
                doctype, name, "script", script.replace(OLD, NEW),
                update_modified=False,
            )


def _fix_reference_links():
    """Belt and braces: rename_doc should have moved these, so this is a no-op."""
    for doctype, field in (("Server Script", "reference_doctype"),
                           ("Client Script", "dt")):
        for name in frappe.get_all(doctype, filters={field: OLD}, pluck="name"):
            frappe.db.set_value(doctype, name, field, NEW, update_modified=False)
