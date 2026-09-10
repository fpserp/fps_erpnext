"""Rename the Job Order stage "Docs" to "Docs received", everywhere it is written.

The value is not just a label on a dropdown -- it is derived and re-derived by a
scheduler. Renaming it in one place only would look fixed for at most 30 minutes.
Every writer and reader found on the site 2026-09-10:

  1. Job Order.fps_stage    the Select options
  2. Job Order rows         8 records currently sitting at "Docs"
  3. Kanban Board column    "FPS Job Tracker" -> column_name, holding those 8
  4. Server Script          "JT Rollup"        -> `stage = "Docs"`
  5. Server Script          "FPS Tracker Sweep" -> the same rollup body, on a
                            */30 cron over every open job. Miss this one and it
                            rewrites "Docs" onto all 8 within half an hour.
  6. Report                 "FPS Open Jobs by SOW" -> ORDER BY FIELD(... 'Docs' ...)

The app-side references (fps_erpnext/api/pipeline.py and the Job Tracker block)
ship in the same commit.

Safe to re-run: every step is a no-op once applied. In the server scripts only
the exact title-case token `stage = "Docs"` is replaced -- the milestone codes
"DOCS" and "DOCS_IN" are upper case and deliberately untouched.
"""

import frappe

OLD = "Docs"
NEW = "Docs received"

SCRIPTS = ("JT Rollup", "FPS Tracker Sweep")
OLD_ASSIGN = 'stage = "%s"' % OLD
NEW_ASSIGN = 'stage = "%s"' % NEW


def execute():
    _rename_field_options()
    _rename_data()
    _rename_kanban_column()
    _rename_server_scripts()
    _rename_report()
    frappe.clear_cache()


def _rename_field_options():
    """Job Order is a custom doctype, so its DocField row IS the definition."""
    name = frappe.db.get_value(
        "DocField", {"parent": "Job Order", "fieldname": "fps_stage"}, "name"
    )
    if name:
        options = frappe.db.get_value("DocField", name, "options") or ""
        if "\n%s\n" % OLD in "\n%s\n" % options:
            frappe.db.set_value(
                "DocField", name,
                "options",
                "\n".join(NEW if o == OLD else o for o in options.split("\n")),
                update_modified=False,
            )

    # A Property Setter, if one exists, overrides the DocField and must agree.
    ps = frappe.db.get_value(
        "Property Setter",
        {"doc_type": "Job Order", "field_name": "fps_stage", "property": "options"},
        "name",
    )
    if ps:
        value = frappe.db.get_value("Property Setter", ps, "value") or ""
        frappe.db.set_value(
            "Property Setter", ps, "value",
            "\n".join(NEW if o == OLD else o for o in value.split("\n")),
            update_modified=False,
        )


def _rename_data():
    frappe.db.sql(
        "update `tabJob Order` set fps_stage = %s where fps_stage = %s", (NEW, OLD)
    )


def _rename_kanban_column():
    col = frappe.db.get_value(
        "Kanban Board Column",
        {"parent": "FPS Job Tracker", "column_name": OLD},
        "name",
    )
    if col:
        frappe.db.set_value(
            "Kanban Board Column", col, "column_name", NEW, update_modified=False
        )


def _rename_server_scripts():
    for name in SCRIPTS:
        if not frappe.db.exists("Server Script", name):
            continue
        script = frappe.db.get_value("Server Script", name, "script") or ""
        if OLD_ASSIGN not in script:
            continue
        frappe.db.set_value(
            "Server Script", name, "script",
            script.replace(OLD_ASSIGN, NEW_ASSIGN),
            update_modified=False,
        )


def _rename_report():
    name = "FPS Open Jobs by SOW"
    if not frappe.db.exists("Report", name):
        return
    query = frappe.db.get_value("Report", name, "query") or ""
    if "'%s'" % OLD not in query:
        return
    frappe.db.set_value(
        "Report", name, "query",
        query.replace("'%s'" % OLD, "'%s'" % NEW),
        update_modified=False,
    )
