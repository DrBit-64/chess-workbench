"""The course-to-study slice uses saved chess content and fixture-only HTTP."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs
from uuid import UUID

import chess.pgn
import httpx
import pytest
from pydantic import SecretStr

from chess_workbench.api import lichess as lichess_api
from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings
from chess_workbench.schemas.lichess import LichessChapterPreview, LichessStudyPreview
from chess_workbench.services.content import ServiceError
from chess_workbench.services.lichess_study import PreparedStudy, prepare_study, publish_study
from chess_workbench.store.base import Base

TOKEN = "fixture-only-lichess-token"
MAIN_PGN = (
    '[Event "Original event"]\n[White "White player"]\n[Black "Black player"]\n'
    '[Result "*"]\n\n1. d4 $1 d5 (1... Nf6 {branch note}) 2. c4 *'
)
FEN_PGN = (
    '[Event "Endgame"]\n[SetUp "1"]\n[FEN "8/8/8/8/8/8/4K2P/6k1 w - - 0 37"]\n'
    '[Result "*"]\n\n37. h4 Kg2 *'
)


async def fixture_course(tmp_path: Path) -> tuple[ChessWorkbenchApp, dict[str, Any]]:
    token_file = tmp_path / "lichess-token"
    token_file.write_text(TOKEN + "\n")
    token_file.chmod(0o600)
    app = create_app(
        Settings(
            service_name=f"lichess-test-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'course.db'}",
            source_storage_root=tmp_path / "data",
            engine_worker_enabled=False,
            lichess_api_token_file=token_file,
        )
    )
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    client = cast(Any, app.asgi_client)
    _, response = await client.post(
        "/api/pgn/imports",
        json={
            "pgn": "\n\n".join((MAIN_PGN, MAIN_PGN, FEN_PGN, MAIN_PGN)),
            "game_titles": ["大章节", "例局一", "残局", "其他章节"],
        },
    )
    assert response.status == 201, response.json
    receipt = cast(dict[str, Any], response.json["import_receipt"])
    parent, child, ending, _ = receipt["games"]
    for game, order in ((child, 1), (ending, 0)):
        _, moved = await client.patch(
            f"/api/course-modules/{game['module_id']}",
            json={"expected_version": 1, "parent_id": parent["module_id"], "sort_order": order},
        )
        assert moved.status == 200, moved.json
    _, empty = await client.post(
        "/api/course-modules",
        json={
            "course_id": receipt["course_id"],
            "parent_id": parent["module_id"],
            "title": "目录占位",
            "sort_order": 2,
        },
    )
    assert empty.status == 201, empty.json
    _, note = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": child["root_occurrence_id"],
            "markdown": "中文计划：准备中心兵推进。",
            "review_status": "approved",
        },
    )
    assert note.status == 201, note.json
    _, narrative = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": child["module_id"],
            "kind": "narrative",
            "sort_order": 10,
            "markdown": "章节正文 {括号} 也保留为文字。",
        },
    )
    assert narrative.status == 201, narrative.json
    return app, receipt


def read_games(pgn: str) -> list[chess.pgn.Game]:
    stream = io.StringIO(pgn)
    games: list[chess.pgn.Game] = []
    while (game := chess.pgn.read_game(stream)) is not None:
        assert not game.errors
        games.append(game)
    return games


async def test_flattened_scope_keeps_order_branches_annotations_and_fen(tmp_path: Path) -> None:
    app, receipt = await fixture_course(tmp_path)
    parent, child, ending, _ = receipt["games"]
    async with app.ctx.database.session() as session:
        prepared = await prepare_study(
            session, UUID(receipt["course_id"]), UUID(parent["module_id"]), token_configured=True
        )
        subsection = await prepare_study(
            session, UUID(receipt["course_id"]), UUID(child["module_id"]), token_configured=True
        )
    assert [chapter.name for chapter in prepared.preview.chapters] == [
        "大章节",
        "大章节 / 残局",
        "大章节 / 例局一",
    ]
    assert prepared.preview.skipped_modules == ["大章节 / 目录占位"]
    assert not prepared.preview.blockers
    assert len(subsection.preview.chapters) == 1
    games = read_games(prepared.pgn)
    assert len(games) == 3
    assert games[0].headers["Event"] == "Original event"
    assert games[0].headers["White"] == "White player"
    assert games[1].headers["ChapterName"] == "大章节 / 残局"
    assert games[1].board().fullmove_number == 37
    assert games[1].headers["SetUp"] == "1"
    d4 = games[2].variations[0]
    assert d4.nags == {1}
    assert [variation.san() for variation in d4.variations] == ["d5", "Nf6"]
    assert d4.variations[1].comment == "branch note"
    assert "中文计划" in games[2].comment
    assert "章节正文" in games[2].comment
    assert [node.san() for node in games[2].mainline()] == ["d4", "d5", "c4"]
    await app.ctx.database.close()


async def test_api_previews_then_sends_the_selected_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, receipt = await fixture_course(tmp_path)
    parent = receipt["games"][0]
    client = cast(Any, app.asgi_client)
    course_path = f"/api/courses/{receipt['course_id']}"
    _, preview = await client.get(
        f"{course_path}/lichess-study-preview?module_id={parent['module_id']}"
    )
    assert preview.status == 200
    assert preview.json["token_configured"] is True
    assert len(preview.json["chapters"]) == 3
    assert TOKEN not in preview.text
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        form = parse_qs(request.content.decode())
        if request.url.path == "/api/study":
            assert form["visibility"] == ["unlisted"]
            assert form["name"] == ["我的章节"]
            assert all(
                key in form for key in ("computer", "explorer", "cloneable", "shareable", "chat")
            )
            return httpx.Response(200, json={"id": "Study123"})
        assert request.url.path == "/api/study/Study123/import-pgn"
        assert form["initial"] == ["true"]
        assert form["orientation"] == ["black"]
        assert "name" not in form  # ChapterName tags name every chapter, not only the first.
        games = read_games(form["pgn"][0])
        assert len(games) == 3
        return httpx.Response(200, json={"chapters": [{"id": f"Chap000{i}"} for i in range(3)]})

    async def fixture_publish(prepared: PreparedStudy, **kwargs: Any) -> Any:
        return await publish_study(prepared, **kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(lichess_api, "publish_study", fixture_publish)
    _, result = await client.post(
        f"{course_path}/lichess-studies",
        json={"module_id": parent["module_id"], "name": "我的章节", "orientation": "black"},
    )
    assert result.status == 200, result.json
    assert result.json["status"] == "complete"
    assert result.json["imported_chapters"] == 3
    assert result.json["study_url"] == "https://lichess.org/study/Study123"
    assert len(requests) == 2
    assert TOKEN not in result.text
    await app.ctx.database.close()


def small_prepared() -> PreparedStudy:
    from uuid import uuid4

    return PreparedStudy(
        preview=LichessStudyPreview(
            name="Fixture",
            chapters=[LichessChapterPreview(module_id=uuid4(), name="one", move_count=4)],
            skipped_modules=[],
            warnings=[],
            blockers=[],
            token_configured=True,
        ),
        pgn=MAIN_PGN,
    )


@pytest.mark.parametrize("failure", ["partial", "timeout", "rate_limit"])
async def test_import_failure_keeps_study_link_without_automatic_retry(failure: str) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/study":
            return httpx.Response(200, json={"id": "Study123"})
        if failure == "timeout":
            raise httpx.ReadTimeout("fixture timeout")
        if failure == "rate_limit":
            return httpx.Response(429, json={"error": "upstream body not exposed"})
        # Actual lila returns a 200 response even when import stops with an error.
        return httpx.Response(200, json={"chapters": [], "error": "PGN rejected"})

    result = await publish_study(
        small_prepared(),
        name="Fixture",
        orientation="white",
        token=SecretStr(TOKEN),
        transport=httpx.MockTransport(handler),
    )
    assert result.status == ("partial" if failure == "partial" else "uncertain")
    assert result.study_url == "https://lichess.org/study/Study123"
    assert result.imported_chapters == 0
    assert len(calls) == 2
    assert "upstream body" not in result.message


async def test_capacity_blocker_stops_before_any_external_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chess_workbench.services import lichess_study

    app, receipt = await fixture_course(tmp_path)
    monkeypatch.setattr(lichess_study, "MAX_CHAPTERS", 2)
    async with app.ctx.database.session() as session:
        prepared = await prepare_study(
            session,
            UUID(receipt["course_id"]),
            UUID(receipt["games"][0]["module_id"]),
            token_configured=True,
        )
    assert prepared.preview.blockers

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("A blocked export must not create a remote study")

    with pytest.raises(ServiceError, match="上限"):
        await publish_study(
            prepared,
            name="Fixture",
            orientation="white",
            token=SecretStr(TOKEN),
            transport=httpx.MockTransport(handler),
        )
    await app.ctx.database.close()


async def test_api_reports_missing_token_and_rejects_foreign_scope(tmp_path: Path) -> None:
    from uuid import uuid4

    app, receipt = await fixture_course(tmp_path)
    app.ctx.settings = app.ctx.settings.model_copy(update={"lichess_api_token_file": None})
    client = cast(Any, app.asgi_client)
    course_path = f"/api/courses/{receipt['course_id']}"
    module_id = receipt["games"][0]["module_id"]
    _, preview = await client.get(f"{course_path}/lichess-study-preview?module_id={module_id}")
    assert preview.status == 200
    assert preview.json["token_configured"] is False
    _, missing = await client.post(
        f"{course_path}/lichess-studies", json={"module_id": module_id, "name": "Fixture"}
    )
    assert missing.status == 503
    assert missing.json["code"] == "lichess_unconfigured"
    assert TOKEN not in missing.text
    _, foreign = await client.get(f"{course_path}/lichess-study-preview?module_id={uuid4()}")
    assert foreign.status == 404
    await app.ctx.database.close()
