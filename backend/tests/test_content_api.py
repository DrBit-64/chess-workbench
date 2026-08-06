from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import chess
from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings
from chess_workbench.store.base import Base
from chess_workbench.store.models import CourseOccurrence, MoveEdge, Position
from sqlalchemy import func, select


def build_test_app(tmp_path: Path) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-content-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'content-api.db'}",
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def create_course_with_root(
    client: Any,
    *,
    title: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _, course_response = await client.post("/api/courses", json={"title": title})
    assert course_response.status == 201
    course = cast(dict[str, Any], course_response.json)

    _, module_response = await client.post(
        "/api/course-modules",
        json={
            "course_id": course["id"],
            "title": "Main line",
            "start_fen": chess.STARTING_FEN,
        },
    )
    assert module_response.status == 201
    module = cast(dict[str, Any], module_response.json)
    assert module["start_occurrence_id"] is not None

    _, root_response = await client.get(f"/api/occurrences/{module['start_occurrence_id']}")
    assert root_response.status == 200
    return course, module, cast(dict[str, Any], root_response.json)


async def test_two_courses_share_graph_facts_but_keep_occurrence_context(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    course_a, _, root_a = await create_course_with_root(client, title="Course A")
    course_b, _, root_b = await create_course_with_root(client, title="Course B")

    _, move_a_response = await client.post(
        "/api/occurrences",
        json={
            "kind": "move",
            "parent_occurrence_id": root_a["id"],
            "uci": "e2e4",
            "nag": 1,
            "context": {"course": "A"},
        },
    )
    _, move_b_response = await client.post(
        "/api/occurrences",
        json={
            "kind": "move",
            "parent_occurrence_id": root_b["id"],
            "uci": "e2e4",
            "nag": 2,
            "context": {"course": "B"},
        },
    )

    assert move_a_response.status == 201
    assert move_b_response.status == 201
    move_a = cast(dict[str, Any], move_a_response.json)
    move_b = cast(dict[str, Any], move_b_response.json)
    assert root_a["position_id"] == root_b["position_id"]
    assert move_a["position_id"] == move_b["position_id"]
    assert move_a["inbound_move_edge_id"] == move_b["inbound_move_edge_id"]
    assert move_a["id"] != move_b["id"]
    assert (move_a["nag"], move_a["context"]) == (1, {"course": "A"})
    assert (move_b["nag"], move_b["context"]) == (2, {"course": "B"})

    _, children_a = await client.get(
        f"/api/courses/{course_a['id']}/occurrences?parent_id={root_a['id']}"
    )
    _, children_b = await client.get(
        f"/api/courses/{course_b['id']}/occurrences?parent_id={root_b['id']}"
    )
    assert [item["id"] for item in children_a.json] == [move_a["id"]]
    assert [item["id"] for item in children_b.json] == [move_b["id"]]


async def test_transposed_paths_share_one_position_and_retain_both_parent_chains(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, _, root_a = await create_course_with_root(client, title="Knight first")
    _, _, root_b = await create_course_with_root(client, title="Pawn first")

    async def play(root: dict[str, Any], moves: tuple[str, ...]) -> list[dict[str, Any]]:
        path: list[dict[str, Any]] = []
        parent_id = root["id"]
        for sort_order, uci in enumerate(moves):
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
            occurrence = cast(dict[str, Any], response.json)
            assert occurrence["parent_id"] == parent_id
            path.append(occurrence)
            parent_id = occurrence["id"]
        return path

    knight_first = await play(root_a, ("g1f3", "g8f6", "g2g3"))
    pawn_first = await play(root_b, ("g2g3", "g8f6", "g1f3"))

    assert knight_first[-1]["position_id"] == pawn_first[-1]["position_id"]
    assert knight_first[-1]["full_fen"] != pawn_first[-1]["full_fen"]
    assert {item["id"] for item in knight_first}.isdisjoint({item["id"] for item in pawn_first})


async def test_illegal_occurrence_move_is_422_and_leaves_no_graph_writes(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    _, _, root = await create_course_with_root(client, title="Rollback")

    async with app.ctx.database.session() as session:
        before = (
            await session.scalar(select(func.count()).select_from(Position)),
            await session.scalar(select(func.count()).select_from(MoveEdge)),
            await session.scalar(select(func.count()).select_from(CourseOccurrence)),
        )

    _, response = await client.post(
        "/api/occurrences",
        json={
            "kind": "move",
            "parent_occurrence_id": root["id"],
            "uci": "e2e5",
        },
    )

    assert response.status == 422
    assert response.json["code"] == "illegal_move"
    async with app.ctx.database.session() as session:
        after = (
            await session.scalar(select(func.count()).select_from(Position)),
            await session.scalar(select(func.count()).select_from(MoveEdge)),
            await session.scalar(select(func.count()).select_from(CourseOccurrence)),
        )
    assert after == before


async def test_stale_updates_conflict_and_archive_is_recoverable_without_cascade(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    course, module, root = await create_course_with_root(client, title="Lifecycle")

    _, stale = await client.patch(
        f"/api/courses/{course['id']}",
        json={"expected_version": 99, "title": "Lost update"},
    )
    assert stale.status == 409
    assert stale.json["code"] == "stale_version"

    _, archived = await client.patch(
        f"/api/courses/{course['id']}",
        json={"expected_version": 1, "archived": True},
    )
    assert archived.status == 200
    assert archived.json["version"] == 2
    assert archived.json["archived_at"] is not None

    _, hidden = await client.get(f"/api/courses/{course['id']}")
    _, visible = await client.get(f"/api/courses/{course['id']}?include_archived=true")
    _, module_still_exists = await client.get(f"/api/course-modules/{module['id']}")
    _, root_still_exists = await client.get(f"/api/occurrences/{root['id']}")
    assert hidden.status == 404
    assert visible.status == 200
    assert module_still_exists.status == 200
    assert root_still_exists.status == 200

    _, restored = await client.patch(
        f"/api/courses/{course['id']}",
        json={"expected_version": 2, "archived": False},
    )
    assert restored.status == 200
    assert restored.json["version"] == 3
    assert restored.json["archived_at"] is None
