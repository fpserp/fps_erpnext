"""
Per-page watermark for FPS PDF generation (v0.0.10).

Strategy: POST-PROCESS THE PDF after wkhtmltopdf generates it.
  1. wkhtmltopdf renders the body + small footer strip (address bar).
  2. After the render returns, we build a 1-page A4 PDF using reportlab
     containing JUST the watermark (with proper transparency).
  3. pypdf merges that watermark page onto every page of the main PDF.
  4. Result: watermark on every page, properly transparent, no CSS quirks.

Why reportlab instead of Pillow:
  Pillow's RGBA→PDF save loses the alpha channel in many versions —
  the watermark page ends up either invisible or covered by an opaque
  white background. Reportlab produces clean PDFs with native alpha support.
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
    """Footer-html file with ONLY the address bar."""
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

    Uses reportlab. The watermark image's PNG alpha is honored automatically
    by reportlab when mask='auto'. Additional opacity is applied via the
    canvas's setFillAlpha → setStrokeAlpha → drawImage with transparency group.

    Returns PDF bytes, or None on failure.
    """
    global _watermark_pdf_cache
    if _watermark_pdf_cache is not None:
        return _watermark_pdf_cache

    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader

        wm_path = frappe.get_app_path(
            "fps_erpnext", "public", "images", "fps_watermark.png"
        )
        if not os.path.exists(wm_path):
            frappe.log_error(
                f"Watermark PNG missing at {wm_path}", "FPS Watermark: setup"
            )
            return None

        # Reportlab uses points (1/72 inch) by default. A4 = 595 × 842 pt.
        PT_PER_MM = 2.834645669
        A4_W, A4_H = A4  # (595.27, 841.89)

        # Build PDF in memory
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=A4)

        # Use a transparency group so the image's alpha is preserved
        # and an extra global alpha (0.22) is applied to the whole image.
        img = ImageReader(wm_path)
        img_w, img_h = img.getSize()
        aspect = img_w / img_h

        wm_h_pt = 55 * PT_PER_MM   # 55 mm tall
        wm_w_pt = wm_h_pt * aspect

        # Position: 10mm from right edge, 30mm from bottom (PDF coords y=bottom)
        x = A4_W - wm_w_pt - 10 * PT_PER_MM
        y = 30 * PT_PER_MM

        # Apply global alpha to the upcoming drawImage call
        c.saveState()
        try:
            c.setFillAlpha(0.22)
            c.setStrokeAlpha(0.22)
            # Some reportlab versions also support transparency for images
            # via "_setStrokeAlpha" — but drawImage relies on the PNG alpha.
        except Exception:
            pass
        c.drawImage(
            img,
            x,
            y,
            width=wm_w_pt,
            height=wm_h_pt,
            mask="auto",
            preserveAspectRatio=True,
        )
        c.restoreState()

        c.showPage()
        c.save()

        _watermark_pdf_cache = buf.getvalue()
        return _watermark_pdf_cache
    except ImportError as e:
        frappe.log_error(
            f"reportlab not available: {e}", "FPS Watermark: reportlab missing"
        )
        return None
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

        result = original_get_pdf(html, options=options, output=output)

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
# Diagnostic APIs
# ---------------------------------------------------------------------------
@frappe.whitelist()
def check_watermark_status():
    """Return whether the watermark patch is currently active."""
    try:
        import frappe.utils.pdf as _frappe_pdf
        fn = getattr(_frappe_pdf, "get_pdf", None)
        is_patched = bool(getattr(fn, "_fps_watermark_patched", False))
        wm_bytes = _build_watermark_pdf_bytes()
        # Detect which backend is in use
        backend = "none"
        try:
            import reportlab  # noqa: F401
            backend = "reportlab"
        except ImportError:
            try:
                from PIL import Image  # noqa: F401
                backend = "pillow-fallback"
            except ImportError:
                pass
        return {
            "patched": is_patched,
            "patch_installed_flag": _patch_installed,
            "watermark_pdf_bytes": len(wm_bytes) if wm_bytes else 0,
            "letter_head_footer_chars": len(_get_letter_head_footer_html()),
            "pdf_backend": backend,
            "app_version": "0.0.10",
        }
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def get_watermark_pdf_b64():
    """Return the watermark PDF as base64 (for visual debugging)."""
    wm = _build_watermark_pdf_bytes()
    if not wm:
        return ""
    return base64.b64encode(wm).decode("ascii")
