"""Session-scoped persistence helpers for mutable Stage 2 content.

The repository never commits.  Callers own the transaction boundary and may
compose these operations with the immutable graph repository in one unit of
work.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import Select, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from chess_workbench.store.models import (
    Course,
    CourseModule,
    CourseOccurrence,
    KnowledgeNote,
    KnowledgeNoteCitation,
    Source,
    SourceFile,
    SourceSpan,
    SourceVersion,
)

ModelT = TypeVar("ModelT")
type MutableModel = (
    Course
    | CourseModule
    | CourseOccurrence
    | Source
    | SourceVersion
    | SourceFile
    | SourceSpan
    | KnowledgeNote
)


class RepositoryConflictError(RuntimeError):
    """A database uniqueness or reference constraint rejected a write."""


class RepositoryStaleVersionError(RuntimeError):
    """An optimistic update lost a race after its initial version check."""


class ContentRepository:
    """Thin repository over a caller-owned :class:`AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, entity: MutableModel) -> None:
        """Add and flush one row inside a savepoint, without committing."""

        try:
            async with self.session.begin_nested():
                self.session.add(entity)
                await self.session.flush()
        except IntegrityError as error:
            raise RepositoryConflictError from error

    async def update(
        self,
        entity: MutableModel,
        expected_version: int,
        changes: Mapping[str, object],
    ) -> None:
        """Apply an ORM-versioned update and flush without committing."""

        if entity.version != expected_version:
            raise RepositoryStaleVersionError
        for field_name, value in changes.items():
            setattr(entity, field_name, value)
        try:
            await self.session.flush()
        except StaleDataError as error:
            raise RepositoryStaleVersionError from error
        except IntegrityError as error:
            raise RepositoryConflictError from error

    async def get_course(self, course_id: UUID) -> Course | None:
        return await self.session.get(Course, course_id)

    async def list_courses(self, *, include_archived: bool = False) -> list[Course]:
        statement = select(Course)
        if not include_archived:
            statement = statement.where(Course.archived_at.is_(None))
        return await self._scalars(statement.order_by(Course.created_at, Course.id))

    async def get_module(
        self,
        module_id: UUID,
        *,
        for_update: bool = False,
    ) -> CourseModule | None:
        return await self.session.get(CourseModule, module_id, with_for_update=for_update)

    async def list_modules(
        self,
        course_id: UUID,
        *,
        parent_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list[CourseModule]:
        statement = select(CourseModule).where(CourseModule.course_id == course_id)
        if parent_id is not None:
            statement = statement.where(CourseModule.parent_id == parent_id)
        if not include_archived:
            statement = statement.where(CourseModule.archived_at.is_(None))
        return await self._scalars(
            statement.order_by(CourseModule.sort_order, CourseModule.created_at, CourseModule.id)
        )

    async def get_occurrence(self, occurrence_id: UUID) -> CourseOccurrence | None:
        return await self.session.get(CourseOccurrence, occurrence_id)

    async def list_occurrences(
        self,
        course_id: UUID,
        *,
        module_id: UUID | None = None,
        parent_id: UUID | None = None,
        roots_only: bool = False,
        include_archived: bool = False,
    ) -> list[CourseOccurrence]:
        statement = select(CourseOccurrence).where(CourseOccurrence.course_id == course_id)
        if module_id is not None:
            statement = statement.where(CourseOccurrence.module_id == module_id)
        if parent_id is not None:
            statement = statement.where(CourseOccurrence.parent_id == parent_id)
        elif roots_only:
            statement = statement.where(CourseOccurrence.parent_id.is_(None))
        if not include_archived:
            statement = statement.where(CourseOccurrence.archived_at.is_(None))
        return await self._scalars(
            statement.order_by(
                CourseOccurrence.sort_order,
                CourseOccurrence.created_at,
                CourseOccurrence.id,
            )
        )

    async def list_module_roots(
        self,
        module_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[CourseOccurrence]:
        statement = select(CourseOccurrence).where(
            CourseOccurrence.module_id == module_id,
            CourseOccurrence.parent_id.is_(None),
        )
        if not include_archived:
            statement = statement.where(CourseOccurrence.archived_at.is_(None))
        return await self._scalars(
            statement.order_by(CourseOccurrence.created_at, CourseOccurrence.id)
        )

    async def find_child_occurrence(
        self,
        parent_id: UUID,
        inbound_move_edge_id: UUID,
    ) -> CourseOccurrence | None:
        return cast(
            CourseOccurrence | None,
            await self.session.scalar(
                select(CourseOccurrence).where(
                    CourseOccurrence.parent_id == parent_id,
                    CourseOccurrence.inbound_move_edge_id == inbound_move_edge_id,
                )
            ),
        )

    async def get_source(self, source_id: UUID) -> Source | None:
        return await self.session.get(Source, source_id)

    async def list_sources(self, *, include_archived: bool = False) -> list[Source]:
        statement = select(Source)
        if not include_archived:
            statement = statement.where(Source.archived_at.is_(None))
        return await self._scalars(statement.order_by(Source.created_at, Source.id))

    async def get_source_version(self, version_id: UUID) -> SourceVersion | None:
        return await self.session.get(SourceVersion, version_id)

    async def list_source_versions(
        self,
        source_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[SourceVersion]:
        statement = select(SourceVersion).where(SourceVersion.source_id == source_id)
        if not include_archived:
            statement = statement.where(SourceVersion.archived_at.is_(None))
        return await self._scalars(statement.order_by(SourceVersion.created_at, SourceVersion.id))

    async def get_source_file(self, file_id: UUID) -> SourceFile | None:
        return await self.session.get(SourceFile, file_id)

    async def list_source_files(
        self,
        source_version_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[SourceFile]:
        statement = select(SourceFile).where(SourceFile.source_version_id == source_version_id)
        if not include_archived:
            statement = statement.where(SourceFile.archived_at.is_(None))
        return await self._scalars(statement.order_by(SourceFile.created_at, SourceFile.id))

    async def get_source_span(self, span_id: UUID) -> SourceSpan | None:
        return await self.session.get(SourceSpan, span_id)

    async def list_source_spans(
        self,
        source_version_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[SourceSpan]:
        statement = select(SourceSpan).where(SourceSpan.source_version_id == source_version_id)
        if not include_archived:
            statement = statement.where(SourceSpan.archived_at.is_(None))
        return await self._scalars(statement.order_by(SourceSpan.created_at, SourceSpan.id))

    async def get_knowledge_note(self, note_id: UUID) -> KnowledgeNote | None:
        return await self.session.get(KnowledgeNote, note_id)

    async def list_knowledge_notes(
        self,
        *,
        occurrence_id: UUID | None = None,
        position_id: UUID | None = None,
        move_edge_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list[KnowledgeNote]:
        statement = select(KnowledgeNote)
        if occurrence_id is not None:
            statement = statement.where(KnowledgeNote.occurrence_id == occurrence_id)
        if position_id is not None:
            statement = statement.where(KnowledgeNote.position_id == position_id)
        if move_edge_id is not None:
            statement = statement.where(KnowledgeNote.move_edge_id == move_edge_id)
        if not include_archived:
            statement = statement.where(KnowledgeNote.archived_at.is_(None))
        return await self._scalars(statement.order_by(KnowledgeNote.created_at, KnowledgeNote.id))

    async def replace_note_citations(
        self,
        note_id: UUID,
        source_span_ids: list[UUID],
    ) -> None:
        await self.session.execute(
            delete(KnowledgeNoteCitation).where(KnowledgeNoteCitation.knowledge_note_id == note_id)
        )
        self.session.add_all(
            KnowledgeNoteCitation(knowledge_note_id=note_id, source_span_id=span_id)
            for span_id in source_span_ids
        )
        try:
            await self.session.flush()
        except IntegrityError as error:
            raise RepositoryConflictError from error

    async def list_note_citation_ids(self, note_id: UUID) -> list[UUID]:
        result = await self.session.scalars(
            select(KnowledgeNoteCitation.source_span_id)
            .where(KnowledgeNoteCitation.knowledge_note_id == note_id)
            .order_by(KnowledgeNoteCitation.source_span_id)
        )
        return list(result)

    async def module_parent_would_cycle(self, module_id: UUID, parent_id: UUID) -> bool:
        """Walk the short module ancestry chain without dialect-specific CTEs."""

        current_id: UUID | None = parent_id
        visited: set[UUID] = set()
        while current_id is not None:
            if current_id == module_id or current_id in visited:
                return True
            visited.add(current_id)
            parent = await self.get_module(current_id)
            if parent is None:
                return False
            current_id = parent.parent_id
        return False

    async def _scalars(self, statement: Select[tuple[ModelT]]) -> list[ModelT]:
        result = await self.session.scalars(statement)
        return list(result)
