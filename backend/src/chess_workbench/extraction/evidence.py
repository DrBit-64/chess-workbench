"""Strict evidence values and renderer/OCR ports for Stage 8B (ADR 0013).

This module owns the side-effect-free evidence contracts that Stage 8B-1
freezes: normalized/pixel boxes, text fragments, the render profile,
rendered pages, OCR request/result models, source-evidence fragments with a
canonical SHA-256, the renderer/OCR Protocols, the stable error model and
the deterministic scripted OCR fake.

It deliberately imports only the standard library and Pydantic: no chess,
HTTP, SQL, filesystem, provider/consumer or other extraction-module import
exists here.  Every object boundary rejects unknown fields and Python
coercions (strict mode, ``extra="forbid"``, frozen).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from typing import Annotated, Any, Literal, Protocol, Self, runtime_checkable

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_FRAGMENTS = 20_000
MAX_TEXT_CODE_POINTS = 100_000

EvidenceOrigin = Literal["embedded_text", "ocr", "diagram"]
PageEvidenceOrigin = Literal["embedded_text", "ocr", "mixed"]


def _reject_whitespace_only(value: str) -> str:
    """Reject empty/whitespace-only text while preserving the value verbatim."""
    if not value.strip():
        raise ValueError("value must not be empty or whitespace-only")
    return value


def _reject_non_finite_json(value: JsonValue) -> JsonValue:
    """Reject NaN/Infinity anywhere inside a JSON value (finite JSON numbers)."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("values must be finite JSON numbers")
        return value
    if isinstance(value, list):
        for item in value:
            _reject_non_finite_json(item)
        return value
    if isinstance(value, dict):
        for item in value.values():
            _reject_non_finite_json(item)
        return value
    return value


def _reject_non_finite_float(value: float | None) -> float | None:
    """Reject NaN/Infinity for strict float fields; ``None`` passes through."""
    if value is not None and not math.isfinite(value):
        raise ValueError("value must be a finite float")
    return value


FiniteJsonValue = Annotated[JsonValue, AfterValidator(_reject_non_finite_json)]


class _StrictModel(BaseModel):
    """Frozen strict object boundary shared by every evidence value."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class NormalizedBox(_StrictModel):
    """Page-normalized box with coordinates in ``[0, 1]`` and positive area."""

    x0: Annotated[float, Field(ge=0, le=1), AfterValidator(_reject_non_finite_float)]
    y0: Annotated[float, Field(ge=0, le=1), AfterValidator(_reject_non_finite_float)]
    x1: Annotated[float, Field(ge=0, le=1), AfterValidator(_reject_non_finite_float)]
    y1: Annotated[float, Field(ge=0, le=1), AfterValidator(_reject_non_finite_float)]

    @model_validator(mode="after")
    def _require_positive_area(self) -> Self:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("box must satisfy x0 < x1 and y0 < y1")
        return self


class PixelBox(_StrictModel):
    """Pixel box with strict nonnegative integer coordinates and positive area."""

    x0: Annotated[int, Field(ge=0)]
    y0: Annotated[int, Field(ge=0)]
    x1: Annotated[int, Field(ge=0)]
    y1: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _require_positive_area(self) -> Self:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("box must satisfy x0 < x1 and y0 < y1")
        return self


class TextFragment(_StrictModel):
    """One ordered text fragment with a pixel box and optional confidence."""

    order: Annotated[int, Field(ge=0, le=MAX_FRAGMENTS - 1)]
    # Whitespace-preserving: accepted text is never trimmed or rewritten.
    text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=MAX_TEXT_CODE_POINTS),
        AfterValidator(_reject_whitespace_only),
    ]
    box: PixelBox
    confidence: Annotated[
        float | None,
        Field(ge=0, le=1),
        AfterValidator(_reject_non_finite_float),
    ] = None


class EmbeddedPageImage(_StrictModel):
    """One decoded PDF image object bound to its rendered-page coordinates."""

    physical_page: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(ge=1, le=10_000)]
    height: Annotated[int, Field(ge=1, le=10_000)]
    page_box: PixelBox
    png_bytes: Annotated[bytes, Field(min_length=1, max_length=MAX_PNG_BYTES)]
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def _check_image(self) -> Self:
        _validate_pixel_area(self.width, self.height)
        if hashlib.sha256(self.png_bytes).hexdigest() != self.content_sha256:
            raise ValueError("content_sha256 does not match embedded image bytes")
        return self


class RenderProfile(_StrictModel):
    """Explicit deterministic rendering limits (defaults per ADR 0013)."""

    dpi: Annotated[int, Field(ge=72, le=600)] = 150
    max_side_px: Annotated[int, Field(ge=1)] = 10_000
    max_pixels: Annotated[int, Field(ge=1)] = 40_000_000
    max_png_bytes: Annotated[int, Field(ge=1)] = 67_108_864
    embedded_text_min_chars: Annotated[int, Field(ge=1)] = 32


def _validate_fragments(fragments: Sequence[TextFragment], width: int, height: int) -> None:
    """Enforce fragment order/count and pixel-box bounds shared by both ports."""
    if len(fragments) > MAX_FRAGMENTS:
        raise ValueError(f"at most {MAX_FRAGMENTS} fragments per page")
    orders = [fragment.order for fragment in fragments]
    if orders != list(range(len(fragments))):
        raise ValueError("fragment orders must be contiguous and unique starting from zero")
    for fragment in fragments:
        if fragment.box.x1 > width or fragment.box.y1 > height:
            raise ValueError("fragment pixel box must lie within the page dimensions")


def _validate_pixel_area(width: int, height: int) -> None:
    if width * height > MAX_PIXELS:
        raise ValueError(f"page pixel area exceeds the {MAX_PIXELS} pixel limit")


class RenderedPage(_StrictModel):
    """Deterministic page render: bytes, dimensions, DPI and embedded text."""

    physical_page: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(ge=1)]
    height: Annotated[int, Field(ge=1)]
    dpi: Annotated[int, Field(ge=72, le=600)]
    png_bytes: Annotated[bytes, Field(min_length=1, max_length=MAX_PNG_BYTES)]
    embedded_fragments: list[TextFragment] = Field(default_factory=list)
    embedded_images: list[EmbeddedPageImage] = Field(default_factory=list)
    renderer_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    renderer_version: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]

    @model_validator(mode="after")
    def _check_page(self) -> Self:
        _validate_pixel_area(self.width, self.height)
        _validate_fragments(self.embedded_fragments, self.width, self.height)
        if any(fragment.confidence is not None for fragment in self.embedded_fragments):
            raise ValueError("embedded-text fragments must have null confidence")
        if any(image.physical_page != self.physical_page for image in self.embedded_images):
            raise ValueError("embedded image physical page must match its rendered page")
        if any(
            image.page_box.x1 > self.width or image.page_box.y1 > self.height
            for image in self.embedded_images
        ):
            raise ValueError("embedded image box must lie within the page dimensions")
        return self


class OcrRequest(_StrictModel):
    """OCR port input: one page image with explicit page/dimensions/language."""

    physical_page: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(ge=1)]
    height: Annotated[int, Field(ge=1)]
    png_bytes: Annotated[bytes, Field(min_length=1, max_length=MAX_PNG_BYTES)]
    language: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)] = ""
    profile: dict[str, FiniteJsonValue] = Field(default_factory=dict)

    @field_validator("profile", mode="before")
    @classmethod
    def _snapshot_profile(cls, value: Any) -> Any:
        # Caller-owned snapshot: later mutation of the caller's dict cannot
        # change the request, and non-finite values are rejected recursively
        # by FiniteJsonValue after the copy.
        return copy.deepcopy(value)

    @model_validator(mode="after")
    def _check_page(self) -> Self:
        _validate_pixel_area(self.width, self.height)
        return self


class OcrPageResult(_StrictModel):
    """OCR port output: ordered OCR-only fragments for one physical page."""

    physical_page: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(ge=1)]
    height: Annotated[int, Field(ge=1)]
    fragments: list[TextFragment] = Field(default_factory=list)
    engine_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    engine_version: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]

    @model_validator(mode="after")
    def _check_result(self) -> Self:
        _validate_pixel_area(self.width, self.height)
        _validate_fragments(self.fragments, self.width, self.height)
        if any(fragment.confidence is None for fragment in self.fragments):
            raise ValueError("OCR fragments must carry a confidence score")
        return self


def source_fragment_sha256(
    physical_page: int,
    box: NormalizedBox,
    text: str,
    origin: EvidenceOrigin,
    engine_name: str,
    engine_version: str,
) -> str:
    """Canonical SHA-256 of one source-evidence fragment.

    The digest covers the compact sorted-key UTF-8 JSON array
    ``[physical_page, [x0, y0, x1, y1], text, origin, engine_name,
    engine_version]`` using the model's JSON numeric values, so the same
    fragment always produces the same lowercase 64-hex digest.
    """
    canonical = json.dumps(
        [
            physical_page,
            [box.x0, box.y0, box.x1, box.y1],
            text,
            origin,
            engine_name,
            engine_version,
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SourceEvidenceFragment(_StrictModel):
    """Immutable source-span candidate with a content-bound SHA-256."""

    physical_page: Annotated[int, Field(ge=1)]
    box: NormalizedBox
    text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=MAX_TEXT_CODE_POINTS),
        AfterValidator(_reject_whitespace_only),
    ]
    origin: EvidenceOrigin
    confidence: Annotated[
        float | None,
        Field(ge=0, le=1),
        AfterValidator(_reject_non_finite_float),
    ] = None
    engine_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    engine_version: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    fragment_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def _check_origin_confidence_rule(self) -> Self:
        if self.origin in {"ocr", "diagram"} and self.confidence is None:
            raise ValueError("OCR and diagram evidence fragments must carry a confidence score")
        if self.origin == "embedded_text" and self.confidence is not None:
            raise ValueError("embedded-text evidence fragments must have null confidence")
        return self

    @model_validator(mode="after")
    def _check_fragment_hash(self) -> Self:
        expected = source_fragment_sha256(
            self.physical_page,
            self.box,
            self.text,
            self.origin,
            self.engine_name,
            self.engine_version,
        )
        if expected != self.fragment_sha256:
            raise ValueError("fragment_sha256 does not match the canonical fragment content")
        return self


class PdfEvidenceError(RuntimeError):
    """Stable evidence error carrying only code, message and retryability.

    ``message`` is the only textual payload: raw PDF bytes, absolute paths
    and provider bodies are never stored on the error.
    """

    def __init__(self, code: str, message: str, retryable: bool) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be an actual bool")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def __str__(self) -> str:
        return self.message

    def __deepcopy__(self, memo: dict[int, Any]) -> PdfEvidenceError:
        return type(self)(self.code, self.message, self.retryable)


@runtime_checkable
class PdfPageRenderer(Protocol):
    """Sync renderer port: one PDF page to a validated ``RenderedPage``."""

    def render_page(
        self, pdf_bytes: bytes, physical_page: int, profile: RenderProfile
    ) -> RenderedPage: ...


@runtime_checkable
class OcrAdapter(Protocol):
    """Async OCR port: one validated page image to an ``OcrPageResult``."""

    async def recognize(self, request: OcrRequest) -> OcrPageResult: ...


class ScriptedOcrAdapter:
    """Deterministic sequential fake implementing the OCR port.

    Outcomes are consumed strictly in order; every call records a deep
    snapshot of the request and returns a deep copy of the result, or
    raises the scripted error.  Exhaustion raises ``AssertionError``.
    """

    def __init__(self, outcomes: Iterable[OcrPageResult | PdfEvidenceError]) -> None:
        validated: list[OcrPageResult | PdfEvidenceError] = []
        for index, outcome in enumerate(outcomes):
            if isinstance(outcome, (OcrPageResult, PdfEvidenceError)):
                validated.append(copy.deepcopy(outcome))
            else:
                raise TypeError(
                    f"outcome at index {index} must be an OcrPageResult or PdfEvidenceError, "
                    f"got {type(outcome).__name__}"
                )
        if not validated:
            raise ValueError("ScriptedOcrAdapter requires at least one outcome")
        self._outcomes = validated
        self._calls: list[OcrRequest] = []

    @property
    def calls(self) -> tuple[OcrRequest, ...]:
        # Fresh deep copies so callers can never mutate the internal
        # snapshots through a previously observed calls tuple.
        return tuple(copy.deepcopy(call) for call in self._calls)

    @property
    def remaining(self) -> int:
        return len(self._outcomes)

    async def recognize(self, request: OcrRequest) -> OcrPageResult:
        self._calls.append(copy.deepcopy(request))
        if not self._outcomes:
            raise AssertionError("ScriptedOcrAdapter exhausted: no outcomes remaining")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, PdfEvidenceError):
            raise outcome
        return copy.deepcopy(outcome)


__all__ = [
    "EvidenceOrigin",
    "PageEvidenceOrigin",
    "EmbeddedPageImage",
    "FiniteJsonValue",
    "MAX_FRAGMENTS",
    "MAX_PIXELS",
    "MAX_PNG_BYTES",
    "MAX_TEXT_CODE_POINTS",
    "NormalizedBox",
    "OcrAdapter",
    "OcrPageResult",
    "OcrRequest",
    "PdfEvidenceError",
    "PdfPageRenderer",
    "PixelBox",
    "RenderedPage",
    "RenderProfile",
    "ScriptedOcrAdapter",
    "SourceEvidenceFragment",
    "TextFragment",
    "source_fragment_sha256",
]
