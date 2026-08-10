"""Adversarial HTTP tests for occurrence/module lifecycle invariants."""

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
            service_name=f"chess-workbench-occurrence-invariants-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'occurrence-invariants.db'}",
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def create_course_module_root(
    client: Any,
    *,
    title: str = "Course",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _, course_response = await client.post("/api/courses", json={"title": title})
    course = cast(dict[str, Any], course_response.json)
    _, module_response = await client.post(
        "/api/course-modules",
        json={
            "course_id": course["id"],
            "title": "Main",
            "start_fen": chess.STARTING_FEN,
        },
    )
    module = cast(dict[str, Any], module_response.json)
    _, root_response = await client.get(f"/api/occurrences/{module['start_occurrence_id']}")
    return course, module, cast(dict[str, Any], root_response.json)


async def create_child(client: Any, parent_id: str, uci: str = "e2e4") -> dict[str, Any]:
    _, response = await client.post(
        "/api/occurrences",
        json={"kind": "move", "parent_occurrence_id": parent_id, "uci": uci},
    )
    assert response.status == 201
    return cast(dict[str, Any], response.json)


async def test_occurrence_with_active_child_cannot_be_archived(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, _, root = await create_course_module_root(client)
    await create_child(client, root["id"])

    _, response = await client.patch(
        f"/api/occurrences/{root['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert response.status == 409
    assert response.json["code"] == "resource_referenced"


async def test_restore_cannot_create_two_active_module_roots(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    course, module, root = await create_course_module_root(client)
    _, original_blocks = await client.get(f"/api/course-modules/{module['id']}/content-blocks")
    original_block_id = original_blocks.json[0]["id"]

    _, archived = await client.patch(
        f"/api/occurrences/{root['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert archived.status == 200
    _, blocks_after_archive = await client.get(f"/api/course-modules/{module['id']}/content-blocks")
    assert blocks_after_archive.json == []
    _, replacement = await client.post(
        "/api/occurrences",
        json={
            "kind": "root",
            "course_id": course["id"],
            "module_id": module["id"],
            "fen": chess.STARTING_FEN,
        },
    )
    assert replacement.status == 201
    _, replacement_blocks = await client.get(f"/api/course-modules/{module['id']}/content-blocks")
    assert len(replacement_blocks.json) == 1
    assert replacement_blocks.json[0]["id"] == original_block_id
    assert replacement_blocks.json[0]["root_occurrence_id"] == replacement.json["id"]

    _, restored = await client.patch(
        f"/api/occurrences/{root['id']}",
        json={"expected_version": 2, "archived": False},
    )
    assert restored.status == 409
    assert restored.json["code"] == "ambiguous_context"


async def test_child_restore_requires_active_parent_and_module(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, module, root = await create_course_module_root(client)
    child = await create_child(client, root["id"])
    _, child_archived = await client.patch(
        f"/api/occurrences/{child['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert child_archived.status == 200
    _, root_archived = await client.patch(
        f"/api/occurrences/{root['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert root_archived.status == 200

    _, restore_with_archived_parent = await client.patch(
        f"/api/occurrences/{child['id']}",
        json={"expected_version": 2, "archived": False},
    )
    assert restore_with_archived_parent.status == 409
    assert restore_with_archived_parent.json["code"] == "resource_referenced"

    _, restore_root = await client.patch(
        f"/api/occurrences/{root['id']}",
        json={"expected_version": 2, "archived": False},
    )
    assert restore_root.status == 200
    _, archive_module = await client.patch(
        f"/api/course-modules/{module['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert archive_module.status == 200
    _, restore_with_archived_module = await client.patch(
        f"/api/occurrences/{child['id']}",
        json={"expected_version": 2, "archived": False},
    )
    assert restore_with_archived_module.status == 409
    assert restore_with_archived_module.json["code"] == "resource_referenced"


async def test_module_reparenting_and_occurrence_context_are_guarded(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    course, module, root = await create_course_module_root(client, title="Hierarchy")
    _, child_module_response = await client.post(
        "/api/course-modules",
        json={
            "course_id": course["id"],
            "parent_id": module["id"],
            "title": "Child",
        },
    )
    child_module = child_module_response.json
    other_course, other_module, _ = await create_course_module_root(client, title="Other")

    _, foreign_parent = await client.patch(
        f"/api/course-modules/{child_module['id']}",
        json={"expected_version": 1, "parent_id": other_module["id"]},
    )
    assert foreign_parent.status == 409
    _, cycle = await client.patch(
        f"/api/course-modules/{module['id']}",
        json={"expected_version": 1, "parent_id": child_module["id"]},
    )
    assert cycle.status == 409
    _, detached = await client.patch(
        f"/api/course-modules/{child_module['id']}",
        json={"expected_version": 1, "parent_id": None},
    )
    assert detached.status == 200 and detached.json["parent_id"] is None

    move = await create_child(client, root["id"])
    _, children = await client.get(
        f"/api/courses/{course['id']}/occurrences?module_id={module['id']}&parent_id={root['id']}"
    )
    assert [item["id"] for item in children.json] == [move["id"]]
    _, moved_between_modules = await client.patch(
        f"/api/occurrences/{move['id']}",
        json={"expected_version": 1, "module_id": child_module["id"]},
    )
    assert moved_between_modules.status == 409
    assert moved_between_modules.json["code"] == "resource_referenced"

    _, detached_root = await client.post(
        "/api/occurrences",
        json={
            "kind": "root",
            "course_id": other_course["id"],
            "fen": chess.STARTING_FEN,
        },
    )
    assert detached_root.status == 201
    assert detached_root.json["module_id"] is None


async def test_generic_patch_cannot_move_occurrence_between_modules(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    course, _, root = await create_course_module_root(client)
    child = await create_child(client, root["id"])
    _, other_module_response = await client.post(
        "/api/course-modules",
        json={"course_id": course["id"], "title": "Other"},
    )
    other_module = cast(dict[str, Any], other_module_response.json)

    _, response = await client.patch(
        f"/api/occurrences/{child['id']}",
        json={"expected_version": 1, "module_id": other_module["id"]},
    )
    assert response.status == 409
    assert response.json["code"] == "resource_referenced"
