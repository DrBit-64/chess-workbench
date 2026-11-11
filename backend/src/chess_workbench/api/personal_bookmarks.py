"""Local notebook API for bookmarking, searching, and returning to recorded positions."""

from uuid import UUID

from pydantic import BaseModel, ValidationError
from sanic import Blueprint, Request
from sanic.response import HTTPResponse, empty, json
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.schemas.personal_bookmarks import (
    NotebookBookmark,
    NotebookBookmarkCreate,
    NotebookBookmarkList,
    NotebookBookmarkQuery,
    NotebookBookmarkTags,
    NotebookBookmarkUpdate,
    NotebookDeleteQuery,
    NotebookOccurrenceList,
    NotebookOccurrenceQuery,
)
from chess_workbench.services.personal_bookmarks import (
    bookmark_tags,
    delete_bookmark,
    get_bookmark,
    list_bookmarks,
    other_occurrences,
    star_bookmark,
    update_bookmark,
)
from chess_workbench.store.database import Database

personal_bookmarks_bp = Blueprint("personal_bookmarks", url_prefix="/api/notebook")
BOOKMARK = {"application/json": openapi_schema(NotebookBookmark)}


def _query[Model: BaseModel](request: Request, model: type[Model]) -> Model:
    values = {k: request.args.get(k) for k in request.args}
    if "tag" in values:
        values["tag"] = request.args.getlist("tag")
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ApiError(422, "validation_error", f"{first['loc'][0]}: {first['msg']}") from exc


@personal_bookmarks_bp.get("/bookmarks")
@openapi.operation("listNotebookBookmarks")
@openapi.tag("notebook")
@openapi.parameter("q", str, "query", required=False)
@openapi.parameter("tag", list[str], "query", required=False)
@openapi.parameter("game_id", UUID, "query", required=False)
@openapi.parameter("offset", int, "query", required=False)
@openapi.parameter("limit", int, "query", required=False)
@openapi.response(200, {"application/json": openapi_schema(NotebookBookmarkList)})
async def search(request: Request) -> HTTPResponse:
    criteria = _query(request, NotebookBookmarkQuery)
    limit = criteria.limit if criteria.game_id is not None else (criteria.limit or 50)
    database: Database = request.app.ctx.database
    async with database.session() as session:
        result = await list_bookmarks(
            session,
            query=criteria.q.strip(),
            tags=criteria.tag,
            game_id=criteria.game_id,
            offset=criteria.offset,
            limit=limit,
        )
    return json(result.model_dump(mode="json"))


@personal_bookmarks_bp.post("/bookmarks")
@openapi.operation("starNotebookPosition")
@openapi.tag("notebook")
@openapi.body({"application/json": openapi_schema(NotebookBookmarkCreate)}, required=True)
@openapi.response(200, BOOKMARK)
async def star(request: Request) -> HTTPResponse:
    body = parse_body(request, NotebookBookmarkCreate)
    database: Database = request.app.ctx.database
    result = await database.run_write(lambda session: star_bookmark(session, body))
    return json(result.model_dump(mode="json"))


@personal_bookmarks_bp.get("/bookmarks/<bookmark_id:uuid>")
@openapi.operation("getNotebookBookmark")
@openapi.tag("notebook")
@openapi.response(200, BOOKMARK)
async def read(request: Request, bookmark_id: UUID) -> HTTPResponse:
    database: Database = request.app.ctx.database
    async with database.session() as session:
        result = await get_bookmark(session, bookmark_id)
    return json(result.model_dump(mode="json"))


@personal_bookmarks_bp.patch("/bookmarks/<bookmark_id:uuid>")
@openapi.operation("updateNotebookBookmark")
@openapi.tag("notebook")
@openapi.body({"application/json": openapi_schema(NotebookBookmarkUpdate)}, required=True)
@openapi.response(200, BOOKMARK)
async def edit(request: Request, bookmark_id: UUID) -> HTTPResponse:
    body = parse_body(request, NotebookBookmarkUpdate)
    database: Database = request.app.ctx.database
    result = await database.run_write(lambda session: update_bookmark(session, bookmark_id, body))
    return json(result.model_dump(mode="json"))


@personal_bookmarks_bp.delete("/bookmarks/<bookmark_id:uuid>")
@openapi.operation("deleteNotebookBookmark")
@openapi.tag("notebook")
@openapi.parameter("expected_version", int, "query", required=True)
@openapi.response(204, description="Permanently removed")
async def remove(request: Request, bookmark_id: UUID) -> HTTPResponse:
    params = _query(request, NotebookDeleteQuery)
    database: Database = request.app.ctx.database
    await database.run_write(
        lambda session: delete_bookmark(session, bookmark_id, params.expected_version)
    )
    return empty()


@personal_bookmarks_bp.get("/bookmark-tags")
@openapi.operation("listNotebookBookmarkTags")
@openapi.tag("notebook")
@openapi.response(200, {"application/json": openapi_schema(NotebookBookmarkTags)})
async def tags(request: Request) -> HTTPResponse:
    database: Database = request.app.ctx.database
    async with database.session() as session:
        result = await bookmark_tags(session)
    return json(result.model_dump(mode="json"))


@personal_bookmarks_bp.get("/bookmarks/<bookmark_id:uuid>/occurrences")
@openapi.operation("findOtherNotebookOccurrences")
@openapi.tag("notebook")
@openapi.parameter("include_variations", bool, "query", required=False)
@openapi.parameter("offset", int, "query", required=False)
@openapi.parameter("limit", int, "query", required=False)
@openapi.response(200, {"application/json": openapi_schema(NotebookOccurrenceList)})
async def occurrences(request: Request, bookmark_id: UUID) -> HTTPResponse:
    params = _query(request, NotebookOccurrenceQuery)
    database: Database = request.app.ctx.database
    async with database.session() as session:
        result = await other_occurrences(
            session,
            bookmark_id,
            include_variations=params.include_variations,
            offset=params.offset,
            limit=params.limit,
        )
    return json(result.model_dump(mode="json"))
