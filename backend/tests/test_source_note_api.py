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
            service_name=f"chess-workbench-source-note-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'source-note-api.db'}",
            engine_worker_enabled=False,
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def create_source_stack(client: Any) -> tuple[dict[str, Any], ...]:
    _, source_response = await client.post(
        "/api/sources",
        json={
            "kind": "book",
            "title": "Practical Chess",
            "author": "A. Author",
            "external_url": "https://example.test/book",
        },
    )
    assert source_response.status == 201
    source = cast(dict[str, Any], source_response.json)

    _, version_response = await client.post(
        "/api/source-versions",
        json={
            "source_id": source["id"],
            "label": "First edition",
            "published_on": "2026-08-09",
            "metadata": {"language": "en"},
        },
    )
    assert version_response.status == 201
    version = cast(dict[str, Any], version_response.json)

    _, file_response = await client.post(
        "/api/source-files",
        json={
            "source_version_id": version["id"],
            "filename": "book.pdf",
            "relative_path": "sources/aa/book.pdf",
            "media_type": "application/pdf",
            "size_bytes": 1024,
            "sha256": "a" * 64,
        },
    )
    assert file_response.status == 201
    source_file = cast(dict[str, Any], file_response.json)

    _, span_response = await client.post(
        "/api/source-spans",
        json={
            "source_version_id": version["id"],
            "source_file_id": source_file["id"],
            "locator": {
                "kind": "page",
                "page_number": 42,
                "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.8, "y1": 0.7},
            },
            "quote": "A useful explanation",
            "confidence": 0.95,
        },
    )
    assert span_response.status == 201
    span = cast(dict[str, Any], span_response.json)
    return source, version, source_file, span


async def create_occurrence(client: Any) -> dict[str, Any]:
    _, course_response = await client.post("/api/courses", json={"title": "Notes"})
    assert course_response.status == 201
    course = cast(dict[str, Any], course_response.json)
    _, module_response = await client.post(
        "/api/course-modules",
        json={
            "course_id": course["id"],
            "title": "Main",
            "start_fen": chess.STARTING_FEN,
        },
    )
    assert module_response.status == 201
    module = cast(dict[str, Any], module_response.json)
    _, occurrence_response = await client.get(f"/api/occurrences/{module['start_occurrence_id']}")
    assert occurrence_response.status == 200
    return cast(dict[str, Any], occurrence_response.json)


async def test_source_resources_have_complete_http_lifecycle(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    source, version, source_file, span = await create_source_stack(client)

    _, sources = await client.get("/api/sources")
    _, versions = await client.get(f"/api/sources/{source['id']}/versions")
    _, files = await client.get(f"/api/source-versions/{version['id']}/files")
    _, spans = await client.get(f"/api/source-versions/{version['id']}/spans")
    assert [item["id"] for item in sources.json] == [source["id"]]
    assert [item["id"] for item in versions.json] == [version["id"]]
    assert [item["id"] for item in files.json] == [source_file["id"]]
    assert [item["id"] for item in spans.json] == [span["id"]]

    _, stale = await client.patch(
        f"/api/sources/{source['id']}",
        json={"expected_version": 99, "title": "Lost update"},
    )
    assert stale.status == 409
    assert stale.json["code"] == "stale_version"

    _, updated_source = await client.patch(
        f"/api/sources/{source['id']}",
        json={
            "expected_version": source["version"],
            "description": "Updated",
            "external_url": None,
        },
    )
    _, updated_version = await client.patch(
        f"/api/source-versions/{version['id']}",
        json={
            "expected_version": version["version"],
            "edition": "Second",
            "external_url": "https://example.test/edition-2",
            "metadata": {"language": "en", "revised": True},
        },
    )
    _, updated_span = await client.patch(
        f"/api/source-spans/{span['id']}",
        json={"expected_version": span["version"], "quote": "Revised quote"},
    )
    assert updated_source.json["version"] == 2
    assert updated_source.json["description"] == "Updated"
    assert updated_source.json["external_url"] is None
    assert updated_version.json["edition"] == "Second"
    assert updated_version.json["metadata"]["revised"] is True
    assert updated_span.json["quote"] == "Revised quote"

    _, immutable_rejected = await client.patch(
        f"/api/source-files/{source_file['id']}",
        json={"expected_version": source_file["version"], "filename": "changed.pdf"},
    )
    assert immutable_rejected.status == 422
    assert immutable_rejected.json["code"] == "validation_error"

    _, archived_file = await client.patch(
        f"/api/source-files/{source_file['id']}",
        json={"expected_version": source_file["version"], "archived": True},
    )
    assert archived_file.status == 200
    _, hidden = await client.get(f"/api/source-files/{source_file['id']}")
    _, visible = await client.get(f"/api/source-files/{source_file['id']}?include_archived=true")
    assert hidden.status == 404
    assert visible.status == 200


async def test_source_span_coordinates_require_a_file_from_the_same_version(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    source, version, source_file, _ = await create_source_stack(client)

    _, missing_file = await client.post(
        "/api/source-spans",
        json={
            "source_version_id": version["id"],
            "locator": {"kind": "page", "page_number": 1},
        },
    )
    assert missing_file.status == 422
    assert missing_file.json["code"] == "validation_error"

    _, whole_version = await client.post(
        "/api/source-spans",
        json={
            "source_version_id": version["id"],
            "locator": {"kind": "whole"},
        },
    )
    assert whole_version.status == 201

    created_coordinate_spans: list[dict[str, Any]] = []
    for locator in (
        {"kind": "video", "start_ms": 1000, "end_ms": 2500},
        {"kind": "text", "start_offset": 7, "end_offset": 19},
    ):
        _, response = await client.post(
            "/api/source-spans",
            json={
                "source_version_id": version["id"],
                "source_file_id": source_file["id"],
                "locator": locator,
            },
        )
        assert response.status == 201
        created_coordinate_spans.append(cast(dict[str, Any], response.json))
    assert [span["locator"]["kind"] for span in created_coordinate_spans] == [
        "video",
        "text",
    ]

    _, updated_locator = await client.patch(
        f"/api/source-spans/{created_coordinate_spans[0]['id']}",
        json={
            "expected_version": 1,
            "locator": {"kind": "text", "start_offset": 20, "end_offset": 30},
        },
    )
    assert updated_locator.status == 200
    assert updated_locator.json["locator"] == {
        "kind": "text",
        "start_offset": 20,
        "end_offset": 30,
    }

    _, second_version_response = await client.post(
        "/api/source-versions",
        json={"source_id": source["id"], "label": "Other edition"},
    )
    second_version = cast(dict[str, Any], second_version_response.json)
    _, wrong_parent = await client.post(
        "/api/source-spans",
        json={
            "source_version_id": second_version["id"],
            "source_file_id": source_file["id"],
            "locator": {"kind": "page", "page_number": 1},
        },
    )
    assert wrong_parent.status == 409
    assert wrong_parent.json["code"] == "ambiguous_context"

    _, invalid_query = await client.get("/api/sources?include_archived=perhaps")
    assert invalid_query.status == 422
    assert invalid_query.json["code"] == "validation_error"


async def test_knowledge_note_http_targets_citations_and_archive(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, _, _, span = await create_source_stack(client)
    occurrence = await create_occurrence(client)

    _, local_response = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": occurrence["id"],
            "markdown": "A local explanation",
            "source_span_ids": [span["id"]],
        },
    )
    assert local_response.status == 201
    local_note = cast(dict[str, Any], local_response.json)
    assert local_note["target"] == {"kind": "occurrence", "occurrence_id": occurrence["id"]}
    assert local_note["source_span_ids"] == [span["id"]]

    _, global_response = await client.post(
        "/api/knowledge-notes",
        json={
            "target": {
                "kind": "global_position",
                "position_id": occurrence["position_id"],
            },
            "markdown": "A global position explanation",
        },
    )
    assert global_response.status == 201
    global_note = cast(dict[str, Any], global_response.json)

    _, move_response = await client.post(
        "/api/occurrences",
        json={
            "kind": "move",
            "parent_occurrence_id": occurrence["id"],
            "uci": "e2e4",
        },
    )
    assert move_response.status == 201
    move_edge_id = move_response.json["inbound_move_edge_id"]
    _, global_move_response = await client.post(
        "/api/knowledge-notes",
        json={
            "target": {"kind": "global_move", "move_edge_id": move_edge_id},
            "markdown": "A global move explanation",
        },
    )
    assert global_move_response.status == 201
    global_move_note = cast(dict[str, Any], global_move_response.json)

    _, local_list = await client.get(f"/api/knowledge-notes?occurrence_id={occurrence['id']}")
    _, global_list = await client.get(
        f"/api/knowledge-notes?position_id={occurrence['position_id']}"
    )
    _, global_move_list = await client.get(f"/api/knowledge-notes?move_edge_id={move_edge_id}")
    assert [item["id"] for item in local_list.json] == [local_note["id"]]
    assert [item["id"] for item in global_list.json] == [global_note["id"]]
    assert [item["id"] for item in global_move_list.json] == [global_move_note["id"]]

    _, ambiguous = await client.get(
        "/api/knowledge-notes"
        f"?occurrence_id={occurrence['id']}&position_id={occurrence['position_id']}"
    )
    assert ambiguous.status == 409
    assert ambiguous.json["code"] == "ambiguous_context"

    _, updated = await client.patch(
        f"/api/knowledge-notes/{local_note['id']}",
        json={
            "expected_version": local_note["version"],
            "markdown": "Revised",
            "source_span_ids": [],
        },
    )
    assert updated.status == 200
    assert updated.json["version"] == 2
    assert updated.json["source_span_ids"] == []

    _, archived = await client.patch(
        f"/api/knowledge-notes/{local_note['id']}",
        json={"expected_version": 2, "archived": True},
    )
    assert archived.status == 200
    _, hidden = await client.get(f"/api/knowledge-notes/{local_note['id']}")
    _, visible = await client.get(f"/api/knowledge-notes/{local_note['id']}?include_archived=true")
    assert hidden.status == 404
    assert visible.status == 200


async def test_note_validation_failure_is_zero_write_and_openapi_is_complete(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    occurrence = await create_occurrence(client)

    _, invalid = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": occurrence["id"],
            "markdown": "Must roll back",
            "source_span_ids": [str(uuid4())],
        },
    )
    assert invalid.status == 404
    assert invalid.json["code"] == "not_found"
    _, notes = await client.get("/api/knowledge-notes")
    assert notes.json == []

    _, unknown_field = await client.post(
        "/api/sources",
        json={"kind": "book", "title": "Bad", "titel": "typo"},
    )
    assert unknown_field.status == 422
    assert unknown_field.json["code"] == "validation_error"

    _, openapi_response = await client.get("/docs/openapi.json")
    assert openapi_response.status == 200
    paths = openapi_response.json["paths"]
    expected_paths = {
        "/api/sources",
        "/api/sources/{source_id}",
        "/api/sources/{source_id}/versions",
        "/api/source-versions",
        "/api/source-versions/{version_id}",
        "/api/source-versions/{version_id}/files",
        "/api/source-versions/{version_id}/spans",
        "/api/source-files",
        "/api/source-files/{file_id}",
        "/api/source-spans",
        "/api/source-spans/{span_id}",
        "/api/knowledge-notes",
        "/api/knowledge-notes/{note_id}",
    }
    assert expected_paths <= paths.keys()
