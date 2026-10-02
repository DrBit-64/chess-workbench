"""Course-to-Lichess preview and explicit publication endpoints."""

from typing import cast
from uuid import UUID

from sanic import Blueprint, Request
from sanic.response import HTTPResponse, json
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.config import SecretFileError, load_secret_file
from chess_workbench.schemas.domain import ErrorResponse
from chess_workbench.schemas.lichess import (
    LichessStudyCreate,
    LichessStudyPreview,
    LichessStudyResult,
)
from chess_workbench.services.lichess_study import prepare_study, publish_study
from chess_workbench.store.database import Database

lichess_blueprint = Blueprint("lichess", url_prefix="/api")
ERROR_SCHEMA = {"application/json": openapi_schema(ErrorResponse)}


@lichess_blueprint.get("/courses/<course_id:uuid>/lichess-study-preview")
@openapi.operation("previewLichessStudy")
@openapi.tag("lichess")
@openapi.summary("Preview a flattened chapter or subsection for a new Lichess study")
@openapi.parameter("module_id", UUID, "query", required=True)
@openapi.response(200, {"application/json": openapi_schema(LichessStudyPreview)}, "Export preview")
@openapi.response(404, ERROR_SCHEMA, "Course or module missing")
@openapi.response(409, ERROR_SCHEMA, "PGN cannot be exported")
@openapi.response(422, ERROR_SCHEMA, "Invalid request")
async def preview_lichess_study(request: Request, course_id: UUID) -> HTTPResponse:
    try:
        module_id = UUID(request.args.get("module_id", ""))
    except ValueError:
        raise ApiError(422, "validation_error", "请选择要发送的章节或小节") from None
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        prepared = await prepare_study(
            session,
            course_id,
            module_id,
            token_configured=request.app.ctx.settings.lichess_api_token_file is not None,
        )
    return json(prepared.preview.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@lichess_blueprint.post("/courses/<course_id:uuid>/lichess-studies")
@openapi.operation("createLichessStudy")
@openapi.tag("lichess")
@openapi.summary("Create a new unlisted Lichess study from saved course content")
@openapi.body({"application/json": openapi_schema(LichessStudyCreate)}, required=True)
@openapi.response(
    200, {"application/json": openapi_schema(LichessStudyResult)}, "Publication outcome"
)
@openapi.response(404, ERROR_SCHEMA, "Course or module missing")
@openapi.response(409, ERROR_SCHEMA, "PGN cannot be exported")
@openapi.response(422, ERROR_SCHEMA, "Request or Lichess capacity limit")
@openapi.response(502, ERROR_SCHEMA, "Lichess request failed or result is uncertain")
@openapi.response(503, ERROR_SCHEMA, "Token not configured or unavailable")
async def create_lichess_study(request: Request, course_id: UUID) -> HTTPResponse:
    body = parse_body(request, LichessStudyCreate)
    try:
        token = load_secret_file(
            request.app.ctx.settings.lichess_api_token_file, label="Lichess token"
        )
    except SecretFileError:
        raise ApiError(
            503, "lichess_unconfigured", "无法读取 Lichess 令牌文件，请检查绝对路径和 600 权限"
        ) from None
    if token is None:
        raise ApiError(
            503, "lichess_unconfigured", "请先配置 Lichess study:write 令牌文件并重启后端"
        )
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        prepared = await prepare_study(session, course_id, body.module_id, token_configured=True)
    # Close the read transaction before waiting for the external service.
    result = await publish_study(
        prepared, name=body.name, orientation=body.orientation, token=token
    )
    return json(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
