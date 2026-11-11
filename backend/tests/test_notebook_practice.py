from pathlib import Path
from typing import Any, cast

from chess_workbench.api.app import create_app
from chess_workbench.config import Settings
from chess_workbench.store.base import Base


async def test_authored_exercise_validates_each_line_and_keeps_the_bookmark(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            service_name="notebook-practice-test",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'practice.db'}",
            engine_worker_enabled=False,
        )
    )
    async with app.ctx.database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    client = cast(Any, app.asgi_client)
    _, imported = await client.post(
        "/api/notebook/imports",
        json={"pgn": '[White "A"]\n[Black "B"]\n\n1. d4 Nf6 *', "selections": [{"index": 0}]},
    )
    assert imported.status == 200, imported.json
    _, detail = await client.get("/api/notebook/games/" + imported.json["games"][0]["id"])
    node = next(n for n in detail.json["nodes"] if n["san"] == "d4")
    _, mark = await client.post("/api/notebook/bookmarks", json={"node_id": node["id"]})
    assert mark.status in (200, 201), mark.json
    url = "/api/notebook/bookmarks/" + mark.json["id"]
    exercise = url + "/practice"
    _, original = await client.get(exercise)
    assert original.json["version"] == 0
    _, invalid = await client.put(
        exercise, json={"expected_version": 0, "prompt": "", "lines": [["g8f6", "c2c4"], ["e2e4"]]}
    )
    assert invalid.status == 422
    _, saved = await client.put(
        exercise,
        json={"expected_version": 0, "prompt": "黑方的应对", "lines": [["g8f6", "c2c4"], ["d7d5"]]},
    )
    assert saved.status == 200
    assert saved.json["version"] == 1
    _, stale = await client.put(
        exercise, json={"expected_version": 0, "prompt": "旧稿", "lines": [["d7d5"]]}
    )
    assert stale.status == 409
    _, removed = await client.request("DELETE", exercise, json={"expected_version": 1})
    assert removed.status == 204
    _, current = await client.get(url)
    assert current.status == 200 and current.json["fen"] == node["fen"]
    await app.ctx.database.close()
