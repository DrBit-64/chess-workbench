"""Review edits retain original game facts and bookmark occurrence identities."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from chess_workbench.api.app import create_app
from chess_workbench.config import Settings
from chess_workbench.domain import PositionState
from chess_workbench.schemas.notebook_tree import NotebookRecordMove, NotebookTreeResult
from chess_workbench.services import ServiceError
from chess_workbench.services.notebook_tree import record_move
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import MoveEdge, Position
from sqlalchemy import func, select

PGN = """[White "White"]
[Black "Black"]
[UTCDate "2026.11.05"]
[UTCTime "05:10:20"]
[TimeControl "300+2"]

1. e4 {[%clk 0:04:51]} e5 (1... c5 2. Nf3) 2. Bc4 *
"""


@dataclass
class Notebook:
    client: Any
    db: Database
    url: str
    version: int
    initial: dict[str, Any]

    async def move(self, parent: str, uci: str) -> dict[str, Any]:
        _, response = await self.client.post(
            self.url + "/moves",
            json={"parent_id": parent, "uci": uci, "expected_version": self.version},
        )
        assert response.status == 200, response.text
        self.version = response.json["game_version"]
        return cast(dict[str, Any], response.json)

    async def branch(self, node: str, action: str) -> dict[str, Any]:
        _, response = await self.client.post(
            f"{self.url}/nodes/{node}/branch",
            json={"kind": action, "expected_version": self.version},
        )
        assert response.status == 200, response.text
        self.version = response.json["game_version"]
        return cast(dict[str, Any], response.json)

    async def nodes(self) -> list[dict[str, Any]]:
        _, game = await self.client.get(self.url)
        return cast(list[dict[str, Any]], game.json["nodes"])


@pytest.fixture
async def notebook(tmp_path: Path) -> AsyncIterator[Notebook]:
    app = create_app(
        Settings(
            service_name=f"notebook-tree-{uuid4().hex}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'tree.db'}",
            engine_worker_enabled=False,
        )
    )
    async with app.ctx.database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    client = cast(Any, app.asgi_client)
    try:
        _, result = await client.post(
            "/api/notebook/imports", json={"pgn": PGN, "selections": [{"index": 0}]}
        )
        assert result.status == 200, result.text
        url = "/api/notebook/games/" + result.json["games"][0]["id"]
        _, game = await client.get(url)
        yield Notebook(client, app.ctx.database, url, game.json["version"], game.json)
    finally:
        await client.aclose()
        await app.ctx.database.close()


async def test_review_priorities_and_provenance_survive_delete_and_restore(
    notebook: Notebook,
) -> None:
    book = notebook
    nodes = {n["san"]: n for n in book.initial["nodes"]}
    root, e4, e5, c5, nf3, bc4 = (nodes[s]["id"] for s in (None, "e4", "e5", "c5", "Nf3", "Bc4"))
    _, before = await book.client.get("/api/notebook/game-catalog")
    _, saved = await book.client.patch(
        f"{book.url}/nodes/{nf3}", json={"note": "备选方案", "expected_version": 1}
    )
    assert saved.status == 200
    _, star = await book.client.post("/api/notebook/bookmarks", json={"node_id": nf3})
    assert star.status == 200, star.text

    added = await book.move(e4, "e7e6")
    e6 = added["selected_id"]
    assert len(added["nodes"]) == 1
    position = PositionState(nodes["e4"]["fen"]).apply_uci("e7e6")
    assert (
        added["nodes"][0].items()
        >= {
            "id": e6,
            "parent_id": e4,
            "is_mainline": False,
            "fen": position.after.full_fen,
            "san": "e6",
            "sort_order": 2,
            "hidden": False,
        }.items()
    )
    version = book.version
    assert await book.move(e4, "e7e6") == {"selected_id": e6, "nodes": [], "game_version": version}
    _, stale = await book.client.post(
        book.url + "/moves", json={"parent_id": e4, "uci": "d7d6", "expected_version": version - 1}
    )
    assert stale.status == 409

    async def visible(parent: str) -> list[str]:
        siblings = (n for n in await book.nodes() if n["parent_id"] == parent and not n["hidden"])
        ordered = sorted(siblings, key=lambda n: n["sort_order"])
        assert [n["sort_order"] for n in ordered] == list(range(len(ordered)))
        return [n["id"] for n in ordered]

    await book.branch(e6, "promote_variation")
    assert await visible(e4) == [e5, e6, c5]
    await book.branch(e6, "demote_variation")
    assert await visible(e4) == [e5, c5, e6]
    # Promote a nested alternative to both the preferred reply and the preferred third ply.
    child = (await book.move(c5, "b1c3"))["selected_id"]
    await book.branch(child, "make_mainline")
    assert await visible(e4) == [c5, e5, e6]
    assert await visible(c5) == [child, nf3]
    assert (await book.branch(child, "make_mainline"))["nodes"] == []
    # Delete the *played* first move. Every visible descendant disappears from notation.
    removed = await book.branch(e4, "delete_subtree")
    assert removed["selected_id"] == root
    assert {n["id"] for n in removed["nodes"]} == {e4, e5, c5, nf3, bc4, child, e6}
    assert await visible(root) == []
    _, hidden_parent = await book.client.post(
        book.url + "/moves", json={"parent_id": e4, "uci": "c7c6", "expected_version": book.version}
    )
    assert hidden_parent.status == 409
    _, archived_star = await book.client.get("/api/notebook/bookmarks/" + star.json["id"])
    assert archived_star.status == 200 and archived_star.json["node_id"] == nf3
    assert archived_star.json["related_moves"][0]["note"] == "备选方案"
    _, original = await book.client.get(book.url + "/pgn")
    _, after = await book.client.get("/api/notebook/game-catalog")
    assert original.body.decode() == PGN
    for field in ["final_fen", "time_control", "started_at", "opening_eco", "opening_name"]:
        assert after.json["items"][0][field] == before.json["items"][0][field]
    assert after.json["items"][0]["final_fen"] == nodes["Bc4"]["fen"]

    await book.move(root, "d2d4")  # Fresh move in front of the hidden original.
    revived = await book.move(root, "e2e4")
    assert revived["selected_id"] == e4 and await visible(e4) == []
    restored = await book.branch(nf3, "restore_path")
    assert restored["selected_id"] == nf3
    assert await visible(e4) == [c5] and await visible(c5) == [nf3]
    # Hidden siblings, including the deeper played position, are not revived by this restore.
    current = {n["id"]: n for n in await book.nodes()}
    assert current[e5]["hidden"] and current[bc4]["hidden"] and current[child]["hidden"]
    assert current[e4]["is_mainline"] and not current[c5]["is_mainline"]
    assert current[e4]["comment"] == nodes["e4"]["comment"] and current[nf3]["note"] == "备选方案"
    assert (await book.branch(nf3, "restore_path"))["nodes"] == []


async def test_illegal_move_protected_root_and_competing_edit(notebook: Notebook) -> None:
    book = notebook
    root = next(n["id"] for n in book.initial["nodes"] if n["parent_id"] is None)
    async with book.db.session() as session:
        positions = await session.scalar(select(func.count()).select_from(Position))
        edges = await session.scalar(select(func.count()).select_from(MoveEdge))

    _, illegal = await book.client.post(
        book.url + "/moves", json={"parent_id": root, "uci": "e2e5", "expected_version": 1}
    )
    assert illegal.status == 422
    _, foreign = await book.client.post(
        book.url + "/moves", json={"parent_id": str(uuid4()), "uci": "e2e4", "expected_version": 1}
    )
    assert foreign.status == 404
    _, protected = await book.client.post(
        f"{book.url}/nodes/{root}/branch", json={"kind": "delete_subtree", "expected_version": 1}
    )
    assert protected.status == 422
    async with book.db.session() as session:
        assert await session.scalar(select(func.count()).select_from(Position)) == positions
        assert await session.scalar(select(func.count()).select_from(MoveEdge)) == edges

    async def write(uci: str) -> NotebookTreeResult:
        body = NotebookRecordMove(parent_id=UUID(root), uci=uci, expected_version=1)
        return await book.db.run_write(lambda s: record_move(s, UUID(book.initial["id"]), body))

    results = await asyncio.gather(write("d2d4"), write("g1f3"), return_exceptions=True)
    assert sorted(r.status if isinstance(r, ServiceError) else 200 for r in results) == [200, 409]
    assert len([r for r in results if isinstance(r, NotebookTreeResult)]) == 1
    final = await book.nodes()
    assert len([n for n in final if n["parent_id"] == root]) == 2


async def test_duplicate_import_occurrences_and_promotion_from_setup(notebook: Notebook) -> None:
    client = notebook.client
    setup_fen = "7k/8/8/8/8/8/p7/5K2 b - - 2 28"
    pgn = (
        '[White "Repeated"]\n\n1. e4 (1. e4 {另一个解释}) e5 *\n\n'
        f'[White "Custom"]\n[SetUp "1"]\n[FEN "{setup_fen}"]\n\n*'
    )
    _, imported = await client.post(
        "/api/notebook/imports", json={"pgn": pgn, "selections": [{"index": 0}, {"index": 1}]}
    )
    assert imported.status == 200
    books = []
    for item in imported.json["games"]:
        url = "/api/notebook/games/" + item["id"]
        _, game = await client.get(url)
        books.append(Notebook(client, notebook.db, url, game.json["version"], game.json))
    repeated, custom = books
    root = next(n for n in repeated.initial["nodes"] if n["parent_id"] is None)
    first, second = sorted(
        (n for n in repeated.initial["nodes"] if n["uci"] == "e2e4"), key=lambda n: n["sort_order"]
    )
    await repeated.branch(first["id"], "delete_subtree")
    assert (await repeated.move(root["id"], "e2e4"))["selected_id"] == second["id"]
    await repeated.branch(first["id"], "restore_path")
    siblings = [n for n in await repeated.nodes() if n["parent_id"] == root["id"]]
    assert [n["id"] for n in siblings] == [second["id"], first["id"]]
    assert siblings[0]["comment"] == "另一个解释"

    _, foreign = await client.post(
        custom.url + "/moves",
        json={"parent_id": root["id"], "uci": "d2d4", "expected_version": custom.version},
    )
    assert foreign.status == 404
    custom_root = custom.initial["nodes"][0]["id"]
    add = await custom.move(custom_root, "a2a1n")
    promotion = add["nodes"][0]
    assert promotion["uci"] == "a2a1n" and promotion["san"] == "a1=N"
    assert promotion["fen"] == PositionState(setup_fen).apply_uci("a2a1n").after.full_fen
    assert promotion["fen"].endswith(" w - - 0 29") and not promotion["is_mainline"]
