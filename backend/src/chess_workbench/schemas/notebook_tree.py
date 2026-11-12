"""Edits to a saved game's working move tree."""

from typing import Literal
from uuid import UUID

from chess_workbench.schemas.domain import StrictContract, UciMove, VersionNumber
from chess_workbench.schemas.personal_games import NotebookNode


class NotebookRecordMove(StrictContract):
    parent_id: UUID
    uci: UciMove
    expected_version: VersionNumber


class NotebookBranchEdit(StrictContract):
    kind: Literal[
        "promote_variation", "demote_variation", "make_mainline", "delete_subtree", "restore_path"
    ]
    expected_version: VersionNumber


class NotebookTreeResult(StrictContract):
    game_version: VersionNumber
    selected_id: UUID
    nodes: list[NotebookNode]
