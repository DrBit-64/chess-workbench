"""Export a Course's occurrence tree back to PGN text (Stage 3C)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from chess_workbench.services.content import ContentService


async def export_pgn(service: ContentService, course_id: UUID) -> str:
    from sqlalchemy import select

    from chess_workbench.store.models import MoveEdge

    occs = await service.list_occurrences(course_id)
    if not occs:
        raise ValueError("course has no occurrences")
    roots = [o for o in occs if o.parent_id is None]
    if len(roots) != 1:
        raise ValueError(f"expected 1 root, found {len(roots)}")
    root = roots[0]

    edge_ids = {o.inbound_move_edge_id for o in occs if o.inbound_move_edge_id}
    stmt = select(MoveEdge).where(MoveEdge.id.in_(edge_ids))
    result = await service.session.execute(stmt)
    edges: dict[UUID, Any] = {e.id: e for e in result.scalars().all()}

    children_map: dict[UUID | None, list[Any]] = {}
    for occ in occs:
        children_map.setdefault(occ.parent_id, []).append(occ)
    for lst in children_map.values():
        lst.sort(key=lambda o: o.sort_order)

    course = await service.get_course(course_id)
    import contextlib
    import json

    stored: dict[str, str] = {}
    if course.description:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            stored = json.loads(course.description)

    lines = [
        f'[Event "{stored.get("event", course.title or "?")}"]',
        f'[Site "{stored.get("site", "ChessWorkbench")}"]',
        f'[Date "{stored.get("date", "????.??.??")}"]',
        f'[Round "{stored.get("round", "?")}"]',
        f'[White "{stored.get("white", "?")}"]',
        f'[Black "{stored.get("black", "?")}"]',
        f'[Result "{stored.get("result", "*")}"]',
    ]
    sf = root.full_fen
    if sf != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1":
        lines.append(f'[FEN "{sf}"]')
        lines.append('[SetUp "1"]')
    lines.append("")

    parts: list[str] = []
    _render_children(children_map.get(root.id, []), children_map, edges, parts, ply=0)
    lines.append(" ".join(parts) if parts else "*")
    return "\n".join(lines) + "\n"


def _render_children(
    siblings: list[Any],
    children_map: dict[UUID | None, list[Any]],
    edges: dict[UUID, Any],
    parts: list[str],
    *,
    ply: int,
) -> None:
    if not siblings:
        return
    for i, occ in enumerate(siblings):
        edge = edges.get(occ.inbound_move_edge_id) if occ.inbound_move_edge_id else None
        san = edge.san if edge else "?"
        ctx: dict[str, object] = occ.context or {}
        comment = str(ctx.get("pgn_comment", ""))
        sub = children_map.get(occ.id, [])
        if i == 0:
            _push_move(parts, san, occ.nag, comment, ply, i)
            for var in siblings[1:]:
                _render_variation(var, children_map, edges, parts, ply)
            if sub:
                _render_children(sub, children_map, edges, parts, ply=ply + 1)
            break


def _render_variation(
    occ: Any,
    children_map: dict[UUID | None, list[Any]],
    edges: dict[UUID, Any],
    parts: list[str],
    ply: int,
) -> None:
    edge = edges.get(occ.inbound_move_edge_id) if occ.inbound_move_edge_id else None
    san = edge.san if edge else "?"
    ctx: dict[str, object] = occ.context or {}
    comment = str(ctx.get("pgn_comment", ""))
    var_parts: list[str] = []
    _push_move(var_parts, san, occ.nag, comment, ply, 0)
    sub = children_map.get(occ.id, [])
    if sub:
        _render_children(sub, children_map, edges, var_parts, ply=ply + 1)
    parts.append("(" + " ".join(var_parts) + ")")


def _push_move(
    parts: list[str], san: str, nag: int | None, comment: str, ply: int, index: int
) -> None:
    if index == 0:
        parts.append(f"{ply // 2 + 1}." if ply % 2 == 0 else f"{ply // 2 + 1}...")
    parts.append(san)
    if nag is not None:
        parts.append(f"${nag}")
    if comment:
        parts.append("{" + comment + "}")
