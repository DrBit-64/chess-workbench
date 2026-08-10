from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import chess
import pytest
from chess_workbench.domain import PositionError, PositionState
from chess_workbench.store import graph_repository
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.graph_repository import (
    GraphInvariantError,
    _assert_edge_matches,
    find_position,
    get_or_create_move,
    get_or_create_position,
)
from chess_workbench.store.models import MoveEdge, Position
from sqlalchemy import func, select


async def create_schema(database: Database) -> None:
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def test_position_identity_converges_while_full_state_stays_external(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'identity.db'}")
    early = PositionState("8/8/8/8/8/4k3/8/4K3 w - - 0 1")
    late = PositionState("8/8/8/8/8/4k3/8/4K3 w - - 99 73")

    try:
        await create_schema(database)
        async with database.session() as session, session.begin():
            first = await get_or_create_position(session, early)
            second = await get_or_create_position(session, late)

        assert first.created is True
        assert second.created is False
        assert first.position.id == second.position.id
        assert first.position.canonical_fen.endswith(" 0 1")
        assert "99 73" not in first.position.canonical_fen
        async with database.session() as session:
            assert await find_position(session, first.position.id) is not None
    finally:
        await database.close()


async def test_move_creation_is_legal_atomic_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'moves.db'}")

    try:
        await create_schema(database)
        # Exercise the portable fallback used by MySQL while retaining a
        # deterministic local database fixture for the focused Stage 2B gate.
        monkeypatch.setattr(graph_repository, "_uses_sqlite_upsert", lambda _session: False)
        async with database.session() as session, session.begin():
            first = await get_or_create_move(session, PositionState(chess.STARTING_FEN), "e2e4")
            repeated = await get_or_create_move(session, PositionState(chess.STARTING_FEN), "e2e4")

        assert first.edge_created is True
        assert repeated.edge_created is False
        assert first.edge.id == repeated.edge.id
        assert first.target.id == repeated.target.id
        assert first.edge.san == "e4"

        async with database.session() as session:
            position_count = await session.scalar(select(func.count()).select_from(Position))
            edge_count = await session.scalar(select(func.count()).select_from(MoveEdge))

        assert position_count == 2
        assert edge_count == 1
    finally:
        await database.close()


async def test_illegal_move_leaves_the_graph_empty(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'rollback.db'}")

    try:
        await create_schema(database)
        async with database.session() as session:
            with pytest.raises(PositionError):
                async with session.begin():
                    await get_or_create_move(
                        session,
                        PositionState(chess.STARTING_FEN),
                        "e2e5",
                    )

        async with database.session() as session:
            position_count = await session.scalar(select(func.count()).select_from(Position))
            edge_count = await session.scalar(select(func.count()).select_from(MoveEdge))

        assert position_count == 0
        assert edge_count == 0
    finally:
        await database.close()


async def test_concurrent_position_creation_converges_on_one_row(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}")
    state = PositionState(chess.STARTING_FEN)

    async def create_once() -> UUID:
        async with database.session() as session, session.begin():
            stored = await get_or_create_position(session, state)
            return stored.position.id

    try:
        await create_schema(database)
        ids = await asyncio.gather(*(create_once() for _ in range(10)))

        async with database.session() as session:
            count = await session.scalar(select(func.count()).select_from(Position))

        assert len(set(ids)) == 1
        assert count == 1
    finally:
        await database.close()


def test_persisted_edge_corruption_is_detected() -> None:
    move = PositionState(chess.STARTING_FEN).apply_uci("e2e4")
    target = Position.from_state(move.after)
    target.id = uuid4()
    edge = MoveEdge(
        from_position_id=uuid4(),
        to_position_id=uuid4(),
        uci=move.uci,
        san=move.san,
    )
    with pytest.raises(GraphInvariantError, match="disagrees"):
        _assert_edge_matches(edge, target, move)
    edge.to_position_id = target.id
    _assert_edge_matches(edge, target, move)
