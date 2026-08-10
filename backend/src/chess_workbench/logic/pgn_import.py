"""Compatibility mapper for one already-parsed PGN game.

The authoritative Source/idempotency transaction is ``PgnImportService``.
This smaller adapter remains useful for internal one-game composition and
tests, and follows the same ordered, iterative occurrence mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue

from chess_workbench.logic.pgn import MAX_MOVE_NODES, PgnGame, PgnNode
from chess_workbench.schemas.domain import (
    CourseCreate,
    CourseModuleCreate,
    OccurrenceMoveCreate,
    OccurrenceUpdate,
)
from chess_workbench.services.content import ContentService


@dataclass(frozen=True, slots=True)
class PgnImportResult:
    course_id: UUID
    module_id: UUID
    root_occurrence_id: UUID
    occurrence_count: int


class PgnImporter:
    def __init__(self, service: ContentService, *, max_nodes: int = MAX_MOVE_NODES) -> None:
        self._service = service
        self._max_nodes = max_nodes

    async def import_game(
        self,
        game: PgnGame,
        *,
        course_title: str | None = None,
    ) -> PgnImportResult:
        title = (course_title or game.header("event") or "Imported game").strip()[:200]
        course = await self._service.create_course(
            CourseCreate(title=title or "Imported game", mode="traditional")
        )
        module = await self._service.create_module(
            CourseModuleCreate(
                course_id=course.id,
                title=title or "Main line",
                start_fen=game.root.fen,
            )
        )
        assert module.start_occurrence_id is not None
        root = await self._service.get_occurrence(module.start_occurrence_id)
        root_context = _context(game.root)
        if game.root.nag is not None or root_context:
            await self._service.update_occurrence(
                root.id,
                OccurrenceUpdate(
                    expected_version=root.version,
                    nag=game.root.nag,
                    context=root_context,
                ),
            )

        count = 1
        stack: list[tuple[PgnNode, UUID, int]] = []
        for sort_order in range(len(game.root.children) - 1, -1, -1):
            stack.append((game.root.children[sort_order], root.id, sort_order))
        while stack:
            node, parent_id, sort_order = stack.pop()
            count += 1
            if count > self._max_nodes + 1:
                raise ValueError(f"PGN exceeds maximum import nodes of {self._max_nodes}")
            assert node.uci is not None
            occurrence = await self._service.create_move_occurrence(
                OccurrenceMoveCreate(
                    parent_occurrence_id=parent_id,
                    uci=node.uci,
                    nag=node.nag,
                    sort_order=sort_order,
                    context=_context(node),
                )
            )
            for child_order in range(len(node.children) - 1, -1, -1):
                stack.append((node.children[child_order], occurrence.id, child_order))

        return PgnImportResult(
            course_id=course.id,
            module_id=module.id,
            root_occurrence_id=root.id,
            occurrence_count=count,
        )


def _context(node: PgnNode) -> dict[str, JsonValue]:
    context: dict[str, JsonValue] = {}
    if node.starting_comment:
        context["pgn_starting_comment"] = node.starting_comment
    if node.comment:
        context["pgn_comment"] = node.comment
    if len(node.nags) > 1:
        context["pgn_nags"] = list(node.nags)
    return context
