from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import StringConstraints, field_validator

from chess_workbench.schemas.domain import StrictContract

GamePlatform = Literal["lichess", "chess.com"]
AccountName = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[a-zA-Z0-9_-]{1,40}$")
]


class NotebookAccountCreate(StrictContract):
    platform: GamePlatform
    username: AccountName
    start_date: date

    @field_validator("start_date")
    @classmethod
    def valid_date(cls, value: date) -> date:
        if not date(2000, 1, 1) <= value <= datetime.now(UTC).date():
            raise ValueError("请选择今天或更早的同步起始日期")
        return value


class NotebookAccountView(StrictContract):
    id: UUID
    platform: GamePlatform
    username: str
    start_date: date
    last_synced_ms: int | None
    imported: int
    existing: int
    queued: int
    waiting: int
    failed: int
    last_error: str | None


class NotebookSyncResult(StrictContract):
    account: NotebookAccountView
    more: bool
