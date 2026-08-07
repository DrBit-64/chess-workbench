"""Import a PGN semantic tree into the course/occurrence layer (Stage 3B)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from chess_workbench.schemas.domain import OccurrenceUpdate
from chess_workbench.services.content import ContentService

if TYPE_CHECKING:
    from chess_workbench.logic.pgn import PgnGame, PgnNode


class PgnImportResult:
    __slots__ = ("course_id", "module_id", "root_occurrence_id", "occurrence_count")

    def __init__(
        self,
        course_id: UUID,
        module_id: UUID,
        root_occurrence_id: UUID,
        occurrence_count: int,
    ) -> None:
        self.course_id = course_id
        self.module_id = module_id
        self.root_occurrence_id = root_occurrence_id
        self.occurrence_count = occurrence_count


class PgnImporter:
    MAX_DEPTH = 500

    def __init__(self, service: ContentService) -> None:
        self._service = service
        self._count = 0

    async def import_game(
        self,
        game: PgnGame,
        *,
        course_title: str | None = None,
    ) -> PgnImportResult:
        from chess_workbench.schemas.domain import CourseCreate, CourseModuleCreate

        title = course_title or game.headers.get("event", "Imported game")

        course = await self._service.create_course(CourseCreate(title=title, mode="traditional"))
        module = await self._service.create_module(
            CourseModuleCreate(
                course_id=course.id,
                title="Main line",
                start_fen=game.root.fen,
            )
        )

        occs = await self._service.list_occurrences(course.id)
        if not occs:
            raise RuntimeError("module creation did not produce a root occurrence")
        root_occ = occs[0]

        root_patch = self._build_update(
            root_occ.version, nag=game.root.nag, comment=game.root.comment
        )
        if root_patch is not None:
            await self._service.update_occurrence(root_occ.id, root_patch)

        self._count = 1
        for child in game.root.children:
            await self._walk_node(child, parent_occ_id=root_occ.id)

        return PgnImportResult(
            course_id=course.id,
            module_id=module.id,
            root_occurrence_id=root_occ.id,
            occurrence_count=self._count,
        )

    async def _walk_node(self, node: PgnNode, parent_occ_id: UUID) -> None:
        if node.ply > self.MAX_DEPTH:
            raise ValueError(f"PGN exceeds maximum import depth of {self.MAX_DEPTH} plies")

        from chess_workbench.schemas.domain import OccurrenceMoveCreate

        assert node.uci is not None, "non-root PGN node must have a UCI move"
        child_occ = await self._service.create_move_occurrence(
            OccurrenceMoveCreate(
                parent_occurrence_id=parent_occ_id,
                uci=node.uci,
                nag=node.nag,
            )
        )
        self._count += 1

        if node.comment:
            patch = self._build_update(child_occ.version, nag=node.nag, comment=node.comment)
            if patch is not None:
                await self._service.update_occurrence(child_occ.id, patch)

        for grandchild in node.children:
            await self._walk_node(grandchild, parent_occ_id=child_occ.id)

    @staticmethod
    def _build_update(
        version: int,
        *,
        nag: int | None,
        comment: str,
    ) -> OccurrenceUpdate | None:
        context: dict[str, Any] | None = None
        if comment:
            context = {"pgn_comment": comment}

        if context is None:
            return None

        return OccurrenceUpdate(
            expected_version=version,
            nag=nag,
            context=context,
        )
