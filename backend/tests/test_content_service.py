from __future__ import annotations

from pathlib import Path

import chess
import pytest
from chess_workbench.schemas.domain import (
    CourseCreate,
    CourseModuleCreate,
    KnowledgeNoteCreate,
    KnowledgeNoteUpdate,
    OccurrenceMoveCreate,
    SourceCreate,
    SourceFileCreate,
    SourceSpanCreate,
    SourceUpdate,
    SourceVersionCreate,
    WholeSpan,
)
from chess_workbench.services import ContentService, ServiceError
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import CourseOccurrence, KnowledgeNote, MoveEdge, Position
from sqlalchemy import func, select


async def create_schema(database: Database) -> None:
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def test_two_courses_share_graph_facts_but_keep_local_context(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'content.db'}")
    try:
        await create_schema(database)
        async with database.session() as session, session.begin():
            service = ContentService(session)
            course_a = await service.create_course(CourseCreate(title="Course A"))
            course_b = await service.create_course(CourseCreate(title="Course B"))
            module_a = await service.create_module(
                CourseModuleCreate(
                    course_id=course_a.id,
                    title="A root",
                    start_fen=chess.STARTING_FEN,
                )
            )
            module_b = await service.create_module(
                CourseModuleCreate(
                    course_id=course_b.id,
                    title="B root",
                    start_fen=chess.STARTING_FEN,
                )
            )
            assert module_a.start_occurrence_id is not None
            assert module_b.start_occurrence_id is not None

            child_a = await service.create_move_occurrence(
                OccurrenceMoveCreate(
                    parent_occurrence_id=module_a.start_occurrence_id,
                    uci="e2e4",
                    nag=1,
                    context={"author": "A"},
                )
            )
            child_b = await service.create_move_occurrence(
                OccurrenceMoveCreate(
                    parent_occurrence_id=module_b.start_occurrence_id,
                    uci="e2e4",
                    nag=2,
                    context={"author": "B"},
                )
            )
            note_a = await service.create_knowledge_note(
                KnowledgeNoteCreate(occurrence_id=child_a.id, markdown="A says this is best")
            )
            note_b = await service.create_knowledge_note(
                KnowledgeNoteCreate(occurrence_id=child_b.id, markdown="B calls this practical")
            )

            assert child_a.position_id == child_b.position_id
            assert child_a.inbound_move_edge_id == child_b.inbound_move_edge_id
            assert child_a.nag == 1
            assert child_b.nag == 2
            assert note_a.target.occurrence_id == child_a.id
            assert note_b.target.occurrence_id == child_b.id

            with pytest.raises(ServiceError) as illegal:
                await service.create_move_occurrence(
                    OccurrenceMoveCreate(
                        parent_occurrence_id=module_a.start_occurrence_id,
                        uci="e2e5",
                    )
                )
            assert illegal.value.code == "illegal_move"
            assert illegal.value.status == 422

        async with database.session() as session:
            assert await session.scalar(select(func.count()).select_from(Position)) == 2
            assert await session.scalar(select(func.count()).select_from(MoveEdge)) == 1
            assert await session.scalar(select(func.count()).select_from(CourseOccurrence)) == 4
            assert await session.scalar(select(func.count()).select_from(KnowledgeNote)) == 2
    finally:
        await database.close()


async def test_sources_citations_optimistic_lock_and_archive_are_service_owned(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'sources.db'}")
    try:
        await create_schema(database)
        async with database.session() as session, session.begin():
            service = ContentService(session)
            source = await service.create_source(SourceCreate(kind="book", title="Book"))
            version = await service.create_source_version(
                SourceVersionCreate(source_id=source.id, label="First")
            )
            source_file = await service.create_source_file(
                SourceFileCreate(
                    source_version_id=version.id,
                    filename="book.pdf",
                    relative_path="sources/book.pdf",
                    media_type="application/pdf",
                    size_bytes=10,
                    sha256="a" * 64,
                )
            )
            span = await service.create_source_span(
                SourceSpanCreate(
                    source_version_id=version.id,
                    source_file_id=source_file.id,
                    locator=WholeSpan(),
                )
            )

            course = await service.create_course(CourseCreate(title="Course"))
            module = await service.create_module(
                CourseModuleCreate(
                    course_id=course.id,
                    title="Root",
                    start_fen=chess.STARTING_FEN,
                )
            )
            assert module.start_occurrence_id is not None
            note = await service.create_knowledge_note(
                KnowledgeNoteCreate(
                    occurrence_id=module.start_occurrence_id,
                    markdown="Cited note",
                    source_span_ids=[span.id],
                )
            )
            assert note.source_span_ids == [span.id]

            note = await service.update_knowledge_note(
                note.id,
                KnowledgeNoteUpdate(expected_version=note.version, source_span_ids=[]),
            )
            assert note.version == 2
            assert note.source_span_ids == []

            source = await service.update_source(
                source.id,
                SourceUpdate(expected_version=source.version, archived=True),
            )
            assert source.archived_at is not None
            assert await service.get_source_version(version.id) == version
            with pytest.raises(ServiceError) as hidden:
                await service.get_source(source.id)
            assert hidden.value.code == "not_found"

            with pytest.raises(ServiceError) as stale:
                await service.update_source(
                    source.id,
                    SourceUpdate(expected_version=1, archived=False),
                )
            assert stale.value.code == "stale_version"
            assert stale.value.details == {
                "resource": "source",
                "id": str(source.id),
                "expected": 1,
                "actual": 2,
            }

            source = await service.update_source(
                source.id,
                SourceUpdate(expected_version=source.version, archived=False),
            )
            assert source.archived_at is None

            second_source = await service.create_source(
                SourceCreate(kind="book", title="Other")
            )
            second_version = await service.create_source_version(
                SourceVersionCreate(source_id=second_source.id, label="Other edition")
            )
            with pytest.raises(ServiceError) as cross_parent:
                await service.create_source_span(
                    SourceSpanCreate(
                        source_version_id=second_version.id,
                        source_file_id=source_file.id,
                        locator=WholeSpan(),
                    )
                )
            assert cross_parent.value.code == "ambiguous_context"
    finally:
        await database.close()
