"""Finish the "Docs" -> "Docs received" rename that rename_docs_stage left half-done.

rename_docs_stage renamed the DATA (8 job orders) but not the OPTION LIST those
8 values have to come from, because it looked for the definition in the wrong
table:

    frappe.db.get_value("DocField", {"parent": "Job Order",
                                     "fieldname": "fps_stage"}, "name")

fps_stage is a CUSTOM FIELD, not a DocField. That lookup returned None, the
patch skipped the rename in silence, and the site was left with 8 records
holding "Docs received" while the Select still offered "Docs". A Select whose
value is not among its options renders empty in the form, and saving the form
can write that empty back -- so this was a live way to lose the stage on 8 open
jobs. (The */30 sweep re-derives fps_stage, so it would have healed itself
within half an hour, but only after showing a blank stage in between.)

The option list was corrected on the live site on 2026-09-10; this patch makes
that reproducible on any other copy of the site and is a no-op where it is
already right.

Also finishes two Client Scripts the original patch never looked at. Both key a
lookup table on the stage LABEL:

    "Job Order - SOW List"        colors['Docs']  -> the list-view pill colour
    "Job Order - SOW Tracker UI"  stage_color()   -> the form indicator colour
                                  stage_words()   -> "Waiting for shipping documents"

With the label renamed and the maps not, all three fall through to their
defaults: a grey pill and the raw stage string.

Only the exact token `'Docs': ` (and its double-quoted twin) is replaced, so the
milestone CODES -- 'DOCS', 'DOCS_IN', and the ['BOOKED', 'DOCS', ...] group
lists -- are untouched. Those are upper case and carry a different meaning.

Safe to re-run.
"""

import frappe

OLD = "Docs"
NEW = "Docs received"

# `'Docs': ` as a dict key, both quote styles. Never the bare word.
KEY_FORMS = (
    ("'%s': " % OLD, "'%s': " % NEW),
    ('"%s": ' % OLD, '"%s": ' % NEW),
)


def execute():
    _fix_select_options()
    _fix_client_scripts()
    _fix_data()
    frappe.clear_cache()


def _fix_select_options():
    """The definition lives in Custom Field. Check DocField too, in case a copy
    of this site has it the other way round."""
    for doctype, filters in (
        ("Custom Field", {"dt": "Job Order", "fieldname": "fps_stage"}),
        ("DocField", {"parent": "Job Order", "fieldname": "fps_stage"}),
        ("Property Setter", {"doc_type": "Job Order", "field_name": "fps_stage",
                             "property": "options"}),
    ):
        field = "value" if doctype == "Property Setter" else "options"
        for name in frappe.get_all(doctype, filters=filters, pluck="name"):
            options = frappe.db.get_value(doctype, name, field) or ""
            if OLD not in options.split("\n"):
                continue
            frappe.db.set_value(
                doctype, name, field,
                "\n".join(NEW if o == OLD else o for o in options.split("\n")),
                update_modified=False,
            )


def _fix_client_scripts():
    """Search for the token; never a hard-coded list of script names."""
    for old_key, new_key in KEY_FORMS:
        for name in frappe.get_all(
            "Client Script", filters={"script": ["like", "%" + old_key + "%"]},
            pluck="name",
        ):
            script = frappe.db.get_value("Client Script", name, "script") or ""
            if old_key not in script:
                # LIKE is case-insensitive in MariaDB, so this weeds out the
                # 'DOCS' milestone code matching a search for 'Docs'.
                continue
            frappe.db.set_value("Client Script", name, "script",
                                script.replace(old_key, new_key),
                                update_modified=False)


def _fix_data():
    """Belt and braces -- rename_docs_stage already did this."""
    frappe.db.sql(
        "update `tabJob Order` set fps_stage = %s where fps_stage = %s", (NEW, OLD)
    )
