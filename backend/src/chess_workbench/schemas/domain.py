"""Strict HTTP contracts for the Stage 2 domain boundary.

These models intentionally contain no persistence or routing behavior.  Create
models describe client-owned input, read models describe server-owned state,
and update models require optimistic-concurrency versions.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

EntityId = UUID
VersionNumber = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RelativePath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10_000)]
Markdown = Annotated[str, StringConstraints(min_length=1, max_length=100_000)]
UciMove = Annotated[str, StringConstraints(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$", to_lower=True)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", to_lower=True)]
Nag = Annotated[int, Field(ge=0, le=255)]

SideToMove = Literal["w", "b"]
SourceKind = Literal["book", "video", "article", "web", "pgn", "game", "manual", "other"]
CourseStatus = Literal["draft", "published"]
CourseMode = Literal["traditional", "opening_explorer"]
HistoryEntityType = Literal[
    "course_module", "course_content_block", "course_occurrence", "knowledge_note"
]
ReviewStatus = Literal["draft", "approved", "rejected"]
NoteType = Literal[
    "general",
    "explanation",
    "plan",
    "candidate_comparison",
    "common_error",
    "memory_hint",
    "source_quote",
]
ErrorCode = Literal[
    "invalid_fen",
    "illegal_position",
    "invalid_uci",
    "illegal_move",
    "invalid_move",
    "not_found",
    "stale_version",
    "resource_referenced",
    "ambiguous_context",
    "validation_error",
    "payload_too_large",
    "unsupported_media_type",
    "invalid_pgn",
    "pgn_limit_exceeded",
    "idempotency_conflict",
    "course_mode_conflict",
    "pgn_not_exportable",
    "source_storage_unavailable",
    "engine_unavailable",
    "engine_failure",
]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(_as_utc)]


class StrictContract(BaseModel):
    """Base for deterministic request and response validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionedRead(StrictContract):
    id: EntityId
    version: VersionNumber
    created_at: UtcDateTime
    updated_at: UtcDateTime
    archived_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_timeline(self) -> VersionedRead:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.archived_at is not None and self.archived_at < self.created_at:
            raise ValueError("archived_at cannot precede created_at")
        return self


class ImmutableRead(StrictContract):
    """Server-owned immutable fact without PATCH lifecycle metadata."""

    id: EntityId
    created_at: UtcDateTime


class VersionedUpdate(StrictContract):
    """PATCH body with required optimistic concurrency and explicit changes."""

    expected_version: VersionNumber
    _non_nullable_updates: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def validate_changes(self) -> VersionedUpdate:
        changed = self.model_fields_set - {"expected_version"}
        if not changed:
            raise ValueError("at least one update field is required")
        for field_name in changed & self._non_nullable_updates:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ErrorResponse(StrictContract):
    """Stable machine-readable error shared by all Stage 2 endpoints."""

    code: ErrorCode
    message: NonEmptyText
    details: dict[str, JsonValue] | None = None


class PositionCreate(StrictContract):
    fen: NonEmptyText


class PositionRead(ImmutableRead):
    position_key: NonEmptyText
    canonical_fen: NonEmptyText
    piece_placement: NonEmptyText
    side_to_move: SideToMove
    castling_rights: str
    en_passant: str
    material_signature: NonEmptyText


class MoveCreate(StrictContract):
    from_position_id: EntityId
    uci: UciMove


class MoveRead(ImmutableRead):
    from_position_id: EntityId
    to_position_id: EntityId
    uci: UciMove
    san: NonEmptyText


# The persistence vocabulary calls the same immutable fact a MoveEdge.
MoveEdgeCreate = MoveCreate
MoveEdgeRead = MoveRead


class CourseCreate(StrictContract):
    title: Title
    description: Description = ""
    category: Title | None = None
    tags: list[Title] = Field(default_factory=list, max_length=50)
    status: CourseStatus = "draft"
    mode: CourseMode = "traditional"

    @field_validator("tags")
    @classmethod
    def tags_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("tags must be unique")
        return value


class CourseRead(VersionedRead):
    title: Title
    description: Description
    category: Title | None = None
    tags: list[Title]
    status: CourseStatus
    mode: CourseMode


class DashboardSummary(StrictContract):
    course_count: NonNegativeInt
    traditional_course_count: NonNegativeInt
    explorer_course_count: NonNegativeInt
    module_count: NonNegativeInt
    source_count: NonNegativeInt
    knowledge_note_count: NonNegativeInt
    position_count: NonNegativeInt
    recent_courses: list[CourseRead]


class CourseUpdate(VersionedUpdate):
    title: Title | None = None
    description: Description | None = None
    category: Title | None = None
    tags: list[Title] | None = Field(default=None, max_length=50)
    status: CourseStatus | None = None
    mode: CourseMode | None = None
    archived: bool | None = None
    _non_nullable_updates = frozenset(
        {"title", "description", "tags", "status", "mode", "archived"}
    )

    @field_validator("tags")
    @classmethod
    def tags_must_be_unique(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("tags must be unique")
        return value


class CourseModuleCreate(StrictContract):
    course_id: EntityId
    parent_id: EntityId | None = None
    title: Title
    description: Description = ""
    start_fen: NonEmptyText | None = None
    sort_order: NonNegativeInt = 0


class CourseModuleRead(VersionedRead):
    course_id: EntityId
    parent_id: EntityId | None = None
    title: Title
    description: Description
    start_occurrence_id: EntityId | None = None
    sort_order: NonNegativeInt


class CourseModuleUpdate(VersionedUpdate):
    parent_id: EntityId | None = None
    title: Title | None = None
    description: Description | None = None
    sort_order: NonNegativeInt | None = None
    archived: bool | None = None
    _non_nullable_updates = frozenset({"title", "description", "sort_order", "archived"})


ContentBlockKind = Literal["section_header", "narrative", "move_sequence", "knowledge_note"]


class CourseContentBlockCreate(StrictContract):
    module_id: EntityId
    kind: ContentBlockKind
    sort_order: NonNegativeInt
    heading: Title | None = None
    markdown: Markdown | None = None
    root_occurrence_id: EntityId | None = None
    knowledge_note_id: EntityId | None = None
    source_span_ids: list[EntityId] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def payload_matches_kind(self) -> CourseContentBlockCreate:
        present = {
            "heading": self.heading is not None,
            "markdown": self.markdown is not None,
            "root_occurrence_id": self.root_occurrence_id is not None,
            "knowledge_note_id": self.knowledge_note_id is not None,
        }
        expected = {
            "section_header": "heading",
            "narrative": "markdown",
            "move_sequence": "root_occurrence_id",
            "knowledge_note": "knowledge_note_id",
        }[self.kind]
        if present[expected] is not True or sum(present.values()) != 1:
            raise ValueError(f"{self.kind} requires only {expected}")
        if self.source_span_ids and self.kind != "narrative":
            raise ValueError("only narrative blocks may cite source spans")
        if len(self.source_span_ids) != len(set(self.source_span_ids)):
            raise ValueError("source_span_ids must be unique")
        return self


class CourseContentBlockRead(VersionedRead):
    module_id: EntityId
    kind: ContentBlockKind
    sort_order: NonNegativeInt
    heading: Title | None = None
    markdown: Markdown | None = None
    root_occurrence_id: EntityId | None = None
    knowledge_note_id: EntityId | None = None
    source_span_ids: list[EntityId]


class CourseContentBlockUpdate(VersionedUpdate):
    sort_order: NonNegativeInt | None = None
    heading: Title | None = None
    markdown: Markdown | None = None
    source_span_ids: list[EntityId] | None = Field(default=None, max_length=100)
    archived: bool | None = None
    _non_nullable_updates = frozenset({"sort_order", "archived"})

    @model_validator(mode="after")
    def only_editable_payload_may_be_supplied(self) -> CourseContentBlockUpdate:
        if self.heading is not None and self.markdown is not None:
            raise ValueError("a content block cannot contain both heading and markdown")
        if self.source_span_ids is not None and len(self.source_span_ids) != len(
            set(self.source_span_ids)
        ):
            raise ValueError("source_span_ids must be unique")
        return self


class CourseKnowledgeNoteBlockCreate(StrictContract):
    """Create one local position note and place it in a Module atomically."""

    occurrence_id: EntityId
    note_type: NoteType = "general"
    markdown: Markdown
    source_span_ids: list[EntityId] = Field(default_factory=list, max_length=100)
    review_status: ReviewStatus = "approved"

    @field_validator("source_span_ids")
    @classmethod
    def source_spans_must_be_unique(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("source_span_ids must be unique")
        return value


class SourceCreate(StrictContract):
    """Create a conceptual work; editions and files are separate resources."""

    kind: SourceKind
    title: Title
    author: Title | None = None
    description: Description = ""
    external_url: AnyHttpUrl | None = None


class SourceRead(VersionedRead):
    kind: SourceKind
    title: Title
    author: Title | None = None
    description: Description
    external_url: AnyHttpUrl | None = None


class SourceUpdate(VersionedUpdate):
    kind: SourceKind | None = None
    title: Title | None = None
    author: Title | None = None
    description: Description | None = None
    external_url: AnyHttpUrl | None = None
    archived: bool | None = None
    _non_nullable_updates = frozenset({"kind", "title", "description", "archived"})


class SourceVersionCreate(StrictContract):
    source_id: EntityId
    label: Title
    edition: Title | None = None
    published_on: date | None = None
    external_url: AnyHttpUrl | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class SourceVersionRead(VersionedRead):
    source_id: EntityId
    label: Title
    edition: Title | None = None
    published_on: date | None = None
    external_url: AnyHttpUrl | None = None
    metadata: dict[str, JsonValue]


class SourceVersionUpdate(VersionedUpdate):
    label: Title | None = None
    edition: Title | None = None
    published_on: date | None = None
    external_url: AnyHttpUrl | None = None
    metadata: dict[str, JsonValue] | None = None
    archived: bool | None = None
    _non_nullable_updates = frozenset({"label", "metadata", "archived"})


class SourceFileCreate(StrictContract):
    source_version_id: EntityId
    filename: Title
    relative_path: RelativePath
    media_type: NonEmptyText
    size_bytes: NonNegativeInt
    sha256: Sha256

    @field_validator("relative_path")
    @classmethod
    def path_must_be_safe_and_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("relative_path must be a safe POSIX relative path")
        return value


class SourceFileRead(VersionedRead):
    source_version_id: EntityId
    filename: Title
    relative_path: RelativePath
    media_type: NonEmptyText
    size_bytes: NonNegativeInt
    sha256: Sha256


class SourceFileUpdate(VersionedUpdate):
    archived: bool | None = None
    _non_nullable_updates = frozenset({"archived"})


class NormalizedBoundingBox(StrictContract):
    x0: Annotated[float, Field(ge=0, le=1)]
    y0: Annotated[float, Field(ge=0, le=1)]
    x1: Annotated[float, Field(ge=0, le=1)]
    y1: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def bounds_must_have_area(self) -> NormalizedBoundingBox:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("bounding box must have positive area")
        return self


class WholeSpan(StrictContract):
    kind: Literal["whole"] = "whole"


class PageSpan(StrictContract):
    kind: Literal["page"] = "page"
    page_number: Annotated[int, Field(ge=1)]
    bbox: NormalizedBoundingBox | None = None
    start_offset: NonNegativeInt | None = None
    end_offset: Annotated[int, Field(gt=0)] | None = None
    fragment_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def offsets_must_be_paired(self) -> PageSpan:
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("page text offsets must be provided together")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset <= self.start_offset
        ):
            raise ValueError("end_offset must be greater than start_offset")
        return self


class VideoSpan(StrictContract):
    kind: Literal["video"] = "video"
    start_ms: NonNegativeInt
    end_ms: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def end_must_follow_start(self) -> VideoSpan:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class TextSpan(StrictContract):
    kind: Literal["text"] = "text"
    start_offset: NonNegativeInt
    end_offset: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def end_must_follow_start(self) -> TextSpan:
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


SpanLocator = Annotated[WholeSpan | PageSpan | VideoSpan | TextSpan, Field(discriminator="kind")]


class SourceSpanCreate(StrictContract):
    source_version_id: EntityId
    source_file_id: EntityId | None = None
    locator: SpanLocator
    quote: Description | None = None
    ocr_text: Description | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None

    @model_validator(mode="after")
    def coordinates_require_a_file(self) -> SourceSpanCreate:
        if not isinstance(self.locator, WholeSpan) and self.source_file_id is None:
            raise ValueError("page, video, and text locators require source_file_id")
        return self


class SourceSpanRead(VersionedRead):
    source_version_id: EntityId
    source_file_id: EntityId | None = None
    locator: SpanLocator
    quote: Description | None = None
    ocr_text: Description | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None


class SourceSpanUpdate(VersionedUpdate):
    locator: SpanLocator | None = None
    quote: Description | None = None
    ocr_text: Description | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    archived: bool | None = None
    _non_nullable_updates = frozenset({"locator", "archived"})


class CitableSourceCreate(StrictContract):
    """Create a human-entered Source, first version, and whole-work span atomically."""

    kind: Literal["manual", "web"] = "manual"
    title: Title
    author: Title | None = None
    description: Description = ""
    external_url: AnyHttpUrl | None = None
    version_label: Title = "manual"
    quote: Description | None = None


class CitableSourceRead(StrictContract):
    source: SourceRead
    source_version: SourceVersionRead
    source_span: SourceSpanRead


class RootOccurrenceCreate(StrictContract):
    kind: Literal["root"] = "root"
    course_id: EntityId
    module_id: EntityId | None = None
    fen: NonEmptyText
    nag: Nag | None = None
    sort_order: NonNegativeInt = 0
    context: dict[str, JsonValue] = Field(default_factory=dict)


class OccurrenceMoveCreate(StrictContract):
    kind: Literal["move"] = "move"
    parent_occurrence_id: EntityId
    uci: UciMove
    nag: Nag | None = None
    sort_order: NonNegativeInt = 0
    context: dict[str, JsonValue] = Field(default_factory=dict)


OccurrenceCreate = Annotated[
    RootOccurrenceCreate | OccurrenceMoveCreate, Field(discriminator="kind")
]


class OccurrenceRead(VersionedRead):
    course_id: EntityId
    module_id: EntityId | None = None
    position_id: EntityId
    parent_id: EntityId | None = None
    inbound_move_edge_id: EntityId | None = None
    full_fen: NonEmptyText
    nag: Nag | None = None
    sort_order: NonNegativeInt
    context: dict[str, JsonValue]

    @model_validator(mode="after")
    def parent_and_move_must_form_a_pair(self) -> OccurrenceRead:
        if (self.parent_id is None) != (self.inbound_move_edge_id is None):
            raise ValueError("parent_id and inbound_move_edge_id must both be set or both be null")
        return self


class EditorOccurrenceRead(OccurrenceRead):
    inbound_uci: UciMove | None = None
    inbound_san: NonEmptyText | None = None

    @model_validator(mode="after")
    def move_labels_match_root_state(self) -> EditorOccurrenceRead:
        if (self.parent_id is None) != (self.inbound_uci is None):
            raise ValueError("root occurrences omit move labels; child occurrences require them")
        if (self.inbound_uci is None) != (self.inbound_san is None):
            raise ValueError("inbound_uci and inbound_san must form a pair")
        return self


class OccurrenceUpdate(VersionedUpdate):
    module_id: EntityId | None = None
    nag: Nag | None = None
    sort_order: NonNegativeInt | None = None
    context: dict[str, JsonValue] | None = None
    archived: bool | None = None
    _non_nullable_updates = frozenset({"sort_order", "context", "archived"})


CourseOccurrenceCreate = OccurrenceCreate
CourseOccurrenceRead = OccurrenceRead
CourseOccurrenceUpdate = OccurrenceUpdate


class OccurrenceNoteTarget(StrictContract):
    kind: Literal["occurrence"] = "occurrence"
    occurrence_id: EntityId


class GlobalPositionNoteTarget(StrictContract):
    kind: Literal["global_position"] = "global_position"
    position_id: EntityId


class GlobalMoveNoteTarget(StrictContract):
    kind: Literal["global_move"] = "global_move"
    move_edge_id: EntityId


NoteTarget = Annotated[
    OccurrenceNoteTarget | GlobalPositionNoteTarget | GlobalMoveNoteTarget,
    Field(discriminator="kind"),
]
GlobalNoteTarget = Annotated[
    GlobalPositionNoteTarget | GlobalMoveNoteTarget,
    Field(discriminator="kind"),
]


class KnowledgeNoteCreate(StrictContract):
    """Create a note; occurrence_id is the safe local default.

    A global note must omit occurrence_id and provide an explicitly global
    discriminated target, preventing accidental promotion of local commentary.
    """

    occurrence_id: EntityId | None = None
    target: GlobalNoteTarget | None = None
    source_note_id: EntityId | None = None
    note_type: NoteType = "general"
    markdown: Markdown | None = None
    source_span_ids: list[EntityId] = Field(default_factory=list, max_length=100)
    review_status: ReviewStatus = "approved"

    @model_validator(mode="after")
    def require_exactly_one_scope(self) -> KnowledgeNoteCreate:
        if (self.occurrence_id is None) == (self.target is None):
            raise ValueError("provide occurrence_id for a local note or one explicit global target")
        if len(self.source_span_ids) != len(set(self.source_span_ids)):
            raise ValueError("source_span_ids must be unique")
        if self.source_note_id is None and self.markdown is None:
            raise ValueError("an original knowledge note requires markdown")
        if self.source_note_id is not None:
            if self.occurrence_id is None:
                raise ValueError("a reference card must target an occurrence")
            if self.markdown is not None:
                raise ValueError(
                    "a reference card renders its source note and must not copy markdown"
                )
            if self.source_span_ids:
                raise ValueError("a reference card inherits citations from its source note")
        return self


class KnowledgeNoteRead(VersionedRead):
    target: NoteTarget
    source_note_id: EntityId | None = None
    note_type: NoteType
    markdown: Markdown | None = None
    source_span_ids: list[EntityId]
    review_status: ReviewStatus


class CourseKnowledgeNoteBlockRead(StrictContract):
    note: KnowledgeNoteRead
    block: CourseContentBlockRead


class KnowledgeNoteUpdate(VersionedUpdate):
    note_type: NoteType | None = None
    markdown: Markdown | None = None
    source_span_ids: list[EntityId] | None = Field(default=None, max_length=100)
    review_status: ReviewStatus | None = None
    archived: bool | None = None
    _non_nullable_updates = frozenset(
        {"note_type", "markdown", "source_span_ids", "review_status", "archived"}
    )

    @field_validator("source_span_ids")
    @classmethod
    def source_spans_must_be_unique(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("source_span_ids must be unique")
        return value


class EditorKnowledgeNoteRead(KnowledgeNoteRead):
    """An editor note plus its live rendered source when it is a reference card."""

    rendered_markdown: Markdown
    rendered_source_span_ids: list[EntityId]
    source_course_id: EntityId
    source_module_id: EntityId | None = None
    source_occurrence_id: EntityId


class CourseModuleEditorRead(StrictContract):
    module: CourseModuleRead
    content_blocks: list[CourseContentBlockRead]
    occurrences: list[EditorOccurrenceRead]
    notes: list[EditorKnowledgeNoteRead]


class ContentRevisionRead(ImmutableRead):
    entity_type: HistoryEntityType
    entity_id: EntityId
    entity_version: VersionNumber
    snapshot: dict[str, JsonValue]


class ContentHistoryRead(StrictContract):
    entity_type: HistoryEntityType
    entity_id: EntityId
    current_version: VersionNumber
    revisions: list[ContentRevisionRead]


class PublishModulesRequest(StrictContract):
    module_ids: list[EntityId] = Field(min_length=1, max_length=100)

    @field_validator("module_ids")
    @classmethod
    def module_ids_must_be_unique(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("module_ids must be unique")
        return value


class ModulePublicationRead(ImmutableRead):
    target_course_id: EntityId
    source_module_id: EntityId
    target_module_id: EntityId
    occurrence_count: NonNegativeInt
    note_count: NonNegativeInt
    replayed: bool


class PublishModulesRead(StrictContract):
    publications: list[ModulePublicationRead]
