"""Strict server-owned review document and ledger contracts.

Composes the immutable normalized CCEF package, the accepted 8D-1 inspection
and verified rendered-page descriptors.  Ledger responses expose immutable
revision/event metadata without server-owned CAS paths or candidate contents.
This module contains no routing, storage or SQL behavior.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, JsonValue, StringConstraints, field_validator, model_validator

from ..extraction.contracts import ExtractionPackage, ExtractionPackageV1_1, LocalId
from ..review.inspection import ReviewInspection, inspect_review_candidate
from .domain import (
    EntityId,
    Nag,
    Sha256,
    StrictContract,
    Title,
    UciMove,
    UtcDateTime,
    VersionNumber,
)

ReviewPageContentPath = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^/api/pdf-extractions/"
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            r"/review/pages/[1-9][0-9]*$"
        ),
        max_length=128,
    ),
]

ReviewPackage = Annotated[
    ExtractionPackage | ExtractionPackageV1_1,
    Field(discriminator="schema_version"),
]


class PdfReviewPageRead(StrictContract):
    physical_page: Annotated[int, Field(ge=1, le=20_000)]
    media_type: Literal["image/png"] = "image/png"
    byte_size: Annotated[int, Field(gt=0)]
    content_sha256: Sha256
    content_url: ReviewPageContentPath


class PdfReviewDocumentRead(StrictContract):
    run_id: EntityId
    normalized_ccef_sha256: Sha256
    package: ReviewPackage
    inspection: ReviewInspection
    pages: list[PdfReviewPageRead]

    @model_validator(mode="after")
    def _validate_review_document(self) -> PdfReviewDocumentRead:
        if self.package.package_id != self.run_id:
            raise ValueError("package_id does not match run_id")
        page_range = self.package.source.page_range
        if page_range is None:
            raise ValueError("source page range is missing")
        # Constant-extra-memory validation: CCEF page ranges are unbounded, so
        # never materialize or iterate a range-sized sequence.
        expected_count = page_range.end_page - page_range.start_page + 1
        if len(self.pages) != expected_count:
            raise ValueError(
                "page descriptors must cover the source range exactly once in ascending order"
            )
        for index, page in enumerate(self.pages):
            if page.physical_page != page_range.start_page + index:
                raise ValueError(
                    "page descriptors must cover the source range exactly once in ascending order"
                )
        run_path = str(self.run_id)
        for page in self.pages:
            expected_url = f"/api/pdf-extractions/{run_path}/review/pages/{page.physical_page}"
            if page.content_url != expected_url:
                raise ValueError("page content_url does not match the run and physical page")
        # Recompute live; the accepted inspection's normalized-candidate error
        # (ValueError) propagates instead of being hidden.
        if self.inspection != inspect_review_candidate(self.package):
            raise ValueError("inspection does not match the current review candidate")
        return self


def _finite_decisions(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if not _is_finite_json(value):
        raise ValueError("review decisions must contain finite JSON values")
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


class PdfReviewRevisionRead(StrictContract):
    id: EntityId
    parent_revision_id: EntityId | None
    revision_number: VersionNumber
    package_sha256: Sha256
    created_at: UtcDateTime


class PdfReviewEventRead(StrictContract):
    id: EntityId
    revision_id: EntityId
    parent_version: Annotated[int, Field(ge=0)]
    resulting_version: VersionNumber
    kind: Literal["created", "edited", "acknowledged", "approved", "rejected", "reopened"]
    decisions: dict[str, JsonValue]
    created_at: UtcDateTime

    _validate_decisions = field_validator("decisions")(_finite_decisions)

    @model_validator(mode="after")
    def version_transition_must_be_contiguous(self) -> PdfReviewEventRead:
        if self.resulting_version != self.parent_version + 1:
            raise ValueError("review event version transition must be contiguous")
        return self


class PdfReviewSessionRead(StrictContract):
    id: EntityId
    target_kind: Literal["extraction_run", "document"]
    target_id: EntityId
    baseline_normalized_ccef_sha256: Sha256
    status: Literal["open", "approved", "rejected"]
    version: VersionNumber
    revisions: list[PdfReviewRevisionRead]
    events: list[PdfReviewEventRead]
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @model_validator(mode="after")
    def ledger_must_be_contiguous(self) -> PdfReviewSessionRead:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        expected = list(range(1, self.version + 1))
        if [revision.revision_number for revision in self.revisions] != expected:
            raise ValueError("review revisions must exactly cover the session version")
        if [event.resulting_version for event in self.events] != expected:
            raise ValueError("review events must exactly cover the session version")
        if [event.parent_version for event in self.events] != list(range(self.version)):
            raise ValueError("review event parent versions must be contiguous")
        if [event.revision_id for event in self.events] != [
            revision.id for revision in self.revisions
        ]:
            raise ValueError("review events must bind their matching revisions")
        if self.revisions[0].parent_revision_id is not None:
            raise ValueError("initial review revision cannot have a parent")
        for parent, revision in zip(self.revisions, self.revisions[1:], strict=False):
            if revision.parent_revision_id != parent.id:
                raise ValueError("review revision parent chain is not contiguous")
        if self.revisions[0].package_sha256 != self.baseline_normalized_ccef_sha256:
            raise ValueError("initial review revision must match the baseline hash")
        return self


class PdfReviewSessionEnvelope(StrictContract):
    replayed: bool
    session: PdfReviewSessionRead


class PdfReviewExistingModuleTarget(StrictContract):
    kind: Literal["existing"]
    module_id: EntityId


class PdfReviewNewModuleTarget(StrictContract):
    kind: Literal["new"]
    title: Title


PdfReviewModuleTarget = Annotated[
    PdfReviewExistingModuleTarget | PdfReviewNewModuleTarget,
    Field(discriminator="kind"),
]


class PdfReviewPublicationPath(StrictContract):
    chapter: PdfReviewModuleTarget
    subsection: PdfReviewModuleTarget | None = None


class PdfReviewPublicationSegment(StrictContract):
    sequence_id: LocalId
    node_ids: list[LocalId] = Field(min_length=1, max_length=10_000)
    target: PdfReviewPublicationPath

    @field_validator("node_ids")
    @classmethod
    def node_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("publication node_ids must be unique")
        return value


class PdfReviewPublishRequest(StrictContract):
    expected_version: VersionNumber
    target_course_id: EntityId
    mapping_version: Literal["review-course-publication/1.1"] = "review-course-publication/1.1"
    segments: list[PdfReviewPublicationSegment] = Field(min_length=1, max_length=100)


class PdfReviewPublishedSegmentRead(StrictContract):
    sequence_id: LocalId
    chapter_module_id: EntityId
    subsection_module_id: EntityId | None
    target_module_id: EntityId
    occurrence_count: Annotated[int, Field(ge=1)]
    note_count: Annotated[int, Field(ge=0)]
    source_span_count: Annotated[int, Field(ge=0)]


class PdfReviewPublicationRead(StrictContract):
    publication_id: EntityId
    review_session_id: EntityId
    review_revision_number: VersionNumber
    target_course_id: EntityId
    mapping_version: Literal["review-course-publication/1.1"]
    plan_sha256: Sha256
    segments: list[PdfReviewPublishedSegmentRead]
    replayed: bool


class PdfReviewAddLine(StrictContract):
    kind: Literal["add_line"]
    sequence_id: LocalId
    parent_node_id: LocalId | None
    moves: list[UciMove] = Field(min_length=1, max_length=256)
    evidence_page: Annotated[int, Field(ge=1, le=20_000)]


class PdfReviewDeleteSubtree(StrictContract):
    kind: Literal["delete_subtree"]
    sequence_id: LocalId
    node_id: LocalId


class PdfReviewPromoteVariation(StrictContract):
    kind: Literal["promote_variation"]
    sequence_id: LocalId
    node_id: LocalId


class PdfReviewMakeMainline(StrictContract):
    kind: Literal["make_mainline"]
    sequence_id: LocalId
    node_id: LocalId


class PdfReviewEditText(StrictContract):
    kind: Literal["edit_text"]
    item_id: LocalId
    annotation_id: LocalId | None = None
    text: Annotated[str, StringConstraints(min_length=1, max_length=200_000)]
    text_format: Literal["plain", "markdown"] | None = None


class PdfReviewSetNag(StrictContract):
    kind: Literal["set_nag"]
    sequence_id: LocalId
    node_id: LocalId
    nag: Nag | None


class PdfReviewExcludeItem(StrictContract):
    kind: Literal["exclude_item"]
    item_id: LocalId


PdfReviewEditOperation = Annotated[
    PdfReviewAddLine
    | PdfReviewDeleteSubtree
    | PdfReviewPromoteVariation
    | PdfReviewMakeMainline
    | PdfReviewEditText
    | PdfReviewSetNag
    | PdfReviewExcludeItem,
    Field(discriminator="kind"),
]


class PdfReviewEditCommand(StrictContract):
    kind: Literal["edit"]
    operation: PdfReviewEditOperation


class PdfReviewAcknowledgeCommand(StrictContract):
    kind: Literal["acknowledge"]
    issue_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=512)]] = Field(
        min_length=1, max_length=1024
    )

    @field_validator("issue_ids")
    @classmethod
    def issue_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("issue_ids must be unique")
        return value


class PdfReviewApproveCommand(StrictContract):
    kind: Literal["approve"]


class PdfReviewRejectCommand(StrictContract):
    kind: Literal["reject"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class PdfReviewReopenCommand(StrictContract):
    kind: Literal["reopen"]
    reason: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ] = None


PdfReviewCommand = Annotated[
    PdfReviewEditCommand
    | PdfReviewAcknowledgeCommand
    | PdfReviewApproveCommand
    | PdfReviewRejectCommand
    | PdfReviewReopenCommand,
    Field(discriminator="kind"),
]


class PdfReviewCommandRequest(StrictContract):
    expected_version: VersionNumber
    command: PdfReviewCommand


class PdfReviewCommandEnvelope(StrictContract):
    session: PdfReviewSessionRead
    document: PdfReviewDocumentRead


__all__ = [
    "ReviewPageContentPath",
    "PdfReviewAcknowledgeCommand",
    "PdfReviewAddLine",
    "PdfReviewApproveCommand",
    "PdfReviewCommandEnvelope",
    "PdfReviewCommandRequest",
    "PdfReviewDeleteSubtree",
    "PdfReviewDocumentRead",
    "PdfReviewEditCommand",
    "PdfReviewEditOperation",
    "PdfReviewEditText",
    "PdfReviewExcludeItem",
    "PdfReviewEventRead",
    "PdfReviewMakeMainline",
    "PdfReviewPageRead",
    "PdfReviewPromoteVariation",
    "PdfReviewRejectCommand",
    "PdfReviewReopenCommand",
    "PdfReviewRevisionRead",
    "PdfReviewSetNag",
    "PdfReviewSessionEnvelope",
    "PdfReviewSessionRead",
]
