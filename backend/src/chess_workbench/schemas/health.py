from typing import Literal

from pydantic import BaseModel, ConfigDict


class BaseHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str
    version: str


class HealthResponse(BaseHealthResponse):
    """Successful health contract shared with the frontend through OpenAPI."""

    status: Literal["ok"] = "ok"
    database: Literal["ok"] = "ok"


class UnhealthyResponse(BaseHealthResponse):
    """Health contract returned when the database round trip fails."""

    status: Literal["error"] = "error"
    database: Literal["error"] = "error"
