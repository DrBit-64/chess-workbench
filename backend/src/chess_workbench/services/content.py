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
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.domain import PositionError, PositionState
from chess_workbench.schemas.domain import (
    CitableSourceCreate,
    CitableSourceRead,
    ContentHistoryRead,
    ContentRevisionRead,
    CourseContentBlockCreate,
    CourseContentBlockRead,
    CourseContentBlockUpdate,
    CourseCreate,
    CourseKnowledgeNoteBlockCreate,
    CourseKnowledgeNoteBlockRead,
    CourseModuleArchiveTreeRead,
    CourseModuleArchiveTreeRequest,
    CourseModuleCreate,
    CourseModuleEditorRead,
    CourseModuleRead,
    CourseModuleUpdate,
    CourseRead,
    CourseUpdate,
    DashboardSummary,
    EditorKnowledgeNoteRead,
    EditorOccurrenceRead,
    ErrorCode,
    GlobalMoveNoteTarget,
    GlobalPositionNoteTarget,
    HistoryEntityType,
    KnowledgeNoteCreate,
    KnowledgeNoteRead,
    KnowledgeNoteUpdate,
    ModulePublicationRead,
    NormalizedBoundingBox,
    OccurrenceCommandRead,
    OccurrenceCommandRequest,
    OccurrenceMoveCreate,
    OccurrenceNoteTarget,
    OccurrenceRead,
    OccurrenceUpdate,
    PageSpan,
    PublishModulesRead,
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
    ContentRevision,
    Course,
    CourseContentBlock,
    CourseModule,
    CourseOccurrence,
    KnowledgeNote,
    ModulePublication,
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

    async def list_courses(
        self,
        *,
        include_archived: bool = False,
        query: str | None = None,
        mode: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        sort: str = "updated_desc",
    ) -> list[CourseRead]:
        rows = await self.repository.list_courses(include_archived=include_archived)
        if query:
            needle = query.casefold()
            rows = [
                row
                for row in rows
                if needle in row.title.casefold()
                or needle in row.description.casefold()
                or (row.category is not None and needle in row.category.casefold())
            ]
        if mode:
            rows = [row for row in rows if row.mode == mode]
        if status:
            rows = [row for row in rows if row.status == status]
        if tag:
            tag_key = tag.casefold()
            rows = [row for row in rows if any(value.casefold() == tag_key for value in row.tags)]
        if sort == "title_asc":
            rows.sort(key=lambda row: (row.title.casefold(), str(row.id)))
        elif sort == "created_desc":
            rows.sort(key=lambda row: (row.created_at, str(row.id)), reverse=True)
        else:
            rows.sort(key=lambda row: (row.updated_at, str(row.id)), reverse=True)
        return [self._course_read(row) for row in rows]

    async def dashboard_summary(self) -> DashboardSummary:
        active_course = Course.archived_at.is_(None)
        course_count = int(
            await self.session.scalar(select(func.count()).select_from(Course).where(active_course))
            or 0
        )
        traditional_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(Course)
                .where(active_course, Course.mode == "traditional")
            )
            or 0
        )
        explorer_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(Course)
                .where(active_course, Course.mode == "opening_explorer")
            )
            or 0
        )
        module_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(CourseModule)
                .where(CourseModule.archived_at.is_(None))
            )
            or 0
        )
        source_count = int(
            await self.session.scalar(
                select(func.count()).select_from(Source).where(Source.archived_at.is_(None))
            )
            or 0
        )
        note_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(KnowledgeNote)
                .where(KnowledgeNote.archived_at.is_(None))
            )
            or 0
        )
        position_count = int(
            await self.session.scalar(select(func.count()).select_from(Position)) or 0
        )
        recent = await self.repository.list_courses()
        recent.sort(key=lambda row: (row.updated_at, str(row.id)), reverse=True)
        return DashboardSummary(
            course_count=course_count,
            traditional_course_count=traditional_count,
            explorer_course_count=explorer_count,
            module_count=module_count,
            source_count=source_count,
            knowledge_note_count=note_count,
            position_count=position_count,
            recent_courses=[self._course_read(row) for row in recent[:5]],
        )

    async def update_course(self, course_id: UUID, data: CourseUpdate) -> CourseRead:
        row = self._require(
            await self.repository.get_course(course_id),
            "course",
            course_id,
            include_archived=True,
        )
        changes = self._changes(data)
        if (
            "mode" in changes
            and changes["mode"] != row.mode
            and await self.repository.course_has_content(course_id)
        ):
            raise self._referenced(
                "course",
                course_id,
                "course mode cannot change after modules or occurrences exist",
            )
        await self._update_changes(row, data.expected_version, changes, "course")
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
                root = await self._create_root_row(
                    course_id=data.course_id,
                    module_id=row.id,
                    state=start_state,
                    nag=None,
                    sort_order=0,
                    context={},
                )
                await self._add(
                    CourseContentBlock(
                        module_id=row.id,
                        kind="move_sequence",
                        sort_order=0,
                        heading=None,
                        markdown=None,
                        root_occurrence_id=root.id,
                        knowledge_note_id=None,
                    ),
                    "course_content_block",
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

    async def archive_module_tree(
        self,
        module_id: UUID,
        data: CourseModuleArchiveTreeRequest,
    ) -> CourseModuleArchiveTreeRead:
        target = self._require(
            await self.repository.get_module(module_id),
            "course_module",
            module_id,
        )
        if target.version != data.expected_version:
            raise ServiceError(
                "stale_version",
                409,
                "expected version does not match the current resource version",
                {
                    "resource": "course_module",
                    "id": str(target.id),
                    "expected": data.expected_version,
                    "actual": target.version,
                },
            )
        modules = await self.repository.list_modules(target.course_id)
        module_by_parent: dict[UUID, list[CourseModule]] = {}
        for module in modules:
            if module.parent_id is not None:
                module_by_parent.setdefault(module.parent_id, []).append(module)
        selected: list[CourseModule] = []
        pending = [target]
        while pending:
            module = pending.pop()
            selected.append(module)
            pending.extend(module_by_parent.get(module.id, []))
        selected_ids = {module.id for module in selected}
        occurrences = [
            row
            for row in await self.repository.list_occurrences(target.course_id)
            if row.module_id in selected_ids
        ]
        invalidated = await self._archive_authoring_content(
            occurrence_rows=occurrences,
            module_ids=selected_ids,
        )
        archived_at = utc_now()
        for module in reversed(selected):
            await self._update_changes(
                module,
                module.version,
                {"archived_at": archived_at},
                "course_module",
            )
        return CourseModuleArchiveTreeRead(
            module_id=module_id,
            archived_module_count=len(selected),
            archived_occurrence_count=len(occurrences),
            invalidated_reference_count=invalidated,
        )

    async def get_module_editor(
        self,
        course_id: UUID,
        module_id: UUID,
    ) -> CourseModuleEditorRead:
        await self._active_course(course_id)
        module = await self._active_module(module_id)
        self._same_parent("module", course_id, module.course_id, module_id)
        occurrence_rows = await self.repository.list_occurrences(
            course_id,
            module_id=module_id,
        )
        edge_ids = {
            row.inbound_move_edge_id
            for row in occurrence_rows
            if row.inbound_move_edge_id is not None
        }
        edges = {
            edge.id: edge
            for edge in await self.session.scalars(
                select(MoveEdge).where(MoveEdge.id.in_(edge_ids))
            )
        }
        editor_occurrences: list[EditorOccurrenceRead] = []
        for row in occurrence_rows:
            edge = edges.get(row.inbound_move_edge_id) if row.inbound_move_edge_id else None
            editor_occurrences.append(
                EditorOccurrenceRead.model_validate(
                    {
                        **self._occurrence_read(row).model_dump(mode="python"),
                        "inbound_uci": edge.uci if edge else None,
                        "inbound_san": edge.san if edge else None,
                    }
                )
            )
        block_rows = await self.repository.list_content_blocks(module_id)
        note_rows = list(
            await self.session.scalars(
                select(KnowledgeNote)
                .where(
                    KnowledgeNote.occurrence_id.in_([row.id for row in occurrence_rows]),
                    KnowledgeNote.archived_at.is_(None),
                )
                .order_by(KnowledgeNote.created_at, KnowledgeNote.id)
            )
        )
        return CourseModuleEditorRead(
            module=await self._module_read(module),
            content_blocks=[await self._content_block_read(row) for row in block_rows],
            occurrences=editor_occurrences,
            notes=[await self._editor_knowledge_note_read(row) for row in note_rows],
        )

    async def create_root_occurrence(self, data: RootOccurrenceCreate) -> OccurrenceRead:
        state = self._position_state(data.fen)
        await self._active_course(data.course_id)
        reusable_block: CourseContentBlock | None = None
        block_sort_order = 0
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
            all_blocks = await self.repository.list_content_blocks(
                data.module_id,
                include_archived=True,
            )
            reusable_block = next(
                (
                    block
                    for block in all_blocks
                    if block.kind == "move_sequence" and block.archived_at is not None
                ),
                None,
            )
            block_sort_order = max((block.sort_order for block in all_blocks), default=-1) + 1

        async with self.session.begin_nested():
            row = await self._create_root_row(
                course_id=data.course_id,
                module_id=data.module_id,
                state=state,
                nag=data.nag,
                sort_order=data.sort_order,
                context=data.context,
            )
            if data.module_id is not None:
                if reusable_block is not None:
                    await self._update_changes(
                        reusable_block,
                        reusable_block.version,
                        {"root_occurrence_id": row.id, "archived_at": None},
                        "course_content_block",
                    )
                else:
                    await self._add(
                        CourseContentBlock(
                            module_id=data.module_id,
                            kind="move_sequence",
                            sort_order=block_sort_order,
                            heading=None,
                            markdown=None,
                            root_occurrence_id=row.id,
                            knowledge_note_id=None,
                        ),
                        "course_content_block",
                    )
        return self._occurrence_read(row)

    async def create_content_block(
        self,
        data: CourseContentBlockCreate,
    ) -> CourseContentBlockRead:
        module = await self._active_module(data.module_id)
        if data.root_occurrence_id is not None:
            root = await self._active_occurrence(data.root_occurrence_id)
            if root.module_id != module.id or root.parent_id is not None:
                raise self._ambiguous(
                    "course_content_block",
                    data.root_occurrence_id,
                    "move_sequence root must be the active root of the same Module",
                )
        if data.knowledge_note_id is not None:
            note = self._require(
                await self.repository.get_knowledge_note(data.knowledge_note_id),
                "knowledge_note",
                data.knowledge_note_id,
            )
            if note.occurrence_id is None:
                raise self._ambiguous(
                    "course_content_block",
                    data.knowledge_note_id,
                    "knowledge_note block must target an occurrence in the same Module",
                )
            occurrence = await self._active_occurrence(note.occurrence_id)
            if occurrence.module_id != module.id:
                raise self._ambiguous(
                    "course_content_block",
                    data.knowledge_note_id,
                    "knowledge_note block belongs to a different Module",
                )
        await self._active_spans(data.source_span_ids)
        row = CourseContentBlock(
            module_id=module.id,
            kind=data.kind,
            sort_order=data.sort_order,
            heading=data.heading,
            markdown=data.markdown,
            root_occurrence_id=data.root_occurrence_id,
            knowledge_note_id=data.knowledge_note_id,
        )
        async with self.session.begin_nested():
            await self._add(row, "course_content_block")
            await self.repository.replace_content_block_citations(row.id, data.source_span_ids)
        return await self._content_block_read(row)

    async def create_course_knowledge_note_block(
        self,
        module_id: UUID,
        data: CourseKnowledgeNoteBlockCreate,
    ) -> CourseKnowledgeNoteBlockRead:
        """Create a local note and append its reading block as one transaction."""

        module = await self._active_module(module_id)
        occurrence = await self._active_occurrence(data.occurrence_id)
        if occurrence.module_id != module.id:
            raise self._ambiguous(
                "course_content_block",
                data.occurrence_id,
                "knowledge note target belongs to a different Module",
            )
        all_blocks = await self.repository.list_content_blocks(
            module.id,
            include_archived=True,
        )
        sort_order = max((block.sort_order for block in all_blocks), default=-1) + 1
        async with self.session.begin_nested():
            note = await self.create_knowledge_note(
                KnowledgeNoteCreate(
                    occurrence_id=data.occurrence_id,
                    note_type=data.note_type,
                    markdown=data.markdown,
                    source_span_ids=data.source_span_ids,
                    review_status=data.review_status,
                )
            )
            block = await self.create_content_block(
                CourseContentBlockCreate(
                    module_id=module.id,
                    kind="knowledge_note",
                    sort_order=sort_order,
                    knowledge_note_id=note.id,
                )
            )
        return CourseKnowledgeNoteBlockRead(note=note, block=block)

    async def get_content_block(
        self,
        block_id: UUID,
        *,
        include_archived: bool = False,
    ) -> CourseContentBlockRead:
        row = self._require(
            await self.repository.get_content_block(block_id),
            "course_content_block",
            block_id,
            include_archived=include_archived,
        )
        return await self._content_block_read(row)

    async def list_content_blocks(
        self,
        module_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[CourseContentBlockRead]:
        self._require(
            await self.repository.get_module(module_id),
            "course_module",
            module_id,
            include_archived=include_archived,
        )
        rows = await self.repository.list_content_blocks(
            module_id,
            include_archived=include_archived,
        )
        return [await self._content_block_read(row) for row in rows]

    async def update_content_block(
        self,
        block_id: UUID,
        data: CourseContentBlockUpdate,
    ) -> CourseContentBlockRead:
        row = self._require(
            await self.repository.get_content_block(block_id),
            "course_content_block",
            block_id,
            include_archived=True,
        )
        changes = self._changes(data)
        if "heading" in changes and row.kind != "section_header":
            raise self._ambiguous(
                "course_content_block", row.id, "only section_header blocks have heading"
            )
        if "markdown" in changes and row.kind != "narrative":
            raise self._ambiguous(
                "course_content_block", row.id, "only narrative blocks have markdown"
            )
        citation_ids = cast(list[UUID] | None, changes.pop("source_span_ids", None))
        if "source_span_ids" in data.model_fields_set:
            if row.kind != "narrative":
                raise self._ambiguous(
                    "course_content_block",
                    row.id,
                    "only narrative blocks may cite source spans",
                )
            assert citation_ids is not None
            await self._active_spans(citation_ids)
            if not changes:
                changes["updated_at"] = utc_now()
        if changes.get("archived_at") is not None and row.kind == "move_sequence":
            raise self._referenced(
                "course_content_block",
                row.id,
                "an active Module root must retain its move_sequence block",
            )
        async with self.session.begin_nested():
            await self._update_changes(row, data.expected_version, changes, "course_content_block")
            if "source_span_ids" in data.model_fields_set:
                await self.repository.replace_content_block_citations(row.id, citation_ids or [])
        return await self._content_block_read(row)

    async def create_move_occurrence(self, data: OccurrenceMoveCreate) -> OccurrenceRead:
        parent = await self._active_occurrence(data.parent_occurrence_id)
        await self._active_course(parent.course_id)
        if parent.module_id is not None:
            await self._active_module(parent.module_id)
        before = self._position_state(parent.full_fen)

        try:
            async with self.session.begin_nested():
                stored_move = await get_or_create_move(self.session, before, data.uci)
                existing = await self.repository.find_child_occurrence(
                    parent.id,
                    stored_move.edge.id,
                    data.sort_order,
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
        linked_block = (
            await self.repository.content_block_for_root(row.id)
            if row.parent_id is None and row.module_id is not None
            else None
        )
        if "module_id" in changes and changes["module_id"] != row.module_id:
            raise self._referenced(
                "course_occurrence",
                occurrence_id,
                "generic occurrence PATCH cannot move a node between modules",
            )
        if "archived_at" in changes and changes["archived_at"] is not None:
            active_children = await self.repository.list_occurrences(
                row.course_id,
                parent_id=row.id,
            )
            if active_children:
                raise self._referenced(
                    "course_occurrence",
                    occurrence_id,
                    "an occurrence with active children cannot be archived",
                )
        if (
            "archived_at" in changes
            and changes["archived_at"] is None
            and row.archived_at is not None
        ):
            if row.parent_id is not None:
                parent = self._require(
                    await self.repository.get_occurrence(row.parent_id),
                    "course_occurrence",
                    row.parent_id,
                    include_archived=True,
                )
                if parent.archived_at is not None:
                    raise self._referenced(
                        "course_occurrence",
                        occurrence_id,
                        "an occurrence cannot be restored while its parent is archived",
                    )
            if row.module_id is not None:
                module = self._require(
                    await self.repository.get_module(row.module_id),
                    "course_module",
                    row.module_id,
                    include_archived=True,
                )
                if module.archived_at is not None:
                    raise self._referenced(
                        "course_occurrence",
                        occurrence_id,
                        "an occurrence cannot be restored while its module is archived",
                    )
                active_roots = await self.repository.list_module_roots(row.module_id)
                if row.parent_id is None and active_roots:
                    raise self._ambiguous(
                        "course_module",
                        row.module_id,
                        "restoring this occurrence would create multiple active module roots",
                    )
        linked_block_changes: dict[str, object] | None = None
        if "archived_at" in changes and linked_block is not None:
            requested_archive = changes["archived_at"]
            if requested_archive is not None and linked_block.archived_at is None:
                linked_block_changes = {"archived_at": requested_archive}
            elif requested_archive is None and linked_block.archived_at is not None:
                linked_block_changes = {"archived_at": None}
        async with self.session.begin_nested():
            await self._update_changes(row, data.expected_version, changes, "course_occurrence")
            if linked_block_changes is not None and linked_block is not None:
                await self._update_changes(
                    linked_block,
                    linked_block.version,
                    linked_block_changes,
                    "course_content_block",
                )
        return self._occurrence_read(row)

    async def execute_occurrence_command(
        self,
        occurrence_id: UUID,
        data: OccurrenceCommandRequest,
    ) -> OccurrenceCommandRead:
        row = await self._active_occurrence(occurrence_id)
        if row.parent_id is None:
            raise self._ambiguous(
                "course_occurrence",
                occurrence_id,
                "the root occurrence cannot be edited as a move",
            )
        if row.version != data.expected_version:
            raise ServiceError(
                "stale_version",
                409,
                "expected version does not match the current resource version",
                {
                    "resource": "course_occurrence",
                    "id": str(row.id),
                    "expected": data.expected_version,
                    "actual": row.version,
                },
            )

        selected_id = row.id
        affected = 0
        invalidated = 0
        if data.kind == "set_nag":
            await self._update_changes(
                row,
                row.version,
                {"nag": data.nag},
                "course_occurrence",
            )
            affected = 1
        elif data.kind == "promote_variation":
            siblings = await self.repository.list_occurrences(
                row.course_id,
                parent_id=row.parent_id,
            )
            index = next(i for i, sibling in enumerate(siblings) if sibling.id == row.id)
            if index > 0:
                desired = [*siblings]
                desired[index - 1], desired[index] = desired[index], desired[index - 1]
                affected = await self._reorder_active_siblings(row.parent_id, desired)
        elif data.kind == "make_mainline":
            child = row
            while child.parent_id is not None:
                siblings = await self.repository.list_occurrences(
                    child.course_id,
                    parent_id=child.parent_id,
                )
                index = next(i for i, sibling in enumerate(siblings) if sibling.id == child.id)
                if index > 0:
                    desired = [child, *siblings[:index], *siblings[index + 1 :]]
                    affected += await self._reorder_active_siblings(child.parent_id, desired)
                child = await self._active_occurrence(child.parent_id)
        else:
            descendants = await self._active_occurrence_subtree(row)
            all_siblings = await self.repository.list_occurrences(
                row.course_id,
                parent_id=row.parent_id,
                include_archived=True,
            )
            archive_sort_order = max(sibling.sort_order for sibling in all_siblings) + 1
            await self._update_changes(
                row,
                row.version,
                {"archived_at": utc_now(), "sort_order": archive_sort_order},
                "course_occurrence",
            )
            invalidated = await self._archive_authoring_content(
                occurrence_rows=descendants,
                module_ids=set(),
            )
            selected_id = row.parent_id
            affected = len(descendants)
            siblings = await self.repository.list_occurrences(
                row.course_id,
                parent_id=row.parent_id,
            )
            if siblings:
                affected += await self._reorder_active_siblings(row.parent_id, siblings)

        return OccurrenceCommandRead(
            selected_occurrence_id=selected_id,
            affected_occurrence_count=affected,
            invalidated_reference_count=invalidated,
        )

    async def _active_occurrence_subtree(
        self,
        root: CourseOccurrence,
    ) -> list[CourseOccurrence]:
        rows = await self.repository.list_occurrences(
            root.course_id,
            module_id=root.module_id,
        )
        children: dict[UUID, list[CourseOccurrence]] = {}
        for row in rows:
            if row.parent_id is not None:
                children.setdefault(row.parent_id, []).append(row)
        result: list[CourseOccurrence] = []
        pending = [root]
        while pending:
            current = pending.pop()
            result.append(current)
            pending.extend(children.get(current.id, []))
        return result

    async def _reorder_active_siblings(
        self,
        parent_id: UUID,
        desired: list[CourseOccurrence],
    ) -> int:
        if not desired:
            return 0
        all_siblings = await self.repository.list_occurrences(
            desired[0].course_id,
            parent_id=parent_id,
            include_archived=True,
        )
        reserved = {
            sibling.sort_order for sibling in all_siblings if sibling.archived_at is not None
        }
        slots: list[int] = []
        candidate = 0
        while len(slots) < len(desired):
            if candidate not in reserved:
                slots.append(candidate)
            candidate += 1
        changed = [
            (row, final_order)
            for row, final_order in zip(desired, slots, strict=True)
            if row.sort_order != final_order
        ]
        if not changed:
            return 0
        temporary = max(sibling.sort_order for sibling in all_siblings) + 1
        for offset, (row, _) in enumerate(changed):
            await self._update_changes(
                row,
                row.version,
                {"sort_order": temporary + offset},
                "course_occurrence",
            )
        for row, final_order in changed:
            await self._update_changes(
                row,
                row.version,
                {"sort_order": final_order},
                "course_occurrence",
            )
        return len(changed)

    async def _archive_authoring_content(
        self,
        *,
        occurrence_rows: list[CourseOccurrence],
        module_ids: set[UUID],
    ) -> int:
        occurrence_ids = {row.id for row in occurrence_rows}
        note_rows: list[KnowledgeNote] = []
        if occurrence_ids:
            note_rows = list(
                await self.session.scalars(
                    select(KnowledgeNote).where(
                        KnowledgeNote.occurrence_id.in_(occurrence_ids),
                        KnowledgeNote.archived_at.is_(None),
                    )
                )
            )
        note_ids = {row.id for row in note_rows}
        reference_rows: list[KnowledgeNote] = []
        if note_ids:
            reference_rows = list(
                await self.session.scalars(
                    select(KnowledgeNote).where(
                        KnowledgeNote.source_note_id.in_(note_ids),
                        KnowledgeNote.archived_at.is_(None),
                    )
                )
            )
        block_conditions = []
        if module_ids:
            block_conditions.append(CourseContentBlock.module_id.in_(module_ids))
        if occurrence_ids:
            block_conditions.append(CourseContentBlock.root_occurrence_id.in_(occurrence_ids))
        if note_ids:
            block_conditions.append(CourseContentBlock.knowledge_note_id.in_(note_ids))
        block_rows = (
            list(
                await self.session.scalars(
                    select(CourseContentBlock).where(
                        or_(*block_conditions),
                        CourseContentBlock.archived_at.is_(None),
                    )
                )
            )
            if block_conditions
            else []
        )
        archived_at = utc_now()
        for note in [*reference_rows, *note_rows]:
            if note.archived_at is None:
                await self._update_changes(
                    note,
                    note.version,
                    {"archived_at": archived_at},
                    "knowledge_note",
                )
        for block in block_rows:
            await self._update_changes(
                block,
                block.version,
                {"archived_at": archived_at},
                "course_content_block",
            )
        for occurrence in reversed(occurrence_rows):
            if occurrence.archived_at is None:
                await self._update_changes(
                    occurrence,
                    occurrence.version,
                    {"archived_at": archived_at},
                    "course_occurrence",
                )
        return len(reference_rows)

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

    async def list_sources(
        self,
        *,
        include_archived: bool = False,
        query: str | None = None,
        kind: str | None = None,
    ) -> list[SourceRead]:
        rows = await self.repository.list_sources(include_archived=include_archived)
        if query:
            needle = query.casefold()
            rows = [
                row
                for row in rows
                if needle in row.title.casefold()
                or (row.author is not None and needle in row.author.casefold())
                or needle in row.description.casefold()
            ]
        if kind:
            rows = [row for row in rows if row.kind == kind]
        return [self._source_read(row) for row in rows]

    async def create_citable_source(self, data: CitableSourceCreate) -> CitableSourceRead:
        """Create the complete minimum citation chain in one transaction."""

        async with self.session.begin_nested():
            source = await self.create_source(
                SourceCreate(
                    kind=data.kind,
                    title=data.title,
                    author=data.author,
                    description=data.description,
                    external_url=data.external_url,
                )
            )
            version = await self.create_source_version(
                SourceVersionCreate(
                    source_id=source.id,
                    label=data.version_label,
                    external_url=data.external_url,
                )
            )
            span = await self.create_source_span(
                SourceSpanCreate(
                    source_version_id=version.id,
                    locator=WholeSpan(),
                    quote=data.quote,
                )
            )
        return CitableSourceRead(source=source, source_version=version, source_span=span)

    async def list_citable_sources(self) -> list[CitableSourceRead]:
        statement = (
            select(Source, SourceVersion, SourceSpan)
            .join(SourceVersion, SourceVersion.source_id == Source.id)
            .join(SourceSpan, SourceSpan.source_version_id == SourceVersion.id)
            .where(
                Source.archived_at.is_(None),
                SourceVersion.archived_at.is_(None),
                SourceSpan.archived_at.is_(None),
            )
            .order_by(Source.title, Source.created_at, SourceSpan.created_at)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            CitableSourceRead(
                source=self._source_read(source),
                source_version=self._source_version_read(version),
                source_span=self._source_span_read(span),
            )
            for source, version, span in rows
        ]

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
            if not isinstance(data.locator, WholeSpan) and row.source_file_id is None:
                raise ServiceError(
                    "validation_error",
                    422,
                    "page, video, and text locators require a source file",
                    {"resource": "source_span", "id": str(span_id)},
                )
            changes.update(self._locator_columns(data.locator))
        await self._update_changes(row, data.expected_version, changes, "source_span")
        return self._source_span_read(row)

    async def create_knowledge_note(self, data: KnowledgeNoteCreate) -> KnowledgeNoteRead:
        scope: str
        target_kind: str
        occurrence_id: UUID | None = None
        occurrence: CourseOccurrence | None = None
        position_id: UUID | None = None
        move_edge_id: UUID | None = None
        if data.occurrence_id is not None:
            occurrence = await self._active_occurrence(data.occurrence_id)
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
        if data.source_note_id is not None:
            assert occurrence is not None
            await self._validate_reference_card(data.source_note_id, occurrence)
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
        if row.source_note_id is not None and (
            "markdown" in data.model_fields_set or "source_span_ids" in data.model_fields_set
        ):
            raise self._ambiguous(
                "knowledge_note",
                note_id,
                "a reference card renders markdown and citations from its source note",
            )
        if await self.repository.note_has_active_references(note_id):
            archives_note = "archived_at" in changes and changes["archived_at"] is not None
            rejects_note = "review_status" in changes and changes["review_status"] != "approved"
            if archives_note or rejects_note:
                raise self._referenced(
                    "knowledge_note",
                    note_id,
                    "an active explorer reference card depends on this source note",
                )
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

    async def get_content_history(
        self,
        entity_type: str,
        entity_id: UUID,
    ) -> ContentHistoryRead:
        row: CourseModule | CourseContentBlock | CourseOccurrence | KnowledgeNote
        if entity_type == "course_module":
            row = self._require(
                await self.repository.get_module(entity_id),
                entity_type,
                entity_id,
                include_archived=True,
            )
        elif entity_type == "course_content_block":
            row = self._require(
                await self.repository.get_content_block(entity_id),
                entity_type,
                entity_id,
                include_archived=True,
            )
        elif entity_type == "course_occurrence":
            row = self._require(
                await self.repository.get_occurrence(entity_id),
                entity_type,
                entity_id,
                include_archived=True,
            )
        elif entity_type == "knowledge_note":
            row = self._require(
                await self.repository.get_knowledge_note(entity_id),
                entity_type,
                entity_id,
                include_archived=True,
            )
        else:
            raise ServiceError(
                "validation_error",
                422,
                "history entity type is not supported",
                {"field": "entity_type"},
            )
        typed_entity_type = cast(HistoryEntityType, entity_type)
        revisions = await self.repository.list_revisions(entity_type, entity_id)
        return ContentHistoryRead.model_validate(
            {
                "entity_type": typed_entity_type,
                "entity_id": entity_id,
                "current_version": row.version,
                "revisions": [
                    ContentRevisionRead(
                        id=revision.id,
                        created_at=revision.created_at,
                        entity_type=typed_entity_type,
                        entity_id=entity_id,
                        entity_version=revision.entity_version,
                        snapshot=revision.snapshot,
                    )
                    for revision in revisions
                ],
            }
        )

    async def publish_modules_to_explorer(
        self,
        target_course_id: UUID,
        module_ids: list[UUID],
    ) -> PublishModulesRead:
        """Clone selected source paths and link their notes in one idempotent unit."""

        target_course = await self._active_course(target_course_id)
        if target_course.mode != "opening_explorer":
            raise ServiceError(
                "course_mode_conflict",
                409,
                "modules can only be published into an opening_explorer course",
                {"resource": "course", "id": str(target_course_id)},
            )

        replayed: list[ModulePublication] = []
        prepared: list[
            tuple[
                CourseModule,
                list[CourseOccurrence],
                dict[UUID, list[KnowledgeNote]],
            ]
        ] = []
        for source_module_id in module_ids:
            receipt = await self.repository.get_module_publication(
                target_course_id, source_module_id
            )
            if receipt is not None:
                replayed.append(receipt)
                continue
            source_module = await self._active_module(source_module_id)
            source_course = await self._active_course(source_module.course_id)
            if source_course.mode != "traditional":
                raise ServiceError(
                    "course_mode_conflict",
                    409,
                    "only traditional modules can be published into an explorer",
                    {"resource": "course_module", "id": str(source_module_id)},
                )
            occurrences = await self.repository.list_occurrences(
                source_course.id,
                module_id=source_module.id,
            )
            roots = [row for row in occurrences if row.parent_id is None]
            if len(roots) != 1:
                raise self._ambiguous(
                    "course_module",
                    source_module.id,
                    "a published Module must contain exactly one active root occurrence",
                )
            notes_by_occurrence: dict[UUID, list[KnowledgeNote]] = {}
            for occurrence in occurrences:
                notes = await self.repository.list_knowledge_notes(occurrence_id=occurrence.id)
                self._ensure_publishable_notes(notes)
                notes_by_occurrence[occurrence.id] = notes
            prepared.append((source_module, occurrences, notes_by_occurrence))

        existing_target_modules = await self.repository.list_modules(target_course_id)
        target_modules = {row.id: row for row in existing_target_modules}
        target_by_position: dict[UUID, list[CourseOccurrence]] = {}
        target_child_by_edge: dict[tuple[UUID, UUID], CourseOccurrence] = {}
        next_child_sort: dict[UUID, int] = {}
        for existing_module in existing_target_modules:
            target_occurrences = await self.repository.list_occurrences(
                target_course_id,
                module_id=existing_module.id,
            )
            for existing_occurrence in target_occurrences:
                target_by_position.setdefault(existing_occurrence.position_id, []).append(
                    existing_occurrence
                )
                if (
                    existing_occurrence.parent_id is not None
                    and existing_occurrence.inbound_move_edge_id is not None
                ):
                    target_child_by_edge.setdefault(
                        (
                            existing_occurrence.parent_id,
                            existing_occurrence.inbound_move_edge_id,
                        ),
                        existing_occurrence,
                    )
                    next_child_sort[existing_occurrence.parent_id] = max(
                        next_child_sort.get(existing_occurrence.parent_id, 0),
                        existing_occurrence.sort_order + 1,
                    )
        next_module_sort = (
            max(
                (row.sort_order for row in existing_target_modules),
                default=-1,
            )
            + 1
        )
        created: list[ModulePublication] = []
        for source_module, occurrences, notes_by_occurrence in prepared:
            async with self.session.begin_nested():
                source_root = next(row for row in occurrences if row.parent_id is None)
                matching_entries = target_by_position.get(source_root.position_id, [])
                target_entry = matching_entries[0] if matching_entries else None
                target_module = (
                    target_modules.get(target_entry.module_id)
                    if target_entry is not None and target_entry.module_id is not None
                    else None
                )
                if target_module is None:
                    target_module = CourseModule(
                        course_id=target_course_id,
                        parent_id=None,
                        title=(
                            "合并探索图"
                            if not target_modules
                            else f"入口局面 {len(target_modules) + 1}"
                        ),
                        description="Opening Explorer merged position graph.",
                        sort_order=next_module_sort,
                    )
                    next_module_sort += 1
                    await self._add(target_module, "course_module")
                    target_modules[target_module.id] = target_module
                    target_entry = CourseOccurrence(
                        course_id=target_course_id,
                        module_id=target_module.id,
                        parent_id=None,
                        position_id=source_root.position_id,
                        inbound_move_edge_id=None,
                        full_fen=source_root.full_fen,
                        nag=None,
                        sort_order=0,
                        context={},
                    )
                    await self._add(target_entry, "course_occurrence")
                    await self._add(
                        CourseContentBlock(
                            module_id=target_module.id,
                            kind="move_sequence",
                            sort_order=0,
                            heading=None,
                            markdown=None,
                            root_occurrence_id=target_entry.id,
                            knowledge_note_id=None,
                        ),
                        "course_content_block",
                    )
                    target_by_position.setdefault(target_entry.position_id, []).append(target_entry)

                assert target_entry is not None
                occurrence_map: dict[UUID, CourseOccurrence] = {source_root.id: target_entry}
                pending = [row for row in occurrences if row.id != source_root.id]
                while pending:
                    progressed = False
                    for source_occurrence in list(pending):
                        if (
                            source_occurrence.parent_id is not None
                            and source_occurrence.parent_id not in occurrence_map
                        ):
                            continue
                        assert source_occurrence.parent_id is not None
                        assert source_occurrence.inbound_move_edge_id is not None
                        target_parent = occurrence_map[source_occurrence.parent_id]
                        edge_key = (
                            target_parent.id,
                            source_occurrence.inbound_move_edge_id,
                        )
                        target_occurrence = target_child_by_edge.get(edge_key)
                        if target_occurrence is None:
                            target_occurrence = CourseOccurrence(
                                course_id=target_course_id,
                                module_id=target_module.id,
                                parent_id=target_parent.id,
                                position_id=source_occurrence.position_id,
                                inbound_move_edge_id=source_occurrence.inbound_move_edge_id,
                                full_fen=source_occurrence.full_fen,
                                nag=None,
                                sort_order=next_child_sort.get(target_parent.id, 0),
                                context={},
                            )
                            await self._add(target_occurrence, "course_occurrence")
                            target_child_by_edge[edge_key] = target_occurrence
                            next_child_sort[target_parent.id] = target_occurrence.sort_order + 1
                            target_by_position.setdefault(target_occurrence.position_id, []).append(
                                target_occurrence
                            )
                        occurrence_map[source_occurrence.id] = target_occurrence
                        pending.remove(source_occurrence)
                        progressed = True
                    if not progressed:
                        raise self._ambiguous(
                            "course_module",
                            source_module.id,
                            "source occurrence paths contain a missing parent or cycle",
                        )
                note_count = 0
                for source_occurrence in occurrences:
                    target_occurrence = occurrence_map[source_occurrence.id]
                    for source_note in notes_by_occurrence[source_occurrence.id]:
                        await self.create_knowledge_note(
                            KnowledgeNoteCreate(
                                occurrence_id=target_occurrence.id,
                                source_note_id=source_note.id,
                            )
                        )
                        note_count += 1
                receipt = ModulePublication(
                    target_course_id=target_course_id,
                    source_module_id=source_module.id,
                    target_module_id=target_module.id,
                    occurrence_count=len(occurrence_map),
                    note_count=note_count,
                )
                try:
                    await self.repository.add_module_publication(receipt)
                except RepositoryConflictError as error:
                    raise ServiceError(
                        "idempotency_conflict",
                        409,
                        "a concurrent module publication already completed",
                        {"resource": "course_module", "id": str(source_module.id)},
                    ) from error
                created.append(receipt)
        by_source = {row.source_module_id: (row, True) for row in replayed}
        by_source.update({row.source_module_id: (row, False) for row in created})
        return PublishModulesRead(
            publications=[
                self._module_publication_read(*by_source[module_id]) for module_id in module_ids
            ]
        )

    def _ensure_publishable_notes(self, notes: list[KnowledgeNote]) -> None:
        """Reject notes whose meaning cannot be preserved as an Explorer reference card."""

        for note in notes:
            if (
                note.source_note_id is not None
                or note.review_status != "approved"
                or note.markdown is None
            ):
                raise self._ambiguous(
                    "knowledge_note",
                    note.id,
                    "publishing requires approved original Traditional occurrence notes",
                )

    async def _validate_reference_card(
        self,
        source_note_id: UUID,
        target_occurrence: CourseOccurrence,
    ) -> None:
        source_note = self._require(
            await self.repository.get_knowledge_note(source_note_id),
            "knowledge_note",
            source_note_id,
        )
        if source_note.source_note_id is not None or source_note.occurrence_id is None:
            raise self._ambiguous(
                "knowledge_note",
                source_note_id,
                "a reference card must point directly to an original occurrence note",
            )
        if source_note.review_status != "approved":
            raise self._ambiguous(
                "knowledge_note",
                source_note_id,
                "a reference card requires an approved source note",
            )
        source_occurrence = await self._active_occurrence(source_note.occurrence_id)
        source_course = await self._active_course(source_occurrence.course_id)
        target_course = await self._active_course(target_occurrence.course_id)
        if source_course.mode != "traditional" or target_course.mode != "opening_explorer":
            raise self._ambiguous(
                "knowledge_note",
                source_note_id,
                "reference cards must link traditional source notes into an opening explorer",
            )

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
        | CourseContentBlock
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
        | CourseContentBlock
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
            async with self.session.begin_nested():
                if row.version != expected_version:
                    raise RepositoryStaleVersionError
                if resource in {
                    "course_module",
                    "course_content_block",
                    "course_occurrence",
                    "knowledge_note",
                }:
                    authoring_row = cast(
                        CourseModule | CourseContentBlock | CourseOccurrence | KnowledgeNote,
                        row,
                    )
                    await self._record_revision(authoring_row, resource)
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

    async def _record_revision(
        self,
        row: CourseModule | CourseContentBlock | CourseOccurrence | KnowledgeNote,
        entity_type: str,
    ) -> None:
        """Capture the exact pre-edit authoring state once per entity version."""

        archived_at = row.archived_at.isoformat() if row.archived_at is not None else None
        snapshot: dict[str, JsonValue]
        if isinstance(row, CourseModule):
            snapshot = {
                "course_id": str(row.course_id),
                "parent_id": str(row.parent_id) if row.parent_id else None,
                "title": row.title,
                "description": row.description,
                "sort_order": row.sort_order,
                "archived_at": archived_at,
            }
        elif isinstance(row, CourseContentBlock):
            snapshot = {
                "module_id": str(row.module_id),
                "kind": row.kind,
                "sort_order": row.sort_order,
                "heading": row.heading,
                "markdown": row.markdown,
                "root_occurrence_id": (
                    str(row.root_occurrence_id) if row.root_occurrence_id else None
                ),
                "knowledge_note_id": (
                    str(row.knowledge_note_id) if row.knowledge_note_id else None
                ),
                "source_span_ids": [
                    str(span_id)
                    for span_id in await self.repository.list_content_block_citation_ids(row.id)
                ],
                "archived_at": archived_at,
            }
        elif isinstance(row, CourseOccurrence):
            snapshot = {
                "course_id": str(row.course_id),
                "module_id": str(row.module_id) if row.module_id else None,
                "parent_id": str(row.parent_id) if row.parent_id else None,
                "position_id": str(row.position_id),
                "inbound_move_edge_id": (
                    str(row.inbound_move_edge_id) if row.inbound_move_edge_id else None
                ),
                "full_fen": row.full_fen,
                "nag": row.nag,
                "sort_order": row.sort_order,
                "context": row.context,
                "archived_at": archived_at,
            }
        else:
            snapshot = {
                "scope": row.scope,
                "target_kind": row.target_kind,
                "occurrence_id": str(row.occurrence_id) if row.occurrence_id else None,
                "position_id": str(row.position_id) if row.position_id else None,
                "move_edge_id": str(row.move_edge_id) if row.move_edge_id else None,
                "source_note_id": str(row.source_note_id) if row.source_note_id else None,
                "note_type": row.note_type,
                "markdown": row.markdown,
                "source_span_ids": [
                    str(span_id) for span_id in await self.repository.list_note_citation_ids(row.id)
                ],
                "review_status": row.review_status,
                "archived_at": archived_at,
            }
        try:
            await self.repository.add_revision(
                ContentRevision(
                    entity_type=entity_type,
                    entity_id=row.id,
                    entity_version=row.version,
                    snapshot=snapshot,
                )
            )
        except RepositoryConflictError as error:
            raise ServiceError(
                "ambiguous_context",
                409,
                "content history already contains this entity version",
                {
                    "resource": entity_type,
                    "id": str(row.id),
                    "version": row.version,
                },
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
    def _referenced(resource: str, resource_id: UUID, message: str) -> ServiceError:
        return ServiceError(
            "resource_referenced",
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

    async def _content_block_read(self, row: CourseContentBlock) -> CourseContentBlockRead:
        return CourseContentBlockRead.model_validate(
            {
                **self._lifecycle(row),
                "module_id": row.module_id,
                "kind": row.kind,
                "sort_order": row.sort_order,
                "heading": row.heading,
                "markdown": row.markdown,
                "root_occurrence_id": row.root_occurrence_id,
                "knowledge_note_id": row.knowledge_note_id,
                "source_span_ids": (await self.repository.list_content_block_citation_ids(row.id)),
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
            "fragment_sha256": None,
        }
        if isinstance(locator, PageSpan):
            columns["page_number"] = locator.page_number
            columns["bbox"] = locator.bbox.model_dump(mode="python") if locator.bbox else None
            columns["start_value"] = locator.start_offset
            columns["end_value"] = locator.end_offset
            columns["fragment_sha256"] = locator.fragment_sha256
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
            locator = PageSpan(
                page_number=row.page_number,
                bbox=bbox,
                start_offset=row.start_value,
                end_offset=row.end_value,
                fragment_sha256=row.fragment_sha256,
            )
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

    async def _editor_knowledge_note_read(
        self,
        row: KnowledgeNote,
    ) -> EditorKnowledgeNoteRead:
        rendered = row
        if row.source_note_id is not None:
            rendered = self._require(
                await self.repository.get_knowledge_note(row.source_note_id),
                "knowledge_note",
                row.source_note_id,
            )
        if rendered.markdown is None or rendered.occurrence_id is None:
            raise self._ambiguous(
                "knowledge_note",
                row.id,
                "an editor note must resolve to an occurrence note with Markdown",
            )
        source_occurrence = await self._active_occurrence(rendered.occurrence_id)
        base = await self._knowledge_note_read(row)
        return EditorKnowledgeNoteRead.model_validate(
            {
                **base.model_dump(mode="python"),
                "rendered_markdown": rendered.markdown,
                "rendered_source_span_ids": await self.repository.list_note_citation_ids(
                    rendered.id
                ),
                "source_course_id": source_occurrence.course_id,
                "source_module_id": source_occurrence.module_id,
                "source_occurrence_id": source_occurrence.id,
            }
        )

    @staticmethod
    def _module_publication_read(
        row: ModulePublication,
        replayed: bool,
    ) -> ModulePublicationRead:
        return ModulePublicationRead(
            id=row.id,
            created_at=row.created_at,
            target_course_id=row.target_course_id,
            source_module_id=row.source_module_id,
            target_module_id=row.target_module_id,
            occurrence_count=row.occurrence_count,
            note_count=row.note_count,
            replayed=replayed,
        )
