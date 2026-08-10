"""Verify real MySQL Alembic round-trip (Stage 3D / DS-MYSQL-01).

These tests run against a real MySQL instance when
``CHESS_WORKBENCH_MYSQL_URL`` is set.  They use the *actual* Alembic
``upgrade → check → downgrade → upgrade`` cycle and assert revision
state and business-table presence against the live database.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from chess_workbench.store.database import Database

MYSQL_URL = os.environ.get("CHESS_WORKBENCH_MYSQL_URL", "")

requires_mysql = pytest.mark.skipif(not MYSQL_URL, reason="CHESS_WORKBENCH_MYSQL_URL not set")

# –– Alembic helpers –––––––––––––––––––––––––––––––––––––––––––––––

_ALEMBIC_INI = os.path.join(os.path.dirname(__file__), os.pardir, "alembic.ini")


def _alembic_config() -> Any:  # alembic.config.Config
    import alembic.config

    cfg = alembic.config.Config(_ALEMBIC_INI)
    db_url = os.environ.get("CHESS_WORKBENCH_DATABASE_URL", "")
    if db_url:
        cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


_BUSINESS_TABLES = frozenset(
    {
        "courses",
        "course_modules",
        "course_occurrences",
        "course_content_blocks",
        "course_content_block_citations",
        "content_revisions",
        "knowledge_notes",
        "knowledge_note_citations",
        "sources",
        "source_files",
        "source_spans",
        "source_versions",
        "positions",
        "move_edges",
        "module_publications",
        "pgn_assets",
        "pgn_imports",
        "pgn_import_games",
        "pgn_occurrence_annotations",
    }
)


def _current_revision(config: Any) -> str | None:
    """Return the current Alembic head revision or None."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = config.get_main_option("sqlalchemy.url")

    async def _get() -> str | None:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
                return row[0] if row else None
        finally:
            await engine.dispose()

    return asyncio.run(_get())


def _present_tables(config: Any) -> frozenset[str]:
    """Return the set of non-Alembic table names present in the database."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = config.get_main_option("sqlalchemy.url")

    async def _get() -> frozenset[str]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_SCHEMA = DATABASE() "
                        "AND TABLE_NAME != 'alembic_version'"
                    )
                )
                return frozenset(row[0] for row in result.fetchall())
        finally:
            await engine.dispose()

    return asyncio.run(_get())


# –– fixtures –––––––––––––––––––––––––––––––––––––––––––––––––––––––


@pytest.fixture(scope="session", autouse=True)
def _mysql_head_schema() -> None:
    """Ensure head revision and all business tables exist once per session.

    Runs before any test that needs the schema, independent of
    collection or execution order.
    """
    import alembic.command

    os.environ.setdefault("CHESS_WORKBENCH_DATABASE_URL", MYSQL_URL)
    cfg = _alembic_config()
    alembic.command.upgrade(cfg, "head")

    assert _current_revision(cfg) == "20260810_0009", "session fixture did not reach head revision"
    assert _present_tables(cfg) >= _BUSINESS_TABLES, "session fixture is missing business tables"


# –– tests ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


@requires_mysql
def test_migration_upgrade_check_downgrade_upgrade() -> None:
    """Alembic upgrade→check→downgrade→upgrade cycle on real MySQL."""
    import alembic.command

    cfg = _alembic_config()

    # Already at head via session fixture; assertions validate pre-state.
    assert _current_revision(cfg) == "20260810_0009"
    assert _present_tables(cfg) >= _BUSINESS_TABLES

    # Real Alembic check (Codex verified: exits 0 on fresh MySQL 8.4).
    alembic.command.check(cfg)

    # Downgrade to empty.
    alembic.command.downgrade(cfg, "base")
    assert _current_revision(cfg) is None
    assert len(_present_tables(cfg)) == 0

    # Re-upgrade so sibling tests see head schema.
    alembic.command.upgrade(cfg, "head")
    assert _current_revision(cfg) == "20260810_0009"


@requires_mysql
async def test_mysql_crud_round_trip() -> None:
    """Create a course via the service layer on Alembic-created schema."""
    from chess_workbench.schemas.domain import CourseCreate
    from chess_workbench.services.content import ContentService

    db = Database(MYSQL_URL)
    try:
        async with db.session() as session, session.begin():
            service = ContentService(session)
            course = await service.create_course(
                CourseCreate(title="MySQL Course", mode="traditional")
            )
            assert course.title == "MySQL Course"
            assert course.mode == "traditional"

            fetched = await service.get_course(course.id)
            assert fetched.title == "MySQL Course"
    finally:
        await db.close()


@requires_mysql
async def test_mysql_position_key_uniqueness() -> None:
    """Position key unique constraint works on Alembic-created MySQL schema."""
    from chess_workbench.domain.position_identity import PositionState
    from chess_workbench.store.graph_repository import get_or_create_position

    db = Database(MYSQL_URL)
    try:
        async with db.session() as session, session.begin():
            state = PositionState.from_fen(
                "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            )
            stored1 = await get_or_create_position(session, state)
            stored2 = await get_or_create_position(session, state)
            assert stored1.position.id == stored2.position.id
    finally:
        await db.close()


@requires_mysql
async def test_mysql_pgn_import_replay_and_semantic_export(tmp_path: Path) -> None:
    """The new PGN provenance/import/export path behaves on real MySQL."""
    from chess_workbench.logic.pgn import parse_pgn_document
    from chess_workbench.logic.pgn_compare import compare_documents
    from chess_workbench.logic.pgn_export import export_import_pgn
    from chess_workbench.schemas.pgn import NewCourseDestination
    from chess_workbench.services.pgn import PgnImportService, prepare_pgn_import

    raw = (Path(__file__).parent / "fixtures" / "pgn" / "02_one_variation.pgn").read_bytes()
    prepared = prepare_pgn_import(
        raw,
        destination=NewCourseDestination(title="MySQL PGN"),
        source_title="MySQL source",
        game_titles=None,
        idempotency_key="mysql-pgn-fixture",
        storage_root=tmp_path / "data",
    )
    db = Database(MYSQL_URL)
    try:
        async with db.session() as session, session.begin():
            service = PgnImportService(session)
            created = await service.import_prepared(prepared)
            replayed = await service.import_prepared(prepared)
            exported = await export_import_pgn(session, created.receipt.id)
            assert not created.replayed
            assert replayed.replayed
            assert replayed.receipt.id == created.receipt.id
            assert replayed.receipt.course_id == created.receipt.course_id
            comparison = compare_documents(
                parse_pgn_document(raw.decode("utf-8")),
                parse_pgn_document(exported),
            )
            assert comparison.equivalent, comparison.differences
    finally:
        await db.close()
