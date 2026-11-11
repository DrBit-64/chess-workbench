"""Contracts for a user's saved games, moves and import selection."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from chess_workbench.schemas.domain import StrictContract, UtcDateTime, VersionNumber

NotebookText = Annotated[str, StringConstraints(max_length=100_000)]


class NotebookGame(StrictContract):
    id: UUID
    white: str
    black: str
    date: str
    result: str
    platform: str | None
    source_url: str | None
    summary: str
    archived_at: UtcDateTime | None
    created_at: UtcDateTime
    version: int


class NotebookGameCatalog(StrictContract):
    items: list[NotebookGame]
    total: int


class NotebookNode(StrictContract):
    id: UUID
    parent_id: UUID | None
    ply: int
    sort_order: int
    is_mainline: bool
    fen: str
    san: str | None
    uci: str | None
    nags: list[int]
    starting_comment: str
    comment: str
    note: str
    version: int


class NotebookGameDetail(NotebookGame):
    headers: dict[str, str]
    nodes: list[NotebookNode]


class NotebookGameUpdate(StrictContract):
    expected_version: VersionNumber
    summary: NotebookText | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def has_changes(self) -> Self:
        if self.summary is None and self.archived is None:
            raise ValueError("provide a summary or archive state")
        return self


class NotebookNodeUpdate(StrictContract):
    expected_version: VersionNumber
    note: NotebookText


class NotebookPreviewRequest(StrictContract):
    pgn: str | None = None
    url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    username: Annotated[str, StringConstraints(max_length=80)] | None = None

    month: Annotated[str, StringConstraints(pattern=r"^\d{4}-(?:0[1-9]|1[0-2])$")] | None = None

    @model_validator(mode="after")
    def one_input(self) -> Self:
        if (self.pgn is None) == (self.url is None):
            raise ValueError("provide one PGN or game link")
        return self


class NotebookCandidate(StrictContract):
    index: int
    white: str
    black: str
    date: str
    result: str
    platform: str | None
    source_url: str | None
    existing_id: UUID | None
    possible_duplicates: list[UUID]


class NotebookImportPreview(StrictContract):
    duplicate_games: list[NotebookGame]
    source_url: str | None
    pgn: str
    games: list[NotebookCandidate]


class NotebookSelection(StrictContract):
    index: Annotated[int, Field(ge=0)]
    action: Literal["save", "open", "copy"] = "save"
    existing_id: UUID | None = None


class NotebookImportRequest(StrictContract):
    source_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    pgn: str
    selections: Annotated[list[NotebookSelection], Field(min_length=1, max_length=1000)]
    request_id: UUID | None = None


class NotebookImportItem(StrictContract):
    id: UUID
    index: int
    created: bool


class NotebookImportResult(StrictContract):
    games: list[NotebookImportItem]
