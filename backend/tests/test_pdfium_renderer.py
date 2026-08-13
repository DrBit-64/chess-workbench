"""Focused tests for the bounded Stage 8B PDFium renderer."""

from __future__ import annotations

import ast
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pypdfium2
import pytest
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from chess_workbench.extraction.evidence import (
    PdfEvidenceError,
    PdfPageRenderer,
    RenderProfile,
)
from chess_workbench.extraction.pdfium import PdfiumPageRenderer

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _pdf(*contents: bytes | None) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for content in contents:
        page = writer.add_blank_page(width=72, height=144)
        if content is None:
            continue
        stream = DecodedStreamObject()
        stream.set_data(content)
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _content(text: str, gray: float = 0.5) -> bytes:
    return (
        f"{gray} {gray} {gray} rg 0 0 72 72 re f\n0 0 0 rg BT /F1 12 Tf 10 100 Td ({text}) Tj ET\n"
    ).encode("ascii")


def _separate_character_content(text: str) -> bytes:
    operators = " ".join(f"({character}) Tj" for character in text)
    return f"0 0 0 rg BT /F1 12 Tf 10 100 Td {operators} ET\n".encode("ascii")


def test_renders_exact_dimensions_rgb_and_white_background() -> None:
    renderer = PdfiumPageRenderer()
    at_72 = renderer.render_page(_pdf(None), 1, RenderProfile(dpi=72))
    at_150 = renderer.render_page(_pdf(None), 1, RenderProfile())

    assert (at_72.width, at_72.height) == (72, 144)
    assert (at_150.width, at_150.height) == (150, 300)
    assert at_72.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(at_72.png_bytes)) as image:
        assert image.mode == "RGB"
        assert image.size == (72, 144)
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_repeat_render_is_byte_deterministic_and_versioned() -> None:
    data = _pdf(_content("Repeat"))
    renderer = PdfiumPageRenderer()
    first = renderer.render_page(data, 1, RenderProfile(dpi=72))
    second = renderer.render_page(data, 1, RenderProfile(dpi=72))

    assert first.png_bytes == second.png_bytes
    assert first.renderer_name == "pdfium"
    assert first.renderer_version
    assert first.model_dump() == second.model_dump()


def test_selects_only_the_requested_physical_page() -> None:
    data = _pdf(None, _content("Second", gray=0.2), _content("Third", gray=0.8))
    renderer = PdfiumPageRenderer()
    second = renderer.render_page(data, 2, RenderProfile(dpi=72))
    third = renderer.render_page(data, 3, RenderProfile(dpi=72))

    assert second.physical_page == 2
    assert third.physical_page == 3
    assert second.png_bytes != third.png_bytes


def test_extracts_ordered_embedded_text_with_bounded_boxes() -> None:
    page = PdfiumPageRenderer().render_page(
        _pdf(_content("Hello PDFium")), 1, RenderProfile(dpi=72)
    )

    assert page.embedded_fragments
    assert [fragment.order for fragment in page.embedded_fragments] == list(
        range(len(page.embedded_fragments))
    )
    assert "Hello PDFium" in "".join(fragment.text for fragment in page.embedded_fragments)
    for fragment in page.embedded_fragments:
        assert fragment.confidence is None
        assert 0 <= fragment.box.x0 < fragment.box.x1 <= page.width
        assert 0 <= fragment.box.y0 < fragment.box.y1 <= page.height


def test_coalesces_separate_pdf_text_objects_into_one_logical_line() -> None:
    page = PdfiumPageRenderer().render_page(
        _pdf(_separate_character_content("1 e4 d5")), 1, RenderProfile(dpi=72)
    )

    assert [fragment.text for fragment in page.embedded_fragments] == ["1 e4 d5"]


def test_blank_page_has_no_embedded_fragments() -> None:
    page = PdfiumPageRenderer().render_page(_pdf(None), 1, RenderProfile(dpi=72))
    assert page.embedded_fragments == []


@pytest.mark.parametrize(
    ("pdf_bytes", "physical_page", "profile", "error_type"),
    [
        (bytearray(b"pdf"), 1, RenderProfile(), TypeError),
        (b"", 1, RenderProfile(), ValueError),
        (b"pdf", True, RenderProfile(), TypeError),
        (b"pdf", 0, RenderProfile(), ValueError),
        (b"pdf", 1, {}, TypeError),
    ],
)
def test_rejects_programmer_misuse_before_opening(
    pdf_bytes: Any,
    physical_page: Any,
    profile: Any,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        PdfiumPageRenderer().render_page(pdf_bytes, physical_page, profile)


def test_invalid_pdf_and_page_range_errors_are_sanitized() -> None:
    renderer = PdfiumPageRenderer()
    with pytest.raises(PdfEvidenceError) as invalid_info:
        renderer.render_page(b"not a pdf", 1, RenderProfile())
    assert invalid_info.value.code == "invalid_pdf"
    assert str(invalid_info.value) == "PDF document could not be opened for rendering"
    assert invalid_info.value.__cause__ is None
    assert invalid_info.value.__context__ is None

    with pytest.raises(PdfEvidenceError) as range_info:
        renderer.render_page(_pdf(None), 2, RenderProfile())
    assert range_info.value.code == "page_out_of_range"
    assert str(range_info.value) == "PDF physical page is outside the selected document"
    assert range_info.value.retryable is False


def test_custom_side_pixel_and_png_limits_fail_before_return() -> None:
    renderer = PdfiumPageRenderer()
    data = _pdf(_content("Limits"))
    for profile in (
        RenderProfile(dpi=72, max_side_px=71),
        RenderProfile(dpi=72, max_pixels=10_000),
        RenderProfile(dpi=72, max_png_bytes=8),
    ):
        with pytest.raises(PdfEvidenceError) as exc_info:
            renderer.render_page(data, 1, profile)
        assert exc_info.value.code == "render_limit_exceeded"
        assert str(exc_info.value) == "PDF page exceeds the rendering limits"


def test_invalid_render_profile_fields_remain_strict() -> None:
    with pytest.raises(ValidationError):
        RenderProfile.model_validate({"dpi": 150, "unknown": True})
    with pytest.raises(ValidationError):
        RenderProfile(dpi=cast(Any, True))


def test_memory_error_and_keyboard_interrupt_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    for exception in (MemoryError, KeyboardInterrupt):

        def fail(_data: bytes, *, _exception: type[BaseException] = exception) -> None:
            raise _exception

        monkeypatch.setattr(pypdfium2, "PdfDocument", fail)
        with pytest.raises(exception):
            PdfiumPageRenderer().render_page(_pdf(None), 1, RenderProfile())


def test_renderer_satisfies_runtime_protocol() -> None:
    renderer: PdfPageRenderer = PdfiumPageRenderer()
    assert isinstance(renderer, PdfPageRenderer)


def test_module_imports_are_within_the_frozen_boundary() -> None:
    path = PROJECT_ROOT / "backend" / "src" / "chess_workbench" / "extraction" / "pdfium.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    relative_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_modules.add(node.module or "")
            elif node.module:
                roots.add(node.module.split(".", 1)[0])
    assert roots <= {"__future__", "io", "math", "typing", "pypdfium2"}
    assert relative_modules == {"evidence"}
