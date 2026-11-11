"""Personal games, import preview, original PGN and per-move notes."""

import asyncio
from itertools import batched
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sanic import Blueprint, Request
from sanic.response import HTTPResponse, empty, json, raw
from sanic_ext import openapi
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import defer

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.schemas.personal_games import (
    NotebookGame,
    NotebookGameCatalog,
    NotebookGameDetail,
    NotebookGameUpdate,
    NotebookImportPreview,
    NotebookImportRequest,
    NotebookImportResult,
    NotebookNode,
    NotebookNodeUpdate,
    NotebookPreviewRequest,
)
from chess_workbench.services.personal_games import (
    delete_game,
    fetch_notebook_pgn,
    game_detail,
    game_source,
    get_game,
    parse_notebook_pgn,
    preview_games,
    save_games,
    update_game,
    update_node,
)
from chess_workbench.store.database import Database
from chess_workbench.store.models.personal_games import PersonalGame

personal_games_blueprint = Blueprint("personal_games", url_prefix="/api/notebook")


def _media(model: type[BaseModel]) -> dict[str, Any]:
    return {"application/json": openapi_schema(model)}


def _database(request: Request) -> Database:
    return cast(Database, request.app.ctx.database)


@personal_games_blueprint.post("/imports/preview")
@openapi.operation("previewNotebookGames")
@openapi.body(_media(NotebookPreviewRequest), required=True)
@openapi.response(200, _media(NotebookImportPreview))
async def preview_notebook_games(request: Request) -> HTTPResponse:
    body = parse_body(request, NotebookPreviewRequest)
    pgn = body.pgn
    source_url = None
    if pgn is None:
        assert body.url is not None
        pgn = await fetch_notebook_pgn(body.url, body.username, body.month)
        source_url = game_source(body.url.strip()).url
    document = await asyncio.to_thread(parse_notebook_pgn, pgn)
    async with _database(request).session() as session:
        candidates = await preview_games(session, document, source_url)
        duplicate_ids = {game_id for row in candidates for game_id in row.possible_duplicates}
        duplicate_ids.update(row.existing_id for row in candidates if row.existing_id is not None)
        duplicates: list[NotebookGame] = []
        for ids in batched(duplicate_ids, 400, strict=False):
            rows = await session.scalars(
                select(PersonalGame)
                .options(defer(PersonalGame.original_pgn), defer(PersonalGame.headers))
                .where(PersonalGame.id.in_(ids))
            )
            duplicates.extend(
                NotebookGame.model_validate(row, from_attributes=True) for row in rows
            )
    return json(
        NotebookImportPreview(
            pgn=pgn, games=candidates, source_url=source_url, duplicate_games=duplicates
        ).model_dump(mode="json")
    )


@personal_games_blueprint.post("/imports")
@openapi.operation("importNotebookGames")
@openapi.body(_media(NotebookImportRequest), required=True)
@openapi.response(200, _media(NotebookImportResult))
async def import_notebook_games(request: Request) -> HTTPResponse:
    body = parse_body(request, NotebookImportRequest)
    document = await asyncio.to_thread(parse_notebook_pgn, body.pgn)
    games = await _database(request).run_write(lambda session: save_games(session, document, body))
    return json(NotebookImportResult(games=games).model_dump(mode="json"))


@personal_games_blueprint.get("/games")
@openapi.operation("listNotebookGames")
@openapi.parameter("archived", bool, "query", required=False)
@openapi.response(
    200, {"application/json": {"type": "array", "items": openapi_schema(NotebookGame)}}
)
async def list_notebook_games(request: Request) -> HTTPResponse:
    archived = _archived(request)
    async with _database(request).session() as session:
        games = await session.scalars(
            select(PersonalGame)
            .options(defer(PersonalGame.original_pgn), defer(PersonalGame.headers))
            .where(
                PersonalGame.archived_at.is_not(None)
                if archived
                else PersonalGame.archived_at.is_(None)
            )
            .order_by(PersonalGame.created_at.desc(), PersonalGame.id)
        )
        return json(
            [
                NotebookGame.model_validate(row, from_attributes=True).model_dump(mode="json")
                for row in games
            ]
        )


def _archived(request: Request) -> bool:
    archived: str = request.args.get("archived", "false")
    if archived not in ("false", "true"):
        raise ApiError(422, "validation_error", "archived 必须为 true 或 false。")
    return archived == "true"


def _page_number(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    value = request.args.get(name, str(default))
    if (
        not value.isascii()
        or not value.isdigit()
        or len(value) > 10
        or not minimum <= int(value) <= maximum
    ):
        raise ApiError(422, "validation_error", f"{name} 的范围为 {minimum} 至 {maximum}。")
    return int(value)


@personal_games_blueprint.get("/game-catalog")
@openapi.operation("searchNotebookGames")
@openapi.parameter("archived", bool, "query", required=False)
@openapi.parameter("q", str, "query", required=False)
@openapi.parameter("limit", int, "query", required=False)
@openapi.parameter("offset", int, "query", required=False)
@openapi.response(200, _media(NotebookGameCatalog))
async def search_notebook_games(request: Request) -> HTTPResponse:
    archived = _archived(request)
    term = request.args.get("q", "").strip()
    if len(term) > 500:
        raise ApiError(422, "validation_error", "搜索词过长。")
    limit = _page_number(request, "limit", 30, 1, 100)
    offset = _page_number(request, "offset", 0, 0, 2_147_483_647)
    conditions: list[ColumnElement[bool]] = [
        PersonalGame.archived_at.is_not(None) if archived else PersonalGame.archived_at.is_(None)
    ]
    if term:
        fields = (
            PersonalGame.white,
            PersonalGame.black,
            PersonalGame.date,
            PersonalGame.result,
            PersonalGame.platform,
            PersonalGame.summary,
        )
        conditions.append(or_(*(field.icontains(term, autoescape=True) for field in fields)))
    async with _database(request).session() as session:
        total = await session.scalar(
            select(func.count()).select_from(PersonalGame).where(*conditions)
        )
        games = await session.scalars(
            select(PersonalGame)
            .options(defer(PersonalGame.original_pgn), defer(PersonalGame.headers))
            .where(*conditions)
            .order_by(PersonalGame.created_at.desc(), PersonalGame.id)
            .limit(limit)
            .offset(offset)
        )
        page = NotebookGameCatalog(
            total=total or 0,
            items=[NotebookGame.model_validate(g, from_attributes=True) for g in games],
        )
        return json(page.model_dump(mode="json"))


@personal_games_blueprint.get("/games/<game_id:uuid>")
@openapi.operation("getNotebookGame")
@openapi.response(200, _media(NotebookGameDetail))
async def get_notebook_game(request: Request, game_id: UUID) -> HTTPResponse:
    async with _database(request).session() as session:
        detail = await game_detail(session, game_id)
    return json(detail.model_dump(mode="json"))


@personal_games_blueprint.patch("/games/<game_id:uuid>")
@openapi.operation("updateNotebookGame")
@openapi.body(_media(NotebookGameUpdate), required=True)
@openapi.response(200, _media(NotebookGame))
async def update_notebook_game(request: Request, game_id: UUID) -> HTTPResponse:
    body = parse_body(request, NotebookGameUpdate)
    result = await _database(request).run_write(lambda session: update_game(session, game_id, body))
    return json(result.model_dump(mode="json"))


@personal_games_blueprint.patch("/games/<game_id:uuid>/nodes/<node_id:uuid>")
@openapi.operation("updateNotebookNode")
@openapi.body(_media(NotebookNodeUpdate), required=True)
@openapi.response(200, _media(NotebookNode))
async def update_notebook_node(request: Request, game_id: UUID, node_id: UUID) -> HTTPResponse:
    body = parse_body(request, NotebookNodeUpdate)
    result = await _database(request).run_write(
        lambda session: update_node(session, game_id, node_id, body)
    )
    return json(result.model_dump(mode="json"))


@personal_games_blueprint.get("/games/<game_id:uuid>/pgn")
@openapi.operation("getNotebookGamePgn")
@openapi.response(200, {"application/x-chess-pgn": {"type": "string"}})
async def get_notebook_game_pgn(request: Request, game_id: UUID) -> HTTPResponse:
    async with _database(request).session() as session:
        game = await get_game(session, game_id)
        return raw(
            game.original_pgn.encode(),
            content_type="application/x-chess-pgn; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="game-{game_id}.pgn"'},
        )


@personal_games_blueprint.delete("/games/<game_id:uuid>")
@openapi.operation("deleteNotebookGame")
@openapi.parameter("expected_version", int, "query", required=True)
@openapi.response(204, description="Archived game removed")
async def delete_notebook_game(request: Request, game_id: UUID) -> HTTPResponse:
    expected = request.args.get("expected_version", "")
    if (
        not expected.isascii()
        or not expected.isdigit()
        or not 1 <= len(expected) <= 12
        or int(expected) < 1
    ):
        raise ApiError(422, "validation_error", "请提供有效的记录版本。")
    await _database(request).run_write(lambda session: delete_game(session, game_id, int(expected)))
    return empty()
