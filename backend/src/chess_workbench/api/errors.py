"""Stable public errors for the Stage 2 HTTP boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sanic import Request
from sanic.response import HTTPResponse, json

from chess_workbench.schemas.domain import ErrorCode, ErrorResponse


@dataclass(slots=True)
class ApiError(Exception):
    """An expected domain failure safe to expose to an API client."""

    status: int
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # Dataclass-generated initializers do not initialize Exception.args.
        # Keeping it populated makes unexpected logging paths retain the safe,
        # public message instead of rendering an empty exception string.
        Exception.__init__(self, self.message)


async def handle_api_error(_: Request, error: ApiError) -> HTTPResponse:
    payload = ErrorResponse(
        code=error.code,
        message=error.message,
        details=error.details,
    )
    return json(payload.model_dump(mode="json"), status=error.status)
