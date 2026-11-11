"""Manage public game accounts and run an interruptible incremental import."""

from typing import cast
from uuid import UUID

from sanic import Blueprint, Request
from sanic.response import HTTPResponse, empty, json
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.schemas.notebook_accounts import (
    NotebookAccountCreate,
    NotebookAccountView,
    NotebookSyncResult,
)
from chess_workbench.services import notebook_accounts as accounts
from chess_workbench.store.database import Database

notebook_accounts_blueprint = Blueprint("notebook_accounts", url_prefix="/api/notebook/accounts")
ACCOUNT = {"application/json": openapi_schema(NotebookAccountView)}


@notebook_accounts_blueprint.get("")
@openapi.operation("listNotebookAccounts")
@openapi.tag("notebook")
@openapi.response(
    200, {"application/json": {"type": "array", "items": openapi_schema(NotebookAccountView)}}
)
async def list_accounts(request: Request) -> HTTPResponse:
    db = cast(Database, request.app.ctx.database)
    async with db.session() as session:
        return json(
            [item.model_dump(mode="json") for item in await accounts.list_accounts(session)]
        )


@notebook_accounts_blueprint.post("")
@openapi.operation("addNotebookAccount")
@openapi.tag("notebook")
@openapi.body({"application/json": openapi_schema(NotebookAccountCreate)}, required=True)
@openapi.response(201, ACCOUNT)
async def add_account(request: Request) -> HTTPResponse:
    body = parse_body(request, NotebookAccountCreate)
    db = cast(Database, request.app.ctx.database)
    item = await db.run_write(lambda session: accounts.create_account(session, body))
    return json(item.model_dump(mode="json"), status=201)


@notebook_accounts_blueprint.delete("/<account_id:uuid>")
@openapi.operation("removeNotebookAccount")
@openapi.tag("notebook")
@openapi.response(204, description="Account removed; previously saved games remain")
async def remove_account(request: Request, account_id: UUID) -> HTTPResponse:
    db = cast(Database, request.app.ctx.database)
    await db.run_write(lambda session: accounts.remove_account(session, account_id))
    return empty(status=204)


@notebook_accounts_blueprint.post("/<account_id:uuid>/sync")
@openapi.operation("syncNotebookAccount")
@openapi.tag("notebook")
@openapi.response(200, {"application/json": openapi_schema(NotebookSyncResult)})
async def sync_account(request: Request, account_id: UUID) -> HTTPResponse:
    db = cast(Database, request.app.ctx.database)
    lock = request.app.ctx.notebook_sync_lock
    if lock.locked():
        raise ApiError(409, "idempotency_conflict", "另一项同步正在进行。稍后可继续。")
    async with lock:
        result = await accounts.sync_step(db, account_id)
    return json(result.model_dump(mode="json"))


@notebook_accounts_blueprint.post("/<account_id:uuid>/retry")
@openapi.operation("retryNotebookAccountGames")
@openapi.tag("notebook")
@openapi.response(200, ACCOUNT)
async def retry_account(request: Request, account_id: UUID) -> HTTPResponse:
    db = cast(Database, request.app.ctx.database)
    result = await db.run_write(lambda session: accounts.retry_failures(session, account_id))
    return json(result.model_dump(mode="json"))
