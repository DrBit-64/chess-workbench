"""Bounded in-memory PDFium page renderer for Stage 8B."""

from __future__ import annotations

import math
from io import BytesIO
from typing import final

import pypdfium2
import pypdfium2.raw as pdfium_c

from .evidence import (
    MAX_FRAGMENTS,
    MAX_PIXELS,
    MAX_PNG_BYTES,
    MAX_TEXT_CODE_POINTS,
    PdfEvidenceError,
    PixelBox,
    RenderedPage,
    RenderProfile,
    TextFragment,
)

_INVALID_PDF = ("invalid_pdf", "PDF document could not be opened for rendering")
_PAGE_OUT_OF_RANGE = (
    "page_out_of_range",
    "PDF physical page is outside the selected document",
)
_RENDER_LIMIT = ("render_limit_exceeded", "PDF page exceeds the rendering limits")
_RENDER_FAILED = ("render_failed", "PDF page could not be rendered")


def _error(value: tuple[str, str]) -> PdfEvidenceError:
    return PdfEvidenceError(value[0], value[1], False)


def _validate_call(pdf_bytes: bytes, physical_page: int, profile: RenderProfile) -> None:
    if type(pdf_bytes) is not bytes:
        raise TypeError("pdf_bytes must be bytes")
    if not pdf_bytes:
        raise ValueError("pdf_bytes must not be empty")
    if type(physical_page) is not int:
        raise TypeError("physical_page must be int")
    if physical_page < 1:
        raise ValueError("physical_page must be at least 1")
    if type(profile) is not RenderProfile:
        raise TypeError("profile must be RenderProfile")


def _pixel_box(
    rect: tuple[float, float, float, float],
    *,
    page_height: float,
    scale: float,
    width: int,
    height: int,
) -> PixelBox | None:
    left, bottom, right, top = rect
    x0 = max(0, min(width, math.floor(left * scale)))
    y0 = max(0, min(height, math.floor((page_height - top) * scale)))
    x1 = max(0, min(width, math.ceil(right * scale)))
    y1 = max(0, min(height, math.ceil((page_height - bottom) * scale)))
    if x0 >= x1 or y0 >= y1:
        return None
    return PixelBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _embedded_fragments(
    page: pypdfium2.PdfPage,
    *,
    page_height: float,
    scale: float,
    width: int,
    height: int,
) -> list[TextFragment]:
    fragments: list[TextFragment] = []
    text_page = page.get_textpage()
    try:
        rectangle_count = text_page.count_rects()
        if rectangle_count > MAX_FRAGMENTS:
            raise _error(_RENDER_LIMIT)
        for rectangle_index in range(rectangle_count):
            rect = text_page.get_rect(rectangle_index)
            text = text_page.get_text_bounded(*rect)
            if not text or not text.strip():
                continue
            if len(text) > MAX_TEXT_CODE_POINTS or len(fragments) >= MAX_FRAGMENTS:
                raise _error(_RENDER_LIMIT)
            box = _pixel_box(
                rect,
                page_height=page_height,
                scale=scale,
                width=width,
                height=height,
            )
            if box is None:
                continue
            fragments.append(
                TextFragment(order=len(fragments), text=text, box=box, confidence=None)
            )
    finally:
        text_page.close()
    return fragments


def _render_open_document(
    document: pypdfium2.PdfDocument,
    physical_page: int,
    profile: RenderProfile,
) -> RenderedPage:
    if physical_page > len(document):
        raise _error(_PAGE_OUT_OF_RANGE)
    scale = profile.dpi / 72
    page = document[physical_page - 1]
    try:
        page_width = page.get_width()
        page_height = page.get_height()
        width = math.ceil(page_width * scale)
        height = math.ceil(page_height * scale)
        if (
            width < 1
            or height < 1
            or width > profile.max_side_px
            or height > profile.max_side_px
            or width * height > min(profile.max_pixels, MAX_PIXELS)
        ):
            raise _error(_RENDER_LIMIT)
        fragments = _embedded_fragments(
            page,
            page_height=page_height,
            scale=scale,
            width=width,
            height=height,
        )
        bitmap = page.render(
            scale=scale,
            rotation=0,
            may_draw_forms=False,
            fill_color=(255, 255, 255, 255),
            draw_annots=False,
            force_bitmap_format=pdfium_c.FPDFBitmap_BGR,
            rev_byteorder=True,
        )
        try:
            image = bitmap.to_pil().convert("RGB")
            output = BytesIO()
            image.save(output, format="PNG", compress_level=9, optimize=False)
            png_bytes = output.getvalue()
        finally:
            bitmap.close()
        if len(png_bytes) > min(profile.max_png_bytes, MAX_PNG_BYTES):
            raise _error(_RENDER_LIMIT)
        return RenderedPage(
            physical_page=physical_page,
            width=width,
            height=height,
            dpi=profile.dpi,
            png_bytes=png_bytes,
            embedded_fragments=fragments,
            renderer_name="pdfium",
            renderer_version=str(pypdfium2.version.PDFIUM_INFO),
        )
    finally:
        page.close()


@final
class PdfiumPageRenderer:
    """Render one selected physical page entirely in memory."""

    def render_page(
        self,
        pdf_bytes: bytes,
        physical_page: int,
        profile: RenderProfile,
    ) -> RenderedPage:
        _validate_call(pdf_bytes, physical_page, profile)
        open_failed = False
        try:
            document = pypdfium2.PdfDocument(pdf_bytes)
        except MemoryError:
            raise
        except (pypdfium2.PdfiumError, OSError, TypeError, ValueError):
            open_failed = True
        if open_failed:
            raise _error(_INVALID_PDF)

        render_failed = False
        try:
            with document:
                return _render_open_document(document, physical_page, profile)
        except PdfEvidenceError:
            raise
        except MemoryError:
            raise
        except (pypdfium2.PdfiumError, OSError, TypeError, ValueError):
            render_failed = True
        if render_failed:
            raise _error(_RENDER_FAILED)
        raise AssertionError("unreachable PDF rendering state")


__all__ = ["PdfiumPageRenderer"]
