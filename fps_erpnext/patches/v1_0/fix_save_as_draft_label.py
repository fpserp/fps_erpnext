"""Repair the garbled "Save as Draft" button label in the Client Scripts.

The button renders as:

    Ã°Â\x9fÂ\x92Â¾ Save as Draft

which is a floppy-disk emoji that was written once as UTF-8 and then read back
as Latin-1: the four bytes of U+1F4BE (F0 9F 92 BE) each became their own
character and were saved that way. The corruption is in the stored script, not
in the rendering, so it survives every reload.

Seven Client Scripts carry the same label. Rather than re-encode the emoji --
which is what broke in the first place, and would break again the next time the
script is exported or copied -- the label becomes plain text. Frappe already
draws its own save icon on that button.

Matches any junk between the quote and the words, so it repairs whatever each
script happens to hold, and is a no-op once clean.
"""

import re

import frappe

# __('<anything that is not a quote>Save as Draft')  ->  __('Save as Draft')
PATTERN = re.compile(r"__\('[^']*?Save as Draft'\)")
REPLACEMENT = "__('Save as Draft')"


def execute():
    for name in frappe.get_all("Client Script", pluck="name"):
        script = frappe.db.get_value("Client Script", name, "script") or ""
        if "Save as Draft" not in script:
            continue

        fixed = PATTERN.sub(REPLACEMENT, script)
        if fixed == script:
            continue

        frappe.db.set_value(
            "Client Script", name, "script", fixed, update_modified=False
        )

    frappe.clear_cache()
