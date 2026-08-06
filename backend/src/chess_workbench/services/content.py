"""Transaction-neutral application service for Stage 2 content.

Every public method operates on the caller-owned ``AsyncSession`` and only
flushes.  API handlers (or import jobs) therefore control commit/rollback with
``async with session.begin()`` while composite occurrence writes remain
protected by savepoints.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, TypeVar, cast
from uuid import UUID

from pydantic import BaseModel, JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.domain import PositionError, PositionState
from chess_workbench.schemas.domain import (
    CourseCreate,
    CourseModuleCreate,
    CourseModuleRead,
    CourseModuleUpdate,
    CourseRead,
    CourseUpdate,
    ErrorCode,
    GlobalMoveNoteTarget,
    GlobalPositionNoteTarget,
    KnowledgeNoteCreate,
    KnowledgeNoteRead,
    KnowledgeNoteUpdate,
    NormalizedBoundingBox,
    OccurrenceMoveCreate,
    OccurrenceNoteTarget,
    OccurrenceRead,
    OccurrenceUpdate,
    PageSpan,
    RootOccurrenceCreate,
    SourceCreate,
    SourceFileCreate,
    SourceFileRead,
    SourceFileUpdate,
    SourceRead,
    SourceSpanCreate,
    SourceSpanRead,
    SourceSpanUpdate,
    SourceUpdate,
    SourceVersionCreate,
    SourceVersionRead,
    SourceVersionUpdate,
    TextSpan,
    VideoSpan,
    WholeSpan,
)
from chess_workbench.store.content_repository import (
    ContentRepository,
    RepositoryConflictError,
    RepositoryStaleVersionError,
)
from chess_workbench.store.graph_repository import get_or_create_move, get_or_create_position
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
    utc_now,
)


class ServiceError(RuntimeError):
    """Stable application error ready for an HTTP adapter."""

    def __init__(
        self,
        code: ErrorCode,
        status: int,
        message: str,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.message = message
        self.details = details
        super().__init__(message)


class _MutableRow(Protocol):
    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


RowT = TypeVar("RowT")


class ContentService:
    """Aggregate service used directly by API handlers and import jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ContentRepository(session)

    async def create_course(self, data: CourseCreate) -> CourseRead:
        row = Course(**data.model_dump(mode="python"))
        await self._add(row, "course")
        return self._course_read(row)

    async def get_course(
        self,
        course_id: UUID,
        *,
        include_archived: bool = False,
    ) -> CourseRead:
        row = self._require(
            await self.repository.get_course(course_id),
            "course",
            course_id,
            include_archived=include_archived,
        )
        return self._course_read(row)

    async def list_courses(self, *, include_archived: bool = False) -> list[CourseRead]:
        rows = await self.repository.list_courses(include_archived=include_archived)
        return [self._course_read(row) for row in rows]

    async def update_course(self, course_id: UUID, data: CourseUpdate) -> CourseRead:
        row = self._require(
            await self.repository.get_course(course_id),
            "course",
            course_id,
            include_archived=True,
        )
        await self._update_changes(row, data.expected_version, self._changes(data), "course")
        return self._course_read(row)

    async def create_module(self, data: CourseModuleCreate) -> CourseModuleRead:
        await self._active_course(data.course_id)
        if data.parent_id is not None:
            parent = await self._active_module(data.parent_id)
            self._same_parent("module", data.course_id, parent.course_id, data.parent_id)
        start_state = self._position_state(data.start_fen) if data.start_fen is not None else None

        async with self.session.begin_nested():
            row = CourseModule(
                course_id=data.course_id,
                parent_id=data.parent_id,
                title=data.title,
                description=data.description,
                sort_order=data.sort_order,
            )
            await self._add(row, "course_module")
            if start_state is not None:
                await self._create_root_row(
                    course_id=data.course_id,
                    module_id=row.id,
                    state=start_state,
                    nag=None,
                    sort_order=0,
                    context={},
                )
        return await self._module_read(row)

    async def get_module(
        self,
        module_id: UUID,
        *,
        include_archived: bool = False,
    ) -> CourseModuleRead:
        row = self._require(
            await self.repository.get_module(module_id),
            "course_module",
            module_id,
            include_archived=include_archived,
        )
        return await self._module_read(row)

    async def list_modules(
        self,
        course_id: UUID,
        *,
        parent_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list[CourseModuleRead]:
        self._require(
            await self.repository.get_course(course_id),
            "course",
            course_id,
            include_archived=include_archived,
        )
        rows = await self.repository.list_modules(
            course_id,
            parent_id=parent_id,
            include_archived=include_archived,
        )
        return [await self._module_read(row) for row in rows]

    async def update_module(
        self,
        module_id: UUID,
        data: CourseModuleUpdate,
    ) -> CourseModuleRead:
        row = self._require(
            await self.repository.get_module(module_id),
            "course_module",
            module_id,
            include_archived=True,
        )
        changes = self._changes(data)
        parent_id = cast(UUID | None, changes.get("parent_id", row.parent_id))
        if "parent_id" in changes and parent_id is not None:
            parent = await self._active_module(parent_id)
            self._same_parent("module", row.course_id, parent.course_id, parent_id)
            if await self.repository.module_parent_would_cycle(row.id, parent_id):
                raise self._ambiguous(
                    "course_module",
                    row.id,
                    "module parent would create a cycle",
                )
        await self._update_changes(row, data.expected_version, changes, "course_module")
        return await self._module_read(row)

    async def create_root_occurrence(self, data: RootOccurrenceCreate) -> OccurrenceRead:
        state = self._position_state(data.fen)
        await self._active_course(data.course_id)
        if data.module_id is not None:
            module = self._require(
                await self.repository.get_module(data.module_id, for_update=True),
                "course_module",
                data.module_id,
            )
            self._same_parent("module", data.course_id, module.course_id, data.module_id)
            roots = await self.repository.list_module_roots(data.module_id)
            if roots:
                raise self._ambiguous(
                    "course_module",
                    data.module_id,
                    "module already has a root occurrence",
                )

        async with self.session.begin_nested():
            row = await self._create_root_row(
                course_id=data.course_id,
                module_id=data.module_id,
                state=state,
                nag=data.nag,
                sort_order=data.sort_order,
                context=data.context,
            )
        return self._occurrence_read(row)

    async def create_move_occurrence(self, data: OccurrenceMoveCreate) -> OccurrenceRead:
        parent = await self._active_occurrence(data.parent_occurrence_id)
        before = self._position_state(parent.full_fen)

        try:
            async with self.session.begin_nested():
                stored_move = await get_or_create_move(self.session, before, data.uci)
                existing = await self.repository.find_child_occurrence(
                    parent.id,
                    stored_move.edge.id,
                )
                if existing is not None:
                    if (
                        existing.nag != data.nag
                        or existing.sort_order != data.sort_order
                        or existing.context != data.context
                    ):
                        raise self._ambiguous(
                            "course_occurrence",
                            existing.id,
                            "the same parent and move already exist with different context",
                        )
                    row = existing
                else:
                    row = CourseOccurrence(
                        course_id=parent.course_id,
                        module_id=parent.module_id,
                        parent_id=parent.id,
                        position_id=stored_move.target.id,
                        inbound_move_edge_id=stored_move.edge.id,
                        full_fen=stored_move.move.after.full_fen,
                        nag=data.nag,
                        sort_order=data.sort_order,
                        context=data.context,
                    )
                    await self._add(row, "course_occurrence")
        except PositionError as error:
            raise self._position_service_error(error) from error
        return self._occurrence_read(row)

    async def get_occurrence(
        self,
        occurrence_id: UUID,
        *,
        include_archived: bool = False,
    ) -> OccurrenceRead:
        row = self._require(
            await self.repository.get_occurrence(occurrence_id),
            "course_occurrence",
            occurrence_id,
            include_archived=include_archived,
        )
        return self._occurrence_read(row)

    async def list_occurrences(
        self,
        course_id: UUID,
        *,
        module_id: UUID | None = None,
        parent_id: UUID | None = None,
        roots_only: bool = False,
        include_archived: bool = False,
    ) -> list[OccurrenceRead]:
        self._require(
            await self.repository.get_course(course_id),
            "course",
            course_id,
            include_archived=include_archived,
        )
        if module_id is not None:
            module = self._require(
                await self.repository.get_module(module_id),
                "course_module",
                module_id,
                include_archived=include_archived,
            )
            self._same_parent("module", course_id, module.course_id, module_id)
        if parent_id is not None:
            parent = self._require(
                await self.repository.get_occurrence(parent_id),
                "course_occurrence",
                parent_id,
                include_archived=include_archived,
            )
            self._same_parent("occurrence", course_id, parent.course_id, parent_id)
        rows = await self.repository.list_occurrences(
            course_id,
            module_id=module_id,
            parent_id=parent_id,
            roots_only=roots_only,
            include_archived=include_archived,
        )
        return [self._occurrence_read(row) for row in rows]

    async def update_occurrence(
        self,
        occurrence_id: UUID,
        data: OccurrenceUpdate,
    ) -> OccurrenceRead:
        row = self._require(
            await self.repository.get_occurrence(occurrence_id),
            "course_occurrence",
            occurrence_id,
            include_archived=True,
        )
        changes = self._changes(data)
        if "module_id" in changes and changes["module_id"] is not None:
            module_id = cast(UUID, changes["module_id"])
            module = await self._active_module(module_id)
            self._same_parent("module", row.course_id, module.course_id, module_id)
        await self._update_changes(row, data.expected_version, changes, "course_occurrence")
        return self._occurrence_read(row)

    async def create_source(self, data: SourceCreate) -> SourceRead:
        row = Source(
            kind=data.kind,
            title=data.title,
            author=data.author,
            description=data.description,
            external_url=self._url(data.external_url),
        )
        await self._add(row, "source")
        return self._source_read(row)

    async def get_source(
        self,
        source_id: UUID,
        *,
        include_archived: bool = False,
    ) -> SourceRead:
        row = self._require(
            await self.repository.get_source(source_id),
            "source",
            source_id,
            include_archived=include_archived,
        )
        return self._source_read(row)

    async def list_sources(self, *, include_archived: bool = False) -> list[SourceRead]:
        rows = await self.repository.list_sources(include_archived=include_archived)
        return [self._source_read(row) for row in rows]

    async def update_source(self, source_id: UUID, data: SourceUpdate) -> SourceRead:
        row = self._require(
            await self.repository.get_source(source_id),
            "source",
            source_id,
            include_archived=True,
        )
        changes = self._changes(data)
        if "external_url" in changes:
            changes["external_url"] = self._url(changes["external_url"])
        await self._update_changes(row, data.expected_version, changes, "source")
        return self._source_read(row)

    async def create_source_version(self, data: SourceVersionCreate) -> SourceVersionRead:
        await self._active_source(data.source_id)
        row = SourceVersion(
            source_id=data.source_id,
            label=data.label,
            edition=data.edition,
            published_on=data.published_on,
            external_url=self._url(data.external_url),
            extra_metadata=data.metadata,
        )
        await self._add(row, "source_version")
        return self._source_version_read(row)

    async def get_source_version(
        self,
        version_id: UUID,
        *,
        include_archived: bool = False,
    ) -> SourceVersionRead:
        row = self._require(
            await self.repository.get_source_version(version_id),
            "source_version",
            version_id,
            include_archived=include_archived,
        )
        return self._source_version_read(row)

    async def list_source_versions(
        self,
        source_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[SourceVersionRead]:
        self._require(
            await self.repository.get_source(source_id),
            "source",
            source_id,
            include_archived=include_archived,
        )
        rows = await self.repository.list_source_versions(
            source_id,
            include_archived=include_archived,
        )
        return [self._source_version_read(row) for row in rows]

    async def update_source_version(
        self,
        version_id: UUID,
        data: SourceVersionUpdate,
    ) -> SourceVersionRead:
        row = self._require(
            await self.repository.get_source_version(version_id),
            "source_version",
            version_id,
            include_archived=True,
        )
        changes = self._changes(data)
        if "metadata" in changes:
            changes["extra_metadata"] = changes.pop("metadata")
        if "external_url" in changes:
            changes["external_url"] = self._url(changes["external_url"])
        await self._update_changes(row, data.expected_version, changes, "source_version")
        return self._source_version_read(row)

    async def create_source_file(self, data: SourceFileCreate) -> SourceFileRead:
        await self._active_source_version(data.source_version_id)
        row = SourceFile(**data.model_dump(mode="python"))
        await self._add(row, "source_file")
        return self._source_file_read(row)

    async def get_source_file(
        self,
        file_id: UUID,
        *,
        include_archived: bool = False,
    ) -> SourceFileRead:
        row = self._require(
            await self.repository.get_source_file(file_id),
            "source_file",
            file_id,
            include_archived=include_archived,
        )
        return self._source_file_read(row)

    async def list_source_files(
        self,
        source_version_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[SourceFileRead]:
        self._require(
            await self.repository.get_source_version(source_version_id),
            "source_version",
            source_version_id,
            include_archived=include_archived,
        )
        rows = await self.repository.list_source_files(
            source_version_id,
            include_archived=include_archived,
        )
        return [self._source_file_read(row) for row in rows]

    async def update_source_file(
        self,
        file_id: UUID,
        data: SourceFileUpdate,
    ) -> SourceFileRead:
        row = self._require(
            await self.repository.get_source_file(file_id),
            "source_file",
            file_id,
            include_archived=True,
        )
        await self._update_changes(
            row,
            data.expected_version,
            self._changes(data),
            "source_file",
        )
        return self._source_file_read(row)

    async def create_source_span(self, data: SourceSpanCreate) -> SourceSpanRead:
        await self._active_source_version(data.source_version_id)
        if data.source_file_id is not None:
            source_file = await self._active_source_file(data.source_file_id)
            self._same_parent(
                "source_file",
                data.source_version_id,
                source_file.source_version_id,
                data.source_file_id,
            )
        row = SourceSpan(
            source_version_id=data.source_version_id,
            source_file_id=data.source_file_id,
            **self._locator_columns(data.locator),
            quote=data.quote,
            ocr_text=data.ocr_text,
            confidence=data.confidence,
        )
        await self._add(row, "source_span")
        return self._source_span_read(row)

    async def get_source_span(
        self,
        span_id: UUID,
        *,
        include_archived: bool = False,
    ) -> SourceSpanRead:
        row = self._require(
            await self.repository.get_source_span(span_id),
            "source_span",
            span_id,
            include_archived=include_archived,
        )
        return self._source_span_read(row)

    async def list_source_spans(
        self,
        source_version_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[SourceSpanRead]:
        self._require(
            await self.repository.get_source_version(source_version_id),
            "source_version",
            source_version_id,
            include_archived=include_archived,
        )
        rows = await self.repository.list_source_spans(
            source_version_id,
            include_archived=include_archived,
        )
        return [self._source_span_read(row) for row in rows]

    async def update_source_span(
        self,
        span_id: UUID,
        data: SourceSpanUpdate,
    ) -> SourceSpanRead:
        row = self._require(
            await self.repository.get_source_span(span_id),
            "source_span",
            span_id,
            include_archived=True,
        )
        changes = self._changes(data)
        if "locator" in changes:
            changes.pop("locator")
            assert data.locator is not None
            changes.update(self._locator_columns(data.locator))
        await self._update_changes(row, data.expected_version, changes, "source_span")
        return self._source_span_read(row)

    async def create_knowledge_note(self, data: KnowledgeNoteCreate) -> KnowledgeNoteRead:
        scope: str
        target_kind: str
        occurrence_id: UUID | None = None
        position_id: UUID | None = None
        move_edge_id: UUID | None = None
        if data.occurrence_id is not None:
            await self._active_occurrence(data.occurrence_id)
            scope = "course"
            target_kind = "occurrence"
            occurrence_id = data.occurrence_id
        elif isinstance(data.target, GlobalPositionNoteTarget):
            await self._active_position(data.target.position_id)
            scope = "global"
            target_kind = "global_position"
            position_id = data.target.position_id
        elif isinstance(data.target, GlobalMoveNoteTarget):
            await self._active_move(data.target.move_edge_id)
            scope = "global"
            target_kind = "global_move"
            move_edge_id = data.target.move_edge_id
        else:
            raise ServiceError(
                "ambiguous_context",
                409,
                "knowledge note target is missing or ambiguous",
            )
        await self._active_spans(data.source_span_ids)

        async with self.session.begin_nested():
            row = KnowledgeNote(
                scope=scope,
                target_kind=target_kind,
                occurrence_id=occurrence_id,
                position_id=position_id,
                move_edge_id=move_edge_id,
                source_note_id=data.source_note_id,
                note_type=data.note_type,
                markdown=data.markdown,
                review_status=data.review_status,
            )
            await self._add(row, "knowledge_note")
            await self.repository.replace_note_citations(row.id, data.source_span_ids)
        return await self._knowledge_note_read(row)

    async def get_knowledge_note(
        self,
        note_id: UUID,
        *,
        include_archived: bool = False,
    ) -> KnowledgeNoteRead:
        row = self._require(
            await self.repository.get_knowledge_note(note_id),
            "knowledge_note",
            note_id,
            include_archived=include_archived,
        )
        return await self._knowledge_note_read(row)

    async def list_knowledge_notes(
        self,
        *,
        occurrence_id: UUID | None = None,
        position_id: UUID | None = None,
        move_edge_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list[KnowledgeNoteRead]:
        filters = [occurrence_id, position_id, move_edge_id]
        if sum(value is not None for value in filters) > 1:
            raise ServiceError(
                "ambiguous_context",
                409,
                "knowledge note list accepts exactly one target filter",
            )
        if occurrence_id is not None:
            self._require(
                await self.repository.get_occurrence(occurrence_id),
                "course_occurrence",
                occurrence_id,
                include_archived=include_archived,
            )
        elif position_id is not None:
            await self._active_position(position_id)
        elif move_edge_id is not None:
            await self._active_move(move_edge_id)
        rows = await self.repository.list_knowledge_notes(
            occurrence_id=occurrence_id,
            position_id=position_id,
            move_edge_id=move_edge_id,
            include_archived=include_archived,
        )
        return [await self._knowledge_note_read(row) for row in rows]

    async def update_knowledge_note(
        self,
        note_id: UUID,
        data: KnowledgeNoteUpdate,
    ) -> KnowledgeNoteRead:
        row = self._require(
            await self.repository.get_knowledge_note(note_id),
            "knowledge_note",
            note_id,
            include_archived=True,
        )
        changes = self._changes(data)
        citation_ids = cast(list[UUID] | None, changes.pop("source_span_ids", None))
        if "source_span_ids" in data.model_fields_set:
            assert citation_ids is not None
            await self._active_spans(citation_ids)
            if not changes:
                changes["updated_at"] = utc_now()
        async with self.session.begin_nested():
            await self._update_changes(row, data.expected_version, changes, "knowledge_note")
            if "source_span_ids" in data.model_fields_set:
                await self.repository.replace_note_citations(row.id, citation_ids or [])
        return await self._knowledge_note_read(row)

    async def _create_root_row(
        self,
        *,
        course_id: UUID,
        module_id: UUID | None,
        state: PositionState,
        nag: int | None,
        sort_order: int,
        context: dict[str, JsonValue],
    ) -> CourseOccurrence:
        stored = await get_or_create_position(self.session, state)
        row = CourseOccurrence(
            course_id=course_id,
            module_id=module_id,
            parent_id=None,
            position_id=stored.position.id,
            inbound_move_edge_id=None,
            full_fen=state.full_fen,
            nag=nag,
            sort_order=sort_order,
            context=context,
        )
        await self._add(row, "course_occurrence")
        return row

    async def _active_course(self, course_id: UUID) -> Course:
        return self._require(await self.repository.get_course(course_id), "course", course_id)

    async def _active_module(self, module_id: UUID) -> CourseModule:
        return self._require(
            await self.repository.get_module(module_id),
            "course_module",
            module_id,
        )

    async def _active_occurrence(self, occurrence_id: UUID) -> CourseOccurrence:
        return self._require(
            await self.repository.get_occurrence(occurrence_id),
            "course_occurrence",
            occurrence_id,
        )

    async def _active_source(self, source_id: UUID) -> Source:
        return self._require(await self.repository.get_source(source_id), "source", source_id)

    async def _active_source_version(self, version_id: UUID) -> SourceVersion:
        return self._require(
            await self.repository.get_source_version(version_id),
            "source_version",
            version_id,
        )

    async def _active_source_file(self, file_id: UUID) -> SourceFile:
        return self._require(
            await self.repository.get_source_file(file_id),
            "source_file",
            file_id,
        )

    async def _active_spans(self, span_ids: list[UUID]) -> None:
        for span_id in span_ids:
            self._require(
                await self.repository.get_source_span(span_id),
                "source_span",
                span_id,
            )

    async def _active_position(self, position_id: UUID) -> Position:
        row = await self.session.get(Position, position_id)
        if row is None:
            raise self._not_found("position", position_id)
        return row

    async def _active_move(self, move_id: UUID) -> MoveEdge:
        row = await self.session.get(MoveEdge, move_id)
        if row is None:
            raise self._not_found("move_edge", move_id)
        return row

    async def _add(
        self,
        row: Course
        | CourseModule
        | CourseOccurrence
        | Source
        | SourceVersion
        | SourceFile
        | SourceSpan
        | KnowledgeNote,
        resource: str,
    ) -> None:
        try:
            await self.repository.add(row)
        except RepositoryConflictError as error:
            raise ServiceError(
                "ambiguous_context",
                409,
                f"{resource} conflicts with an existing resource or reference",
                {"resource": resource},
            ) from error

    async def _update_changes(
        self,
        row: Course
        | CourseModule
        | CourseOccurrence
        | Source
        | SourceVersion
        | SourceFile
        | SourceSpan
        | KnowledgeNote,
        expected_version: int,
        changes: Mapping[str, object],
        resource: str,
    ) -> None:
        try:
            await self.repository.update(row, expected_version, changes)
        except RepositoryStaleVersionError as error:
            raise ServiceError(
                "stale_version",
                409,
                "expected version does not match the current resource version",
                {
                    "resource": resource,
                    "id": str(row.id),
                    "expected": expected_version,
                    "actual": row.version,
                },
            ) from error
        except RepositoryConflictError as error:
            raise ServiceError(
                "ambiguous_context",
                409,
                f"{resource} update conflicts with an existing resource or reference",
                {"resource": resource, "id": str(row.id)},
            ) from error

    @staticmethod
    def _changes(data: BaseModel) -> dict[str, object]:
        changes: dict[str, object] = data.model_dump(mode="python", exclude_unset=True)
        changes.pop("expected_version", None)
        if "archived" in changes:
            archived = cast(bool, changes.pop("archived"))
            changes["archived_at"] = utc_now() if archived else None
        return changes

    @staticmethod
    def _require(
        row: RowT | None,
        resource: str,
        resource_id: UUID,
        *,
        include_archived: bool = False,
    ) -> RowT:
        if row is None or (not include_archived and getattr(row, "archived_at", None) is not None):
            raise ContentService._not_found(resource, resource_id)
        return row

    @staticmethod
    def _same_parent(
        resource: str,
        expected_parent_id: UUID,
        actual_parent_id: UUID,
        resource_id: UUID,
    ) -> None:
        if expected_parent_id != actual_parent_id:
            raise ServiceError(
                "ambiguous_context",
                409,
                f"{resource} belongs to a different parent resource",
                {
                    "resource": resource,
                    "id": str(resource_id),
                    "expected_parent_id": str(expected_parent_id),
                    "actual_parent_id": str(actual_parent_id),
                },
            )

    @staticmethod
    def _not_found(resource: str, resource_id: UUID) -> ServiceError:
        return ServiceError(
            "not_found",
            404,
            f"{resource} was not found",
            {"resource": resource, "id": str(resource_id)},
        )

    @staticmethod
    def _ambiguous(resource: str, resource_id: UUID, message: str) -> ServiceError:
        return ServiceError(
            "ambiguous_context",
            409,
            message,
            {"resource": resource, "id": str(resource_id)},
        )

    @staticmethod
    def _position_state(fen: str) -> PositionState:
        try:
            return PositionState(fen)
        except PositionError as error:
            raise ContentService._position_service_error(error) from error

    @staticmethod
    def _position_service_error(error: PositionError) -> ServiceError:
        return ServiceError(error.code.value, 422, error.message)

    @staticmethod
    def _url(value: object | None) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _lifecycle(row: _MutableRow) -> dict[str, object]:
        return {
            "id": row.id,
            "version": row.version,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "archived_at": row.archived_at,
        }

    @classmethod
    def _course_read(cls, row: Course) -> CourseRead:
        return CourseRead.model_validate(
            {
                **cls._lifecycle(row),
                "title": row.title,
                "description": row.description,
                "category": row.category,
                "tags": row.tags,
                "status": row.status,
                "mode": row.mode,
            }
        )

    async def _module_read(self, row: CourseModule) -> CourseModuleRead:
        roots = await self.repository.list_module_roots(row.id)
        if len(roots) > 1:
            raise self._ambiguous(
                "course_module",
                row.id,
                "module has multiple active root occurrences",
            )
        return CourseModuleRead.model_validate(
            {
                **self._lifecycle(row),
                "course_id": row.course_id,
                "parent_id": row.parent_id,
                "title": row.title,
                "description": row.description,
                "start_occurrence_id": roots[0].id if roots else None,
                "sort_order": row.sort_order,
            }
        )

    @classmethod
    def _occurrence_read(cls, row: CourseOccurrence) -> OccurrenceRead:
        return OccurrenceRead.model_validate(
            {
                **cls._lifecycle(row),
                "course_id": row.course_id,
                "module_id": row.module_id,
                "position_id": row.position_id,
                "parent_id": row.parent_id,
                "inbound_move_edge_id": row.inbound_move_edge_id,
                "full_fen": row.full_fen,
                "nag": row.nag,
                "sort_order": row.sort_order,
                "context": row.context,
            }
        )

    @classmethod
    def _source_read(cls, row: Source) -> SourceRead:
        return SourceRead.model_validate(
            {
                **cls._lifecycle(row),
                "kind": row.kind,
                "title": row.title,
                "author": row.author,
                "description": row.description,
                "external_url": row.external_url,
            }
        )

    @classmethod
    def _source_version_read(cls, row: SourceVersion) -> SourceVersionRead:
        return SourceVersionRead.model_validate(
            {
                **cls._lifecycle(row),
                "source_id": row.source_id,
                "label": row.label,
                "edition": row.edition,
                "published_on": row.published_on,
                "external_url": row.external_url,
                "metadata": row.extra_metadata,
            }
        )

    @classmethod
    def _source_file_read(cls, row: SourceFile) -> SourceFileRead:
        return SourceFileRead.model_validate(
            {
                **cls._lifecycle(row),
                "source_version_id": row.source_version_id,
                "filename": row.filename,
                "relative_path": row.relative_path,
                "media_type": row.media_type,
                "size_bytes": row.size_bytes,
                "sha256": row.sha256,
            }
        )

    @staticmethod
    def _locator_columns(locator: object) -> dict[str, object]:
        columns: dict[str, object] = {
            "locator_kind": getattr(locator, "kind", None),
            "page_number": None,
            "bbox": None,
            "start_value": None,
            "end_value": None,
        }
        if isinstance(locator, PageSpan):
            columns["page_number"] = locator.page_number
            columns["bbox"] = locator.bbox.model_dump(mode="python") if locator.bbox else None
        elif isinstance(locator, VideoSpan):
            columns["start_value"] = locator.start_ms
            columns["end_value"] = locator.end_ms
        elif isinstance(locator, TextSpan):
            columns["start_value"] = locator.start_offset
            columns["end_value"] = locator.end_offset
        elif not isinstance(locator, WholeSpan):
            raise ServiceError(
                "ambiguous_context",
                409,
                "source span locator is not recognized",
            )
        return columns

    @classmethod
    def _source_span_read(cls, row: SourceSpan) -> SourceSpanRead:
        if row.locator_kind == "whole":
            locator: WholeSpan | PageSpan | VideoSpan | TextSpan = WholeSpan()
        elif row.locator_kind == "page" and row.page_number is not None:
            bbox = NormalizedBoundingBox.model_validate(row.bbox) if row.bbox is not None else None
            locator = PageSpan(page_number=row.page_number, bbox=bbox)
        elif (
            row.locator_kind == "video"
            and row.start_value is not None
            and row.end_value is not None
        ):
            locator = VideoSpan(start_ms=row.start_value, end_ms=row.end_value)
        elif (
            row.locator_kind == "text" and row.start_value is not None and row.end_value is not None
        ):
            locator = TextSpan(start_offset=row.start_value, end_offset=row.end_value)
        else:
            raise cls._ambiguous(
                "source_span",
                row.id,
                "persisted source span locator is inconsistent",
            )
        return SourceSpanRead.model_validate(
            {
                **cls._lifecycle(row),
                "source_version_id": row.source_version_id,
                "source_file_id": row.source_file_id,
                "locator": locator,
                "quote": row.quote,
                "ocr_text": row.ocr_text,
                "confidence": row.confidence,
            }
        )

    async def _knowledge_note_read(self, row: KnowledgeNote) -> KnowledgeNoteRead:
        if row.target_kind == "occurrence" and row.occurrence_id is not None:
            target: OccurrenceNoteTarget | GlobalPositionNoteTarget | GlobalMoveNoteTarget = (
                OccurrenceNoteTarget(occurrence_id=row.occurrence_id)
            )
        elif row.target_kind == "global_position" and row.position_id is not None:
            target = GlobalPositionNoteTarget(position_id=row.position_id)
        elif row.target_kind == "global_move" and row.move_edge_id is not None:
            target = GlobalMoveNoteTarget(move_edge_id=row.move_edge_id)
        else:
            raise self._ambiguous(
                "knowledge_note",
                row.id,
                "persisted knowledge note target is inconsistent",
            )
        citation_ids = await self.repository.list_note_citation_ids(row.id)
        return KnowledgeNoteRead.model_validate(
            {
                **self._lifecycle(row),
                "target": target,
                "source_note_id": row.source_note_id,
                "note_type": row.note_type,
                "markdown": row.markdown,
                "source_span_ids": citation_ids,
                "review_status": row.review_status,
            }
        )
