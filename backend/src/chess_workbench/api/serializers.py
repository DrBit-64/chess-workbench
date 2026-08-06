"""Explicit ORM-to-contract mapping for the public Stage 2 API."""

from __future__ import annotations

from uuid import UUID

from pydantic import AnyHttpUrl

from chess_workbench.schemas.domain import (
    CourseModuleRead,
    CourseRead,
    GlobalMoveNoteTarget,
    GlobalPositionNoteTarget,
    KnowledgeNoteRead,
    MoveRead,
    NormalizedBoundingBox,
    OccurrenceNoteTarget,
    OccurrenceRead,
    PageSpan,
    PositionRead,
    SourceFileRead,
    SourceRead,
    SourceSpanRead,
    SourceVersionRead,
    TextSpan,
    VideoSpan,
    WholeSpan,
)
from chess_workbench.store.models import (
    Course,
    CourseModule,
    CourseOccurrence,
    KnowledgeNote,
    MoveEdge,
    Position,
    Source,
    SourceFile,
    SourceSpan,
    SourceVersion,
)


def position_read(value: Position) -> PositionRead:
    return PositionRead(
        id=value.id,
        created_at=value.created_at,
        position_key=value.position_key,
        canonical_fen=value.canonical_fen,
        piece_placement=value.piece_placement,
        side_to_move=value.side_to_move,  # type: ignore[arg-type]
        castling_rights=value.castling_rights,
        en_passant=value.en_passant,
        material_signature=value.material_signature,
    )


def move_read(value: MoveEdge) -> MoveRead:
    return MoveRead(
        id=value.id,
        created_at=value.created_at,
        from_position_id=value.from_position_id,
        to_position_id=value.to_position_id,
        uci=value.uci,
        san=value.san,
    )


def course_read(value: Course) -> CourseRead:
    return CourseRead(
        id=value.id,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        title=value.title,
        description=value.description,
        category=value.category,
        tags=value.tags,
        status=value.status,  # type: ignore[arg-type]
    )


def module_read(value: CourseModule, start_occurrence_id: UUID | None) -> CourseModuleRead:
    return CourseModuleRead(
        id=value.id,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        course_id=value.course_id,
        parent_id=value.parent_id,
        title=value.title,
        description=value.description,
        start_occurrence_id=start_occurrence_id,
        sort_order=value.sort_order,
    )


def occurrence_read(value: CourseOccurrence) -> OccurrenceRead:
    return OccurrenceRead(
        id=value.id,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        course_id=value.course_id,
        module_id=value.module_id,
        position_id=value.position_id,
        parent_id=value.parent_id,
        inbound_move_edge_id=value.inbound_move_edge_id,
        full_fen=value.full_fen,
        nag=value.nag,
        sort_order=value.sort_order,
        context=value.context,
    )


def source_read(value: Source) -> SourceRead:
    return SourceRead(
        id=value.id,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        kind=value.kind,  # type: ignore[arg-type]
        title=value.title,
        author=value.author,
        description=value.description,
        external_url=AnyHttpUrl(value.external_url) if value.external_url is not None else None,
    )


def source_version_read(value: SourceVersion) -> SourceVersionRead:
    return SourceVersionRead(
        id=value.id,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        source_id=value.source_id,
        label=value.label,
        edition=value.edition,
        published_on=value.published_on,
        external_url=AnyHttpUrl(value.external_url) if value.external_url is not None else None,
        metadata=value.extra_metadata,
    )


def source_file_read(value: SourceFile) -> SourceFileRead:
    return SourceFileRead(
        id=value.id,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        source_version_id=value.source_version_id,
        filename=value.filename,
        relative_path=value.relative_path,
        media_type=value.media_type,
        size_bytes=value.size_bytes,
        sha256=value.sha256,
    )


def source_span_read(value: SourceSpan) -> SourceSpanRead:
    locator: WholeSpan | PageSpan | VideoSpan | TextSpan
    if value.locator_kind == "whole":
        locator = WholeSpan()
    elif value.locator_kind == "page":
        locator = PageSpan(
            page_number=_required(value.page_number, "page_number"),
            bbox=(
                NormalizedBoundingBox.model_validate(value.bbox) if value.bbox is not None else None
            ),
        )
    elif value.locator_kind == "video":
        locator = VideoSpan(
            start_ms=_required(value.start_value, "start_value"),
            end_ms=_required(value.end_value, "end_value"),
        )
    elif value.locator_kind == "text":
        locator = TextSpan(
            start_offset=_required(value.start_value, "start_value"),
            end_offset=_required(value.end_value, "end_value"),
        )
    else:
        raise ValueError(f"unsupported persisted locator kind: {value.locator_kind}")

    return SourceSpanRead(
        id=value.id,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        source_version_id=value.source_version_id,
        source_file_id=value.source_file_id,
        locator=locator,
        quote=value.quote,
        ocr_text=value.ocr_text,
        confidence=value.confidence,
    )


def note_read(value: KnowledgeNote) -> KnowledgeNoteRead:
    target: OccurrenceNoteTarget | GlobalPositionNoteTarget | GlobalMoveNoteTarget
    if value.target_kind == "occurrence":
        target = OccurrenceNoteTarget(occurrence_id=_required(value.occurrence_id, "occurrence_id"))
    elif value.target_kind == "global_position":
        target = GlobalPositionNoteTarget(position_id=_required(value.position_id, "position_id"))
    elif value.target_kind == "global_move":
        target = GlobalMoveNoteTarget(move_edge_id=_required(value.move_edge_id, "move_edge_id"))
    else:
        raise ValueError(f"unsupported persisted note target: {value.target_kind}")

    return KnowledgeNoteRead(
        id=value.id,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        target=target,
        note_type=value.note_type,  # type: ignore[arg-type]
        markdown=value.markdown,
        source_span_ids=sorted((citation.source_span_id for citation in value.citations), key=str),
        review_status=value.review_status,  # type: ignore[arg-type]
    )


def _required[T](value: T | None, field: str) -> T:
    if value is None:
        raise ValueError(f"persisted {field} is unexpectedly null")
    return value
