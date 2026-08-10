from __future__ import annotations

from pathlib import Path

import chess
import pytest
from chess_workbench.schemas.domain import (
    CourseContentBlockCreate,
    CourseContentBlockUpdate,
    CourseCreate,
    CourseModuleCreate,
    KnowledgeNoteCreate,
    KnowledgeNoteUpdate,
    OccurrenceMoveCreate,
    OccurrenceNoteTarget,
    RootOccurrenceCreate,
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
            assert isinstance(note_a.target, OccurrenceNoteTarget)
            assert note_a.target.occurrence_id == child_a.id
            assert isinstance(note_b.target, OccurrenceNoteTarget)
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

            second_source = await service.create_source(SourceCreate(kind="book", title="Other"))
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


async def test_catalog_filters_cover_every_search_field_and_sort(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'catalog-filters.db'}")
    try:
        await create_schema(database)
        async with database.session() as session, session.begin():
            service = ContentService(session)
            alpha = await service.create_course(
                CourseCreate(
                    title="Alpha title",
                    description="Quiet plans",
                    category="Opening",
                    tags=["Study", "White"],
                    status="published",
                    mode="traditional",
                )
            )
            beta = await service.create_course(
                CourseCreate(
                    title="Beta",
                    description="Dynamic candidate search",
                    tags=["Black"],
                    mode="opening_explorer",
                )
            )
            gamma = await service.create_course(
                CourseCreate(
                    title="Gamma",
                    category="Endgame laboratory",
                    tags=[],
                )
            )

            assert [row.id for row in await service.list_courses(query="alpha")] == [alpha.id]
            assert [row.id for row in await service.list_courses(query="candidate")] == [beta.id]
            assert [row.id for row in await service.list_courses(query="laboratory")] == [gamma.id]
            assert await service.list_courses(query="absent") == []
            assert [row.id for row in await service.list_courses(mode="opening_explorer")] == [
                beta.id
            ]
            assert [row.id for row in await service.list_courses(status="published")] == [alpha.id]
            assert [row.id for row in await service.list_courses(tag="study")] == [alpha.id]
            assert [row.title for row in await service.list_courses(sort="title_asc")] == [
                "Alpha title",
                "Beta",
                "Gamma",
            ]
            assert len(await service.list_courses(sort="created_desc")) == 3
            assert len(await service.list_courses()) == 3

            book = await service.create_source(
                SourceCreate(
                    kind="book",
                    title="Positional Manual",
                    author="Averbakh",
                    description="Technique",
                )
            )
            web = await service.create_source(
                SourceCreate(
                    kind="web",
                    title="Chess article",
                    description="Candidate move notes",
                )
            )
            assert [row.id for row in await service.list_sources(query="manual")] == [book.id]
            assert [row.id for row in await service.list_sources(query="averbakh")] == [book.id]
            assert [row.id for row in await service.list_sources(query="candidate")] == [web.id]
            assert await service.list_sources(query="absent") == []
            assert [row.id for row in await service.list_sources(kind="web")] == [web.id]
            assert len(await service.list_sources()) == 2
    finally:
        await database.close()


async def test_content_block_update_rules_and_detached_root_are_service_owned(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'block-rules.db'}")
    try:
        await create_schema(database)
        async with database.session() as session, session.begin():
            service = ContentService(session)
            course = await service.create_course(CourseCreate(title="Authoring"))
            module = await service.create_module(
                CourseModuleCreate(
                    course_id=course.id,
                    title="Chapter",
                    start_fen=chess.STARTING_FEN,
                )
            )
            assert module.start_occurrence_id is not None
            child = await service.create_move_occurrence(
                OccurrenceMoveCreate(
                    parent_occurrence_id=module.start_occurrence_id,
                    uci="e2e4",
                )
            )
            filtered_occurrences = await service.list_occurrences(
                course.id,
                module_id=module.id,
                parent_id=module.start_occurrence_id,
            )
            assert [row.id for row in filtered_occurrences] == [child.id]
            with pytest.raises(ServiceError) as duplicate_root:
                await service.create_root_occurrence(
                    RootOccurrenceCreate(
                        course_id=course.id,
                        module_id=module.id,
                        fen=chess.STARTING_FEN,
                    )
                )
            assert duplicate_root.value.code == "ambiguous_context"
            move_block = (await service.list_content_blocks(module.id))[0]
            section = await service.create_content_block(
                CourseContentBlockCreate(
                    module_id=module.id,
                    kind="section_header",
                    sort_order=1,
                    heading="First heading",
                )
            )
            narrative = await service.create_content_block(
                CourseContentBlockCreate(
                    module_id=module.id,
                    kind="narrative",
                    sort_order=2,
                    markdown="First text",
                )
            )
            section = await service.update_content_block(
                section.id,
                CourseContentBlockUpdate(
                    expected_version=section.version,
                    heading="Revised heading",
                ),
            )
            narrative = await service.update_content_block(
                narrative.id,
                CourseContentBlockUpdate(
                    expected_version=narrative.version,
                    markdown="Revised text",
                ),
            )
            assert section.heading == "Revised heading"
            assert narrative.markdown == "Revised text"

            with pytest.raises(ServiceError) as wrong_heading:
                await service.update_content_block(
                    narrative.id,
                    CourseContentBlockUpdate(
                        expected_version=narrative.version,
                        heading="Not allowed",
                    ),
                )
            assert wrong_heading.value.code == "ambiguous_context"
            with pytest.raises(ServiceError) as wrong_markdown:
                await service.update_content_block(
                    section.id,
                    CourseContentBlockUpdate(
                        expected_version=section.version,
                        markdown="Not allowed",
                    ),
                )
            assert wrong_markdown.value.code == "ambiguous_context"
            with pytest.raises(ServiceError) as protected_root:
                await service.update_content_block(
                    move_block.id,
                    CourseContentBlockUpdate(
                        expected_version=move_block.version,
                        archived=True,
                    ),
                )
            assert protected_root.value.code == "resource_referenced"

            detached_root = await service.create_root_occurrence(
                RootOccurrenceCreate(
                    course_id=course.id,
                    fen=chess.STARTING_FEN,
                )
            )
            assert detached_root.module_id is None
    finally:
        await database.close()
