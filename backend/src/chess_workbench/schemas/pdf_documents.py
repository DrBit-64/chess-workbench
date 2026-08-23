"""Strict public contracts for incremental PDF extraction document identity."""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import Field, JsonValue, field_validator, model_validator

from chess_workbench.schemas.domain import (
    EntityId,
    Sha256,
    StrictContract,
    UtcDateTime,
    VersionNumber,
)
from chess_workbench.schemas.jobs import JobRead


def _finite_profile(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if not _is_finite_json(value):
        raise ValueError("profile must contain finite JSON values")
    return value


def _is_finite_json(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_finite_json(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_finite_json(item) for key, item in value.items())
    return False


class PdfExtractionDocumentCreate(StrictContract):
    initial_run_id: EntityId


class PdfExtractionDocumentAppendCreate(StrictContract):
    expected_version: VersionNumber
    first_page: Annotated[int, Field(ge=1, le=20_000)]
    last_page: Annotated[int, Field(ge=1, le=20_000)]
    profile: dict[str, JsonValue] = Field(default_factory=dict)

    _validate_profile = field_validator("profile")(_finite_profile)

    @model_validator(mode="after")
    def page_range_must_be_ordered(self) -> PdfExtractionDocumentAppendCreate:
        if self.last_page < self.first_page:
            raise ValueError("last_page must be greater than or equal to first_page")
        return self


class PdfExtractionDocumentSegmentRead(StrictContract):
    id: EntityId
    run_id: EntityId
    ordinal: Annotated[int, Field(ge=1)]
    first_page: Annotated[int, Field(ge=1)]
    last_page: Annotated[int, Field(ge=1)]
    normalized_ccef_sha256: Sha256
    created_at: UtcDateTime


class PdfExtractionDocumentRevisionRead(StrictContract):
    id: EntityId
    predecessor_revision_id: EntityId | None
    terminal_segment_id: EntityId
    revision_number: Annotated[int, Field(ge=1)]
    segment_count: Annotated[int, Field(ge=1)]
    first_page: Annotated[int, Field(ge=1)]
    last_page: Annotated[int, Field(ge=1)]
    algorithm_version: Annotated[str, Field(min_length=1, max_length=64)]
    normalized_ccef_sha256: Sha256
    created_at: UtcDateTime


class PdfExtractionDocumentAppendRead(StrictContract):
    id: EntityId
    run_id: EntityId
    predecessor_revision_id: EntityId
    expected_version: VersionNumber
    predecessor_normalized_ccef_sha256: Sha256
    first_page: Annotated[int, Field(ge=1)]
    last_page: Annotated[int, Field(ge=1)]
    pipeline_version: Annotated[str, Field(min_length=1, max_length=32)]
    profile: dict[str, JsonValue]
    job: JobRead
    created_at: UtcDateTime

    _validate_profile = field_validator("profile")(_finite_profile)


class PdfExtractionDocumentRead(StrictContract):
    id: EntityId
    pdf_asset_id: EntityId
    version: VersionNumber
    first_page: Annotated[int, Field(ge=1)]
    last_page: Annotated[int, Field(ge=1)]
    normalized_ccef_sha256: Sha256
    segments: list[PdfExtractionDocumentSegmentRead]
    revisions: list[PdfExtractionDocumentRevisionRead]
    append_attempts: list[PdfExtractionDocumentAppendRead]
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @model_validator(mode="after")
    def relations_must_match_head(self) -> PdfExtractionDocumentRead:
        if self.last_page < self.first_page:
            raise ValueError("document page range must be ordered")
        if len(self.segments) != self.version or len(self.revisions) != self.version:
            raise ValueError("document version must match committed segment and revision counts")
        if [item.ordinal for item in self.segments] != list(range(1, self.version + 1)):
            raise ValueError("document segment ordinals must be contiguous")
        if [item.revision_number for item in self.revisions] != list(range(1, self.version + 1)):
            raise ValueError("document revision numbers must be contiguous")
        head = self.revisions[-1]
        if (
            head.first_page != self.first_page
            or head.last_page != self.last_page
            or head.normalized_ccef_sha256 != self.normalized_ccef_sha256
        ):
            raise ValueError("document head must match its current revision")
        return self


class PdfExtractionDocumentEnvelope(StrictContract):
    replayed: bool
    document: PdfExtractionDocumentRead


class PdfExtractionDocumentAppendEnvelope(StrictContract):
    replayed: bool
    append: PdfExtractionDocumentAppendRead
    document: PdfExtractionDocumentRead


class PdfExtractionDocumentList(StrictContract):
    items: list[PdfExtractionDocumentRead]


__all__ = [
    "PdfExtractionDocumentAppendCreate",
    "PdfExtractionDocumentAppendEnvelope",
    "PdfExtractionDocumentAppendRead",
    "PdfExtractionDocumentCreate",
    "PdfExtractionDocumentEnvelope",
    "PdfExtractionDocumentList",
    "PdfExtractionDocumentRead",
    "PdfExtractionDocumentRevisionRead",
    "PdfExtractionDocumentSegmentRead",
]
