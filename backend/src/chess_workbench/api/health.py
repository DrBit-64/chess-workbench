from typing import Any, cast

from pydantic import BaseModel
from sanic import Blueprint, Request
from sanic.response import HTTPResponse, json
from sanic_ext import openapi

from chess_workbench.config import Settings
from chess_workbench.schemas.health import HealthResponse, UnhealthyResponse
from chess_workbench.store.database import Database

health_blueprint = Blueprint("health", url_prefix="/api")


def _oas30_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Translate Pydantic's single-value const into an OpenAPI 3.0 enum."""

    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    properties = cast(dict[str, dict[str, Any]], schema.get("properties", {}))
    for property_schema in properties.values():
        if "const" in property_schema:
            property_schema["enum"] = [property_schema.pop("const")]
    return schema


HEALTH_SCHEMA = _oas30_schema(HealthResponse)
UNHEALTHY_SCHEMA = _oas30_schema(UnhealthyResponse)


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
