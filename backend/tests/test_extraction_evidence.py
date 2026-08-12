"""Focused tests for the Stage 8B-1 strict evidence values and ports.

Covers DS-STAGE8B-EVIDENCE-PORTS-01: strict boxes/fragments/profile,
rendered pages, OCR request/result, source-evidence hashing, Protocols,
the stable error model, the deterministic scripted OCR fake and import
purity.  No snapshots, filesystem, network, clock or randomness.
"""

from __future__ import annotations

import asyncio
import copy
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from chess_workbench.extraction import evidence as evidence_module
from chess_workbench.extraction.evidence import (
    MAX_PNG_BYTES,
    NormalizedBox,
    OcrAdapter,
    OcrPageResult,
    OcrRequest,
    PdfEvidenceError,
    PdfPageRenderer,
    PixelBox,
    RenderedPage,
    RenderProfile,
    ScriptedOcrAdapter,
    SourceEvidenceFragment,
    TextFragment,
    source_fragment_sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_PNG = b"\x89PNG\r\n\x1a\n" + b"deterministic-payload"


def _box(x0: int = 0, y0: int = 0, x1: int = 100, y1: int = 200) -> PixelBox:
    return PixelBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _normalized(
    x0: float = 0.0, y0: float = 0.0, x1: float = 1.0, y1: float = 1.0
) -> NormalizedBox:
    return NormalizedBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _fragment(
    order: int = 0,
    text: str = "fragment text",
    box: PixelBox | None = None,
    confidence: float | None = None,
) -> TextFragment:
    return TextFragment(
        order=order,
        text=text,
        box=box if box is not None else _box(),
        confidence=confidence,
    )


def _page(**overrides: Any) -> RenderedPage:
    values: dict[str, Any] = {
        "physical_page": 1,
        "width": 100,
        "height": 200,
        "dpi": 150,
        "png_bytes": _PNG,
        "renderer_name": "pdfium",
        "renderer_version": "1.0",
    }
    values.update(overrides)
    return RenderedPage.model_validate(values)


def _request(**overrides: Any) -> OcrRequest:
    values: dict[str, Any] = {
        "physical_page": 3,
        "width": 100,
        "height": 200,
        "png_bytes": _PNG,
        "language": "",
        "profile": {},
    }
    values.update(overrides)
    return OcrRequest.model_validate(values)


def _ocr_result(**overrides: Any) -> OcrPageResult:
    values: dict[str, Any] = {
        "physical_page": 3,
        "width": 100,
        "height": 200,
        "fragments": [_fragment(confidence=0.9)],
        "engine_name": "paddle",
        "engine_version": "3.0",
    }
    values.update(overrides)
    return OcrPageResult.model_validate(values)


def _evidence(**overrides: Any) -> SourceEvidenceFragment:
    values: dict[str, Any] = {
        "physical_page": 5,
        "box": _normalized(),
        "text": "fragment text",
        "origin": "embedded_text",
        "confidence": None,
        "engine_name": "pdfium",
        "engine_version": "1.0",
    }
    values.update(overrides)
    values["fragment_sha256"] = source_fragment_sha256(
        values["physical_page"],
        values["box"],
        values["text"],
        values["origin"],
        values["engine_name"],
        values["engine_version"],
    )
    return SourceEvidenceFragment.model_validate(values)


# ---------------------------------------------------------------------------
# NormalizedBox
# ---------------------------------------------------------------------------


def test_normalized_box_valid_and_full_page() -> None:
    box = NormalizedBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
    assert (box.x0, box.y0, box.x1, box.y1) == (0.0, 0.0, 1.0, 1.0)
    partial = NormalizedBox(x0=0.1, y0=0.2, x1=0.9, y1=0.8)
    assert partial.x0 == 0.1


def test_normalized_box_accepts_integer_json_numbers() -> None:
    box = NormalizedBox.model_validate({"x0": 0, "y0": 0, "x1": 1, "y1": 1})
    assert box.x0 == 0.0 and box.x1 == 1.0


def test_normalized_box_rejects_strings_bools_and_unknown_fields() -> None:
    for bad in ("0", True, None):
        with pytest.raises(ValidationError):
            NormalizedBox(x0=cast(Any, bad), y0=0.0, x1=1.0, y1=1.0)
    with pytest.raises(ValidationError):
        NormalizedBox.model_validate({"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0, "z": 0.5})


def test_normalized_box_rejects_non_finite_and_out_of_range() -> None:
    for bad in (float("nan"), float("inf"), float("-inf"), -0.1, 1.1):
        with pytest.raises(ValidationError):
            NormalizedBox(x0=cast(Any, bad), y0=0.0, x1=1.0, y1=1.0)


def test_normalized_box_requires_positive_area() -> None:
    with pytest.raises(ValidationError):
        NormalizedBox(x0=0.5, y0=0.0, x1=0.5, y1=1.0)
    with pytest.raises(ValidationError):
        NormalizedBox(x0=0.0, y0=0.5, x1=1.0, y1=0.5)
    with pytest.raises(ValidationError):
        NormalizedBox(x0=0.5, y0=0.0, x1=0.0, y1=1.0)


def test_normalized_box_json_round_trip() -> None:
    box = NormalizedBox.model_validate_json('{"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}')
    again = NormalizedBox.model_validate_json(box.model_dump_json())
    assert again == box


# ---------------------------------------------------------------------------
# PixelBox
# ---------------------------------------------------------------------------


def test_pixel_box_valid_and_strict_rejections() -> None:
    box = _box()
    assert (box.x0, box.y0, box.x1, box.y1) == (0, 0, 100, 200)
    for bad in (True, False, -1, 3.0, "3", None):
        with pytest.raises(ValidationError):
            PixelBox(x0=cast(Any, bad), y0=0, x1=100, y1=200)
    with pytest.raises(ValidationError):
        PixelBox.model_validate({"x0": 0, "y0": 0, "x1": 100, "y1": 200, "z": 1})


def test_pixel_box_requires_positive_area() -> None:
    with pytest.raises(ValidationError):
        PixelBox(x0=50, y0=0, x1=50, y1=200)
    with pytest.raises(ValidationError):
        PixelBox(x0=0, y0=100, x1=100, y1=100)
    with pytest.raises(ValidationError):
        PixelBox(x0=50, y0=0, x1=0, y1=200)


# ---------------------------------------------------------------------------
# TextFragment
# ---------------------------------------------------------------------------


def test_text_fragment_valid_with_and_without_confidence() -> None:
    embedded = _fragment(confidence=None)
    assert embedded.confidence is None
    ocr = _fragment(confidence=0.95)
    assert ocr.confidence == 0.95
    assert _fragment().model_dump() == _fragment().model_dump()


def test_text_fragment_order_bounds_and_bool_rejection() -> None:
    assert _fragment(order=0).order == 0
    assert _fragment(order=19999).order == 19999
    for bad in (-1, 20000):
        with pytest.raises(ValidationError):
            _fragment(order=cast(Any, bad))
    with pytest.raises(ValidationError):
        _fragment(order=cast(Any, True))


def test_text_fragment_text_constraints_and_verbatim_preservation() -> None:
    kept = _fragment(text="  keep  internal   whitespace  ")
    assert kept.text == "  keep  internal   whitespace  "
    non_ascii = _fragment(text="\u68cb\u4e66 \u7b2c1\u7ae0")
    assert non_ascii.text == "\u68cb\u4e66 \u7b2c1\u7ae0"
    for bad in ("", "   \n\t", "x" * 100_001):
        with pytest.raises(ValidationError):
            _fragment(text=cast(Any, bad))
    assert len(_fragment(text="x" * 100_000).text) == 100_000


def test_text_fragment_confidence_is_strict_finite_bounded() -> None:
    for ok in (0.0, 1.0, 0.5, 0):
        assert _fragment(confidence=ok).confidence == float(ok)
    for bad in (True, "0.5", -0.1, 1.5, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            _fragment(confidence=cast(Any, bad))


def test_text_fragment_rejects_unknown_fields_and_wrong_box() -> None:
    with pytest.raises(ValidationError):
        TextFragment.model_validate(
            {"order": 0, "text": "x", "box": _box(), "confidence": None, "extra": 1}
        )
    with pytest.raises(ValidationError):
        TextFragment.model_validate({"order": 0, "text": "x", "box": (0, 0, 100, 200)})
    with pytest.raises(ValidationError):
        TextFragment.model_validate({"order": 0, "text": "x", "box": {"x0": 0, "y0": 0, "x1": 100}})


def test_text_fragment_json_round_trip() -> None:
    fragment = TextFragment.model_validate_json(
        '{"order": 0, "text": "  spaced  ", "box": '
        '{"x0": 0, "y0": 0, "x1": 100, "y1": 200}, "confidence": 0.5}'
    )
    assert fragment.text == "  spaced  "
    again = TextFragment.model_validate_json(fragment.model_dump_json())
    assert again == fragment


# ---------------------------------------------------------------------------
# RenderProfile
# ---------------------------------------------------------------------------


def test_render_profile_exact_defaults() -> None:
    profile = RenderProfile()
    assert profile.dpi == 150
    assert profile.max_side_px == 10_000
    assert profile.max_pixels == 40_000_000
    assert profile.max_png_bytes == 67_108_864
    assert profile.embedded_text_min_chars == 32


def test_render_profile_bounds_and_bool_rejection() -> None:
    assert RenderProfile(dpi=72).dpi == 72
    assert RenderProfile(dpi=600).dpi == 600
    for bad_dpi in (71, 601, True, 150.0, "150"):
        with pytest.raises(ValidationError):
            RenderProfile(dpi=cast(Any, bad_dpi))
    for field in ("max_side_px", "max_pixels", "max_png_bytes", "embedded_text_min_chars"):
        with pytest.raises(ValidationError):
            RenderProfile(**{field: 0})
        with pytest.raises(ValidationError):
            RenderProfile(**{field: cast(Any, True)})
    with pytest.raises(ValidationError):
        RenderProfile.model_validate(RenderProfile().model_dump() | {"extra": 1})


# ---------------------------------------------------------------------------
# RenderedPage
# ---------------------------------------------------------------------------


def test_rendered_page_valid_minimal() -> None:
    page = _page()
    assert page.physical_page == 1
    assert (page.width, page.height) == (100, 200)
    assert page.dpi == 150
    assert page.png_bytes == _PNG
    assert page.embedded_fragments == []
    assert page.renderer_name == "pdfium"


def test_rendered_page_physical_dimension_and_dpi_constraints() -> None:
    for bad in (0, -1, True):
        with pytest.raises(ValidationError):
            _page(physical_page=cast(Any, bad))
    for field in ("width", "height"):
        for dim_bad in (0, -1, True, 100.0):
            with pytest.raises(ValidationError):
                _page(**{field: cast(Any, dim_bad)})
    for bad_dpi in (71, 601):
        with pytest.raises(ValidationError):
            _page(dpi=bad_dpi)


def test_rendered_page_png_bytes_nonempty_bounded() -> None:
    with pytest.raises(ValidationError):
        _page(png_bytes=b"")
    with pytest.raises(ValidationError):
        _page(png_bytes=b"x" * (MAX_PNG_BYTES + 1))
    assert len(_page(png_bytes=b"x" * MAX_PNG_BYTES).png_bytes) == MAX_PNG_BYTES


def test_rendered_page_fragment_orders_contiguous_unique_from_zero() -> None:
    assert (
        len(_page(embedded_fragments=[_fragment(0), _fragment(1), _fragment(2)]).embedded_fragments)
        == 3
    )
    for bad_orders in ([0, 2], [1, 2], [0, 0], [2, 0]):
        with pytest.raises(ValidationError):
            _page(embedded_fragments=[_fragment(order=o) for o in bad_orders])
    with pytest.raises(ValidationError):
        _page(embedded_fragments=(_fragment(0),))  # tuple coercion rejected


def test_rendered_page_fragment_boxes_inside_dimensions() -> None:
    _page(embedded_fragments=[_fragment(box=_box(x1=100, y1=200))])
    with pytest.raises(ValidationError):
        _page(embedded_fragments=[_fragment(box=_box(x1=101))])
    with pytest.raises(ValidationError):
        _page(embedded_fragments=[_fragment(box=_box(y1=201))])


def test_rendered_page_pixel_area_limit() -> None:
    assert _page(width=8000, height=5000).width * 5000 == 40_000_000
    with pytest.raises(ValidationError):
        _page(width=7000, height=6000)


def test_rendered_page_embedded_fragments_require_null_confidence() -> None:
    with pytest.raises(ValidationError, match="null confidence"):
        _page(embedded_fragments=[_fragment(confidence=0.9)])


def test_rendered_page_renderer_name_version_limits() -> None:
    assert _page(renderer_name="  pdfium  ").renderer_name == "pdfium"
    for field in ("renderer_name", "renderer_version"):
        for bad in ("", "   ", "x" * 101):
            with pytest.raises(ValidationError):
                _page(**{field: bad})
    _page(renderer_version="x" * 100)


def test_rendered_page_preserves_bytes_and_text_exactly() -> None:
    png = b"\x00\x01\x02binary" + b"tail"
    page = _page(png_bytes=png, embedded_fragments=[_fragment(text="  spaced  ")])
    assert page.png_bytes == png
    assert page.embedded_fragments[0].text == "  spaced  "


def test_rendered_page_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _page(path="/tmp/absolute")


def test_rendered_page_is_frozen() -> None:
    page = _page()
    with pytest.raises(ValidationError, match="frozen"):
        page.width = 999


# ---------------------------------------------------------------------------
# OcrRequest
# ---------------------------------------------------------------------------


def test_ocr_request_valid_defaults() -> None:
    request = _request()
    assert request.language == ""
    assert request.profile == {}
    assert request.physical_page == 3
    assert request.png_bytes == _PNG


def test_ocr_request_same_page_dimension_and_png_constraints() -> None:
    for bad in (0, True):
        with pytest.raises(ValidationError):
            _request(physical_page=cast(Any, bad))
    for field in ("width", "height"):
        with pytest.raises(ValidationError):
            _request(**{field: 0})
    with pytest.raises(ValidationError):
        _request(png_bytes=b"")
    with pytest.raises(ValidationError):
        _request(png_bytes=b"x" * (MAX_PNG_BYTES + 1))
    assert _request(width=8000, height=5000).width == 8000
    with pytest.raises(ValidationError, match="pixel area"):
        _request(width=7000, height=6000)


def test_ocr_request_language_trimmed_and_max_64() -> None:
    assert _request(language="  ch  ").language == "ch"
    assert len(_request(language="x" * 64).language) == 64
    with pytest.raises(ValidationError):
        _request(language="x" * 65)
    with pytest.raises(ValidationError):
        _request(language=cast(Any, 5))


def test_ocr_request_profile_deep_copy_isolation() -> None:
    profile: dict[str, Any] = {"a": [1, {"b": 2.5}], "c": "x", "d": None, "e": True}
    request = _request(profile=profile)
    profile["a"][1]["b"] = 999
    profile["c"] = "MUTATED"
    assert request.profile == {"a": [1, {"b": 2.5}], "c": "x", "d": None, "e": True}


def test_ocr_request_profile_rejects_nested_non_finite() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError, match="finite JSON numbers"):
            _request(profile={"root": {"nested": [1, bad]}})


def test_ocr_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _request(**{"png_path": "/tmp/x.png"})


# ---------------------------------------------------------------------------
# OcrPageResult
# ---------------------------------------------------------------------------


def test_ocr_page_result_valid_and_requires_confidence() -> None:
    result = _ocr_result()
    assert result.physical_page == 3
    assert result.fragments[0].confidence == 0.9
    with pytest.raises(ValidationError, match="confidence"):
        _ocr_result(fragments=[_fragment(confidence=None)])


def test_ocr_page_result_order_count_and_box_bounds() -> None:
    _ocr_result(fragments=[_fragment(0, confidence=0.9), _fragment(1, confidence=0.8)])
    for bad_orders in ([0, 2], [1], [0, 0]):
        with pytest.raises(ValidationError):
            _ocr_result(fragments=[_fragment(o, confidence=0.9) for o in bad_orders])
    with pytest.raises(ValidationError):
        _ocr_result(fragments=[_fragment(box=_box(x1=101), confidence=0.9)])
    assert _ocr_result(width=8000, height=5000, fragments=[]).width == 8000
    with pytest.raises(ValidationError, match="pixel area"):
        _ocr_result(width=7000, height=6000, fragments=[])


def test_ocr_page_result_engine_limits_and_unknown_fields() -> None:
    assert _ocr_result(engine_name="  paddle  ").engine_name == "paddle"
    for field in ("engine_name", "engine_version"):
        for bad in ("", "   ", "x" * 101):
            with pytest.raises(ValidationError):
                _ocr_result(**{field: bad})
    with pytest.raises(ValidationError):
        _ocr_result(**{"raw_body": "provider bytes"})


def test_ocr_page_result_is_frozen() -> None:
    result = _ocr_result()
    with pytest.raises(ValidationError, match="frozen"):
        result.width = 999


# ---------------------------------------------------------------------------
# SourceEvidenceFragment + canonical hash
# ---------------------------------------------------------------------------


def test_source_evidence_fragment_valid_both_origins() -> None:
    embedded = _evidence()
    assert embedded.origin == "embedded_text"
    assert embedded.confidence is None
    assert len(embedded.fragment_sha256) == 64
    ocr = _evidence(origin="ocr", confidence=0.88)
    assert ocr.origin == "ocr"
    assert ocr.confidence == 0.88


def test_source_fragment_sha256_is_stable_and_content_bound() -> None:
    box = _normalized(0.1, 0.2, 0.9, 0.8)
    first = source_fragment_sha256(5, box, "  text  ", "embedded_text", "pdfium", "1.0")
    second = source_fragment_sha256(5, box, "  text  ", "embedded_text", "pdfium", "1.0")
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first) is not None
    for field, value in [
        ("physical_page", 6),
        ("text", "other"),
        ("origin", "ocr"),
        ("engine_name", "other"),
        ("engine_version", "2.0"),
    ]:
        if field == "physical_page":
            assert (
                source_fragment_sha256(
                    cast(int, value), box, "  text  ", "embedded_text", "pdfium", "1.0"
                )
                != first
            )
        elif field == "text":
            assert (
                source_fragment_sha256(5, box, cast(str, value), "embedded_text", "pdfium", "1.0")
                != first
            )
        elif field == "origin":
            assert (
                source_fragment_sha256(5, box, "  text  ", cast(Any, value), "pdfium", "1.0")
                != first
            )
        elif field == "engine_name":
            assert (
                source_fragment_sha256(5, box, "  text  ", "embedded_text", cast(str, value), "1.0")
                != first
            )
        else:
            assert (
                source_fragment_sha256(
                    5, box, "  text  ", "embedded_text", "pdfium", cast(str, value)
                )
                != first
            )


def test_source_evidence_hash_mismatch_rejected() -> None:
    values: dict[str, Any] = {
        "physical_page": 5,
        "box": _normalized(),
        "text": "fragment text",
        "origin": "embedded_text",
        "confidence": None,
        "engine_name": "pdfium",
        "engine_version": "1.0",
        "fragment_sha256": "0" * 64,
    }
    with pytest.raises(ValidationError, match="fragment_sha256"):
        SourceEvidenceFragment.model_validate(values)


def test_source_evidence_hash_includes_non_ascii_text_verbatim() -> None:
    digest = source_fragment_sha256(
        5, _normalized(), "\u68cb\u4e66 \u7b2c1\u7ae0", "embedded_text", "pdfium", "1.0"
    )
    fragment = _evidence(text="\u68cb\u4e66 \u7b2c1\u7ae0")
    assert fragment.fragment_sha256 == digest
    assert fragment.text == "\u68cb\u4e66 \u7b2c1\u7ae0"


def test_source_evidence_origin_confidence_rule() -> None:
    with pytest.raises(ValidationError, match="confidence"):
        _evidence(origin="ocr", confidence=None)
    with pytest.raises(ValidationError, match="confidence"):
        _evidence(origin="embedded_text", confidence=0.5)
    with pytest.raises(ValidationError):
        _evidence(origin="handwritten")


def test_source_evidence_fragment_sha256_format() -> None:
    for bad in ("A" * 64, "0" * 63, "0" * 65, "g" * 64, ""):
        with pytest.raises(ValidationError):
            SourceEvidenceFragment.model_validate(
                {
                    "physical_page": 5,
                    "box": _normalized(),
                    "text": "x",
                    "origin": "embedded_text",
                    "confidence": None,
                    "engine_name": "pdfium",
                    "engine_version": "1.0",
                    "fragment_sha256": bad,
                }
            )


def test_source_evidence_json_round_trip() -> None:
    fragment = _evidence(origin="ocr", confidence=0.7)
    again = SourceEvidenceFragment.model_validate_json(fragment.model_dump_json())
    assert again == fragment


def test_source_evidence_rejects_unknown_fields_and_is_frozen() -> None:
    with pytest.raises(ValidationError):
        _evidence(**{"raw_text": "secret"})
    fragment = _evidence()
    with pytest.raises(ValidationError, match="frozen"):
        fragment.text = "mutated"


# ---------------------------------------------------------------------------
# PdfEvidenceError
# ---------------------------------------------------------------------------


def test_pdf_evidence_error_fields_and_string_form() -> None:
    error = PdfEvidenceError("ocr_unavailable", "OCR engine is unavailable", True)
    assert error.code == "ocr_unavailable"
    assert error.message == "OCR engine is unavailable"
    assert error.retryable is True
    assert str(error) == "OCR engine is unavailable"
    assert isinstance(error, RuntimeError)
    permanent = PdfEvidenceError("render_failed", "page could not be rendered", False)
    assert permanent.retryable is False


def test_pdf_evidence_error_constructor_validation() -> None:
    for bad_code in ("", "   ", 123, None):
        with pytest.raises(ValueError):
            PdfEvidenceError(cast(Any, bad_code), "message", False)
    for bad_message in ("", "   ", 123, None):
        with pytest.raises(ValueError):
            PdfEvidenceError("render_failed", cast(Any, bad_message), False)
    for bad_retryable in ("yes", 0, 1, None):
        with pytest.raises(TypeError, match="actual bool"):
            PdfEvidenceError("render_failed", "message", cast(Any, bad_retryable))


def test_pdf_evidence_error_has_no_raw_content_field_and_deepcopy_is_safe() -> None:
    error = PdfEvidenceError("render_failed", "clean message", False)
    assert not hasattr(error, "body")
    assert not hasattr(error, "path")
    assert not hasattr(error, "raw")
    assert set(vars(error)) == {"code", "message", "retryable"}
    cloned = copy.deepcopy(error)
    assert cloned is not error
    assert cloned.code == error.code and cloned.message == error.message
    assert cloned.retryable == error.retryable


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


def test_pdf_page_renderer_protocol_runtime_check() -> None:
    class GoodRenderer:
        def render_page(
            self, pdf_bytes: bytes, physical_page: int, profile: RenderProfile
        ) -> RenderedPage:
            return _page(physical_page=physical_page)

    class MissingRenderer:
        pass

    conforming_renderer: PdfPageRenderer = GoodRenderer()
    assert isinstance(conforming_renderer, PdfPageRenderer)
    assert isinstance(GoodRenderer(), PdfPageRenderer)
    assert not isinstance(MissingRenderer(), PdfPageRenderer)
    assert not isinstance(42, PdfPageRenderer)


def test_ocr_adapter_protocol_runtime_check() -> None:
    class GoodAdapter:
        async def recognize(self, request: OcrRequest) -> OcrPageResult:
            return _ocr_result()

    class MissingAdapter:
        pass

    conforming_adapter: OcrAdapter = GoodAdapter()
    assert isinstance(conforming_adapter, OcrAdapter)
    assert isinstance(GoodAdapter(), OcrAdapter)
    assert not isinstance(MissingAdapter(), OcrAdapter)
    assert isinstance(ScriptedOcrAdapter([_ocr_result()]), OcrAdapter)


# ---------------------------------------------------------------------------
# ScriptedOcrAdapter
# ---------------------------------------------------------------------------


def test_scripted_ocr_fifo_success_and_accounting() -> None:
    adapter = ScriptedOcrAdapter(
        [
            _ocr_result(physical_page=1, fragments=[_fragment(text="one", confidence=0.9)]),
            _ocr_result(physical_page=2, fragments=[_fragment(text="two", confidence=0.8)]),
        ]
    )
    assert adapter.remaining == 2
    assert adapter.calls == ()
    assert isinstance(adapter.calls, tuple)

    async def run() -> None:
        first = await adapter.recognize(_request(physical_page=1))
        assert first.fragments[0].text == "one"
        assert adapter.remaining == 1
        second = await adapter.recognize(_request(physical_page=2))
        assert second.fragments[0].text == "two"

    asyncio.run(run())
    assert adapter.remaining == 0
    assert len(adapter.calls) == 2


def test_scripted_ocr_error_then_success() -> None:
    adapter = ScriptedOcrAdapter(
        [
            PdfEvidenceError("ocr_unavailable", "OCR engine is unavailable", True),
            _ocr_result(physical_page=3, fragments=[_fragment(text="recovered", confidence=0.9)]),
        ]
    )

    async def run() -> None:
        with pytest.raises(PdfEvidenceError) as excinfo:
            await adapter.recognize(_request(physical_page=3))
        assert excinfo.value.code == "ocr_unavailable"
        assert excinfo.value.retryable is True
        result = await adapter.recognize(_request(physical_page=3))
        assert result.fragments[0].text == "recovered"

    asyncio.run(run())
    assert adapter.remaining == 0
    assert len(adapter.calls) == 2


def test_scripted_ocr_exhaustion_raises_assertion_error() -> None:
    adapter = ScriptedOcrAdapter([_ocr_result()])

    async def run() -> None:
        await adapter.recognize(_request())
        assert adapter.remaining == 0
        with pytest.raises(AssertionError, match="exhausted"):
            await adapter.recognize(_request())

    asyncio.run(run())
    assert adapter.remaining == 0
    assert len(adapter.calls) == 2


def test_scripted_ocr_rejects_empty_and_invalid_outcomes() -> None:
    with pytest.raises(ValueError, match="at least one outcome"):
        ScriptedOcrAdapter([])
    with pytest.raises(TypeError, match="index 0"):
        ScriptedOcrAdapter(cast(Any, [123]))
    with pytest.raises(TypeError, match="index 1"):
        ScriptedOcrAdapter(cast(Any, [_ocr_result(), "bad", _ocr_result()]))
    # A finite generator iterable is accepted.
    adapter = ScriptedOcrAdapter(r for r in [_ocr_result()])
    assert adapter.remaining == 1


def test_scripted_ocr_request_snapshot_isolation() -> None:
    adapter = ScriptedOcrAdapter([_ocr_result()])
    request = _request(profile={"a": 1})

    async def run() -> None:
        await adapter.recognize(request)
        request.profile["a"] = 999

    asyncio.run(run())
    assert adapter.calls[0].profile == {"a": 1}


def test_scripted_ocr_result_copy_isolation() -> None:
    outcome = _ocr_result(fragments=[_fragment(text="original", confidence=0.9)])
    adapter = ScriptedOcrAdapter([outcome])

    async def run() -> None:
        returned = await adapter.recognize(_request())
        returned.fragments.clear()
        returned.fragments.append(_fragment(order=0, text="extra", confidence=0.1))

    asyncio.run(run())
    assert outcome.fragments[0].text == "original"
    assert len(outcome.fragments) == 1
    assert len(adapter.calls) == 1


def test_scripted_ocr_outcome_deep_copy_at_construction() -> None:
    first = _ocr_result(fragments=[_fragment(text="first", confidence=0.9)])
    second = _ocr_result(fragments=[_fragment(text="second", confidence=0.8)])
    adapter = ScriptedOcrAdapter([first, second])
    first.fragments.clear()

    async def run() -> None:
        returned = await adapter.recognize(_request())
        assert returned.fragments[0].text == "first"

    asyncio.run(run())


def test_scripted_ocr_calls_tuple_mutation_isolation() -> None:
    adapter = ScriptedOcrAdapter([_ocr_result()])

    async def run() -> None:
        await adapter.recognize(_request(profile={"k": "v"}))

    asyncio.run(run())
    first_view = adapter.calls
    first_view[0].profile["k"] = "MUTATED"
    assert adapter.calls[0].profile == {"k": "v"}


# ---------------------------------------------------------------------------
# Import purity and package exports
# ---------------------------------------------------------------------------


def test_evidence_module_imports_without_forbidden_modules() -> None:
    code = (
        "import importlib.util, sys; "
        "from pathlib import Path; "
        "path = Path('backend/src/chess_workbench/extraction/evidence.py'); "
        "spec = importlib.util.spec_from_file_location('_evidence_pure', path); "
        "mod = importlib.util.module_from_spec(spec); "
        "sys.modules['_evidence_pure'] = mod; "
        "spec.loader.exec_module(mod); "
        "forbidden = ('chess_workbench.store', 'chess_workbench.services', "
        "'chess_workbench.api', 'chess_workbench.schemas.domain', "
        "'chess_workbench.extraction.contracts', 'chess_workbench.extraction.provider', "
        "'chess_workbench.extraction.decoder', 'sqlalchemy', 'sanic', 'httpx', "
        "'aiohttp', 'requests', 'chess', 'subprocess'); "
        "bad = [m for m in forbidden if m in sys.modules]; "
        "print('bad=', bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"forbidden modules imported: {result.stdout}{result.stderr}"


def test_evidence_source_does_not_mention_forbidden_concepts() -> None:
    source = (
        REPO_ROOT / "backend" / "src" / "chess_workbench" / "extraction" / "evidence.py"
    ).read_text(encoding="utf-8")
    for token in (
        "httpx",
        "aiohttp",
        "requests",
        "sqlalchemy",
        "sanic",
        "pathlib",
        "subprocess",
        "sleep",
        "open(",
        "api_key",
        "ExtractionPackage",
    ):
        assert token not in source, f"evidence.py mentions {token!r}"


def test_package_exports_evidence_names() -> None:
    import chess_workbench.extraction as extraction

    for name in (
        "EvidenceOrigin",
        "NormalizedBox",
        "PixelBox",
        "TextFragment",
        "RenderProfile",
        "RenderedPage",
        "OcrRequest",
        "OcrPageResult",
        "SourceEvidenceFragment",
        "source_fragment_sha256",
        "PdfPageRenderer",
        "OcrAdapter",
        "PdfEvidenceError",
        "ScriptedOcrAdapter",
    ):
        assert getattr(extraction, name) is getattr(evidence_module, name), name
