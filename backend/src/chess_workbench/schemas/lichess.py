"""One-way course publication to a new Lichess study."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from chess_workbench.schemas.domain import StrictContract

StudyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class LichessStudyScope(StrictContract):
    module_id: UUID | None = None
    module_ids: list[UUID] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def one_scope_format(self) -> Self:
        if self.module_id is not None and self.module_ids is not None:
            raise ValueError("module_id and module_ids cannot be provided together")
        return self


class LichessStudyCreate(LichessStudyScope):
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
