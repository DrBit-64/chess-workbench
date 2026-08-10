from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.domain import MoveResult, PositionState
from chess_workbench.store.models import MoveEdge, Position


class GraphInvariantError(RuntimeError):
    """Persisted graph facts disagree with authoritative chess rules."""


@dataclass(frozen=True, slots=True)
class StoredPosition:
    position: Position
    created: bool


@dataclass(frozen=True, slots=True)
class StoredMove:
    source: Position
    edge: MoveEdge
    target: Position
    move: MoveResult
    source_created: bool
    edge_created: bool
    target_created: bool


async def find_position(session: AsyncSession, position_id: UUID) -> Position | None:
    return await session.get(Position, position_id)


def _uses_sqlite_upsert(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "sqlite"


async def get_or_create_position(
    session: AsyncSession,
    state: PositionState,
) -> StoredPosition:
    # A SQLite read-before-write upsert can deadlock: concurrent deferred
    # transactions all acquire SHARED locks for the SELECT and then cannot
    # upgrade while another writer is waiting to commit.  Start with one
    # atomic INSERT .. ON CONFLICT instead.  This also lets SQLite's busy
    # timeout serialize contenders without leaking database-is-locked errors.
    if _uses_sqlite_upsert(session):
        inserted_id = (
            await session.execute(
                sqlite_insert(Position)
                .values(
                    position_key=state.position_key,
                    canonical_fen=state.canonical_fen,
                    piece_placement=state.piece_placement,
                    side_to_move=state.side_to_move,
                    castling_rights=state.castling_rights,
                    en_passant=state.en_passant,
                    material_signature=state.material_signature,
                )
                .on_conflict_do_nothing(index_elements=[Position.position_key])
                .returning(Position.id)
            )
        ).scalar_one_or_none()
        stored = await session.scalar(
            select(Position).where(Position.position_key == state.position_key)
        )
        if stored is None:
            raise GraphInvariantError("SQLite position upsert did not return a persisted row")
        return StoredPosition(stored, created=inserted_id is not None)

    existing = await session.scalar(
        select(Position).where(Position.position_key == state.position_key)
    )
    if existing is not None:
        return StoredPosition(existing, created=False)

    candidate = Position.from_state(state)
    try:
        async with session.begin_nested():
            session.add(candidate)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(Position).where(Position.position_key == state.position_key)
        )
        if existing is None:
            raise
        return StoredPosition(existing, created=False)

    return StoredPosition(candidate, created=True)


async def get_or_create_move(
    session: AsyncSession,
    before: PositionState,
    uci: str,
) -> StoredMove:
    """Validate and persist one global move fact without committing the unit of work."""

    move = before.apply_uci(uci)
    stored_source = await get_or_create_position(session, move.before)
    stored_target = await get_or_create_position(session, move.after)

    existing_edge = await session.scalar(
        select(MoveEdge).where(
            MoveEdge.from_position_id == stored_source.position.id,
            MoveEdge.uci == move.uci,
        )
    )
    if existing_edge is not None:
        _assert_edge_matches(existing_edge, stored_target.position, move)
        return StoredMove(
            source=stored_source.position,
            edge=existing_edge,
            target=stored_target.position,
            move=move,
            source_created=stored_source.created,
            edge_created=False,
            target_created=stored_target.created,
        )

    candidate = MoveEdge(
        from_position_id=stored_source.position.id,
        to_position_id=stored_target.position.id,
        uci=move.uci,
        san=move.san,
    )
    try:
        async with session.begin_nested():
            session.add(candidate)
            await session.flush()
    except IntegrityError:
        existing_edge = await session.scalar(
            select(MoveEdge).where(
                MoveEdge.from_position_id == stored_source.position.id,
                MoveEdge.uci == move.uci,
            )
        )
        if existing_edge is None:
            raise
        _assert_edge_matches(existing_edge, stored_target.position, move)
        edge = existing_edge
        edge_created = False
    else:
        edge = candidate
        edge_created = True

    return StoredMove(
        source=stored_source.position,
        edge=edge,
        target=stored_target.position,
        move=move,
        source_created=stored_source.created,
        edge_created=edge_created,
        target_created=stored_target.created,
    )


def _assert_edge_matches(edge: MoveEdge, target: Position, move: MoveResult) -> None:
    if edge.to_position_id != target.id or edge.san != move.san:
        raise GraphInvariantError(
            "persisted move edge disagrees with the authoritative target position or SAN"
        )
