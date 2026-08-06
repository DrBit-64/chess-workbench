from typing import cast

from sanic import Blueprint, Request
from sanic.response import HTTPResponse, json
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema
from chess_workbench.config import Settings
from chess_workbench.schemas.health import HealthResponse, UnhealthyResponse
from chess_workbench.store.database import Database

health_blueprint = Blueprint("health", url_prefix="/api")
HEALTH_SCHEMA = openapi_schema(HealthResponse)
UNHEALTHY_SCHEMA = openapi_schema(UnhealthyResponse)


@health_blueprint.get("/health", name="health")
@openapi.operation("getHealth")
@openapi.summary("Check API and database health")
@openapi.tag("system")
@openapi.response(200, {"application/json": HEALTH_SCHEMA}, "API and database are healthy")
@openapi.response(503, {"application/json": UNHEALTHY_SCHEMA}, "Database is unavailable")
async def get_health(request: Request) -> HTTPResponse:
    """Return service health after a real database round trip."""

    database = cast(Database, request.app.ctx.database)
    settings = cast(Settings, request.app.ctx.settings)

    try:
        await database.ping()
    except Exception:
        unhealthy_payload = UnhealthyResponse(
            service=settings.service_name,
            version=settings.version,
        )
        return json(unhealthy_payload.model_dump(mode="json"), status=503)

    healthy_payload = HealthResponse(
        service=settings.service_name,
        version=settings.version,
    )
    return json(healthy_payload.model_dump(mode="json"))
