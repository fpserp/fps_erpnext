"""
Per-page watermark for FPS PDF generation.

How it works:
1. Monkey-patches frappe.utils.pdf.get_pdf to add wkhtmltopdf's --footer-html option.
2. The --footer-html points to a small HTML file containing the FPS watermark image
   positioned at the bottom-right of the page.
3. wkhtmltopdf renders the footer-html on EVERY page (this is its native behavior),
   so the watermark appears on every page of multi-page PDFs.
4. We only patch once per worker process, guarded by a module-level flag.
"""

import os
import tempfile
import base64
import frappe


# Module-level state
_patch_installed = False
_watermark_html_path = None


def _build_watermark_html_file():
    """Create the temporary HTML file used as wkhtmltopdf's --footer-html.

    Returns the absolute path to the temp file, or None if the watermark image
    cannot be located. The file is created once per worker process and reused.
    """
    global _watermark_html_path

    if _watermark_html_path and os.path.exists(_watermark_html_path):
        return _watermark_html_path

    try:
        # Locate the watermark image bundled with this app
        wm_path = frappe.get_app_path(
            "fps_erpnext", "public", "images", "fps_watermark.png"
        )
        if not os.path.exists(wm_path):
            return None

        with open(wm_path, "rb") as fh:
            wm_b64 = base64.b64encode(fh.read()).decode("ascii")

        # The HTML below is rendered by wkhtmltopdf as the page footer.
        # The footer area is sized via the print format's margin_bottom.
        # The watermark image is positioned absolute so it sits in the bottom-
        # right of the footer strip, which is the bottom-right of each page.
        html = (
            "<!DOCTYPE html>"
            "<html><head><meta charset=\"utf-8\"></head>"
            "<body style=\"margin:0;padding:0;\">"
            "<div style=\"position:relative;width:100%;height:100%;\">"
            f"<img src=\"data:image/png;base64,{wm_b64}\" "
            "style=\"position:absolute;right:8mm;bottom:8mm;width:180px;"
            "opacity:0.18;\" alt=\"\"/>"
            "</div></body></html>"
        )

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix="_fps_watermark.html", delete=False, encoding="utf-8"
        )
        tmp.write(html)
        tmp.close()
        _watermark_html_path = tmp.name
        return _watermark_html_path
    except Exception:
        frappe.log_error(
            frappe.get_traceback(), "FPS Watermark: failed to build watermark HTML"
        )
        return None


def _is_fps_format(html):
    """Heuristic to detect if the HTML being rendered is one of our FPS print formats.

    We don't want to inject a watermark into emails, system reports, or other PDFs
    that happen to flow through the same get_pdf function — only into Quotation /
    Sales Invoice / POD / FPS Enquiry prints that use the FPS layout.
    """
    if not html:
        return False
    needles = (
        "Fast Planet Shipping",
        "fps_test",
        "fps_invoice",
        "fps_pod",
        "FPS Enquiry Format",
        "FPS Standard",
    )
    return any(n in html for n in needles)


def _make_patched_get_pdf(original_get_pdf):
    """Build the patched version of frappe.utils.pdf.get_pdf."""

    def patched(html, options=None, output=None):
        options = dict(options or {})

        try:
            if _is_fps_format(html) and "footer-html" not in options:
                wm_path = _build_watermark_html_file()
                if wm_path:
                    options["footer-html"] = wm_path
                    # Reserve room at the bottom of every page for the footer-html
                    # to render in. 35mm gives the 180px watermark room to breathe
                    # plus the address line that's already in the body.
                    options["margin-bottom"] = "35"
                    options["footer-spacing"] = "0"
        except Exception:
            # Never break PDF generation — fall through to the original call
            frappe.log_error(
                frappe.get_traceback(), "FPS Watermark: patched get_pdf failed"
            )

        return original_get_pdf(html, options=options, output=output)

    return patched


def install_watermark_patch():
    """Monkey-patch frappe.utils.pdf.get_pdf once per worker process.

    Wired up via `before_request` in hooks.py so it runs at the start of every
    web request. The `_patch_installed` flag ensures the actual patching only
    happens on the first request per worker.
    """
    global _patch_installed
    if _patch_installed:
        return

    try:
        import frappe.utils.pdf as _frappe_pdf

        original = getattr(_frappe_pdf, "get_pdf", None)
        if original is None:
            return

        # Guard against double-patching if the module is reloaded
        if getattr(original, "_fps_watermark_patched", False):
            _patch_installed = True
            return

        patched = _make_patched_get_pdf(original)
        patched._fps_watermark_patched = True  # type: ignore[attr-defined]
        _frappe_pdf.get_pdf = patched
        _patch_installed = True
    except Exception:
        frappe.log_error(
            frappe.get_traceback(), "FPS Watermark: install_watermark_patch failed"
        )
