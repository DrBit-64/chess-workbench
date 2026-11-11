"""Bulk mapping of a validated PGN tree onto the shared position and move graph."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import batched
from uuid import UUID, uuid4

from sqlalchemy import insert, select, tuple_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.domain import PositionState
from chess_workbench.logic.pgn import PgnNode
from chess_workbench.store.graph_repository import GraphInvariantError
from chess_workbench.store.models.graph import MoveEdge, Position
from chess_workbench.store.models.personal_games import PersonalGameNode


@dataclass(frozen=True, slots=True)
class _Occurrence:
    id: UUID
    parent: UUID | None
    order: int
    mainline: bool
    key: str
    source_key: str | None
    node: PgnNode


async def persist_game_tree(session: AsyncSession, game_id: UUID, root: PgnNode) -> None:
    """The PGN parser has already validated every move and produced its SAN and full FEN.

    Upsert graph facts set-wise before inserting the ordered, path-specific occurrences.
    A previously known edge must agree with both the target position and the PGN SAN.
    """
    occurrences: list[_Occurrence] = []
    states: dict[str, PositionState] = {}
    moves: dict[tuple[str, str], tuple[str, str]] = {}
    stack: list[tuple[PgnNode, UUID | None, int, bool, str | None]] = [(root, None, 0, True, None)]
    while stack:
        node, parent, order, mainline, source_key = stack.pop()
        state = PositionState(node.fen)
        key = state.position_key
        states.setdefault(key, state)
        node_id = uuid4()
        occurrences.append(_Occurrence(node_id, parent, order, mainline, key, source_key, node))
        if source_key is not None:
            assert node.uci is not None and node.san is not None
            moves[source_key, node.uci] = (key, node.san)
        for index in reversed(range(len(node.children))):
            stack.append((node.children[index], node_id, index, mainline and index == 0, key))

    sqlite = session.get_bind().dialect.name == "sqlite"
    position_values = [
        {
            "position_key": s.position_key,
            "canonical_fen": s.canonical_fen,
            "piece_placement": s.piece_placement,
            "side_to_move": s.side_to_move,
            "castling_rights": s.castling_rights,
            "en_passant": s.en_passant,
            "material_signature": s.material_signature,
        }
        for _, s in sorted(states.items())
    ]
    # The only supported database families are SQLite and MySQL/MariaDB.
    position_upsert = (
        sqlite_insert(Position).on_conflict_do_nothing(index_elements=[Position.position_key])
        if sqlite
        else mysql_insert(Position).on_duplicate_key_update(id=Position.id)
    )
    await session.execute(position_upsert, position_values)
    positions: dict[str, UUID] = {}
    for keys in batched(states, 400, strict=False):
        rows = await session.execute(
            select(Position.position_key, Position.id).where(Position.position_key.in_(keys))
        )
        positions.update((k, i) for k, i in rows)

    edge_ids = await _persist_edges(session, moves, positions, sqlite)
    values = []
    for occ in occurrences:
        node = occ.node
        edge = (
            edge_ids[positions[occ.source_key], node.uci]
            if occ.source_key is not None and node.uci is not None
            else None
        )
        values.append(
            {
                "id": occ.id,
                "game_id": game_id,
                "parent_id": occ.parent,
                "position_id": positions[occ.key],
                "move_edge_id": edge,
                "ply": node.ply,
                "sort_order": occ.order,
                "is_mainline": occ.mainline,
                "fen": node.fen,
                "san": node.san,
                "uci": node.uci,
                "nags": list(node.nags),
                "starting_comment": node.starting_comment,
                "comment": node.comment,
                "note": "",
            }
        )
    # Pre-order keeps parents available before their children even when executemany
    # splits at a driver page boundary. Root and non-root rows use one parameter shape.
    await session.execute(
        insert(PersonalGameNode), values, execution_options={"render_nulls": True}
    )


async def _persist_edges(
    session: AsyncSession,
    moves: dict[tuple[str, str], tuple[str, str]],
    positions: dict[str, UUID],
    sqlite: bool,
) -> dict[tuple[UUID, str], UUID]:
    if not moves:
        return {}
    expected = {
        (positions[src], uci): (positions[dst], san) for (src, uci), (dst, san) in moves.items()
    }
    values = [
        {"from_position_id": src, "to_position_id": dst, "uci": uci, "san": san}
        for (src, uci), (dst, san) in sorted(expected.items())
    ]
    edge_upsert = (
        sqlite_insert(MoveEdge).on_conflict_do_nothing(
            index_elements=[MoveEdge.from_position_id, MoveEdge.uci]
        )
        if sqlite
        else mysql_insert(MoveEdge).on_duplicate_key_update(id=MoveEdge.id)
    )
    await session.execute(edge_upsert, values)
    ids: dict[tuple[UUID, str], UUID] = {}
    for keys in batched(expected, 400, strict=False):
        rows = await session.execute(
            select(
                MoveEdge.from_position_id,
                MoveEdge.uci,
                MoveEdge.to_position_id,
                MoveEdge.san,
                MoveEdge.id,
            ).where(tuple_(MoveEdge.from_position_id, MoveEdge.uci).in_(keys))
        )
        for source, uci, target, san, edge_id in rows:
            if expected[source, uci] != (target, san):
                raise GraphInvariantError("persisted edge disagrees with the imported move")
            ids[source, uci] = edge_id
    return ids
