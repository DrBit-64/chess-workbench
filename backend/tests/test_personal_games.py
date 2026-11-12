"""Round-trip a personal game with raw PGN, annotations, branches and duplicate policy."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from chess_workbench.api.app import create_app
from chess_workbench.config import Settings
from chess_workbench.schemas.personal_games import NotebookImportRequest, NotebookSelection
from chess_workbench.services.content import ServiceError
from chess_workbench.services.personal_games import (
    fetch_notebook_pgn,
    game_source,
    parse_notebook_pgn,
    preview_games,
    save_games,
)
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models.graph import MoveEdge, Position
from chess_workbench.store.models.personal_games import PersonalGameNode
from pytest import MonkeyPatch
from sqlalchemy import func, select

PGN = """[Event "Study"]
[Site "https://lichess.org/AbCd1234"]
[White "White"]
[Black "Black"]
[Result "1-0"]

1. d4! {原始评语} Nf6 (1... d5 {另一条}) 2. c4 1-0
"""

SETUP = """[White "Endgame"]
[Black "Test"]
[SetUp "1"]
[FEN "8/8/5k2/8/3K4/8/7P/8 b - - 67 24"]
[Result "*"]

24... Ke6 *
"""


async def test_notebook_import_edit_archive_delete(tmp_path: Any) -> None:
    app = create_app(
        Settings(
            service_name=f"notebook-{uuid4().hex}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'notebook.db'}",
            engine_worker_enabled=False,
        )
    )
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    client = cast(Any, app.asgi_client)
    path = "/api/notebook"
    document = PGN + "\n" + SETUP + "\n\n"
    _, preview = await client.post(f"{path}/imports/preview", json={"pgn": document})
    assert preview.status == 200
    assert [g["white"] for g in preview.json["games"]] == ["White", "Endgame"]
    request = {
        "pgn": document,
        "selections": [{"index": 1}, {"index": 0}],
        "request_id": str(uuid4()),
    }
    _, created = await client.post(f"{path}/imports", json=request)
    assert created.status == 200
    second, first = [item["id"] for item in created.json["games"]]
    _, replay = await client.post(f"{path}/imports", json=request)
    assert [(item["id"], item["created"]) for item in replay.json["games"]] == [
        (second, False),
        (first, False),
    ]
    _, setup = await client.get(f"{path}/games/{second}")
    assert setup.json["nodes"][0]["fen"].endswith(" b - - 67 24")
    _, saved_setup = await client.get(f"{path}/games/{second}/pgn")
    assert saved_setup.body.decode() == SETUP + "\n\n"
    _, original = await client.get(f"{path}/games/{first}/pgn")
    assert original.body.decode() == PGN + "\n"
    _, detail = await client.get(f"{path}/games/{first}")
    nodes = detail.json["nodes"]
    d4 = next(n for n in nodes if n["san"] == "d4")
    variation = next(n for n in nodes if n["san"] == "d5")
    assert d4["nags"] == [1] and d4["comment"] == "原始评语"
    assert variation["parent_id"] == d4["id"] and not variation["is_mainline"]
    game_url = f"{path}/games/{first}"
    note_url = f"{game_url}/nodes/{variation['id']}"
    _, note = await client.patch(note_url, json={"expected_version": 1, "note": "我考虑过的变例"})
    assert note.status == 200 and note.json["version"] == 2
    _, conflict = await client.patch(note_url, json={"expected_version": 1, "note": "old"})
    assert conflict.status == 409
    _, summary = await client.patch(game_url, json={"expected_version": 1, "summary": "换后"})
    assert summary.status == 200
    _, filtered = await client.get(f"{path}/game-catalog", params={"q": "换后", "limit": 1})
    assert filtered.json["total"] == 1 and filtered.json["items"][0]["id"] == first
    _, next_page = await client.get(f"{path}/game-catalog?limit=1&offset=1")
    assert next_page.json["total"] == 2 and len(next_page.json["items"]) == 1
    _, again = await client.post(f"{path}/imports", json={"pgn": PGN, "selections": [{"index": 0}]})
    assert again.json["games"][0] == {"id": first, "index": 0, "created": False}
    _, detail = await client.get(game_url)
    assert detail.json["summary"] == "换后"
    assert (
        next(n for n in detail.json["nodes"] if n["id"] == variation["id"])["note"]
        == "我考虑过的变例"
    )
    _, cleared = await client.patch(note_url, json={"expected_version": 2, "note": ""})
    assert (
        cleared.status == 200 and cleared.json["note"] == "" and cleared.json["comment"] == "另一条"
    )
    _, protected = await client.delete(f"{game_url}?expected_version=2")
    assert protected.status == 409
    _, archive = await client.patch(game_url, json={"expected_version": 2, "archived": True})
    assert archive.status == 200
    _, listed = await client.get(f"{path}/games")
    assert [g["id"] for g in listed.json] == [second]
    _, restored = await client.patch(game_url, json={"expected_version": 3, "archived": False})
    assert restored.status == 200 and restored.json["archived_at"] is None
    _, archive = await client.patch(game_url, json={"expected_version": 4, "archived": True})
    _, deleted = await client.delete(f"{game_url}?expected_version={archive.json['version']}")
    assert deleted.status == 204
    _, missing = await client.get(game_url)
    assert missing.status == 404
    async with app.ctx.database.session() as session:
        assert await session.get(PersonalGameNode, UUID(d4["id"])) is None
        assert (await session.scalar(select(func.count()).select_from(Position)) or 0) > 2
        assert (await session.scalar(select(func.count()).select_from(MoveEdge)) or 0) > 1
    await app.ctx.database.close()


async def test_source_less_duplicates_are_a_choice_and_bulk_rollback_is_atomic(
    tmp_path: Any,
) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'choice.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    raw = PGN.replace("https://lichess.org/AbCd1234", "OTB")
    doc = parse_notebook_pgn(raw)
    create = NotebookImportRequest(pgn=raw, selections=[NotebookSelection(index=0)])
    async with db.session() as session, session.begin():
        original = (await save_games(session, doc, create))[0]
    async with db.session() as session, session.begin():
        assert (await preview_games(session, doc))[0].possible_duplicates == [original.id]
    with pytest.raises(ServiceError, match="可能相同"):
        async with db.session() as session, session.begin():
            combined = SETUP + "\n" + raw
            await save_games(
                session,
                parse_notebook_pgn(combined),
                NotebookImportRequest(
                    pgn=combined,
                    selections=[NotebookSelection(index=0), NotebookSelection(index=1)],
                ),
            )
    async with db.session() as session, session.begin():
        assert not (await preview_games(session, parse_notebook_pgn(SETUP)))[0].possible_duplicates
        open_existing = NotebookSelection(index=0, action="open", existing_id=original.id)
        assert (
            await save_games(
                session, doc, create.model_copy(update={"selections": [open_existing]})
            )
        )[0].id == original.id
        copy = NotebookSelection(index=0, action="copy")
        duplicate = (
            await save_games(session, doc, create.model_copy(update={"selections": [copy]}))
        )[0]
        assert duplicate.created and duplicate.id != original.id
    await db.close()


async def test_lichess_download_uses_canonical_id_and_rejects_untrusted_hosts(
    monkeypatch: MonkeyPatch,
) -> None:
    client_type = httpx.AsyncClient
    seen = []

    def serve(req: httpx.Request) -> httpx.Response:
        seen.append((req.url.host, req.url.path))
        return httpx.Response(200, text=PGN)

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(serve), **kw)
    )
    assert await fetch_notebook_pgn("https://lichess.org/AbCd1234abcd/black#12", None, None) == PGN
    assert seen == [("lichess.org", "/game/export/AbCd1234")]
    assert game_source("https://lichess.org/game/AbCd1234").url == "https://lichess.org/AbCd1234"
    with pytest.raises(ServiceError, match="单局链接"):
        await fetch_notebook_pgn("https://lichess.org.example/AbCd1234", None, None)
    assert len(seen) == 1
    assert (
        game_source("https://www.chess.com/analysis/game/live/1234/analysis").external_id
        == "live/1234"
    )


async def test_catalog_cards_use_mainline_final_fen_and_lichess_openings(tmp_path: Any) -> None:
    app = create_app(
        Settings(
            service_name=f"notebook-cards-{uuid4().hex}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'cards.db'}",
            engine_worker_enabled=False,
        )
    )
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    # The variation is longer than the actual game, and this non-Lichess PGN's
    # provider opening label differs from the verified Lichess classification.
    pgn = """[White "First"]
[WhiteElo "2000"]
[BlackElo "1994"]
[TimeControl "300+3"]
[ECO "D10"]
[Opening "Slav Defense"]

1. c4 Nf6 (1... c6 2. d4 d5 3. Nc3) 2. d4 *

[White "Second"]
[WhiteElo "?"]
[TimeControl "1/259200"]

1. d4 Nf6 2. c4 *

[White "Study"]
[SetUp "1"]
[FEN "8/8/5k2/8/3K4/8/7P/8 b - - 67 24"]

*

[White "Native"]
[Site "https://lichess.org/ZYXwv123"]
[Opening "Indian Defense"]
[ECO "A45"]
[TimeControl "-"]

1. d4 Nf6 2. c4 *
"""
    client = cast(Any, app.asgi_client)
    _, saved = await client.post(
        "/api/notebook/imports",
        json={"pgn": pgn, "selections": [{"index": index} for index in range(4)]},
    )
    assert saved.status == 200, saved.json
    _, result = await client.get("/api/notebook/game-catalog")
    assert result.status == 200, result.json
    cards = {row["white"]: row for row in result.json["items"]}
    a, b, setup, native = (cards[key] for key in ("First", "Second", "Study", "Native"))
    assert (a["white_rating"], a["black_rating"], a["time_control"]) == (2000, 1994, "300+3")
    assert (b["white_rating"], b["black_rating"], b["time_control"]) == (None, None, "1/259200")
    assert (a["opening_eco"], a["opening_name"]) == ("A50", "Indian Defense: Normal Variation")
    assert (b["opening_eco"], b["opening_name"]) == (a["opening_eco"], a["opening_name"])
    assert a["final_fen"] == "rnbqkb1r/pppppppp/5n2/8/2PP4/8/PP2PPPP/RNBQKBNR b KQkq d3 0 2"
    assert b["final_fen"].endswith(" b KQkq c3 0 2")
    assert setup["final_fen"] == "8/8/5k2/8/3K4/8/7P/8 b - - 67 24"
    assert (setup["opening_eco"], setup["opening_name"], setup["time_control"]) == (
        None,
        None,
        None,
    )
    assert (native["opening_eco"], native["opening_name"], native["time_control"]) == (
        "A45",
        "Indian Defense",
        "-",
    )
    await app.ctx.database.close()
