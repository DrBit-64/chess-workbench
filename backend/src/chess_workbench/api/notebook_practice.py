from typing import cast
from uuid import UUID

from sanic import Blueprint, Request
from sanic.response import HTTPResponse, empty, json
from sanic_ext import openapi
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.schemas.notebook_practice import PracticeEdit, PracticeRead, PracticeRemove
from chess_workbench.services.notebook_practice import delete_practice, read_practice, save_practice
from chess_workbench.store.database import Database

notebook_practice_blueprint = Blueprint("notebook_practice", url_prefix="/api/notebook")
route = "/bookmarks/<bookmark_id:uuid>/practice"
response_schema = {"application/json": openapi_schema(PracticeRead)}


@notebook_practice_blueprint.get(route)
@openapi.operation("getBookmarkPractice")
@openapi.tag("notebook")
@openapi.response(200, response_schema)
async def get_practice(request: Request, bookmark_id: UUID) -> HTTPResponse:
    db = cast(Database, request.app.ctx.database)
    async with db.session() as session:
        result = await read_practice(session, bookmark_id)
    return json(result.model_dump())


@notebook_practice_blueprint.put(route)
@openapi.operation("saveBookmarkPractice")
@openapi.tag("notebook")
@openapi.body({"application/json": openapi_schema(PracticeEdit)}, required=True)
@openapi.response(200, response_schema)
async def put_practice(request: Request, bookmark_id: UUID) -> HTTPResponse:
    body = parse_body(request, PracticeEdit)
    db = cast(Database, request.app.ctx.database)
    try:
        result = await db.run_write(lambda session: save_practice(session, bookmark_id, body))
    except (IntegrityError, StaleDataError) as error:
        raise ApiError(409, "stale_version", "收藏或练习已经变更，请重新载入。") from error
    return json(result.model_dump())


@notebook_practice_blueprint.delete(route)
@openapi.operation("deleteBookmarkPractice")
@openapi.tag("notebook")
@openapi.body({"application/json": openapi_schema(PracticeRemove)}, required=True)
@openapi.response(204, description="Exercise removed")
async def remove_practice(request: Request, bookmark_id: UUID) -> HTTPResponse:
    body = parse_body(request, PracticeRemove)
    db = cast(Database, request.app.ctx.database)
    try:
        await db.run_write(
            lambda session: delete_practice(session, bookmark_id, body.expected_version)
        )
    except StaleDataError as error:
        raise ApiError(409, "stale_version", "练习已在另一处修改，请重新载入。") from error
    return empty()
