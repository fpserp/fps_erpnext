"""Remove the "?? " left where an emoji was destroyed on the way into the database.

THREE RECORDS, all created 2026-05-24 by whatever tool built the FPS
customisations:

    Custom Field  Sales Invoice-fps_ap_profitability_sec
                  "?? AP Costs & Profitability (Admin Only)"
    Custom Field  Purchase Invoice-fps_section_reference
                  "?? FPS Job Order Link (Mandatory)"
    Client Script Purchase Invoice - Job Order Helper
                  __('?? Mandatory: Select a Job Order')

THIS IS NOT MOJIBAKE, AND THE DIFFERENCE MATTERS. Mojibake is UTF-8 read back as
Latin-1: the bytes survive, so "Ã°Â\\x9fÂ\\x92Â¾" can be decoded back to a floppy
disk and the fix restores the original. What is stored here is two ASCII
question marks, U+003F U+003F -- checked byte by byte. The emoji was replaced at
the moment it was written and NOTHING about it survives. There is no way to know
which character it was, so this patch does not guess one: it removes the orphan
prefix and leaves a clean label.

THE DATABASE IS NOT AT FAULT, which is worth recording so nobody goes hunting
for a charset problem. Four-byte characters store perfectly well on this site --
the "Qashio Settings - Sync Now Button" client script holds a folder emoji and
two Comments hold a pushpin, all intact. So the columns are utf8mb4 and an emoji
CAN be put back by hand if one is wanted; the fault was in the writing tool, not
the storage.

SEARCH-BASED, NOT A LIST OF THREE. An earlier patch in this series hard-coded
the records it expected to find and missed six others, which then failed
silently for a day. The scan that found these three covered 17,000+ rows across
Custom Field, DocField, Property Setter, Client Script, Server Script, Workspace,
Report and Print Format and found no others -- but the search runs anyway, so a
fourth appearing later is caught rather than overlooked.

The pattern is deliberately tight. A label must START with "?? " (the shape of a
lost leading emoji), and in a script the "??" must open a quoted string --
__('?? ...). A bare "??" mid-sentence is left alone; it is far more likely to be
someone's punctuation than a lost glyph.

Safe to re-run: once stripped, nothing matches.
"""

import frappe

PREFIX = "?? "

SCRIPT_SOURCES = ("Client Script", "Server Script")

# Only where "??" opens a quoted string, both quote styles.
SCRIPT_FORMS = (("('?? ", "('"), ('("?? ', '("'))


def execute():
	changed = _strip_labels() + _strip_property_setters() + _strip_scripts()
	if changed:
		frappe.db.commit()
		frappe.clear_cache()
	frappe.logger().info("FPS: stripped a lost-emoji prefix from %d records" % changed)


def _strip_labels():
	"""Custom Field labels only.

	DocField is deliberately NOT touched. Both known cases are Custom Fields,
	and the scan found no DocField carrying the prefix -- but if one ever did,
	editing the DocField row would be the wrong repair for a STOCK doctype,
	because the next migrate re-imports that doctype's JSON and puts the old
	label straight back. The right fix there is a Property Setter, which is a
	judgement call this patch should not make silently. It is logged instead.
	"""
	changed = 0
	for row in frappe.get_all(
		"Custom Field",
		filters={"label": ["like", "??%"]},
		fields=["name", "label"],
	):
		value = row.get("label") or ""
		if not value.startswith(PREFIX):
			continue
		frappe.db.set_value("Custom Field", row["name"], "label",
		                    value[len(PREFIX):], update_modified=False)
		changed += 1

	for row in frappe.get_all(
		"DocField",
		filters={"parenttype": "DocType", "label": ["like", "??%"]},
		fields=["name", "parent", "fieldname", "label"],
	):
		if (row.get("label") or "").startswith(PREFIX):
			frappe.log_error(
				title="FPS: %s.%s label starts with '?? ' -- needs a Property Setter"
				% (row.get("parent"), row.get("fieldname"))
			)

	return changed


def _strip_property_setters():
	"""A label override could carry the same orphan prefix."""
	changed = 0
	for row in frappe.get_all(
		"Property Setter",
		filters={"property": "label", "value": ["like", "??%"]},
		fields=["name", "value"],
	):
		value = row.get("value") or ""
		if not value.startswith(PREFIX):
			continue
		frappe.db.set_value("Property Setter", row["name"], "value",
		                    value[len(PREFIX):], update_modified=False)
		changed += 1
	return changed


def _strip_scripts():
	changed = 0
	for doctype in SCRIPT_SOURCES:
		for name in frappe.get_all(
			doctype, filters={"script": ["like", "%??%"]}, pluck="name"
		):
			script = frappe.db.get_value(doctype, name, "script") or ""
			fixed = script
			for old, new in SCRIPT_FORMS:
				fixed = fixed.replace(old, new)
			if fixed == script:
				# "??" is in there, but not opening a quoted string. Leave it --
				# it is punctuation, not a lost glyph.
				continue
			frappe.db.set_value(doctype, name, "script", fixed, update_modified=False)
			changed += 1
	return changed
