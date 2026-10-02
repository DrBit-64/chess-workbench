"""One-way course publication to a new Lichess study."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from chess_workbench.schemas.domain import StrictContract

StudyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class LichessStudyCreate(StrictContract):
    module_id: UUID
    name: StudyName
    orientation: Literal["white", "black"] = "white"


class LichessChapterPreview(StrictContract):
    module_id: UUID
    name: str
    move_count: int


class LichessStudyPreview(StrictContract):
    name: str
    chapters: list[LichessChapterPreview]
    skipped_modules: list[str]
    warnings: list[str]
    blockers: list[str]
    token_configured: bool
    max_chapters: int = 64


class LichessStudyResult(StrictContract):
    study_url: str
    status: Literal["complete", "partial", "uncertain"]
    imported_chapters: Annotated[int, Field(ge=0)]
    expected_chapters: Annotated[int, Field(ge=1)]
    message: str
