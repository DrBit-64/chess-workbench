from pathlib import Path
from typing import Any, cast
from uuid import UUID

from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.api.engine import _engine_api_error
from chess_workbench.config import Settings
from chess_workbench.services.uci import EngineError
from chess_workbench.store.base import Base

FIXTURE_ENGINE = Path(__file__).parent / "fixtures" / "fake_uci_engine.py"


async def _app(tmp_path: Path) -> ChessWorkbenchApp:
    app = create_app(
        Settings(
            service_name=f"stage6-api-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
            stockfish_path=FIXTURE_ENGINE,
            syzygy_path=tmp_path / "missing",
            engine_worker_enabled=False,
        )
    )
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return app


async def test_analysis_http_contract_returns_four_lines_and_cache_hit(tmp_path: Path) -> None:
    app = await _app(tmp_path)
    client = cast(Any, app.asgi_client)
    _, capabilities = await client.get("/api/engine/capabilities")
    assert capabilities.status == 200
    assert capabilities.json["available"] is True
    assert capabilities.json["default_parameters"]["multipv"] == 4

    body = {
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "parameters": capabilities.json["default_parameters"],
    }
    _, first = await client.post("/api/engine/analyses", json=body)
    _, second = await client.post("/api/engine/analyses", json=body)
    assert first.status == second.status == 200
    assert len(first.json["lines"]) == 4
    assert first.json["from_cache"] is False
    assert second.json["from_cache"] is True
    assert first.json["id"] == second.json["id"]


async def test_application_lifecycle_starts_and_reaps_enabled_worker(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            service_name=f"stage6-worker-lifecycle-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker-lifecycle.db'}",
            stockfish_path=FIXTURE_ENGINE,
            syzygy_path=tmp_path / "missing",
            engine_worker_enabled=True,
            engine_worker_poll_ms=50,
        )
    )
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    client = cast(Any, app.asgi_client)

    _, response = await client.get("/api/health")

    assert response.status == 200
    assert app.ctx.worker_task is not None
    assert app.ctx.worker_task.done()


async def test_job_cancel_and_http_invalidation_polling_are_durable(tmp_path: Path) -> None:
    app = await _app(tmp_path)
    client = cast(Any, app.asgi_client)
    request = {
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "idempotency_key": "api-job",
    }
    _, queued = await client.post("/api/engine/analysis-jobs", json=request)
    assert queued.status == 202
    _, cancelled = await client.post(f"/api/jobs/{queued.json['id']}/cancel")
    assert cancelled.status == 200
    assert cancelled.json["status"] == "cancelled"

    # This is the correctness path even if a WebSocket connected before the
    # request has disconnected and missed both notifications.
    _, events = await client.get("/api/invalidations?after=0")
    assert events.status == 200
    assert [(event["resource_type"], event["reason"]) for event in events.json] == [
        ("job", "queued"),
        ("job", "cancelled"),
    ]


async def test_engine_contracts_forbid_unknown_fields(tmp_path: Path) -> None:
    app = await _app(tmp_path)
    client = cast(Any, app.asgi_client)
    _, response = await client.post(
        "/api/engine/analyses",
        json={"fen": "8/8/8/8/8/8/4K3/6k1 w - - 0 1", "surprise": True},
    )
    assert response.status == 422
    assert response.json["code"] == "validation_error"


def test_engine_error_mapping_distinguishes_unavailable_from_engine_failure() -> None:
    unavailable = _engine_api_error(EngineError("engine_unavailable", "missing"))
    assert unavailable.status == 503
    assert unavailable.code == "engine_unavailable"
    assert unavailable.details == {"engine_code": "engine_unavailable"}

    failure = _engine_api_error(EngineError("resource_limit", "too large"))
    assert failure.status == 422
    assert failure.code == "engine_failure"
    assert failure.details == {"engine_code": "resource_limit"}


async def test_job_lookup_cancellation_validation_and_idempotency_errors_are_explicit(
    tmp_path: Path,
) -> None:
    app = await _app(tmp_path)
    client = cast(Any, app.asgi_client)
    missing_id = UUID("00000000-0000-0000-0000-000000000001")
    try:
        _, missing = await client.get(f"/api/jobs/{missing_id}")
        assert missing.status == 404
        assert missing.json["code"] == "not_found"

        _, missing_cancel = await client.post(f"/api/jobs/{missing_id}/cancel")
        assert missing_cancel.status == 404
        assert missing_cancel.json["code"] == "not_found"

        _, invalid_cursor = await client.get("/api/invalidations?after=not-an-integer")
        assert invalid_cursor.status == 422
        assert invalid_cursor.json["code"] == "validation_error"

        request = {
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "idempotency_key": "conflicting-api-job",
        }
        _, queued = await client.post("/api/engine/analysis-jobs", json=request)
        assert queued.status == 202
        _, replay = await client.get(f"/api/jobs/{queued.json['id']}")
        assert replay.status == 200
        assert replay.json["id"] == queued.json["id"]

        conflicting = {
            **request,
            "fen": "8/8/8/8/8/8/4K3/6k1 w - - 0 1",
        }
        _, conflict = await client.post("/api/engine/analysis-jobs", json=conflicting)
        assert conflict.status == 409
        assert conflict.json["code"] == "idempotency_conflict"
    finally:
        await client.aclose()
        await app.ctx.database.close()


async def test_engine_unavailable_resource_limits_and_game_errors_are_explicit(
    tmp_path: Path,
) -> None:
    unavailable_app = create_app(
        Settings(
            service_name=f"stage6-unavailable-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'unavailable.db'}",
            stockfish_path=tmp_path / "missing-stockfish",
            syzygy_path=tmp_path / "missing-syzygy",
            engine_worker_enabled=False,
        )
    )
    async with unavailable_app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    unavailable_client = cast(Any, unavailable_app.asgi_client)
    try:
        _, capabilities = await unavailable_client.get("/api/engine/capabilities")
        assert capabilities.status == 200
        assert capabilities.json["available"] is False
        assert capabilities.json["install_hint"]

        _, unavailable_job = await unavailable_client.post(
            "/api/engine/analysis-jobs",
            json={"idempotency_key": "missing-engine"},
        )
        assert unavailable_job.status == 503
        assert unavailable_job.json["code"] == "engine_unavailable"

        _, unavailable_analysis = await unavailable_client.post(
            "/api/engine/analyses",
            json={},
        )
        assert unavailable_analysis.status == 503
        assert unavailable_analysis.json["code"] == "engine_unavailable"
    finally:
        await unavailable_client.aclose()
        await unavailable_app.ctx.database.close()

    app = await _app(tmp_path / "game-errors")
    client = cast(Any, app.asgi_client)
    missing_id = UUID("00000000-0000-0000-0000-000000000002")
    try:
        _, limited = await client.post(
            "/api/engine/analyses",
            json={"parameters": {"threads": 5}},
        )
        assert limited.status == 422
        assert limited.json["code"] == "engine_failure"
        assert limited.json["details"] == {"engine_code": "resource_limit"}

        _, missing_analysis = await client.get(f"/api/engine/analyses/{missing_id}")
        assert missing_analysis.status == 404
        assert missing_analysis.json["code"] == "not_found"

        _, missing_game = await client.get(f"/api/engine/games/{missing_id}")
        assert missing_game.status == 404
        assert missing_game.json["code"] == "not_found"
        _, missing_game_move = await client.post(
            f"/api/engine/games/{missing_id}/moves",
            json={"uci": "e2e4", "expected_version": 1},
        )
        assert missing_game_move.status == 404
        assert missing_game_move.json["code"] == "not_found"

        _, created = await client.post("/api/engine/games", json={})
        assert created.status == 201
        game_id = created.json["id"]

        _, engine_first = await client.post(
            "/api/engine/games",
            json={"user_color": "black"},
        )
        assert engine_first.status == 201
        assert engine_first.json["moves"][0]["actor"] == "engine"

        _, stale = await client.post(
            f"/api/engine/games/{game_id}/moves",
            json={"uci": "e2e4", "expected_version": 999},
        )
        assert stale.status == 409
        assert stale.json["code"] == "stale_version"

        _, illegal = await client.post(
            f"/api/engine/games/{game_id}/moves",
            json={"uci": "e2e5", "expected_version": created.json["version"]},
        )
        assert illegal.status == 422
        assert illegal.json["code"] == "illegal_move"

        _, terminal = await client.post(
            "/api/engine/games",
            json={
                "fen": "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
                "user_color": "black",
            },
        )
        assert terminal.status == 201
        assert terminal.json["status"] == "finished"
        _, inactive = await client.post(
            f"/api/engine/games/{terminal.json['id']}/moves",
            json={"uci": "h8h7", "expected_version": terminal.json["version"]},
        )
        assert inactive.status == 422
        assert inactive.json["code"] == "illegal_move"

        _, mate_in_one = await client.post(
            "/api/engine/games",
            json={
                "fen": "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1",
                "user_color": "white",
            },
        )
        assert mate_in_one.status == 201
        _, checkmate = await client.post(
            f"/api/engine/games/{mate_in_one.json['id']}/moves",
            json={"uci": "f7g7", "expected_version": mate_in_one.json["version"]},
        )
        assert checkmate.status == 200
        assert checkmate.json["status"] == "finished"
        assert checkmate.json["result"] == "1-0"
        assert [move["uci"] for move in checkmate.json["moves"]] == ["f7g7"]

        _, missing_review = await client.post(f"/api/engine/games/{missing_id}/review")
        assert missing_review.status == 404
        assert missing_review.json["code"] == "not_found"

        _, missing_draft = await client.post(
            f"/api/engine/games/{missing_id}/review/course-draft",
            json={"title": "Missing game", "finding_plies": [1]},
        )
        assert missing_draft.status == 404
        assert missing_draft.json["code"] == "not_found"
    finally:
        await client.aclose()
        await app.ctx.database.close()
