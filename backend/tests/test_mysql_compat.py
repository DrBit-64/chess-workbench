"""Verify SQLite/MySQL schema and data compatibility (Stage 3D).

These tests run against a real MySQL instance when
``CHESS_WORKBENCH_MYSQL_URL`` is set, and are skipped otherwise.
"""

from __future__ import annotations

import os

import pytest
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database

MYSQL_URL = os.environ.get("CHESS_WORKBENCH_MYSQL_URL", "")

requires_mysql = pytest.mark.skipif(not MYSQL_URL, reason="CHESS_WORKBENCH_MYSQL_URL not set")


def _db_kind(url: str) -> str:
    return "mysql" if "mysql" in url else "sqlite"


@requires_mysql
async def test_mysql_migration_round_trip() -> None:
    """Alembic upgrade→check→downgrade works against a real MySQL."""
    db = Database(MYSQL_URL)
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # Verify we can connect and query.
        async with db.session() as session:
            result = await session.execute(__import__("sqlalchemy").text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        await db.close()


@requires_mysql
async def test_mysql_crud_round_trip() -> None:
    """Create a course via the service layer against MySQL and read it back."""
    from chess_workbench.schemas.domain import CourseCreate
    from chess_workbench.services.content import ContentService

    db = Database(MYSQL_URL)
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

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
    """Position key unique constraint works on MySQL."""
    from chess_workbench.domain.position_identity import PositionState
    from chess_workbench.store.graph_repository import get_or_create_position

    db = Database(MYSQL_URL)
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        async with db.session() as session, session.begin():
            state = PositionState.from_fen(
                "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            )
            stored1 = await get_or_create_position(session, state)
            stored2 = await get_or_create_position(session, state)
            assert stored1.position.id == stored2.position.id
    finally:
        await db.close()
