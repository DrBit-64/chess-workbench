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
            service_name=f"course-learning-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'course-learning.db'}",
            engine_worker_enabled=False,
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def create_course_module(
    client: Any,
    title: str,
    *,
    mode: str = "traditional",
    parent_id: str | None = None,
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
            **({"parent_id": parent_id} if parent_id else {}),
        },
    )
    assert module_response.status == 201
    return course, cast(dict[str, Any], module_response.json)


async def create_move(client: Any, parent_id: str, uci: str, order: int) -> dict[str, Any]:
    _, response = await client.post(
        "/api/occurrences",
        json={
            "kind": "move",
            "parent_occurrence_id": parent_id,
            "uci": uci,
            "sort_order": order,
        },
    )
    assert response.status == 201
    return cast(dict[str, Any], response.json)


async def command(client: Any, occurrence: dict[str, Any], kind: str, **payload: object) -> Any:
    return (
        await client.post(
            f"/api/occurrences/{occurrence['id']}/commands",
            json={"kind": kind, "expected_version": occurrence["version"], **payload},
        )
    )[1]


async def test_course_score_commands_reorder_annotate_and_delete(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    course, module = await create_course_module(client, "Book")
    root_id = module["start_occurrence_id"]
    e4 = await create_move(client, root_id, "e2e4", 0)
    d4 = await create_move(client, root_id, "d2d4", 1)
    await create_move(client, e4["id"], "e7e5", 0)
    c5 = await create_move(client, e4["id"], "c7c5", 1)

    promoted = await command(client, d4, "promote_variation")
    assert promoted.status == 200
    _, editor_response = await client.get(f"/api/courses/{course['id']}/editor/{module['id']}")
    occurrences = editor_response.json["occurrences"]
    e4 = next(item for item in occurrences if item["id"] == e4["id"])
    c5 = next(item for item in occurrences if item["id"] == c5["id"])
    assert next(item for item in occurrences if item["id"] == d4["id"])["sort_order"] == 0

    mainlined = await command(client, c5, "make_mainline")
    assert mainlined.status == 200
    _, editor_response = await client.get(f"/api/courses/{course['id']}/editor/{module['id']}")
    occurrences = editor_response.json["occurrences"]
    e4 = next(item for item in occurrences if item["id"] == e4["id"])
    c5 = next(item for item in occurrences if item["id"] == c5["id"])
    assert (e4["sort_order"], c5["sort_order"]) == (0, 0)

    annotated = await command(client, c5, "set_nag", nag=3)
    assert annotated.status == 200
    _, c5_response = await client.get(f"/api/occurrences/{c5['id']}")
    c5 = cast(dict[str, Any], c5_response.json)
    assert c5["nag"] == 3

    deleted = await command(client, e4, "delete_subtree")
    assert deleted.status == 200
    assert deleted.json["selected_occurrence_id"] == root_id
    _, editor_response = await client.get(f"/api/courses/{course['id']}/editor/{module['id']}")
    remaining = editor_response.json["occurrences"]
    assert [item["inbound_uci"] for item in remaining] == [None, "d2d4"]
    assert remaining[1]["sort_order"] == 0


async def test_readding_moves_reuses_archived_match_and_frees_archived_order(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    course, module = await create_course_module(client, "Book")
    root_id = module["start_occurrence_id"]

    archived_e4 = await create_move(client, root_id, "e2e4", 0)
    deleted = await command(client, archived_e4, "delete_subtree")
    assert deleted.status == 200

    await create_move(client, root_id, "d2d4", 0)
    await create_move(client, root_id, "c2c4", 1)
    restored_e4 = await create_move(client, root_id, "e2e4", 2)

    assert restored_e4["id"] == archived_e4["id"]
    assert restored_e4["archived_at"] is None
    _, editor_response = await client.get(f"/api/courses/{course['id']}/editor/{module['id']}")
    active_moves = [
        (item["inbound_uci"], item["sort_order"])
        for item in editor_response.json["occurrences"]
        if item["parent_id"] == root_id
    ]
    assert active_moves == [("d2d4", 0), ("c2c4", 1), ("e2e4", 2)]


async def test_module_tree_archive_invalidates_explorer_reference(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, source_module = await create_course_module(client, "Source")
    _, child_module_response = await client.post(
        "/api/course-modules",
        json={
            "course_id": source_module["course_id"],
            "parent_id": source_module["id"],
            "title": "Game 1",
        },
    )
    assert child_module_response.status == 201
    _, explorer_module = await create_course_module(client, "Explorer", mode="opening_explorer")
    _, source_note_response = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": source_module["start_occurrence_id"],
            "markdown": "Source explanation",
            "review_status": "approved",
        },
    )
    source_note = source_note_response.json
    _, reference_response = await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": explorer_module["start_occurrence_id"],
            "source_note_id": source_note["id"],
        },
    )
    assert reference_response.status == 201

    _, archived = await client.post(
        f"/api/course-modules/{source_module['id']}/archive-tree",
        json={"expected_version": source_module["version"]},
    )
    assert archived.status == 200
    assert archived.json["archived_module_count"] == 2
    assert archived.json["invalidated_reference_count"] == 1
    _, source_modules = await client.get(f"/api/courses/{source_module['course_id']}/modules")
    assert source_modules.json == []
    _, explorer_editor = await client.get(
        f"/api/courses/{explorer_module['course_id']}/editor/{explorer_module['id']}"
    )
    assert explorer_editor.status == 200
    assert explorer_editor.json["notes"] == []
