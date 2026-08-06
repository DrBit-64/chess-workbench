"""HTTP boundary for immutable global chess facts."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sanic import Blueprint, Request
from sanic.response import HTTPResponse, json
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.api.serializers import move_read, position_read
from chess_workbench.domain import PositionError, PositionState
from chess_workbench.schemas.domain import (
    ErrorResponse,
    MoveCreate,
    MoveRead,
    PositionCreate,
    PositionRead,
)
from chess_workbench.store.database import Database
from chess_workbench.store.graph_repository import (
    find_position,
    get_or_create_move,
    get_or_create_position,
)
from chess_workbench.store.models import MoveEdge

graph_blueprint = Blueprint("position_graph", url_prefix="/api")

ERROR_SCHEMA = {"application/json": openapi_schema(ErrorResponse)}
POSITION_SCHEMA = {"application/json": openapi_schema(PositionRead)}
MOVE_SCHEMA = {"application/json": openapi_schema(MoveRead)}


@graph_blueprint.post("/positions", name="create_position")
@openapi.operation("createPosition")
@openapi.summary("Validate and resolve a global standard-chess position")
@openapi.tag("position-graph")
@openapi.body({"application/json": openapi_schema(PositionCreate)}, required=True)
@openapi.response(200, POSITION_SCHEMA, "Existing canonical position")
@openapi.response(201, POSITION_SCHEMA, "Canonical position created")
@openapi.response(422, ERROR_SCHEMA, "FEN is invalid or structurally illegal")
async def create_position(request: Request) -> HTTPResponse:
    body = parse_body(request, PositionCreate)
    try:
        state = PositionState(body.fen)
    except PositionError as error:
        raise _position_api_error(error) from error

    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        stored = await get_or_create_position(session, state)

    payload = position_read(stored.position)
    return json(payload.model_dump(mode="json"), status=201 if stored.created else 200)


@graph_blueprint.get("/positions/<position_id:uuid>", name="get_position")
@openapi.operation("getPosition")
@openapi.summary("Read one canonical position")
@openapi.tag("position-graph")
@openapi.response(200, POSITION_SCHEMA, "Canonical position")
@openapi.response(404, ERROR_SCHEMA, "Position not found")
async def get_position(request: Request, position_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        position = await find_position(session, position_id)
        if position is None:
            raise ApiError(404, "not_found", "position was not found")
        payload = position_read(position)
    return json(payload.model_dump(mode="json"))


@graph_blueprint.post("/moves", name="create_move")
@openapi.operation("createMove")
@openapi.summary("Validate and resolve a global legal-move edge")
@openapi.tag("position-graph")
@openapi.body({"application/json": openapi_schema(MoveCreate)}, required=True)
@openapi.response(200, MOVE_SCHEMA, "Existing move edge")
@openapi.response(201, MOVE_SCHEMA, "Move edge created")
@openapi.response(404, ERROR_SCHEMA, "Source position not found")
@openapi.response(422, ERROR_SCHEMA, "Move is invalid or illegal")
async def create_move(request: Request) -> HTTPResponse:
    body = parse_body(request, MoveCreate)
    database = cast(Database, request.app.ctx.database)
    try:
        async with database.session() as session, session.begin():
            source = await find_position(session, body.from_position_id)
            if source is None:
                raise ApiError(404, "not_found", "source position was not found")
            stored = await get_or_create_move(
                session,
                PositionState(source.canonical_fen),
                body.uci,
            )
    except PositionError as error:
        raise _position_api_error(error) from error

    payload = move_read(stored.edge)
    return json(payload.model_dump(mode="json"), status=201 if stored.edge_created else 200)


@graph_blueprint.get("/moves/<move_id:uuid>", name="get_move")
@openapi.operation("getMove")
@openapi.summary("Read one global move edge")
@openapi.tag("position-graph")
@openapi.response(200, MOVE_SCHEMA, "Move edge")
@openapi.response(404, ERROR_SCHEMA, "Move edge not found")
async def get_move(request: Request, move_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        edge = await session.get(MoveEdge, move_id)
        if edge is None:
            raise ApiError(404, "not_found", "move edge was not found")
        payload = move_read(edge)
    return json(payload.model_dump(mode="json"))


def _position_api_error(error: PositionError) -> ApiError:
    return ApiError(
        status=422,
        code=error.code.value,
        message=error.message,
    )
