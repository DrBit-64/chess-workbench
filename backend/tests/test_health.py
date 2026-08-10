import json
from pathlib import Path
from typing import Any, cast

from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings


def build_test_app(tmp_path: Path) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-test-{tmp_path.name}",
            version="0.1.0",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'health.db'}",
            engine_worker_enabled=False,
        )
    )


async def test_health_reports_real_database_status(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = cast(Any, app.asgi_client)

    _, response = await client.get("/api/health")

    assert response.status == 200
    assert response.json == {
        "status": "ok",
        "service": f"chess-workbench-test-{tmp_path.name}",
        "version": "0.1.0",
        "database": "ok",
    }
    assert (tmp_path / "health.db").is_file()


async def test_health_returns_503_without_leaking_database_error(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    database = app.ctx.database

    async def fail_ping() -> None:
        raise RuntimeError("secret database detail")

    database.ping = fail_ping  # type: ignore[method-assign]
    client = cast(Any, app.asgi_client)

    _, response = await client.get("/api/health")

    assert response.status == 503
    assert response.json == {
        "status": "error",
        "service": f"chess-workbench-test-{tmp_path.name}",
        "version": "0.1.0",
        "database": "error",
    }
    assert "secret" not in response.text


async def test_openapi_exposes_health_contract(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = cast(Any, app.asgi_client)

    _, response = await client.get("/docs/openapi.json")

    assert response.status == 200
    assert response.json["info"]["title"] == "ChessWorkbench API"
    operation = response.json["paths"]["/api/health"]["get"]
    assert operation["operationId"] == "getHealth"
    assert set(operation["responses"]) >= {"200", "503"}
    assert '"const"' not in json.dumps(response.json)
