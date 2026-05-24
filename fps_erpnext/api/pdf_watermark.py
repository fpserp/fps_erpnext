"""
Per-page watermark for FPS PDF generation (v0.0.9).

Strategy: POST-PROCESS THE PDF after wkhtmltopdf generates it.
  1. Frappe calls frappe.utils.pdf.get_pdf to render the HTML to PDF.
  2. We monkey-patch get_pdf so AFTER wkhtmltopdf returns the PDF bytes,
     we stamp a watermark image onto every page using pypdf (PyPDF2 fork).
  3. The watermark page is generated in-memory with Pillow (RGBA → PDF)
     and merged onto every page via pypdf.merge_page().
  4. This sidesteps wkhtmltopdf's quirky support for position:fixed and
     CSS3 page rules entirely.
"""

import os
import io
import tempfile
import base64
import frappe


# Module-level state
_patch_installed = False
_watermark_pdf_cache = None  # cached watermark PDF bytes


# ---------------------------------------------------------------------------
# Letter head footer (address bar) → wkhtmltopdf --footer-html
# ---------------------------------------------------------------------------
def _get_letter_head_footer_html():
    try:
        lh = frappe.get_cached_doc("Letter Head", "FPS Standard")
        return lh.footer or ""
    except Exception:
        return ""


def _build_address_only_footer_file():
    """Footer-html file with ONLY the address bar (no watermark here)."""
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


# ---------------------------------------------------------------------------
# Watermark PDF page (built once per worker, cached)
# ---------------------------------------------------------------------------
def _build_watermark_pdf_bytes():
    """Build a 1-page A4 PDF with the watermark at body bottom-right.

    Uses Pillow to create the watermark page. Pillow's RGBA→PDF save preserves
    transparency in version 9+ (which is bundled with Frappe v15+).
    Returns PDF bytes or None on failure.
    """
    global _watermark_pdf_cache
    if _watermark_pdf_cache is not None:
        return _watermark_pdf_cache

    try:
        from PIL import Image

        wm_path = frappe.get_app_path(
            "fps_erpnext", "public", "images", "fps_watermark.png"
        )
        if not os.path.exists(wm_path):
            return None

        # Constants
        PT_PER_MM = 2.834645669
        A4_W = int(210 * PT_PER_MM)  # 595 pt
        A4_H = int(297 * PT_PER_MM)  # 842 pt

        # Load + resize watermark to 55mm height (at 72 DPI = 1pt/px)
        img = Image.open(wm_path).convert("RGBA")
        target_h = int(55 * PT_PER_MM)  # ~156 pt
        aspect = img.width / img.height
        target_w = int(target_h * aspect)
        img_resized = img.resize((target_w, target_h), Image.LANCZOS)

        # Reduce alpha to ~22% so it acts as a watermark (semi-transparent)
        alpha = img_resized.split()[3]
        alpha = alpha.point(lambda p: int(p * 0.22))
        img_resized.putalpha(alpha)

        # Create transparent A4 canvas and paste the watermark at body bottom-right.
        # Position: 10mm from right edge, 30mm from bottom edge.
        canvas = Image.new("RGBA", (A4_W, A4_H), (255, 255, 255, 0))
        x = A4_W - target_w - int(10 * PT_PER_MM)
        y = A4_H - target_h - int(30 * PT_PER_MM)
        # In PIL, y=0 is the TOP of the image. So we computed y as distance
        # from top, equivalent to (A4_H - 30mm - height) from the top.
        canvas.paste(img_resized, (x, y), img_resized)

        # Save as PDF (PIL preserves RGBA → PDF transparency in v9+)
        buf = io.BytesIO()
        canvas.save(buf, "PDF", resolution=72.0)
        _watermark_pdf_cache = buf.getvalue()
        return _watermark_pdf_cache
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "FPS Watermark: build_watermark_pdf failed",
        )
        return None


# ---------------------------------------------------------------------------
# Post-process the PDF → stamp watermark on every page
# ---------------------------------------------------------------------------
def _stamp_watermark_on_pdf(pdf_bytes):
    """Merge the watermark page onto every page of the input PDF."""
    try:
        from pypdf import PdfReader, PdfWriter

        wm_pdf_bytes = _build_watermark_pdf_bytes()
        if not wm_pdf_bytes:
            return pdf_bytes

        wm_reader = PdfReader(io.BytesIO(wm_pdf_bytes))
        wm_page = wm_reader.pages[0]

        main_reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()

        for page in main_reader.pages:
            page.merge_page(wm_page)
            writer.add_page(page)

        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:
        # Never break PDF generation — log and return original bytes
        frappe.log_error(
            frappe.get_traceback(), "FPS Watermark: stamp on pdf failed"
        )
        return pdf_bytes


# ---------------------------------------------------------------------------
# FPS print-format detection
# ---------------------------------------------------------------------------
def _is_fps_format(html):
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


# ---------------------------------------------------------------------------
# Patched get_pdf
# ---------------------------------------------------------------------------
def _make_patched_get_pdf(original_get_pdf):
    def patched(html, options=None, output=None):
        options = dict(options or {})
        is_fps = _is_fps_format(html)

        try:
            if is_fps:
                # Address bar as wkhtmltopdf --footer-html (rendered every page)
                addr_path = _build_address_only_footer_file()
                if addr_path:
                    options["footer-html"] = addr_path
                    options["margin-bottom"] = "15"
                    options["footer-spacing"] = "0"
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                "FPS Watermark: option-build failed",
            )

        # Let wkhtmltopdf produce the PDF
        result = original_get_pdf(html, options=options, output=output)

        # Post-process: stamp the watermark on every page.
        # Only do this when we got bytes back (output=None case).
        try:
            if (
                is_fps
                and output is None
                and isinstance(result, (bytes, bytearray))
                and len(result) > 0
            ):
                result = _stamp_watermark_on_pdf(result)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                "FPS Watermark: post-process failed",
            )

        return result

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
        wm_bytes = _build_watermark_pdf_bytes()
        return {
            "patched": is_patched,
            "patch_installed_flag": _patch_installed,
            "watermark_pdf_bytes": len(wm_bytes) if wm_bytes else 0,
            "letter_head_footer_chars": len(_get_letter_head_footer_html()),
        }
    except Exception as e:
        return {"error": str(e)}
