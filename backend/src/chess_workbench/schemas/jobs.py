"""Generic job read contract shared by every async API resource.

The engine module re-exports these names so existing engine imports and the
generated OpenAPI document remain unchanged; new extraction contracts import
the generic contract from here instead of depending on engine schemas.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from chess_workbench.schemas.domain import NonEmptyText, StrictContract, UtcDateTime

JobStatusValue = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class JobRead(StrictContract):
    id: UUID
    kind: NonEmptyText
    status: JobStatusValue
    payload: dict[str, object]
    result: dict[str, object] | None
    attempt_count: int
    max_attempts: int
    cancel_requested_at: UtcDateTime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
