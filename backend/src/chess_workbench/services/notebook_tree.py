"""Edit an occurrence tree without rewriting the imported moves or their source links."""

from collections import defaultdict
from itertools import batched
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, load_only

from chess_workbench.domain import PositionError, PositionState
from chess_workbench.schemas.notebook_tree import (
    NotebookBranchEdit,
    NotebookRecordMove,
    NotebookTreeResult,
)
from chess_workbench.schemas.personal_games import NotebookNode
from chess_workbench.services import ServiceError
from chess_workbench.services.personal_games import check_notebook_version, flush_notebook_edits
from chess_workbench.store.graph_repository import get_or_create_move
from chess_workbench.store.models.personal_games import PersonalGame, PersonalGameNode

type Ranks = dict[PersonalGameNode, int]


async def _lock_game(session: AsyncSession, game_id: UUID, expected: int) -> PersonalGame:
    game = await session.scalar(
        select(PersonalGame)
        .where(PersonalGame.id == game_id)
        .options(defer(PersonalGame.original_pgn), defer(PersonalGame.headers))
        .with_for_update()
    )
    if game is None:
        raise ServiceError("not_found", 404, "这盘棋已删除或不存在。")
    check_notebook_version(game.version, expected)
    return game


async def _node(session: AsyncSession, game_id: UUID, node_id: UUID) -> PersonalGameNode:
    node = await session.get(PersonalGameNode, node_id)
    if node is None or node.game_id != game_id:
        raise ServiceError("not_found", 404, "未找到此棋步。")
    return node


def _require_visible(node: PersonalGameNode) -> None:
    if node.hidden:
        raise ServiceError("resource_referenced", 409, "这个棋步已移出棋谱，请先恢复路径。")


async def _siblings(session: AsyncSession, game_id: UUID, parent: UUID) -> list[PersonalGameNode]:
    return list(
        await session.scalars(
            select(PersonalGameNode)
            .where(PersonalGameNode.game_id == game_id, PersonalGameNode.parent_id == parent)
            .order_by(PersonalGameNode.sort_order)
        )
    )


def _set_order(ranks: Ranks, ordered: list[PersonalGameNode]) -> None:
    ranks.update((node, rank) for rank, node in enumerate(ordered) if node.sort_order != rank)


def _append_visible(ranks: Ranks, siblings: list[PersonalGameNode], node: PersonalGameNode) -> None:
    others = [child for child in siblings if child != node]
    _set_order(
        ranks,
        [child for child in others if not child.hidden]
        + [node]
        + [child for child in others if child.hidden],
    )


async def _finish(
    session: AsyncSession,
    game: PersonalGame,
    selected: UUID,
    changed: set[PersonalGameNode],
    ranks: Ranks,
) -> NotebookTreeResult:
    changed.update(ranks)
    if ranks:
        # Reserve disjoint slots before swapping. The sibling order index is unique
        # immediately on both SQLite and MySQL, even within a single transaction.
        for node in ranks:
            node.sort_order = -1 - node.sort_order
        await flush_notebook_edits(session)
        for node, rank in ranks.items():
            node.sort_order = rank
    nodes: list[NotebookNode] = []
    if changed:
        game.version += 1
        await flush_notebook_edits(session)
        # Multi-level operations only loaded topology. Read full changed rows in bounded
        # batches so large PGN comments don't have to be read for unaffected branches.
        for ids in batched((node.id for node in changed), 400, strict=False):
            rows = await session.scalars(
                select(PersonalGameNode).where(PersonalGameNode.id.in_(ids))
            )
            nodes.extend(NotebookNode.model_validate(row, from_attributes=True) for row in rows)
    return NotebookTreeResult(game_version=game.version, selected_id=selected, nodes=nodes)


async def record_move(
    session: AsyncSession, game_id: UUID, body: NotebookRecordMove
) -> NotebookTreeResult:
    game = await _lock_game(session, game_id, body.expected_version)
    parent = await _node(session, game_id, body.parent_id)
    _require_visible(parent)
    siblings = await _siblings(session, game_id, parent.id)
    # Imported PGNs can repeat a UCI as two separate occurrences with different notes.
    # Siblings are ordered with visible occurrences first. Keep their identity intact.
    node = next((item for item in siblings if item.uci == body.uci), None)
    ranks: Ranks = {}
    if node is not None:
        if not node.hidden:
            return await _finish(session, game, node.id, set(), ranks)
        node.hidden = False
    else:
        try:
            stored = await get_or_create_move(session, PositionState(parent.fen), body.uci)
        except PositionError as error:
            raise ServiceError("illegal_move", 422, "这个局面不能走这步棋。") from error
        node = PersonalGameNode(
            id=uuid4(),
            game_id=game.id,
            parent_id=parent.id,
            position_id=stored.target.id,
            move_edge_id=stored.edge.id,
            ply=parent.ply + 1,
            sort_order=len(siblings),
            hidden=False,
            is_mainline=False,
            fen=stored.move.after.full_fen,
            san=stored.move.san,
            uci=stored.move.uci,
            nags=[],
            starting_comment="",
            comment="",
            note="",
        )
        session.add(node)
    _append_visible(ranks, siblings, node)
    return await _finish(session, game, node.id, {node}, ranks)


async def edit_branch(
    session: AsyncSession, game_id: UUID, node_id: UUID, body: NotebookBranchEdit
) -> NotebookTreeResult:
    game = await _lock_game(session, game_id, body.expected_version)
    node = await _node(session, game_id, node_id)
    if node.parent_id is None:
        raise ServiceError("validation_error", 422, "起始局面没有可编辑的棋步。")
    selected = node.id
    ranks: Ranks = {}
    changed: set[PersonalGameNode] = set()
    if body.kind == "delete_subtree":
        selected = node.parent_id
    elif body.kind != "restore_path":
        _require_visible(node)
    if body.kind in ("promote_variation", "demote_variation"):
        siblings = await _siblings(session, game_id, node.parent_id)
        offset = siblings.index(node)
        neighbor = offset + (-1 if body.kind == "promote_variation" else 1)
        if 0 <= neighbor < len(siblings) and not siblings[neighbor].hidden:
            siblings[offset], siblings[neighbor] = siblings[neighbor], siblings[offset]
            _set_order(ranks, siblings)
    elif (body.kind == "delete_subtree" and node.hidden) or (
        body.kind == "restore_path" and not node.hidden
    ):
        return await _finish(session, game, selected, changed, ranks)
    else:
        # Load links once even for a thousand-ply game; avoid recursive traversal or
        # one database round trip per ply. Version checks also protect concurrent notes.
        rows = await session.scalars(
            select(PersonalGameNode)
            .where(PersonalGameNode.game_id == game_id)
            .options(
                load_only(
                    PersonalGameNode.id,
                    PersonalGameNode.parent_id,
                    PersonalGameNode.sort_order,
                    PersonalGameNode.hidden,
                    PersonalGameNode.version,
                )
            )
            .order_by(PersonalGameNode.sort_order)
        )
        by_id = {row.id: row for row in rows}
        children: dict[UUID, list[PersonalGameNode]] = defaultdict(list)
        for row in by_id.values():
            if row.parent_id is not None:
                children[row.parent_id].append(row)
        if body.kind == "delete_subtree":
            stack = [node]
            while stack:
                current = stack.pop()
                if not current.hidden:
                    current.hidden = True
                    changed.add(current)
                    stack.extend(children[current.id])
            siblings = children[node.parent_id]
            _set_order(ranks, sorted(siblings, key=lambda child: child.hidden))
        else:
            current = node
            while current.parent_id is not None:
                siblings = children[current.parent_id]
                if body.kind == "restore_path":
                    if not current.hidden:
                        break
                    current.hidden = False
                    changed.add(current)
                    _append_visible(ranks, siblings, current)
                elif siblings[0] != current:
                    _set_order(ranks, [current] + [child for child in siblings if child != current])
                current = by_id[current.parent_id]
    return await _finish(session, game, selected, changed, ranks)
