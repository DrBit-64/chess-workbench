"""PGN HTTP import/idempotency/provenance acceptance tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings
from chess_workbench.logic.pgn import parse_pgn, parse_pgn_document
from chess_workbench.logic.pgn_compare import compare_documents, compare_games
from chess_workbench.store.base import Base
from chess_workbench.store.models import (
    Course,
    CourseModule,
    CourseOccurrence,
    PgnAsset,
    PgnImport,
    PgnOccurrenceAnnotation,
    Source,
    SourceFile,
    SourceSpan,
)
from sqlalchemy import func, select

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pgn"


def build_test_app(tmp_path: Path) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-pgn-api-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'pgn-api.db'}",
            source_storage_root=tmp_path / "data",
            engine_worker_enabled=False,
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def table_counts(app: ChessWorkbenchApp) -> tuple[int, ...]:
    models = (
        PgnImport,
        PgnAsset,
        Source,
        SourceFile,
        SourceSpan,
        Course,
        CourseModule,
        CourseOccurrence,
    )
    async with app.ctx.database.session() as session:
        counts: list[int] = []
        for model in models:
            counts.append((await session.scalar(select(func.count()).select_from(model))) or 0)
        return tuple(counts)


async def test_json_raw_and_multipart_replay_one_logical_import(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    text = (FIXTURE_DIR / "02_one_variation.pgn").read_text()

    _, created_response = await client.post("/api/pgn/imports", json={"pgn": text})
    assert created_response.status == 201
    created = cast(dict[str, Any], created_response.json)["import_receipt"]
    counts = await table_counts(app)
    assert created_response.headers["idempotency-replayed"] == "false"
    assert created_response.headers["location"] == f"/api/pgn/imports/{created['id']}"

    _, json_replay = await client.post("/api/pgn/imports", json={"pgn": text})
    _, raw_replay = await client.post(
        "/api/pgn/imports",
        content=text.encode(),
        headers={"content-type": "application/x-chess-pgn"},
    )
    _, multipart_replay = await client.post(
        "/api/pgn/imports",
        files={"file": ("game.pgn", text.encode(), "application/x-chess-pgn")},
    )

    for response in (json_replay, raw_replay, multipart_replay):
        assert response.status == 200
        assert response.headers["idempotency-replayed"] == "true"
        assert response.json["import_receipt"]["id"] == created["id"]
        assert response.json["import_receipt"]["course_id"] == created["course_id"]
    assert await table_counts(app) == counts

    _, get_response = await client.get(f"/api/pgn/imports/{created['id']}")
    assert get_response.status == 200
    assert get_response.json["id"] == created["id"]
    assert created["game_count"] == 1
    assert created["occurrence_count"] > 1


async def test_multi_game_import_creates_one_asset_and_ordered_modules(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    first = (FIXTURE_DIR / "01_mainline.pgn").read_text()
    second = (FIXTURE_DIR / "07_unicode_comment.pgn").read_text()

    _, response = await client.post(
        "/api/pgn/imports",
        json={"pgn": first + "\n" + second, "game_titles": ["First", "Second"]},
    )

    assert response.status == 201
    receipt = response.json["import_receipt"]
    assert receipt["game_count"] == 2
    assert [game["game_index"] for game in receipt["games"]] == [0, 1]
    async with app.ctx.database.session() as session:
        modules = list(
            await session.scalars(
                select(CourseModule)
                .where(CourseModule.course_id == UUID(receipt["course_id"]))
                .order_by(CourseModule.sort_order)
            )
        )
        spans = list(await session.scalars(select(SourceSpan)))
    assert [(module.title, module.sort_order) for module in modules] == [
        ("First", 0),
        ("Second", 1),
    ]
    assert len(spans) == 2
    assert all(span.locator_kind == "text" for span in spans)

    _, download = await client.get(f"/api/pgn/imports/{receipt['id']}/download")
    assert download.status == 200
    assert download.headers["content-type"] == "application/x-chess-pgn; charset=utf-8"
    assert download.headers["cache-control"] == "no-store"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert int(download.headers["content-length"]) == len(download.body)
    comparison = compare_documents(
        parse_pgn_document(first + "\n" + second),
        parse_pgn_document(download.text),
    )
    assert comparison.equivalent, comparison.differences

    first_game = receipt["games"][0]
    _, module_download = await client.get(
        f"/api/courses/{receipt['course_id']}/pgn?module_id={first_game['module_id']}"
    )
    module_comparison = compare_games(parse_pgn(first), parse_pgn(module_download.text))
    assert module_comparison.equivalent, module_comparison.differences


async def test_idempotency_conflict_and_invalid_pgn_leave_zero_writes(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    first = (FIXTURE_DIR / "01_mainline.pgn").read_text()
    second = (FIXTURE_DIR / "02_one_variation.pgn").read_text()
    headers = {"idempotency-key": "same-user-action"}

    _, created = await client.post("/api/pgn/imports", json={"pgn": first}, headers=headers)
    assert created.status == 201
    counts = await table_counts(app)
    _, conflict = await client.post("/api/pgn/imports", json={"pgn": second}, headers=headers)
    assert conflict.status == 409
    assert conflict.json["code"] == "idempotency_conflict"
    assert await table_counts(app) == counts

    empty_app = build_test_app(tmp_path / "invalid")
    await create_schema(empty_app)
    empty_client = cast(Any, empty_app.asgi_client)
    _, invalid = await empty_client.post(
        "/api/pgn/imports",
        json={"pgn": '[Result "*"]\n\n1. e4 e5 2. Kf3 *'},
    )
    assert invalid.status == 422
    assert invalid.json["code"] == "invalid_pgn"
    assert await table_counts(empty_app) == (0,) * 8


async def test_existing_course_append_bumps_version_once_and_replay_precedes_stale(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    text = (FIXTURE_DIR / "01_mainline.pgn").read_text()
    _, course_response = await client.post(
        "/api/courses",
        json={"title": "Existing", "mode": "traditional"},
    )
    course = course_response.json
    body = {
        "pgn": text,
        "destination": {
            "kind": "existing_course",
            "course_id": course["id"],
            "expected_version": 1,
        },
    }

    _, created = await client.post("/api/pgn/imports", json=body)
    assert created.status == 201
    receipt = created.json["import_receipt"]
    assert receipt["course_id"] == course["id"]
    assert receipt["course_version"] == 2

    # The original expected_version is now stale, but replay lookup is first.
    _, replay = await client.post("/api/pgn/imports", json=body)
    assert replay.status == 200
    assert replay.json["import_receipt"]["id"] == receipt["id"]
    _, fetched = await client.get(f"/api/courses/{course['id']}")
    assert fetched.json["version"] == 2


async def test_same_bytes_different_new_course_reuses_source_asset(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    text = (FIXTURE_DIR / "01_mainline.pgn").read_text()

    _, first = await client.post(
        "/api/pgn/imports",
        json={"pgn": text, "destination": {"kind": "new_course", "title": "Copy A"}},
    )
    _, second = await client.post(
        "/api/pgn/imports",
        json={"pgn": text, "destination": {"kind": "new_course", "title": "Copy B"}},
    )
    assert first.status == second.status == 201
    assert first.json["import_receipt"]["course_id"] != second.json["import_receipt"]["course_id"]
    assert first.json["import_receipt"]["asset_id"] == second.json["import_receipt"]["asset_id"]
    counts = await table_counts(app)
    assert counts[:5] == (2, 1, 1, 1, 2)


async def test_opening_explorer_target_and_stale_target_roll_back_all_sql(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    text = (FIXTURE_DIR / "01_mainline.pgn").read_text()
    _, course_response = await client.post(
        "/api/courses",
        json={"title": "Explorer", "mode": "opening_explorer"},
    )
    course = course_response.json
    before = await table_counts(app)
    _, conflict = await client.post(
        "/api/pgn/imports",
        json={
            "pgn": text,
            "destination": {
                "kind": "existing_course",
                "course_id": course["id"],
                "expected_version": 1,
            },
        },
    )
    assert conflict.status == 409
    assert conflict.json["code"] == "course_mode_conflict"
    assert await table_counts(app) == before


async def test_concurrent_same_request_converges_to_one_receipt(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    lifecycle_app = cast(Any, app)
    text = (FIXTURE_DIR / "02_one_variation.pgn").read_text()

    # SanicASGITestClient starts and stops the whole app around every request,
    # which is deliberately unsuitable for concurrent calls on one client.
    # Keep one application lifespan around the four ASGI transport requests so
    # this exercises endpoint concurrency rather than racing test lifecycles.
    lifecycle_app.router.reset()
    lifecycle_app.signal_router.reset()
    await lifecycle_app._startup()
    await lifecycle_app._server_event("init", "before")
    await lifecycle_app._server_event("init", "after")
    try:
        responses = await asyncio.gather(
            *(
                httpx.AsyncClient.request(
                    client,
                    "POST",
                    "/api/pgn/imports",
                    json={"pgn": text},
                )
                for _ in range(4)
            )
        )
        assert sorted(response.status_code for response in responses) == [200, 200, 200, 201]
        assert len({response.json()["import_receipt"]["id"] for response in responses}) == 1
        assert (await table_counts(app))[0] == 1
    finally:
        await lifecycle_app._server_event("shutdown", "before")
        await lifecycle_app._server_event("shutdown", "after")


async def test_transport_shape_media_and_payload_limits_are_strict(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    text = (FIXTURE_DIR / "01_mainline.pgn").read_text()

    _, unknown_json = await client.post(
        "/api/pgn/imports",
        json={"pgn": text, "unknown": True},
    )
    _, unknown_part = await client.post(
        "/api/pgn/imports",
        files={"file": ("game.pgn", text.encode(), "application/x-chess-pgn")},
        data={"extra": "not allowed"},
    )
    _, unsupported = await client.post(
        "/api/pgn/imports",
        content=text.encode(),
        headers={"content-type": "application/octet-stream"},
    )
    _, too_large = await client.post(
        "/api/pgn/imports",
        content=b"x" * (5 * 1024 * 1024 + 1),
        headers={"content-type": "application/x-chess-pgn"},
    )

    assert unknown_json.status == 422
    assert unknown_part.status == 422
    assert unsupported.status == 415
    assert unsupported.json["code"] == "unsupported_media_type"
    assert too_large.status == 413
    assert too_large.json["code"] == "payload_too_large"
    assert await table_counts(app) == (0,) * 8


async def test_same_parent_same_uci_variations_keep_distinct_order_and_annotations(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    text = (
        '[Event "Duplicate source alternatives"]\n[Result "*"]\n\n'
        "1. e4 $1 {main copy} ( {alternative starts} 1. e4 $2 {author repeats it}) *"
    )
    receipt = (await client.post("/api/pgn/imports", json={"pgn": text}))[1].json["import_receipt"]
    root_id = UUID(receipt["games"][0]["root_occurrence_id"])
    async with app.ctx.database.session() as session:
        children = list(
            await session.scalars(
                select(CourseOccurrence)
                .where(CourseOccurrence.parent_id == root_id)
                .order_by(CourseOccurrence.sort_order)
            )
        )
        annotations = {
            row.occurrence_id: row
            for row in await session.scalars(
                select(PgnOccurrenceAnnotation).where(
                    PgnOccurrenceAnnotation.occurrence_id.in_([item.id for item in children])
                )
            )
        }
    assert len(children) == 2
    assert [child.sort_order for child in children] == [0, 1]
    assert children[0].inbound_move_edge_id == children[1].inbound_move_edge_id
    assert annotations[children[0].id].nags == [1]
    assert annotations[children[1].id].nags == [2]
    assert annotations[children[1].id].starting_comment == "alternative starts"
    assert annotations[children[0].id].comment == "main copy"
    assert annotations[children[1].id].comment == "author repeats it"


async def test_preparation_validation_and_missing_resources_use_stable_errors(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    text = (FIXTURE_DIR / "01_mainline.pgn").read_text()

    _, empty = await client.post(
        "/api/pgn/imports",
        content=b"",
        headers={"content-type": "application/x-chess-pgn"},
    )
    _, bad_utf8 = await client.post(
        "/api/pgn/imports",
        content=b"\xff\xfe",
        headers={"content-type": "application/x-chess-pgn"},
    )
    _, title_count = await client.post(
        "/api/pgn/imports",
        json={"pgn": text, "game_titles": ["one", "too many"]},
    )
    _, bad_key = await client.post(
        "/api/pgn/imports",
        json={"pgn": text},
        headers={"idempotency-key": "contains space"},
    )
    _, missing_receipt = await client.get(f"/api/pgn/imports/{uuid4()}")
    _, missing_download = await client.get(f"/api/pgn/imports/{uuid4()}/download")
    _, missing_target = await client.post(
        "/api/pgn/imports",
        json={
            "pgn": text,
            "destination": {
                "kind": "existing_course",
                "course_id": str(uuid4()),
                "expected_version": 1,
            },
        },
    )

    assert empty.status == 422 and empty.json["code"] == "invalid_pgn"
    assert bad_utf8.status == 422 and bad_utf8.json["details"]["reason"] == "invalid_utf8"
    assert title_count.status == 422
    assert bad_key.status == 422
    assert missing_receipt.status == missing_download.status == 404
    assert missing_target.status == 404
    assert await table_counts(app) == (0,) * 8


async def test_stale_existing_target_and_module_title_fallbacks(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, course_response = await client.post("/api/courses", json={"title": "Target"})
    course = course_response.json
    _, updated = await client.patch(
        f"/api/courses/{course['id']}",
        json={"expected_version": 1, "description": "changed"},
    )
    assert updated.json["version"] == 2
    _, stale = await client.post(
        "/api/pgn/imports",
        json={
            "pgn": (FIXTURE_DIR / "01_mainline.pgn").read_text(),
            "destination": {
                "kind": "existing_course",
                "course_id": course["id"],
                "expected_version": 1,
            },
        },
    )
    assert stale.status == 409 and stale.json["code"] == "stale_version"

    _, players = await client.post(
        "/api/pgn/imports",
        json={"pgn": '[White "Alice"]\n[Black "Bob"]\n[Result "*"]\n\n*'},
    )
    _, anonymous = await client.post(
        "/api/pgn/imports",
        json={"pgn": '[Result "*"]\n\n*'},
    )
    assert players.status == anonymous.status == 201
    async with app.ctx.database.session() as session:
        modules = list(
            await session.scalars(select(CourseModule).order_by(CourseModule.created_at))
        )
    assert [module.title for module in modules] == ["Alice vs Bob", "Game 1"]


async def test_multipart_options_and_download_query_errors(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    text = (FIXTURE_DIR / "01_mainline.pgn").read_text()

    _, missing_file = await client.post(
        "/api/pgn/imports",
        data={"options": "{}"},
    )
    _, invalid_options = await client.post(
        "/api/pgn/imports",
        files={"file": ("game.pgn", text.encode(), "application/x-chess-pgn")},
        data={"options": "not-json"},
    )
    _, configured = await client.post(
        "/api/pgn/imports",
        files={"file": ("game.pgn", text.encode(), "application/x-chess-pgn")},
        data={"options": '{"source_title":"Uploaded source"}'},
    )
    # A form without any file is encoded as application/x-www-form-urlencoded,
    # so it is rejected at the media-type boundary before multipart validation.
    assert missing_file.status == 415
    assert invalid_options.status == 422
    assert configured.status == 201

    receipt = configured.json["import_receipt"]
    course_url = f"/api/courses/{receipt['course_id']}/pgn"
    _, missing_module = await client.get(course_url)
    _, invalid_module = await client.get(f"{course_url}?module_id=not-a-uuid")
    _, unknown_module = await client.get(f"{course_url}?module_id={uuid4()}")
    module_id = receipt["games"][0]["module_id"]
    _, unknown_leaf = await client.get(
        f"{course_url}?module_id={module_id}&leaf_occurrence_id={uuid4()}"
    )
    assert missing_module.status == invalid_module.status == 422
    assert unknown_module.status == unknown_leaf.status == 404
