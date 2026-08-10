"""ADR 0006 explicit mixed-content block acceptance tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import chess
from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings
from chess_workbench.store.base import Base


def build_test_app(tmp_path: Path) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-blocks-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'blocks.db'}",
            source_storage_root=tmp_path / "data",
            engine_worker_enabled=False,
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def create_module(client: Any, title: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _, course_response = await client.post("/api/courses", json={"title": title})
    course = cast(dict[str, Any], course_response.json)
    _, module_response = await client.post(
        "/api/course-modules",
        json={
            "course_id": course["id"],
            "title": "Chapter",
            "start_fen": chess.STARTING_FEN,
        },
    )
    assert course_response.status == module_response.status == 201
    return course, cast(dict[str, Any], module_response.json)


async def test_module_root_is_an_explicit_move_sequence_and_blocks_are_editable(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, module = await create_module(client, "Mixed chapter")

    _, initial = await client.get(f"/api/course-modules/{module['id']}/content-blocks")
    assert initial.status == 200
    assert initial.json == [
        {
            **initial.json[0],
            "kind": "move_sequence",
            "sort_order": 0,
            "root_occurrence_id": module["start_occurrence_id"],
            "heading": None,
            "markdown": None,
            "knowledge_note_id": None,
        }
    ]

    _, section = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": module["id"],
            "kind": "section_header",
            "sort_order": 1,
            "heading": "Strategic idea",
        },
    )
    _, narrative = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": module["id"],
            "kind": "narrative",
            "sort_order": 2,
            "markdown": "Control **the centre**.",
        },
    )
    assert section.status == narrative.status == 201

    _, edited = await client.patch(
        f"/api/course-content-blocks/{narrative.json['id']}",
        json={"expected_version": 1, "markdown": "Control **both** central squares."},
    )
    _, stale = await client.patch(
        f"/api/course-content-blocks/{narrative.json['id']}",
        json={"expected_version": 1, "markdown": "lost update"},
    )
    assert edited.status == 200 and edited.json["version"] == 2
    assert stale.status == 409 and stale.json["code"] == "stale_version"

    _, listed = await client.get(f"/api/course-modules/{module['id']}/content-blocks")
    assert [(item["kind"], item["sort_order"]) for item in listed.json] == [
        ("move_sequence", 0),
        ("section_header", 1),
        ("narrative", 2),
    ]
    assert listed.json[2]["markdown"] == "Control **both** central squares."


async def test_block_payload_order_and_cross_module_references_are_rejected(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, first = await create_module(client, "First")
    _, second = await create_module(client, "Second")

    _, invalid_shape = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": first["id"],
            "kind": "narrative",
            "sort_order": 1,
            "heading": "wrong field",
        },
    )
    _, duplicate_order = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": first["id"],
            "kind": "section_header",
            "sort_order": 0,
            "heading": "duplicate",
        },
    )
    _, cross_module = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": first["id"],
            "kind": "move_sequence",
            "sort_order": 1,
            "root_occurrence_id": second["start_occurrence_id"],
        },
    )
    assert invalid_shape.status == 422
    assert duplicate_order.status == cross_module.status == 409
    assert cross_module.json["code"] == "ambiguous_context"

    initial = (await client.get(f"/api/course-modules/{first['id']}/content-blocks"))[1]
    move_block = initial.json[0]
    _, protected = await client.patch(
        f"/api/course-content-blocks/{move_block['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert protected.status == 409 and protected.json["code"] == "resource_referenced"


async def test_delayed_root_is_appended_after_existing_narrative(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, course_response = await client.post("/api/courses", json={"title": "FEN later"})
    _, module_response = await client.post(
        "/api/course-modules",
        json={"course_id": course_response.json["id"], "title": "Setup later"},
    )
    module = module_response.json
    assert module["start_occurrence_id"] is None
    _, narrative = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": module["id"],
            "kind": "narrative",
            "sort_order": 0,
            "markdown": "Choose the starting position later.",
        },
    )
    assert narrative.status == 201

    _, root = await client.post(
        "/api/occurrences",
        json={
            "kind": "root",
            "course_id": course_response.json["id"],
            "module_id": module["id"],
            "fen": chess.STARTING_FEN,
        },
    )
    assert root.status == 201
    _, blocks = await client.get(f"/api/course-modules/{module['id']}/content-blocks")
    assert [(item["kind"], item["sort_order"]) for item in blocks.json] == [
        ("narrative", 0),
        ("move_sequence", 1),
    ]
    assert blocks.json[1]["root_occurrence_id"] == root.json["id"]


async def test_occurrence_note_can_be_embedded_only_in_its_own_module(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, first = await create_module(client, "Notes")
    _, second = await create_module(client, "Other")
    _, note = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": first["start_occurrence_id"],
            "markdown": "A local explanation",
        },
    )
    _, embedded = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": first["id"],
            "kind": "knowledge_note",
            "sort_order": 1,
            "knowledge_note_id": note.json["id"],
        },
    )
    _, foreign = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": second["id"],
            "kind": "knowledge_note",
            "sort_order": 1,
            "knowledge_note_id": note.json["id"],
        },
    )
    assert embedded.status == 201
    assert foreign.status == 409


async def test_narrative_citations_round_trip_update_and_enter_history(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, module = await create_module(client, "Cited prose")
    _, first_source = await client.post(
        "/api/citable-sources",
        json={"kind": "manual", "title": "Book A", "quote": "First passage"},
    )
    _, second_source = await client.post(
        "/api/citable-sources",
        json={"kind": "manual", "title": "Book B", "quote": "Second passage"},
    )
    first_span = first_source.json["source_span"]["id"]
    second_span = second_source.json["source_span"]["id"]

    _, created = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": module["id"],
            "kind": "narrative",
            "sort_order": 1,
            "markdown": "A source-backed paragraph.",
            "source_span_ids": [first_span],
        },
    )
    assert created.status == 201
    assert created.json["source_span_ids"] == [first_span]

    _, updated = await client.patch(
        f"/api/course-content-blocks/{created.json['id']}",
        json={"expected_version": 1, "source_span_ids": [second_span]},
    )
    assert updated.status == 200
    assert updated.json["version"] == 2
    assert updated.json["source_span_ids"] == [second_span]

    _, history = await client.get(f"/api/history/course_content_block/{created.json['id']}")
    assert history.status == 200
    assert history.json["revisions"][0]["snapshot"]["source_span_ids"] == [first_span]

    _, cleared = await client.patch(
        f"/api/course-content-blocks/{created.json['id']}",
        json={
            "expected_version": 2,
            "markdown": "Revised prose without a citation.",
            "source_span_ids": [],
        },
    )
    assert cleared.status == 200
    assert cleared.json["version"] == 3
    assert cleared.json["source_span_ids"] == []

    _, invalid_kind = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": module["id"],
            "kind": "section_header",
            "sort_order": 2,
            "heading": "Not citable",
            "source_span_ids": [second_span],
        },
    )
    _, valid_section = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": module["id"],
            "kind": "section_header",
            "sort_order": 2,
            "heading": "Valid heading",
        },
    )
    _, invalid_update = await client.patch(
        f"/api/course-content-blocks/{valid_section.json['id']}",
        json={"expected_version": 1, "source_span_ids": [second_span]},
    )
    _, missing_span = await client.post(
        "/api/course-content-blocks",
        json={
            "module_id": module["id"],
            "kind": "narrative",
            "sort_order": 2,
            "markdown": "Missing source",
            "source_span_ids": [str(uuid4())],
        },
    )
    assert invalid_kind.status == 422
    assert valid_section.status == 201
    assert invalid_update.status == 409
    assert invalid_update.json["message"] == "only narrative blocks may cite source spans"
    assert missing_span.status == 404


async def test_position_note_and_reading_block_are_created_atomically(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, first = await create_module(client, "Atomic note")
    _, second = await create_module(client, "Foreign target")

    _, created = await client.post(
        f"/api/course-modules/{first['id']}/knowledge-note-blocks",
        json={
            "occurrence_id": first["start_occurrence_id"],
            "markdown": "This belongs in the reading flow.",
        },
    )
    assert created.status == 201
    assert created.json["note"]["markdown"] == "This belongs in the reading flow."
    assert created.json["block"]["knowledge_note_id"] == created.json["note"]["id"]
    assert created.json["block"]["sort_order"] == 1

    _, blocks = await client.get(f"/api/course-modules/{first['id']}/content-blocks")
    assert [item["kind"] for item in blocks.json] == ["move_sequence", "knowledge_note"]

    _, rejected = await client.post(
        f"/api/course-modules/{first['id']}/knowledge-note-blocks",
        json={
            "occurrence_id": second["start_occurrence_id"],
            "markdown": "Must roll back.",
        },
    )
    assert rejected.status == 409
    _, foreign_notes = await client.get(
        f"/api/knowledge-notes?occurrence_id={second['start_occurrence_id']}"
    )
    assert foreign_notes.status == 200
    assert foreign_notes.json == []


async def test_pgn_import_creates_one_move_sequence_block_per_game(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    fixture = Path(__file__).parent / "fixtures" / "pgn"
    text = (
        (fixture / "01_mainline.pgn").read_text()
        + "\n"
        + (fixture / "07_unicode_comment.pgn").read_text()
    )
    _, response = await client.post("/api/pgn/imports", json={"pgn": text})
    assert response.status == 201
    receipt = response.json["import_receipt"]
    for game in receipt["games"]:
        _, blocks = await client.get(f"/api/course-modules/{game['module_id']}/content-blocks")
        assert len(blocks.json) == 1
        assert blocks.json[0]["kind"] == "move_sequence"
        assert blocks.json[0]["root_occurrence_id"] == game["root_occurrence_id"]


async def test_editor_state_exposes_ordered_move_labels_paths_and_transposition(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    course, module = await create_module(client, "Transposition editor")
    root_id = module["start_occurrence_id"]

    async def play(parent_id: str, uci: str, sort_order: int = 0) -> dict[str, Any]:
        _, response = await client.post(
            "/api/occurrences",
            json={
                "kind": "move",
                "parent_occurrence_id": parent_id,
                "uci": uci,
                "sort_order": sort_order,
            },
        )
        assert response.status == 201, response.json
        return cast(dict[str, Any], response.json)

    knight = await play(root_id, "g1f3", 0)
    knight_reply = await play(knight["id"], "g8f6")
    knight_target = await play(knight_reply["id"], "g2g3")
    pawn = await play(root_id, "g2g3", 1)
    pawn_reply = await play(pawn["id"], "g8f6")
    pawn_target = await play(pawn_reply["id"], "g1f3")

    _, editor = await client.get(f"/api/courses/{course['id']}/editor/{module['id']}")
    assert editor.status == 200
    by_id = {item["id"]: item for item in editor.json["occurrences"]}
    assert by_id[root_id]["inbound_uci"] is None
    assert by_id[knight["id"]]["inbound_uci"] == "g1f3"
    assert by_id[knight["id"]]["inbound_san"] == "Nf3"
    assert by_id[pawn["id"]]["sort_order"] == 1
    assert knight_target["position_id"] == pawn_target["position_id"]
    assert knight_target["id"] != pawn_target["id"]
