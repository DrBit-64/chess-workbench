"""Personal notebook bookmarks, their explicit move links, and search results."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from chess_workbench.schemas.domain import StrictContract, UtcDateTime, VersionNumber

TagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
MatchField = Literal["title", "tag", "note", "move_note"]


class NotebookBookmarkCreate(StrictContract):
    node_id: UUID
    related_node_id: UUID | None = None


class NotebookBookmarkUpdate(StrictContract):
    expected_version: VersionNumber
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=100_000)
    tags: list[TagName] | None = Field(default=None, max_length=64)
    active: bool | None = None

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, tags: list[str] | None) -> list[str] | None:
        return list(dict.fromkeys(tags)) if tags is not None else None

    @model_validator(mode="after")
    def check_patch(self) -> Self:
        changed = self.model_fields_set - {"expected_version"}
        if not changed or any(getattr(self, field) is None for field in changed):
            raise ValueError(
                "supply a value for at least one editable field; clear with an empty value"
            )
        return self


class NotebookOccurrence(StrictContract):
    game_id: UUID
    node_id: UUID
    white: str
    black: str
    date: str
    fen: str
    ply: int
    san: str | None
    is_mainline: bool
    archived: bool


class NotebookRelatedMove(StrictContract):
    node_id: UUID
    san: str
    note: str


class NotebookMatch(StrictContract):
    field: MatchField
    text: str


class NotebookBookmark(NotebookOccurrence):
    id: UUID
    title: str
    note: str
    tags: list[str]
    active: bool
    version: int
    created_at: UtcDateTime
    related_moves: list[NotebookRelatedMove]
    matches: list[NotebookMatch]


class NotebookBookmarkList(StrictContract):
    items: list[NotebookBookmark]
    total: int


class NotebookOccurrenceList(StrictContract):
    items: list[NotebookOccurrence]
    total: int


class NotebookBookmarkTags(StrictContract):
    tags: list[str]


class NotebookBookmarkQuery(StrictContract):
    q: str = Field(default="", max_length=500)
    tag: list[TagName] = Field(default_factory=list, max_length=64)
    game_id: UUID | None = None
    offset: int = Field(default=0, ge=0)
    limit: int | None = Field(default=None, ge=1, le=500)


class NotebookOccurrenceQuery(StrictContract):
    include_variations: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class NotebookDeleteQuery(StrictContract):
    expected_version: VersionNumber
