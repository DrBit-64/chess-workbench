"""Record and organize moves in the user's review copy of a game."""

from typing import cast
from uuid import UUID

from sanic import Blueprint, Request
from sanic.response import HTTPResponse, json
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.schemas.notebook_tree import (
    NotebookBranchEdit,
    NotebookRecordMove,
    NotebookTreeResult,
)
from chess_workbench.services.notebook_tree import edit_branch, record_move
from chess_workbench.store.database import Database

notebook_tree_blueprint = Blueprint("notebook_tree", url_prefix="/api/notebook")


@notebook_tree_blueprint.post("/games/<game_id:uuid>/moves")
@openapi.operation("recordNotebookMove")
@openapi.body({"application/json": openapi_schema(NotebookRecordMove)}, required=True)
@openapi.response(200, {"application/json": openapi_schema(NotebookTreeResult)})
async def record_notebook_move(request: Request, game_id: UUID) -> HTTPResponse:
    body = parse_body(request, NotebookRecordMove)
    database = cast(Database, request.app.ctx.database)
    result = await database.run_write(lambda session: record_move(session, game_id, body))
    return json(result.model_dump(mode="json"))


@notebook_tree_blueprint.post("/games/<game_id:uuid>/nodes/<node_id:uuid>/branch")
@openapi.operation("editNotebookBranch")
@openapi.body({"application/json": openapi_schema(NotebookBranchEdit)}, required=True)
@openapi.response(200, {"application/json": openapi_schema(NotebookTreeResult)})
async def edit_notebook_branch(request: Request, game_id: UUID, node_id: UUID) -> HTTPResponse:
    body = parse_body(request, NotebookBranchEdit)
    database = cast(Database, request.app.ctx.database)
    result = await database.run_write(lambda session: edit_branch(session, game_id, node_id, body))
    return json(result.model_dump(mode="json"))
