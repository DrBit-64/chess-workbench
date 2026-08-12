"""Stage 8A PDF asset and extraction HTTP contracts.

The create models describe client-owned input, the read models describe
server-owned immutable receipts, and the envelopes wrap idempotent replay
results.  No relative/absolute storage path is ever exposed; profile values
are deep-copied and must be finite JSON numbers.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from chess_workbench.schemas.domain import (
    EntityId,
    NonEmptyText,
    Sha256,
    StrictContract,
    Title,
    UtcDateTime,
)
from chess_workbench.schemas.jobs import JobRead


def _require_ordered_page_range(first_page: int, last_page: int) -> None:
    if last_page < first_page:
        raise ValueError("last_page cannot be less than first_page")


def _deep_copy_json(value: JsonValue) -> JsonValue:
    """Recursively snapshot a JSON value and reject any non-finite number."""
    if isinstance(value, dict):
        return {key: _deep_copy_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("profile values must be finite numbers")
    return value


def _finite_profile(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: _deep_copy_json(item) for key, item in value.items()}


class PdfAssetUploadMetadata(StrictContract):
    title: Title | None = None
    author: Title | None = None
    edition: Title | None = None


class PdfExtractionCreate(StrictContract):
    pdf_asset_id: EntityId
    first_page: Annotated[int, Field(ge=1)]
    last_page: Annotated[int, Field(ge=1)]
    profile: dict[str, JsonValue] = Field(default_factory=dict)

    _validate_profile = field_validator("profile")(_finite_profile)

    @model_validator(mode="after")
    def page_range_must_be_ordered(self) -> PdfExtractionCreate:
        _require_ordered_page_range(self.first_page, self.last_page)
        return self


class PdfAssetRead(StrictContract):
    id: EntityId
    content_sha256: Sha256
    byte_size: Annotated[int, Field(gt=0)]
    page_count: Annotated[int, Field(ge=1, le=20_000)]
    source_id: EntityId
    source_version_id: EntityId
    source_file_id: EntityId
    filename: Title
    title: Title
    author: Title | None = None
    edition: Title | None = None
    created_at: UtcDateTime


class PdfAssetEnvelope(StrictContract):
    replayed: bool
    asset: PdfAssetRead


class PdfAssetList(StrictContract):
    items: list[PdfAssetRead]


class PdfEvidenceSummary(StrictContract):
    """Verified public summary of one fully committed Stage 8B artifact set."""

    status: Literal["committed"] = "committed"
    page_count: Annotated[int, Field(ge=1, le=20_000)]
    fragment_count: Annotated[int, Field(ge=0, le=200_000)]
    warning_count: Annotated[int, Field(ge=0, le=20_000)]
    render_manifest_sha256: Sha256
    ocr_manifest_sha256: Sha256


class PdfExtractionRead(StrictContract):
    id: EntityId
    pdf_asset_id: EntityId
    first_page: Annotated[int, Field(ge=1)]
    last_page: Annotated[int, Field(ge=1)]
    pipeline_version: NonEmptyText
    profile: dict[str, JsonValue]
    job: JobRead
    evidence: PdfEvidenceSummary | None = None
    has_conflicts: bool = False
    created_at: UtcDateTime

    _validate_profile = field_validator("profile")(_finite_profile)

    @model_validator(mode="after")
    def page_range_must_be_ordered(self) -> PdfExtractionRead:
        _require_ordered_page_range(self.first_page, self.last_page)
        return self


class PdfExtractionEnvelope(StrictContract):
    replayed: bool
    extraction: PdfExtractionRead


class PdfExtractionList(StrictContract):
    items: list[PdfExtractionRead]
