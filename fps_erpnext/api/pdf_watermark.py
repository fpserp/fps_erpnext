"""
Per-page watermark for FPS PDF generation (v0.0.11).

Strategy: POST-PROCESS THE PDF after wkhtmltopdf generates it.
  1. wkhtmltopdf renders the body + small footer strip (address bar).
  2. After the render, we build a 1-page A4 PDF containing JUST the
     watermark (positioned at body bottom-right with proper transparency).
  3. pypdf merges that watermark page onto every page of the main PDF.

We try reportlab first (proper PDF transparency). If reportlab is
unavailable we fall back to a Pillow-based small-image approach
positioned via pypdf's Transformation.
"""

import os
import io
import tempfile
import base64
import frappe


# Module-level state
_patch_installed = False
_watermark_pdf_cache = None
_watermark_backend_used = "none"


# ---------------------------------------------------------------------------
# Letter head footer → wkhtmltopdf --footer-html
# ---------------------------------------------------------------------------
def _get_letter_head_footer_html():
    try:
        lh = frappe.get_cached_doc("Letter Head", "FPS Standard")
        return lh.footer or ""
    except Exception:
        return ""


def _build_address_only_footer_file():
    try:
        lh_footer = _get_letter_head_footer_html()
        html = (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<style>html,body{margin:0;padding:0;width:100%;}</style>'
            '</head><body>' + lh_footer + '</body></html>'
        )
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix="_fps_addr.html", delete=False, encoding="utf-8"
        )
        tmp.write(html)
        tmp.close()
        return tmp.name
    except Exception:
        frappe.log_error(frappe.get_traceback(), "FPS Watermark: addr footer failed")
        return None


# ---------------------------------------------------------------------------
# Watermark page generation — reportlab primary, Pillow fallback
# ---------------------------------------------------------------------------
def _build_watermark_pdf_reportlab():
    """Reportlab path — proper PDF transparency."""
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader

    wm_path = frappe.get_app_path("fps_erpnext", "public", "images", "fps_watermark.png")
    if not os.path.exists(wm_path):
        return None

    PT_PER_MM = 2.834645669
    A4_W, A4_H = A4  # 595.27, 841.89

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)

    img = ImageReader(wm_path)
    img_w, img_h = img.getSize()
    aspect = img_w / img_h
    wm_h_pt = 55 * PT_PER_MM
    wm_w_pt = wm_h_pt * aspect

    x = A4_W - wm_w_pt - 10 * PT_PER_MM
    y = 30 * PT_PER_MM

    c.saveState()
    try:
        c.setFillAlpha(0.15)
        c.setStrokeAlpha(0.15)
    except Exception:
        pass
    c.drawImage(img, x, y, width=wm_w_pt, height=wm_h_pt, mask="auto",
                preserveAspectRatio=True)
    c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()


def _build_watermark_pdf_pillow():
    """Pillow fallback — save the small watermark image as a PDF.

    Pillow's PDF save in our env may flatten RGBA to RGB by alpha-blending
    with white. The resulting image is OPAQUE faded gray (no true alpha) —
    when pypdf positions this small image PDF on each page, it covers only
    the bottom-right corner where the image is, and looks watermark-like
    even though technically opaque.
    """
    from PIL import Image

    wm_path = frappe.get_app_path("fps_erpnext", "public", "images", "fps_watermark.png")
    if not os.path.exists(wm_path):
        return None

    PT_PER_MM = 2.834645669

    img = Image.open(wm_path).convert("RGBA")
    target_h = int(55 * PT_PER_MM)
    aspect = img.width / img.height
    target_w = int(target_h * aspect)
    img_resized = img.resize((target_w, target_h), Image.LANCZOS)

    # Blend with white to simulate transparency (since RGBA → PDF often loses alpha)
    white_bg = Image.new("RGB", img_resized.size, (255, 255, 255))
    # Pull the alpha channel and use it for blending
    if img_resized.mode == "RGBA":
        alpha = img_resized.split()[3]
        # Reduce alpha to ~25% so the blend produces a faded result
        alpha = alpha.point(lambda p: int(p * 0.25))
        rgb = img_resized.convert("RGB")
        # Composite: rgb on white_bg using alpha as mask
        white_bg.paste(rgb, (0, 0), alpha)
    else:
        white_bg = img_resized.convert("RGB")

    # Save the SMALL faded image as PDF (not A4 — just the image)
    buf = io.BytesIO()
    white_bg.save(buf, "PDF", resolution=72.0)
    return buf.getvalue()


def _build_watermark_pdf_bytes():
    """Return cached watermark PDF bytes; build once per worker."""
    global _watermark_pdf_cache, _watermark_backend_used
    if _watermark_pdf_cache is not None:
        return _watermark_pdf_cache

    # Try reportlab first
    try:
        result = _build_watermark_pdf_reportlab()
        if result:
            _watermark_pdf_cache = result
            _watermark_backend_used = "reportlab"
            return result
    except ImportError:
        pass
    except Exception:
        frappe.log_error(frappe.get_traceback(), "FPS Watermark: reportlab build failed")

    # Fall back to Pillow
    try:
        result = _build_watermark_pdf_pillow()
        if result:
            _watermark_pdf_cache = result
            _watermark_backend_used = "pillow"
            return result
    except Exception:
        frappe.log_error(frappe.get_traceback(), "FPS Watermark: pillow build failed")

    return None


# ---------------------------------------------------------------------------
# Post-process: merge watermark onto every page
# ---------------------------------------------------------------------------
def _stamp_watermark_on_pdf(pdf_bytes):
    """Merge the watermark page onto every page of the main PDF.

    For the reportlab path the watermark is A4 so merge_page() centers
    correctly. For the Pillow fallback the watermark PDF is just the image
    size — we use Transformation to translate it into the bottom-right corner.
    """
    try:
        from pypdf import PdfReader, PdfWriter, Transformation

        wm_pdf_bytes = _build_watermark_pdf_bytes()
        if not wm_pdf_bytes:
            return pdf_bytes

        wm_reader = PdfReader(io.BytesIO(wm_pdf_bytes))
        wm_page = wm_reader.pages[0]

        main_reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()

        # Detect whether the watermark page is A4 (reportlab) or small (Pillow).
        # Reportlab A4 = 595x842; if smaller, use translation to position.
        wm_w = float(wm_page.mediabox.width)
        wm_h = float(wm_page.mediabox.height)
        is_a4 = wm_w > 400 and wm_h > 700  # rough check

        PT_PER_MM = 2.834645669

        for page in main_reader.pages:
            if is_a4:
                # Reportlab path — same-size pages, direct merge
                page.merge_page(wm_page)
            else:
                # Pillow small-image path — translate into bottom-right
                page_w = float(page.mediabox.width)
                tx = page_w - wm_w - 10 * PT_PER_MM
                ty = 30 * PT_PER_MM
                op = Transformation().translate(tx=tx, ty=ty)
                page.merge_transformed_page(wm_page, op)
            writer.add_page(page)

        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "FPS Watermark: stamp failed")
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
            frappe.log_error(frappe.get_traceback(), "FPS Watermark: option-build failed")

        result = original_get_pdf(html, options=options, output=output)

        try:
            if (is_fps and output is None
                    and isinstance(result, (bytes, bytearray)) and len(result) > 0):
                result = _stamp_watermark_on_pdf(result)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "FPS Watermark: post-process failed")

        return result

    return patched


def install_watermark_patch():
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
        frappe.log_error(frappe.get_traceback(), "FPS Watermark: install failed")


# ---------------------------------------------------------------------------
# Diagnostic APIs
# ---------------------------------------------------------------------------
@frappe.whitelist()
def check_watermark_status():
    try:
        import frappe.utils.pdf as _frappe_pdf
        fn = getattr(_frappe_pdf, "get_pdf", None)
        is_patched = bool(getattr(fn, "_fps_watermark_patched", False))
        wm_bytes = _build_watermark_pdf_bytes()
        reportlab_available = False
        try:
            import reportlab  # noqa: F401
            reportlab_available = True
        except ImportError:
            pass
        return {
            "patched": is_patched,
            "patch_installed_flag": _patch_installed,
            "watermark_pdf_bytes": len(wm_bytes) if wm_bytes else 0,
            "letter_head_footer_chars": len(_get_letter_head_footer_html()),
            "reportlab_available": reportlab_available,
            "watermark_backend_used": _watermark_backend_used,
            "app_version": "0.0.12",
        }
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def get_watermark_pdf_b64():
    wm = _build_watermark_pdf_bytes()
    if not wm:
        return ""
    return base64.b64encode(wm).decode("ascii")
