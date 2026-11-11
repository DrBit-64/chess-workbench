from typing import Annotated

from pydantic import Field

from chess_workbench.schemas.domain import StrictContract

AnswerLine = Annotated[list[str], Field(min_length=1, max_length=128)]


class PracticeEdit(StrictContract):
    expected_version: int = Field(ge=0)
    prompt: str = Field(max_length=4000)
    lines: list[AnswerLine] = Field(min_length=1, max_length=32)


class PracticeRead(StrictContract):
    version: int
    prompt: str
    lines: list[list[str]]


class PracticeRemove(StrictContract):
    expected_version: int = Field(ge=1)
