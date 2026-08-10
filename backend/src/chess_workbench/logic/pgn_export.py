"""Bounded occurrence-scope PGN exporter with explicit corruption checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import chess
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.store.models import (
    Course,
    CourseModule,
    CourseOccurrence,
    MoveEdge,
    PgnImport,
    PgnImportGame,
    PgnOccurrenceAnnotation,
)

MAX_EXPORT_NODES = 50_000
STANDARD_FEN = chess.STARTING_FEN


class PgnExportError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(slots=True)
class _ExportNode:
    occurrence: CourseOccurrence
    edge: MoveEdge | None
    annotation: PgnOccurrenceAnnotation | None
    children: list[_ExportNode]


async def export_module_pgn(
    session: AsyncSession,
    course_id: UUID,
    module_id: UUID,
    *,
    leaf_occurrence_id: UUID | None = None,
    max_nodes: int = MAX_EXPORT_NODES,
) -> str:
    course = await session.get(Course, course_id)
    if course is None or course.archived_at is not None:
        raise PgnExportError("course_not_found", "Course was not found")
    module = await session.get(CourseModule, module_id)
    if module is None or module.archived_at is not None or module.course_id != course_id:
        raise PgnExportError("module_not_found", "Module was not found in the Course")
    occurrences = list(
        await session.scalars(
            select(CourseOccurrence).where(
                CourseOccurrence.course_id == course_id,
                CourseOccurrence.module_id == module_id,
                CourseOccurrence.archived_at.is_(None),
            )
        )
    )
    if not occurrences:
        raise PgnExportError("empty_module", "Module has no active occurrences")
    if len(occurrences) > max_nodes:
        raise PgnExportError("node_limit", "Module exceeds the PGN export node limit")

    by_id = {occurrence.id: occurrence for occurrence in occurrences}
    roots = [occurrence for occurrence in occurrences if occurrence.parent_id is None]
    if len(roots) != 1:
        raise PgnExportError("root_count", "Module must have exactly one active root")
    root = roots[0]
    if leaf_occurrence_id is not None and leaf_occurrence_id not in by_id:
        foreign_leaf = await session.get(CourseOccurrence, leaf_occurrence_id)
        if foreign_leaf is None:
            raise PgnExportError("leaf_not_found", "leaf occurrence was not found")
        raise PgnExportError(
            "leaf_scope",
            "leaf occurrence belongs to a different Course or Module",
        )
    selected = _selected_occurrences(by_id, root, leaf_occurrence_id)
    selected_ids = set(selected)

    edge_ids = {
        occurrence.inbound_move_edge_id
        for occurrence in selected.values()
        if occurrence.inbound_move_edge_id is not None
    }
    edges = {
        edge.id: edge
        for edge in await session.scalars(select(MoveEdge).where(MoveEdge.id.in_(edge_ids)))
    }
    annotations = {
        annotation.occurrence_id: annotation
        for annotation in await session.scalars(
            select(PgnOccurrenceAnnotation).where(
                PgnOccurrenceAnnotation.occurrence_id.in_(selected_ids)
            )
        )
    }
    tree_root = _validated_tree(root, selected, edges, annotations)

    import_game = cast(
        PgnImportGame | None,
        await session.scalar(select(PgnImportGame).where(PgnImportGame.module_id == module_id)),
    )
    result = (
        "*"
        if leaf_occurrence_id is not None
        else (import_game.movetext_result if import_game is not None else "*")
    )
    headers = _headers(import_game, module, root.full_fen, result)
    return _render(headers, tree_root, result)


async def export_import_pgn(session: AsyncSession, import_id: UUID) -> str:
    receipt = await session.get(PgnImport, import_id)
    if receipt is None:
        raise PgnExportError("import_not_found", "PGN import receipt was not found")
    games = list(
        await session.scalars(
            select(PgnImportGame)
            .where(PgnImportGame.pgn_import_id == import_id)
            .order_by(PgnImportGame.game_index)
        )
    )
    if len(games) != receipt.game_count:
        raise PgnExportError("game_count", "PGN import receipt has an inconsistent game set")
    rendered = [
        await export_module_pgn(session, receipt.course_id, game.module_id) for game in games
    ]
    return "\n\n".join(text.rstrip() for text in rendered) + "\n"


async def export_pgn(
    service: Any,
    course_id: UUID,
    *,
    module_id: UUID | None = None,
    leaf_occurrence_id: UUID | None = None,
) -> str:
    """Compatibility adapter that now requires an unambiguous Module scope."""

    if module_id is None:
        raise PgnExportError("module_required", "module_id is required for Course PGN export")
    return await export_module_pgn(
        service.session,
        course_id,
        module_id,
        leaf_occurrence_id=leaf_occurrence_id,
    )


def _selected_occurrences(
    by_id: dict[UUID, CourseOccurrence],
    root: CourseOccurrence,
    leaf_id: UUID | None,
) -> dict[UUID, CourseOccurrence]:
    if leaf_id is None:
        return by_id
    leaf = by_id.get(leaf_id)
    if leaf is None:
        raise PgnExportError("leaf_not_found", "leaf occurrence was not found in the Module")
    path: dict[UUID, CourseOccurrence] = {}
    current = leaf
    while True:
        if current.id in path:
            raise PgnExportError("cycle", "occurrence path contains a cycle")
        path[current.id] = current
        if current.parent_id is None:
            break
        parent = by_id.get(current.parent_id)
        if parent is None:
            raise PgnExportError("broken_parent", "occurrence path leaves the Module")
        current = parent
    if current.id != root.id:
        raise PgnExportError("wrong_root", "leaf is not a descendant of the Module root")
    return path


def _validated_tree(
    root: CourseOccurrence,
    occurrences: dict[UUID, CourseOccurrence],
    edges: dict[UUID, MoveEdge],
    annotations: dict[UUID, PgnOccurrenceAnnotation],
) -> _ExportNode:
    children_by_parent: dict[UUID, list[CourseOccurrence]] = {}
    for occurrence in occurrences.values():
        if occurrence.id == root.id:
            if occurrence.inbound_move_edge_id is not None:
                raise PgnExportError("root_edge", "Module root has an inbound MoveEdge")
            continue
        if occurrence.parent_id not in occurrences:
            raise PgnExportError("broken_parent", "occurrence parent is outside the export scope")
        if occurrence.inbound_move_edge_id is None or occurrence.inbound_move_edge_id not in edges:
            raise PgnExportError("missing_edge", "occurrence has no valid inbound MoveEdge")
        children_by_parent.setdefault(occurrence.parent_id, []).append(occurrence)
    for children in children_by_parent.values():
        children.sort(key=lambda item: item.sort_order)
        if [child.sort_order for child in children] != list(range(len(children))):
            raise PgnExportError("sibling_order", "sibling sort_order must be contiguous from zero")

    built: dict[UUID, _ExportNode] = {}
    visited: set[UUID] = set()
    stack: list[tuple[str, CourseOccurrence]] = [("enter", root)]
    while stack:
        action, occurrence = stack.pop()
        if action == "exit":
            built[occurrence.id] = _ExportNode(
                occurrence=occurrence,
                edge=(
                    edges.get(occurrence.inbound_move_edge_id)
                    if occurrence.inbound_move_edge_id is not None
                    else None
                ),
                annotation=annotations.get(occurrence.id),
                children=[built[child.id] for child in children_by_parent.get(occurrence.id, [])],
            )
            continue
        if occurrence.id in visited:
            raise PgnExportError("cycle", "occurrence graph contains a cycle or repeated node")
        visited.add(occurrence.id)
        stack.append(("exit", occurrence))
        for child in reversed(children_by_parent.get(occurrence.id, [])):
            stack.append(("enter", child))
    if visited != set(occurrences):
        raise PgnExportError("unreachable", "Module contains occurrences unreachable from its root")
    return built[root.id]


def _headers(
    import_game: PgnImportGame | None,
    module: CourseModule,
    root_fen: str,
    result: str,
) -> list[tuple[str, str]]:
    if import_game is not None:
        headers = [(str(item["name"]), str(item["value"])) for item in import_game.headers]
    else:
        headers = [
            ("Event", module.title),
            ("Site", "ChessWorkbench"),
            ("Date", "????.??.??"),
            ("Round", "?"),
            ("White", "?"),
            ("Black", "?"),
            ("Result", result),
        ]
    headers = [(name, result if name.lower() == "result" else value) for name, value in headers]
    if not any(name.lower() == "result" for name, _ in headers):
        headers.append(("Result", result))
    if root_fen != STANDARD_FEN:
        if not any(name.lower() == "fen" for name, _ in headers):
            headers.append(("FEN", root_fen))
        if not any(name.lower() == "setup" for name, _ in headers):
            headers.append(("SetUp", "1"))
    return headers


def _render(headers: list[tuple[str, str]], root: _ExportNode, result: str) -> str:
    lines = [f'[{name} "{_tag_value(value)}"]' for name, value in headers]
    parts: list[str] = []
    root_annotation = root.annotation
    if root_annotation is not None and root_annotation.comment:
        parts.append(_comment(root_annotation.comment))
    elif root.occurrence.context.get("pgn_comment"):
        parts.append(_comment(str(root.occurrence.context["pgn_comment"])))

    stack: list[tuple[str, _ExportNode | str]] = [("process", root)]
    while stack:
        action, value = stack.pop()
        if action == "literal":
            parts.append(cast(str, value))
            continue
        node = cast(_ExportNode, value)
        if action == "move":
            parts.extend(_move_tokens(node))
            continue
        if action == "branch":
            stack.append(("literal", ")"))
            stack.append(("process", node))
            stack.append(("move", node))
            stack.append(("literal", "("))
            continue
        if not node.children:
            continue
        main = node.children[0]
        stack.append(("process", main))
        for variation in reversed(node.children[1:]):
            stack.append(("branch", variation))
        stack.append(("move", main))
    parts.append(result)
    lines.extend(("", " ".join(parts)))
    return "\n".join(lines) + "\n"


def _move_tokens(node: _ExportNode) -> list[str]:
    if node.edge is None or node.occurrence.parent_id is None:
        raise PgnExportError("missing_edge", "non-root occurrence lacks an inbound edge")
    # The resulting occurrence fullmove counter increments only after Black's
    # move. Derive the pre-move number/turn by applying the edge to a board
    # reconstructed from the edge source in callers would require a join; the
    # child full FEN contains enough information for canonical numbering.
    after = chess.Board(node.occurrence.full_fen)
    if after.turn == chess.BLACK:
        move_number = after.fullmove_number
        prefix = f"{move_number}."
    else:
        move_number = max(1, after.fullmove_number - 1)
        prefix = f"{move_number}..."
    tokens: list[str] = []
    annotation = node.annotation
    if annotation is not None and annotation.starting_comment:
        tokens.append(_comment(annotation.starting_comment))
    tokens.extend((prefix, node.edge.san))
    nags = (
        annotation.nags
        if annotation is not None
        else ([node.occurrence.nag] if node.occurrence.nag is not None else [])
    )
    tokens.extend(f"${int(nag)}" for nag in nags)
    comment = (
        annotation.comment
        if annotation is not None
        else str((node.occurrence.context or {}).get("pgn_comment", ""))
    )
    if comment:
        tokens.append(_comment(comment))
    return tokens


def _tag_value(value: str) -> str:
    safe = value.replace("\r", " ").replace("\n", " ")
    return safe.replace("\\", "\\\\").replace('"', '\\"')


def _comment(value: str) -> str:
    safe = value.replace("}", "]")
    return "{" + safe + "}"
