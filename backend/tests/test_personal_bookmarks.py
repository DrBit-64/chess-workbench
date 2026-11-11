"""Notebook acceptance across star provenance, mutable move notes and graph transpositions."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from chess_workbench.api.app import create_app
from chess_workbench.config import Settings
from chess_workbench.store.base import Base

BASE = "/api/notebook"
GAME_A = (
    '[White "A"]\n[Black "Guest"]\n\n'
    "1. Nf3 Nf6 2. d4 d5 3. Ng1 (3. Nc3 Nc6 4. Nb1 Nb8) Ng8 4. Nf3 Nf6 *"
)
GAME_B = '[White "B"]\n[Black "Guest"]\n\n1. d4 d5 2. Nf3 Nf6 *'


@pytest.fixture
async def notebook(tmp_path: Path) -> AsyncIterator[tuple[Any, list[Any]]]:
    app = create_app(
        Settings(
            service_name=f"bookmarks-{uuid4().hex}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'notebook.db'}",
            engine_worker_enabled=False,
        )
    )
    async with app.ctx.database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    client = cast(Any, app.asgi_client)
    try:
        _, result = await client.post(
            f"{BASE}/imports",
            json={
                "pgn": f"{GAME_A}\n\n{GAME_B}",
                "selections": [{"index": 0}, {"index": 1}],
            },
        )
        assert result.status == 200, result.text
        games = []
        for entry in result.json["games"]:
            _, game = await client.get(f"{BASE}/games/{entry['id']}")
            games.append(game.json)
        yield client, games
    finally:
        await client.aclose()
        await app.ctx.database.close()


async def test_search_only_links_chosen_move_notes_and_retains_on_unstar(
    notebook: tuple[Any, list[Any]],
) -> None:
    client, (game, _) = notebook
    nodes = {node["ply"]: node for node in game["nodes"] if node["is_mainline"]}
    before = nodes[4]
    chosen_move = nodes[5]
    notes_url = f"{BASE}/games/{game['id']}/nodes"
    for node, note in [(chosen_move, "临场考虑换后的王"), (nodes[1], "不相关的同局评语")]:
        _, result = await client.patch(
            f"{notes_url}/{node['id']}", json={"expected_version": 1, "note": note}
        )
        assert result.status == 200, result.text
    _, star = await client.post(
        f"{BASE}/bookmarks", json={"node_id": before["id"], "related_node_id": chosen_move["id"]}
    )
    assert star.status == 200
    bookmark = star.json
    assert bookmark["related_moves"][0]["note"] == "临场考虑换后的王"
    url = f"{BASE}/bookmarks/{bookmark['id']}"
    _, edit = await client.patch(
        url,
        json={
            "expected_version": bookmark["version"],
            "title": "换后时机",
            "note": "先看王的位置，再看100%_保障。",
            "tags": ["车残局", "换后", "车残局"],
        },
    )
    assert edit.status == 200
    assert set(edit.json["tags"]) == {"车残局", "换后"}
    _, stale = await client.patch(url, json={"expected_version": 1, "title": "旧稿"})
    assert stale.status == 409
    for q, kind in [
        ("王的位置", "note"),
        ("换后的王", "move_note"),
        ("%_", "note"),
        ("时机", "title"),
    ]:
        _, found = await client.get(
            f"{BASE}/bookmarks", params=[("tag", "换后"), ("tag", "车残局"), ("q", q)]
        )
        assert found.json["total"] == 1
        assert found.json["items"][0]["matches"][0]["field"] == kind
    for params in [[("q", "不相关")], [("tag", "换后"), ("tag", "王兵残局")], [("q", "%_X")]]:
        _, missing = await client.get(f"{BASE}/bookmarks", params=params)
        assert missing.json["total"] == 0
    # Starring from the board also makes its incoming move available, in the same record.
    _, current = await client.post(f"{BASE}/bookmarks", json={"node_id": before["id"]})
    assert current.json["id"] == bookmark["id"]
    assert {m["node_id"] for m in current.json["related_moves"]} == {
        chosen_move["id"],
        before["id"],
    }
    _, hidden = await client.patch(
        url, json={"expected_version": current.json["version"], "active": False}
    )
    assert hidden.status == 200
    _, none = await client.get(f"{BASE}/bookmarks", params={"game_id": game["id"]})
    assert none.json["total"] == 0
    _, again = await client.post(f"{BASE}/bookmarks", json={"node_id": before["id"]})
    assert again.json["note"] == edit.json["note"]
    assert again.json["id"] == bookmark["id"]
    _, delete = await client.delete(url, params={"expected_version": again.json["version"]})
    assert delete.status == 204
    _, gone = await client.get(url)
    assert gone.status == 404
    _, original = await client.get(f"{BASE}/games/{game['id']}")
    assert (
        next(n for n in original.json["nodes"] if n["id"] == chosen_move["id"])["note"]
        == "临场考虑换后的王"
    )


async def test_position_lookup_includes_unstarred_games_repetitions_and_variations(
    notebook: tuple[Any, list[Any]],
) -> None:
    client, (game, other_game) = notebook
    source = next(n for n in game["nodes"] if n["ply"] == 4 and n["is_mainline"])
    _, created = await client.post(f"{BASE}/bookmarks", json={"node_id": source["id"]})
    bookmark = created.json
    url = f"{BASE}/bookmarks/{bookmark['id']}/occurrences"
    _, hits = await client.get(url)
    assert {(h["game_id"], h["ply"], h["is_mainline"]) for h in hits.json["items"]} == {
        (game["id"], 8, True),
        (other_game["id"], 4, True),
    }
    assert source["id"] not in {h["node_id"] for h in hits.json["items"]}
    _, extended = await client.get(url, params={"include_variations": "true"})
    assert extended.json["total"] == 3
    assert any(not hit["is_mainline"] for hit in extended.json["items"])
    branch = next(n for n in game["nodes"] if not n["is_mainline"] and n["ply"] == 8)
    _, branch_hit = await client.post(f"{BASE}/bookmarks", json={"node_id": branch["id"]})
    assert branch_hit.json["node_id"] == branch["id"] and branch_hit.json["is_mainline"] is False
    root = next(n for n in game["nodes"] if n["parent_id"] is None)
    _, root_hit = await client.post(f"{BASE}/bookmarks", json={"node_id": root["id"]})
    assert root_hit.json["related_moves"] == [] and root_hit.json["fen"] == root["fen"]
    _, bad = await client.post(
        f"{BASE}/bookmarks", json={"node_id": root["id"], "related_node_id": branch["id"]}
    )
    assert bad.status == 422
    _, archive = await client.patch(
        f"{BASE}/games/{game['id']}", json={"expected_version": game["version"], "archived": True}
    )
    assert archive.status == 200
    _, preserved = await client.get(f"{BASE}/bookmarks/{bookmark['id']}")
    assert preserved.json["node_id"] == source["id"] and preserved.json["archived"]
