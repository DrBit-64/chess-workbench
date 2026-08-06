from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import chess
from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.api.errors import ApiError
from chess_workbench.config import Settings
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import MoveEdge, Position
from sqlalchemy import func, select


def build_test_app(tmp_path: Path) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-graph-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'graph-api.db'}",
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


class NeverDatabase:
    """Test boundary proving validation and contract requests need no database."""

    def session(self) -> None:
        raise AssertionError("the request unexpectedly opened a database session")

    async def close(self) -> None:
        pass


async def test_position_and_move_endpoints_are_idempotent_and_authoritative(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    _, created_position = await client.post("/api/positions", json={"fen": chess.STARTING_FEN})
    _, existing_position = await client.post("/api/positions", json={"fen": chess.STARTING_FEN})

    assert created_position.status == 201
    assert existing_position.status == 200
    assert created_position.json["id"] == existing_position.json["id"]

    move_body = {
        "from_position_id": created_position.json["id"],
        "uci": "e2e4",
    }
    _, created_move = await client.post("/api/moves", json=move_body)
    _, existing_move = await client.post("/api/moves", json=move_body)

    assert created_move.status == 201
    assert existing_move.status == 200
    assert created_move.json == existing_move.json
    assert created_move.json["san"] == "e4"

    async with app.ctx.database.session() as session:
        position_count = await session.scalar(select(func.count()).select_from(Position))
        move_count = await session.scalar(select(func.count()).select_from(MoveEdge))
    assert position_count == 2
    assert move_count == 1


async def test_illegal_move_returns_stable_422_without_writes(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, position = await client.post("/api/positions", json={"fen": chess.STARTING_FEN})

    async with app.ctx.database.session() as session:
        before_positions = await session.scalar(select(func.count()).select_from(Position))
        before_moves = await session.scalar(select(func.count()).select_from(MoveEdge))

    _, response = await client.post(
        "/api/moves",
        json={"from_position_id": position.json["id"], "uci": "e2e5"},
    )

    assert response.status == 422
    assert response.json == {
        "code": "illegal_move",
        "message": "Move is not legal in the supplied position.",
        "details": None,
    }
    async with app.ctx.database.session() as session:
        after_positions = await session.scalar(select(func.count()).select_from(Position))
        after_moves = await session.scalar(select(func.count()).select_from(MoveEdge))
    assert (after_positions, after_moves) == (before_positions, before_moves)


async def test_graph_contract_is_in_openapi_without_private_json_schema_refs(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    client = cast(Any, app.asgi_client)

    _, response = await client.get("/docs/openapi.json")

    assert response.status == 200
    assert response.json["openapi"] == "3.0.3"
    positions = response.json["paths"]["/api/positions"]
    moves = response.json["paths"]["/api/moves"]
    assert positions["post"]["operationId"] == "createPosition"
    assert moves["post"]["operationId"] == "createMove"
    assert positions["post"]["requestBody"]["required"] is True
    assert moves["post"]["requestBody"]["required"] is True

    move_errors = moves["post"]["responses"]["422"]["content"]["application/json"]["schema"]
    assert move_errors["properties"]["details"]["nullable"] is True
    assert move_errors["properties"]["details"]["type"] == "object"

    position_path_parameter = response.json["paths"]["/api/positions/{position_id}"]["get"][
        "parameters"
    ][0]
    assert position_path_parameter == {
        "in": "path",
        "name": "position_id",
        "required": True,
        "schema": {"format": "uuid", "type": "string"},
    }

    document = json.dumps(response.json)
    assert '"const"' not in document
    assert '"$defs"' not in document
    assert '"type": "null"' not in document


async def test_invalid_body_is_stable_and_never_opens_a_database_session(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    app.ctx.database = cast(Database, NeverDatabase())
    client = cast(Any, app.asgi_client)

    _, missing_field = await client.post("/api/positions", json={})
    _, malformed_json = await client.post(
        "/api/positions",
        content="{",
        headers={"content-type": "application/json"},
    )
    _, invalid_fen = await client.post("/api/positions", json={"fen": "not-a-fen"})

    assert missing_field.status == 422
    assert missing_field.json == {
        "code": "validation_error",
        "message": "request body failed validation",
        "details": {"errors": [{"type": "missing", "loc": ["fen"], "msg": "Field required"}]},
    }
    assert malformed_json.status == 422
    assert malformed_json.json == {
        "code": "validation_error",
        "message": "request body must contain valid JSON",
        "details": None,
    }
    assert invalid_fen.status == 422
    assert invalid_fen.json["code"] == "invalid_fen"


def test_api_error_retains_its_safe_message_for_logging() -> None:
    error = ApiError(404, "not_found", "position was not found")

    assert str(error) == "position was not found"
    assert error.args == ("position was not found",)
