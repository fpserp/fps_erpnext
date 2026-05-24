"""
Per-page watermark for FPS PDF generation.

How it works:
1. Monkey-patches frappe.utils.pdf.get_pdf to write a custom --footer-html
   that contains BOTH the FPS watermark image AND the existing footer content
   (address line) from the Letter Head footer field.
2. wkhtmltopdf renders --footer-html on EVERY page, so the watermark appears
   on every page of multi-page PDFs.
3. Patches once per worker process.
"""

import os
import tempfile
import base64
import frappe


# Module-level state
_patch_installed = False
_watermark_b64_cache = None


def _get_watermark_base64():
    """Read the bundled watermark PNG and return base64. Cached per process."""
    global _watermark_b64_cache
    if _watermark_b64_cache is not None:
        return _watermark_b64_cache
    try:
        wm_path = frappe.get_app_path(
            "fps_erpnext", "public", "images", "fps_watermark.png"
        )
        if not os.path.exists(wm_path):
            return ""
        with open(wm_path, "rb") as fh:
            _watermark_b64_cache = base64.b64encode(fh.read()).decode("ascii")
        return _watermark_b64_cache
    except Exception:
        return ""


def _get_letter_head_footer_html():
    """Return the raw HTML stored in Letter Head FPS Standard's footer field.

    This is the address bar with the location/phone/email/web icons.
    We need to render it ourselves so it appears on every page when wkhtmltopdf
    uses our combined --footer-html file.
    """
    try:
        lh = frappe.get_cached_doc("Letter Head", "FPS Standard")
        return lh.footer or ""
    except Exception:
        return ""


def _build_combined_footer_html_file():
    """Create a temp HTML file containing watermark + address line.

    This file is passed to wkhtmltopdf as --footer-html, so it renders on
    every page. The file is regenerated per call so any letter-head edits
    are picked up immediately.
    """
    try:
        wm_b64 = _get_watermark_base64()
        lh_footer = _get_letter_head_footer_html()

        # Watermark image sits ABOVE the address line.
        # Layout:
        #   - footer strip is ~35mm tall (set via margin-bottom)
        #   - watermark at top-right of strip (offset to overlap into body area)
        #   - address bar at the bottom of the strip
        # Watermark sizing/position:
        #   - height: 55mm (per request — bigger, more prominent)
        #   - top: -50mm means the watermark extends 50mm ABOVE the footer
        #     strip top edge, so it sits in the body area (~5cm above the
        #     address bar). wkhtmltopdf allows footer-html elements to
        #     overflow into the body area for absolute-positioned children.
        #   - opacity: 0.12 (slightly lighter than before so it doesn't
        #     interfere with body text where it overlaps).
        watermark_block = ""
        if wm_b64:
            watermark_block = (
                f'<img src="data:image/png;base64,{wm_b64}" '
                'style="position:absolute;right:10mm;top:-50mm;height:55mm;'
                'width:auto;opacity:0.12;pointer-events:none;z-index:0;" alt=""/>'
            )

        html = (
            '<!DOCTYPE html>'
            '<html><head><meta charset="utf-8">'
            '<style>'
            'html,body{margin:0;padding:0;width:100%;}'
            '.fps-footer-wrap{position:relative;width:100%;}'
            '</style>'
            '</head><body>'
            '<div class="fps-footer-wrap">'
            f'{watermark_block}'
            f'<div style="position:relative;z-index:1;">{lh_footer}</div>'
            '</div>'
            '</body></html>'
        )

        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix="_fps_footer.html",
            delete=False,
            encoding="utf-8",
        )
        tmp.write(html)
        tmp.close()
        return tmp.name
    except Exception:
        frappe.log_error(
            frappe.get_traceback(), "FPS Watermark: build_combined_footer_html failed"
        )
        return None


def _is_fps_format(html):
    """Detect FPS print formats to avoid touching unrelated PDFs (emails etc)."""
    if not html:
        return False
    needles = (
        "Fast Planet Shipping",
        "fps_test",
        "fps_invoice",
        "fps_pod",
        "FPS Enquiry Format",
        "FPS Standard",
        "fastplanet.ae",
    )
    return any(n in html for n in needles)


def _make_patched_get_pdf(original_get_pdf):
    """Build the patched version of frappe.utils.pdf.get_pdf."""

    def patched(html, options=None, output=None):
        options = dict(options or {})

        try:
            if _is_fps_format(html):
                wm_path = _build_combined_footer_html_file()
                if wm_path:
                    # ALWAYS overwrite footer-html — even if Frappe already set
                    # one for the letter head footer. Our combined file
                    # includes that content plus the watermark.
                    options["footer-html"] = wm_path
                    options["margin-bottom"] = "40"
                    options["footer-spacing"] = "0"

                    # Marker so we can verify in logs / via API
                    options["fps-watermark-injected"] = "1"
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), "FPS Watermark: patched get_pdf failed"
            )

        # Strip our internal marker before passing to wkhtmltopdf (it isn't a real flag)
        options.pop("fps-watermark-injected", None)
        return original_get_pdf(html, options=options, output=output)

    return patched


def install_watermark_patch():
    """Monkey-patch frappe.utils.pdf.get_pdf once per worker process.

    Wired via `before_request` in hooks.py — fires on every web request,
    but `_patch_installed` ensures the actual patching happens only once.
    """
    global _patch_installed
    if _patch_installed:
        return

    try:
        import frappe.utils.pdf as _frappe_pdf

        original = getattr(_frappe_pdf, "get_pdf", None)
        if original is None:
            return

        # Guard against double-patching
        if getattr(original, "_fps_watermark_patched", False):
            _patch_installed = True
            return

        patched = _make_patched_get_pdf(original)
        patched._fps_watermark_patched = True  # type: ignore[attr-defined]
        _frappe_pdf.get_pdf = patched
        _patch_installed = True
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "FPS Watermark: install_watermark_patch failed",
        )


# ---------------------------------------------------------------------------
# Diagnostic API — call this to verify the patch is installed on the live site
# ---------------------------------------------------------------------------
@frappe.whitelist()
def check_watermark_status():
    """Return whether the watermark patch is currently active on this worker."""
    try:
        import frappe.utils.pdf as _frappe_pdf
        fn = getattr(_frappe_pdf, "get_pdf", None)
        is_patched = bool(getattr(fn, "_fps_watermark_patched", False))
        wm_b64_len = len(_get_watermark_base64())
        lh_footer_len = len(_get_letter_head_footer_html())
        return {
            "patched": is_patched,
            "watermark_b64_chars": wm_b64_len,
            "letter_head_footer_chars": lh_footer_len,
            "patch_installed_flag": _patch_installed,
        }
    except Exception as e:
        return {"error": str(e)}
