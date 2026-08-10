"""HTTP acceptance tests for opening-explorer reference-card invariants."""

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
            service_name=f"chess-workbench-note-link-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'note-link.db'}",
            engine_worker_enabled=False,
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def create_course_root(
    client: Any,
    *,
    title: str,
    mode: str = "traditional",
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, course_response = await client.post(
        "/api/courses",
        json={"title": title, "mode": mode},
    )
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
    return course, cast(dict[str, Any], occurrence_response.json)


async def create_note(
    client: Any,
    occurrence_id: str,
    *,
    markdown: str = "Original source explanation.",
    review_status: str = "approved",
) -> dict[str, Any]:
    _, response = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": occurrence_id,
            "markdown": markdown,
            "review_status": review_status,
        },
    )
    assert response.status == 201
    return cast(dict[str, Any], response.json)


async def test_reference_card_is_a_live_contentless_link(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, traditional_root = await create_course_root(client, title="Book")
    _, explorer_root = await create_course_root(
        client,
        title="Explorer",
        mode="opening_explorer",
    )
    source_note = await create_note(client, traditional_root["id"])

    _, response = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": explorer_root["id"],
            "source_note_id": source_note["id"],
        },
    )

    assert response.status == 201
    reference = cast(dict[str, Any], response.json)
    assert reference["source_note_id"] == source_note["id"]
    assert reference["markdown"] is None
    assert reference["source_span_ids"] == []

    _, duplicate = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": explorer_root["id"],
            "source_note_id": source_note["id"],
        },
    )
    assert duplicate.status == 409
    assert duplicate.json["code"] == "ambiguous_context"


async def test_reference_card_rejects_copied_or_independent_content(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, traditional_root = await create_course_root(client, title="Book")
    _, explorer_root = await create_course_root(
        client,
        title="Explorer",
        mode="opening_explorer",
    )
    source_note = await create_note(client, traditional_root["id"])

    _, copied = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": explorer_root["id"],
            "source_note_id": source_note["id"],
            "markdown": "Stale copied content",
        },
    )
    _, cited = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": explorer_root["id"],
            "source_note_id": source_note["id"],
            "source_span_ids": [str(uuid4())],
        },
    )
    assert copied.status == 422
    assert cited.status == 422

    _, created = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": explorer_root["id"],
            "source_note_id": source_note["id"],
        },
    )
    reference = cast(dict[str, Any], created.json)
    _, edit_markdown = await client.patch(
        f"/api/knowledge-notes/{reference['id']}",
        json={"expected_version": 1, "markdown": "Detached copy"},
    )
    _, edit_citations = await client.patch(
        f"/api/knowledge-notes/{reference['id']}",
        json={"expected_version": 1, "source_span_ids": []},
    )
    assert edit_markdown.status == 409
    assert edit_citations.status == 409


async def test_reference_card_requires_direct_approved_traditional_source(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, traditional_root = await create_course_root(client, title="Book")
    _, other_traditional_root = await create_course_root(client, title="Other book")
    _, explorer_root = await create_course_root(
        client,
        title="Explorer",
        mode="opening_explorer",
    )
    _, second_explorer_root = await create_course_root(
        client,
        title="Other explorer",
        mode="opening_explorer",
    )
    approved = await create_note(client, traditional_root["id"])
    draft = await create_note(
        client,
        traditional_root["id"],
        markdown="Draft",
        review_status="draft",
    )

    _, wrong_target = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": other_traditional_root["id"],
            "source_note_id": approved["id"],
        },
    )
    _, draft_source = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": explorer_root["id"],
            "source_note_id": draft["id"],
        },
    )
    assert wrong_target.status == 409
    assert draft_source.status == 409

    _, first_link_response = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": explorer_root["id"],
            "source_note_id": approved["id"],
        },
    )
    first_link = cast(dict[str, Any], first_link_response.json)
    _, chained = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": second_explorer_root["id"],
            "source_note_id": first_link["id"],
        },
    )
    assert chained.status == 409

    _, global_response = await client.post(
        "/api/knowledge-notes",
        json={
            "target": {
                "kind": "global_position",
                "position_id": traditional_root["position_id"],
            },
            "markdown": "Global fact",
        },
    )
    global_note = cast(dict[str, Any], global_response.json)
    _, global_source = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": second_explorer_root["id"],
            "source_note_id": global_note["id"],
        },
    )
    assert global_source.status == 409


async def test_active_reference_protects_source_note_lifecycle(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, traditional_root = await create_course_root(client, title="Book")
    _, explorer_root = await create_course_root(
        client,
        title="Explorer",
        mode="opening_explorer",
    )
    source_note = await create_note(client, traditional_root["id"])
    _, reference_response = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": explorer_root["id"],
            "source_note_id": source_note["id"],
        },
    )
    reference = cast(dict[str, Any], reference_response.json)

    _, reject = await client.patch(
        f"/api/knowledge-notes/{source_note['id']}",
        json={"expected_version": 1, "review_status": "rejected"},
    )
    _, archive = await client.patch(
        f"/api/knowledge-notes/{source_note['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert reject.status == 409
    assert reject.json["code"] == "resource_referenced"
    assert archive.status == 409

    _, archive_reference = await client.patch(
        f"/api/knowledge-notes/{reference['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert archive_reference.status == 200
    _, archive_source = await client.patch(
        f"/api/knowledge-notes/{source_note['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert archive_source.status == 200
