"""
Per-page watermark for FPS PDF generation.

Approach (v0.0.8):
  1. The watermark is INJECTED INTO THE BODY HTML as a position:fixed element.
     wkhtmltopdf renders position:fixed elements on every page (its native
     behavior for fixed-positioned direct children of body).
  2. The address bar (letter head footer field) is passed as wkhtmltopdf's
     --footer-html so it appears at the bottom of every page in its own strip.
  3. This separation lets the watermark sit in the body bottom-right area
     (just above the footer strip) on every page — fully visible, never
     clipped by the footer strip boundary.
"""

import os
import re
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
    """Return the raw HTML stored in Letter Head FPS Standard's footer field."""
    try:
        lh = frappe.get_cached_doc("Letter Head", "FPS Standard")
        return lh.footer or ""
    except Exception:
        return ""


def _build_address_only_footer_file():
    """Footer-html file with ONLY the address bar (no watermark).

    The watermark goes in the body via position:fixed; this file just renders
    the address line in wkhtmltopdf's footer strip on every page.
    """
    try:
        lh_footer = _get_letter_head_footer_html()
        html = (
            '<!DOCTYPE html>'
            '<html><head><meta charset="utf-8">'
            '<style>html,body{margin:0;padding:0;width:100%;}</style>'
            '</head><body>'
            f'{lh_footer}'
            '</body></html>'
        )
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix="_fps_addr.html", delete=False, encoding="utf-8"
        )
        tmp.write(html)
        tmp.close()
        return tmp.name
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "FPS Watermark: build address footer file failed",
        )
        return None


def _build_watermark_html_block():
    """Build the <img> tag for the watermark, styled to sit at body bottom-right.

    position: fixed makes wkhtmltopdf render it on EVERY page at the same
    spot. bottom:30mm + height:55mm = watermark occupies 30mm to 85mm from
    page bottom — visible in the body area, just above the footer strip.
    """
    wm_b64 = _get_watermark_base64()
    if not wm_b64:
        return ""
    return (
        '<img src="data:image/png;base64,' + wm_b64 + '" '
        'class="fps-page-watermark" '
        'style="position:fixed;bottom:30mm;right:10mm;height:55mm;'
        'width:auto;opacity:0.18;z-index:-1;pointer-events:none;" alt=""/>'
    )


def _inject_watermark_into_html(html):
    """Insert the fixed-position watermark <img> right after the <body> tag."""
    block = _build_watermark_html_block()
    if not block:
        return html
    # Skip if already injected (defensive)
    if "fps-page-watermark" in html:
        return html
    # Insert after the FIRST <body ...> tag
    new_html, count = re.subn(
        r"(<body[^>]*>)", r"\1\n" + block, html, count=1
    )
    return new_html if count else html


def _is_fps_format(html):
    """Detect FPS print formats."""
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
    def patched(html, options=None, output=None):
        options = dict(options or {})
        try:
            if _is_fps_format(html):
                # Inject the position:fixed watermark into body HTML.
                # wkhtmltopdf renders fixed-position elements on every page.
                html = _inject_watermark_into_html(html)

                # Address-only footer strip (small, just the address line)
                addr_path = _build_address_only_footer_file()
                if addr_path:
                    options["footer-html"] = addr_path
                    options["margin-bottom"] = "15"
                    options["footer-spacing"] = "0"
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), "FPS Watermark: patched get_pdf failed"
            )

        return original_get_pdf(html, options=options, output=output)

    return patched


def install_watermark_patch():
    """Monkey-patch frappe.utils.pdf.get_pdf once per worker process."""
    global _patch_installed
    if _patch_installed:
        return
    try:
        import frappe.utils.pdf as _frappe_pdf

        original = getattr(_frappe_pdf, "get_pdf", None)
        if original is None:
            return
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
# Diagnostic API
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
