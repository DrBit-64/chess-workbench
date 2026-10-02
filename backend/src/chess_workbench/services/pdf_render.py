"""One native PDFium thread shared by extraction and review page reads."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from chess_workbench.extraction.evidence import PdfPageRenderer, RenderedPage, RenderProfile

_PDFIUM_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdfium")


async def render_pdf_page(
    renderer: PdfPageRenderer, pdf_bytes: bytes, page: int, profile: RenderProfile
) -> RenderedPage:
    future = asyncio.get_running_loop().run_in_executor(
        _PDFIUM_EXECUTOR, renderer.render_page, pdf_bytes, page, profile
    )
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        # The executor remains serial even if a caller abandons the wait.
        await asyncio.shield(future)
        raise
