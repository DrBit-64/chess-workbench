"""Account sync persists source provenance and can retry without restoring deleted games."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from chess_workbench.api.app import create_app
from chess_workbench.config import Settings
from chess_workbench.services import ServiceError
from chess_workbench.services import notebook_accounts as accounts
from chess_workbench.services import notebook_platforms as upstream
from chess_workbench.store.base import Base

BASE = "/api/notebook"
LINK = "https://www.chess.com/game/daily/12345"
PGN = (
    f'[White "Example"]\n[Black "Opponent"]\n[Link "{LINK}"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 1-0'
)


def mock_provider(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    monkeypatch.setattr(
        upstream, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_chesscom_link_uses_verified_archive_and_preserves_original_pgn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def provider(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.host == "www.chess.com":
            return httpx.Response(
                200,
                text=(
                    '<meta property="og:title" content="Example vs. Opponent">'
                    '<meta property="og:description" content="2024-11-28">'
                ),
            )
        assert str(request.url) == "https://api.chess.com/pub/player/example/games/2024/11"
        return httpx.Response(200, json={"games": [{"url": LINK, "pgn": PGN, "rules": "chess"}]})

    mock_provider(monkeypatch, provider)
    assert await upstream.fetch_chesscom_pgn(LINK) == PGN
    assert await upstream.fetch_chesscom_pgn(LINK, "Example", "2024-11") == PGN
    assert calls.count("/game/daily/12345") == 1
    with pytest.raises(ServiceError) as bad:
        await upstream.fetch_chesscom_pgn("https://www.chess.com.evil.invalid/game/live/1")
    assert bad.value.status == 422


async def test_incremental_sync_does_not_resurrect_deleted_game_and_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    month = now.strftime("%Y/%m")
    end_time = int(now.timestamp()) - 1
    archive = f"https://api.chess.com/pub/player/example/games/{month}"

    def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/archives"):
            return httpx.Response(200, json={"archives": [archive]})
        assert str(request.url) == archive
        return httpx.Response(
            200,
            json={
                "games": [
                    {"url": LINK, "rules": "chess", "end_time": end_time, "pgn": PGN},
                    {
                        "url": LINK + "6",
                        "rules": "chess",
                        "end_time": end_time,
                        "pgn": PGN.replace(LINK, LINK + "6"),
                    },
                ]
            },
        )

    mock_provider(monkeypatch, provider)
    monkeypatch.setattr(accounts, "DRAIN_BATCH", 1)
    app = create_app(
        Settings(
            service_name=f"account-{uuid4().hex}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'account.db'}",
            engine_worker_enabled=False,
        )
    )
    async with app.ctx.database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    client = cast(Any, app.asgi_client)
    try:
        account_data = {
            "platform": "chess.com",
            "username": "Example",
            "start_date": f"{now.year}-01-01",
        }
        _, added = await client.post(f"{BASE}/accounts", json=account_data)
        assert added.status == 201, added.text
        url = f"{BASE}/accounts/{added.json['id']}"
        _, duplicate = await client.post(f"{BASE}/accounts", json=account_data)
        assert duplicate.status == 409
        _, sync = await client.post(f"{url}/sync")
        assert sync.status == 200, sync.text
        assert sync.json["more"] and sync.json["account"]["queued"] == 1
        # A later request resumes the saved queue; it doesn't need to re-fetch the games.
        _, sync = await client.post(f"{url}/sync")
        assert sync.status == 200
        assert not sync.json["more"] and sync.json["account"]["imported"] == 2
        _, games = await client.get(f"{BASE}/games")
        assert len(games.json) == 2
        game = games.json[0]
        game_url = f"{BASE}/games/{game['id']}"
        _, archived = await client.patch(
            game_url, json={"expected_version": game["version"], "archived": True}
        )
        assert archived.status == 200
        _, removed = await client.delete(
            game_url, params={"expected_version": archived.json["version"]}
        )
        assert removed.status == 204, removed.text
        _, resync = await client.post(f"{url}/sync")
        assert resync.status == 200, resync.text
        _, games = await client.get(f"{BASE}/games")
        assert len(games.json) == 1 and games.json[0]["id"] != game["id"]
        _, removed = await client.delete(url)
        assert removed.status == 204
        _, remaining = await client.get(f"{BASE}/games")
        assert remaining.json == games.json
    finally:
        await client.aclose()
        await app.ctx.database.close()


async def test_lichess_page_keeps_ongoing_ids_and_rechecks_after_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def provider(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/api/games/export/_ids" and request.content == b"abcd1234"
            rows = [
                {
                    "id": "abcd1234",
                    "createdAt": 20,
                    "status": "resign",
                    "variant": "standard",
                    "pgn": '[Site "https://lichess.org/abcd1234"]\n\n1. e4 1-0',
                }
            ]
        else:
            assert request.url.params["ongoing"] == "true"
            rows = [
                {
                    "id": "abcd1234",
                    "createdAt": 20,
                    "status": "started",
                    "variant": "standard",
                    "pgn": "1. e4 *",
                },
                {
                    "id": "abcd2345",
                    "createdAt": 21,
                    "status": "resign",
                    "variant": "crazyhouse",
                    "pgn": "variant",
                },
            ]
        return httpx.Response(200, text="\n".join(map(json.dumps, rows)))

    mock_provider(monkeypatch, provider)
    async with upstream.client() as http:
        games, boundary = await upstream.lichess_page(http, "example", 10, 100)
        assert games == [upstream.RemoteGame("abcd1234", "https://lichess.org/abcd1234", None)]
        assert boundary == 100
        [ended] = await upstream.refresh_waiting(http, ["abcd1234"])
        assert ended.external_id == "abcd1234" and ended.pgn and "1-0" in ended.pgn
