"""Test KnowledgeNote.source_note_id at the service layer."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import chess
from chess_workbench.schemas.domain import (
    CourseCreate,
    CourseModuleCreate,
    KnowledgeNoteCreate,
)
from chess_workbench.services import ContentService
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database


async def _root_note(
    service: ContentService,
    title: str,
    markdown: str,
) -> tuple[UUID, UUID]:
    """Create course+module+root occurrence+note. Return (root_occurrence_id, note_id)."""
    course = await service.create_course(CourseCreate(title=title))
    await service.create_module(
        CourseModuleCreate(
            course_id=course.id,
            title="Main",
            start_fen=chess.STARTING_FEN,
        ),
    )
    occs = await service.list_occurrences(course.id)
    root_id = occs[0].id
    note = await service.create_knowledge_note(
        KnowledgeNoteCreate(occurrence_id=root_id, markdown=markdown),
    )
    return root_id, note.id


async def test_note_without_source_note_id_has_none(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'n1.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session() as session, session.begin():
        service = ContentService(session)
        _, note_id = await _root_note(service, "Course", "Text")
        fetched = await service.get_knowledge_note(note_id)
        assert fetched.source_note_id is None


async def test_note_source_link_round_trip(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'n2.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session() as session, session.begin():
        service = ContentService(session)
        _, orig_id = await _root_note(service, "Trad", "Original.")
        explorer_root, _ = await _root_note(service, "Explorer", "Dummy")
        linked = await service.create_knowledge_note(
            KnowledgeNoteCreate(
                occurrence_id=explorer_root,
                source_note_id=orig_id,
                markdown="Aggregated.",
            ),
        )
        assert linked.source_note_id == orig_id
        fetched = await service.get_knowledge_note(linked.id)
        assert fetched.source_note_id == orig_id


async def test_source_note_id_preserved_on_read(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'n3.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session() as session, session.begin():
        service = ContentService(session)
        _, n1_id = await _root_note(service, "Src", "A.")
        root2, n2_id = await _root_note(service, "Tgt", "B.")
        linked = await service.create_knowledge_note(
            KnowledgeNoteCreate(
                occurrence_id=root2,
                source_note_id=n1_id,
                markdown="Linked.",
            ),
        )
        assert (await service.get_knowledge_note(linked.id)).source_note_id == n1_id
