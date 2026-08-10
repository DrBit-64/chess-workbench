"""Strict PGN import/export HTTP contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from chess_workbench.schemas.domain import StrictContract, Title, UtcDateTime

PgnText = Annotated[str, StringConstraints(min_length=1)]


class NewCourseDestination(StrictContract):
    kind: Literal["new_course"] = "new_course"
    title: Title | None = None


class ExistingCourseDestination(StrictContract):
    kind: Literal["existing_course"]
    course_id: UUID
    expected_version: Annotated[int, Field(ge=1)]


PgnDestination = Annotated[
    NewCourseDestination | ExistingCourseDestination,
    Field(discriminator="kind"),
]


class PgnImportJson(StrictContract):
    pgn: PgnText
    destination: PgnDestination = Field(default_factory=NewCourseDestination)
    source_title: Title | None = None
    game_titles: list[Title] | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def game_titles_must_not_be_empty(self) -> PgnImportJson:
        if self.game_titles is not None and not self.game_titles:
            raise ValueError("game_titles must contain at least one title when provided")
        return self


class PgnImportOptions(StrictContract):
    destination: PgnDestination = Field(default_factory=NewCourseDestination)
    source_title: Title | None = None
    game_titles: list[Title] | None = Field(default=None, max_length=1_000)


class PgnImportGameRead(StrictContract):
    id: UUID
    game_index: int
    module_id: UUID
    root_occurrence_id: UUID
    source_span_id: UUID
    occurrence_count: int


class PgnImportRead(StrictContract):
    id: UUID
    created_at: UtcDateTime
    asset_id: UUID
    source_id: UUID
    source_version_id: UUID
    source_file_id: UUID
    course_id: UUID
    course_version: int
    game_count: int
    occurrence_count: int
    games: list[PgnImportGameRead]


class PgnImportEnvelope(StrictContract):
    replayed: bool
    import_receipt: PgnImportRead


class PgnDownloadMetadata(StrictContract):
    """Documentation-only representation of download response metadata."""

    generated_at: datetime
