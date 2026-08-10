"""Stage 4C citation, history, and Explorer publication acceptance."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import chess
from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings
from chess_workbench.store.base import Base


def build_test_app(tmp_path: Path) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-stage4c-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'stage4c.db'}",
            source_storage_root=tmp_path / "data",
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def create_module(
    client: Any,
    title: str,
    *,
    mode: str = "traditional",
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, course_response = await client.post("/api/courses", json={"title": title, "mode": mode})
    course = cast(dict[str, Any], course_response.json)
    _, module_response = await client.post(
        "/api/course-modules",
        json={
            "course_id": course["id"],
            "title": "Main line",
            "start_fen": chess.STARTING_FEN,
        },
    )
    assert course_response.status == module_response.status == 201
    return course, cast(dict[str, Any], module_response.json)


async def create_move(
    client: Any,
    parent_id: str,
    uci: str,
    sort_order: int,
) -> dict[str, Any]:
    _, response = await client.post(
        "/api/occurrences",
        json={
            "kind": "move",
            "parent_occurrence_id": parent_id,
            "uci": uci,
            "sort_order": sort_order,
        },
    )
    assert response.status == 201
    return cast(dict[str, Any], response.json)


async def create_note(
    client: Any,
    occurrence_id: str,
    markdown: str,
    *,
    review_status: str = "approved",
    source_span_ids: list[str] | None = None,
) -> dict[str, Any]:
    _, response = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": occurrence_id,
            "markdown": markdown,
            "review_status": review_status,
            "source_span_ids": source_span_ids or [],
        },
    )
    assert response.status == 201
    return cast(dict[str, Any], response.json)


async def test_citable_source_and_pre_edit_history_are_real_and_reloadable(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    _, citable_response = await client.post(
        "/api/citable-sources",
        json={
            "kind": "web",
            "title": "Human opening note",
            "external_url": "https://example.test/opening",
            "quote": "Prefer active development.",
        },
    )
    assert citable_response.status == 201
    citable = cast(dict[str, Any], citable_response.json)
    assert citable["source_version"]["source_id"] == citable["source"]["id"]
    assert citable["source_span"]["source_version_id"] == citable["source_version"]["id"]
    assert citable["source_span"]["locator"] == {"kind": "whole"}

    _, listed = await client.get("/api/citable-sources")
    assert listed.status == 200
    assert [item["source"]["title"] for item in listed.json] == ["Human opening note"]

    _, module = await create_module(client, "History course")
    note = await create_note(
        client,
        module["start_occurrence_id"],
        "Original **Markdown**",
        source_span_ids=[citable["source_span"]["id"]],
    )
    _, updated = await client.patch(
        f"/api/knowledge-notes/{note['id']}",
        json={"expected_version": 1, "markdown": "Revised Markdown"},
    )
    assert updated.status == 200 and updated.json["version"] == 2
    _, stale = await client.patch(
        f"/api/knowledge-notes/{note['id']}",
        json={"expected_version": 1, "markdown": "Lost write"},
    )
    assert stale.status == 409 and stale.json["code"] == "stale_version"

    _, history = await client.get(f"/api/history/knowledge_note/{note['id']}")
    assert history.status == 200
    assert history.json["current_version"] == 2
    assert len(history.json["revisions"]) == 1
    snapshot = history.json["revisions"][0]["snapshot"]
    assert snapshot["markdown"] == "Original **Markdown**"
    assert snapshot["source_span_ids"] == [citable["source_span"]["id"]]

    _, renamed = await client.patch(
        f"/api/course-modules/{module['id']}",
        json={"expected_version": 1, "title": "Renamed"},
    )
    assert renamed.status == 200
    _, module_history = await client.get(f"/api/history/course_module/{module['id']}")
    assert module_history.json["revisions"][0]["snapshot"]["title"] == "Main line"
    blocks = (await client.get(f"/api/course-modules/{module['id']}/content-blocks"))[1].json
    _, block_history = await client.get(f"/api/history/course_content_block/{blocks[0]['id']}")
    _, occurrence_history = await client.get(
        f"/api/history/course_occurrence/{module['start_occurrence_id']}"
    )
    assert block_history.status == occurrence_history.status == 200
    assert block_history.json["current_version"] == 1
    assert occurrence_history.json["current_version"] == 1

    _, unsupported = await client.get(f"/api/history/course/{module['id']}")
    assert unsupported.status == 422
    assert unsupported.json["code"] == "validation_error"


async def test_publish_modules_is_atomic_idempotent_and_keeps_live_note_links(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, source_module = await create_module(client, "Source book")
    root_id = source_module["start_occurrence_id"]
    e4 = await create_move(client, root_id, "e2e4", 0)
    await create_move(client, root_id, "d2d4", 1)
    root_note = await create_note(client, root_id, "Choose a central pawn.")
    e4_note = await create_note(client, e4["id"], "The open-game branch.")
    _, second_source_module = await create_module(client, "Second source")
    second_e4 = await create_move(
        client,
        second_source_module["start_occurrence_id"],
        "e2e4",
        0,
    )
    await create_move(client, second_e4["id"], "c7c5", 0)
    second_e4_note = await create_note(
        client,
        second_e4["id"],
        "The Sicilian source opinion.",
    )
    explorer, _ = await create_module(
        client,
        "My Explorer",
        mode="opening_explorer",
    )
    initial_modules = (await client.get(f"/api/courses/{explorer['id']}/modules"))[1].json

    _, published = await client.post(
        f"/api/courses/{explorer['id']}/publish-modules",
        json={"module_ids": [source_module["id"], second_source_module["id"]]},
    )
    assert published.status == 200
    receipts = published.json["publications"]
    assert [item["replayed"] for item in receipts] == [False, False]
    assert [item["occurrence_count"] for item in receipts] == [3, 3]
    assert [item["note_count"] for item in receipts] == [2, 1]
    assert receipts[0]["target_module_id"] == receipts[1]["target_module_id"]
    receipt = receipts[0]

    _, replay = await client.post(
        f"/api/courses/{explorer['id']}/publish-modules",
        json={"module_ids": [source_module["id"], second_source_module["id"]]},
    )
    assert replay.status == 200
    assert replay.json["publications"] == [{**item, "replayed": True} for item in receipts]

    _, modules_response = await client.get(f"/api/courses/{explorer['id']}/modules")
    modules = cast(list[dict[str, Any]], modules_response.json)
    assert modules == initial_modules
    target_module = next(item for item in modules if item["id"] == receipt["target_module_id"])
    _, editor = await client.get(f"/api/courses/{explorer['id']}/editor/{target_module['id']}")
    assert editor.status == 200
    assert len(editor.json["occurrences"]) == 4
    target_root = next(item for item in editor.json["occurrences"] if item["parent_id"] is None)
    target_e4 = next(item for item in editor.json["occurrences"] if item["inbound_uci"] == "e2e4")
    assert [
        item["inbound_uci"]
        for item in editor.json["occurrences"]
        if item["parent_id"] == target_root["id"]
    ] == ["e2e4", "d2d4"]
    assert [
        item["inbound_uci"]
        for item in editor.json["occurrences"]
        if item["parent_id"] == target_e4["id"]
    ] == ["c7c5"]
    root_cards = (await client.get(f"/api/knowledge-notes?occurrence_id={target_root['id']}"))[
        1
    ].json
    e4_cards = (await client.get(f"/api/knowledge-notes?occurrence_id={target_e4['id']}"))[1].json
    assert [item["source_note_id"] for item in root_cards] == [root_note["id"]]
    assert [item["source_note_id"] for item in e4_cards] == [
        e4_note["id"],
        second_e4_note["id"],
    ]
    assert root_cards[0]["markdown"] is None


async def test_publication_into_an_empty_explorer_creates_one_generic_component(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, first_source = await create_module(client, "Named source chapter A")
    _, second_source = await create_module(client, "Named source chapter B")
    await create_move(client, first_source["start_occurrence_id"], "e2e4", 0)
    await create_move(client, second_source["start_occurrence_id"], "d2d4", 0)
    _, explorer_response = await client.post(
        "/api/courses",
        json={"title": "Empty Explorer", "mode": "opening_explorer"},
    )
    explorer = cast(dict[str, Any], explorer_response.json)

    _, published = await client.post(
        f"/api/courses/{explorer['id']}/publish-modules",
        json={"module_ids": [first_source["id"], second_source["id"]]},
    )

    assert published.status == 200
    receipts = cast(list[dict[str, Any]], published.json["publications"])
    assert receipts[0]["target_module_id"] == receipts[1]["target_module_id"]
    modules = (await client.get(f"/api/courses/{explorer['id']}/modules"))[1].json
    assert [(item["id"], item["title"]) for item in modules] == [
        (receipts[0]["target_module_id"], "合并探索图")
    ]
    editor = (
        await client.get(f"/api/courses/{explorer['id']}/editor/{receipts[0]['target_module_id']}")
    )[1].json
    assert sorted(
        item["inbound_uci"] for item in editor["occurrences"] if item["inbound_uci"] is not None
    ) == ["d2d4", "e2e4"]


async def test_invalid_batch_publication_writes_nothing(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, valid_module = await create_module(client, "Valid source")
    _, invalid_module = await create_module(client, "Draft source")
    await create_note(client, valid_module["start_occurrence_id"], "Approved")
    await create_note(
        client,
        invalid_module["start_occurrence_id"],
        "Not approved",
        review_status="draft",
    )
    _, explorer_module = await create_module(
        client,
        "Empty explorer",
        mode="opening_explorer",
    )
    _, explorer_course_response = await client.get(f"/api/course-modules/{explorer_module['id']}")
    explorer_course_id = explorer_course_response.json["course_id"]
    before = (await client.get(f"/api/courses/{explorer_course_id}/modules"))[1].json

    _, rejected = await client.post(
        f"/api/courses/{explorer_course_id}/publish-modules",
        json={"module_ids": [valid_module["id"], invalid_module["id"]]},
    )
    assert rejected.status == 409
    after = (await client.get(f"/api/courses/{explorer_course_id}/modules"))[1].json
    assert after == before

    _, wrong_target = await client.post(
        f"/api/courses/{explorer_course_response.json['course_id']}/publish-modules",
        json={"module_ids": [explorer_module["id"]]},
    )
    assert wrong_target.status == 409

    _, traditional_target_response = await client.get(f"/api/course-modules/{valid_module['id']}")
    _, traditional_target = await client.post(
        f"/api/courses/{traditional_target_response.json['course_id']}/publish-modules",
        json={"module_ids": [valid_module["id"]]},
    )
    assert traditional_target.status == 409
    assert traditional_target.json["code"] == "course_mode_conflict"

    _, rootless_module = await client.post(
        "/api/course-modules",
        json={
            "course_id": traditional_target_response.json["course_id"],
            "title": "Rootless draft",
        },
    )
    _, rootless_publish = await client.post(
        f"/api/courses/{explorer_course_id}/publish-modules",
        json={"module_ids": [rootless_module.json["id"]]},
    )
    assert rootless_publish.status == 409
    assert rootless_publish.json["code"] == "ambiguous_context"
