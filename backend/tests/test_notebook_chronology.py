from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from chess_workbench.api.app import create_app
from chess_workbench.config import Settings
from chess_workbench.domain.game_chronology import catalog_date, game_chronology
from chess_workbench.services import notebook_platforms
from chess_workbench.store.base import Base
from chess_workbench.store.models.personal_games import PersonalGame
from sqlalchemy import update


def test_partial_and_zoned_pgn_dates() -> None:
    imported = datetime(2026, 11, 12, tzinfo=UTC)
    for raw, when, display in [
        ("2023.??.??", datetime(2023, 1, 1, tzinfo=UTC), "2023.??.??"),
        ("2023.05.??", datetime(2023, 5, 1, tzinfo=UTC), "2023.05.??"),
        ("2023.02.30", imported, "????.??.??"),
        ("????.??.??", imported, "????.??.??"),
    ]:
        tags = {"date": raw}
        assert game_chronology(tags, imported) == (when, None, None)
        assert catalog_date(tags) == display
    zoned = {"Date": "2024.10.01", "StartTime": "00:30:00", "Timezone": "UTC+02:00"}
    assert game_chronology(zoned, imported).started_at == datetime(2024, 9, 30, 22, 30, tzinfo=UTC)


async def test_catalog_sorts_before_pagination_and_keeps_whole_result_clock_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings(
            service_name=f"sort-{uuid4().hex}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'sort.db'}",
            engine_worker_enabled=False,
        )
    )
    async with app.ctx.database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    client = cast(Any, app.asgi_client)
    api = "/api/notebook"
    link = "https://lichess.org/AbCd1234"

    def score(white: str, extra: str) -> str:
        return f'[White "{white}"]\n[Black "Common Opponent"]\n{extra}\n1. e4 1-0'

    native = score("newest public", f'[Site "{link}"]\n[TimeControl "300+3"]\n')
    precise = datetime(2025, 11, 1, 14, 5, 6, 218000, tzinfo=UTC)

    def source(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pgnInJson"] == "true"
        return httpx.Response(
            200, json={"createdAt": int(precise.timestamp() * 1000), "pgn": native}
        )

    monkeypatch.setattr(
        notebook_platforms,
        "client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(source)),
    )
    try:
        _, preview = await client.post(f"{api}/imports/preview", json={"url": link})
        assert (
            preview.json["pgn"] == native
            and datetime.fromisoformat(preview.json["source_started_at"]) == precise
        )
        _, saved = await client.post(
            f"{api}/imports",
            json={key: preview.json[key] for key in ("pgn", "source_url", "source_started_at")}
            | {"selections": [{"index": 0}]},
        )
        assert saved.status == 200
        document = "\n\n".join(
            [
                score(
                    "early", '[Date "2025.10.01"]\n[UTCTime "10:30:00"]\n[TimeControl "300+3"]\n'
                ),
                score("unknown", '[TimeControl "?"]\n'),
                score(
                    "late", '[UTCDate "2025.10.01"]\n[UTCTime "21:30:00"]\n[TimeControl "600+0"]\n'
                ),
                score("partial", '[UTCDate "2023.05.??"]\n[TimeControl "300+3"]\n'),
            ]
        )
        _, saved = await client.post(
            f"{api}/imports", json={"pgn": document, "selections": [{"index": i} for i in range(4)]}
        )
        assert saved.status == 200
        # Simulate offline-upgraded rows from a populated database, without reimport.
        async with app.ctx.database.session() as session, session.begin():
            await session.execute(
                update(PersonalGame)
                .where(PersonalGame.white != "newest public")
                .values(order_at=None, time_control=None, started_at=None)
            )

        async def catalog(**params: Any) -> dict[str, Any]:
            _, response = await client.get(f"{api}/game-catalog", params=params)
            assert response.status == 200, response.text
            return cast(dict[str, Any], response.json)

        result = await catalog(limit=2, offset=1)
        assert [r["white"] for r in result["items"]] == ["newest public", "late"]
        assert set(result["time_controls"]) == {None, "300+3", "600+0"}
        subset = await catalog(order="asc", time_control="300+3", q="Common", limit=1, offset=1)
        assert subset["total"] == 3 and [g["white"] for g in subset["items"]] == ["early"]
        assert set(subset["time_controls"]) == set(result["time_controls"])
        assert [r["white"] for r in (await catalog(time_control="?"))["items"]] == ["unknown"]
        earliest = (await catalog(order="asc", limit=1))["items"][0]
        assert earliest["date"] == "2023.05.??" and earliest["started_at"] is None
    finally:
        await client.aclose()
        await app.ctx.database.close()
