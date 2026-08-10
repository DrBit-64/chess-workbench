"""Stage 4A real dashboard/catalog/source query acceptance."""

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
            service_name=f"chess-workbench-dashboard-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'dashboard.db'}",
            engine_worker_enabled=False,
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def test_dashboard_uses_real_active_counts_and_recent_courses(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    courses: list[dict[str, Any]] = []
    for payload in (
        {
            "title": "Sicilian plans",
            "description": "Sharp opening",
            "tags": ["opening", "black"],
            "status": "published",
            "mode": "traditional",
        },
        {
            "title": "Decision explorer",
            "tags": ["opening"],
            "mode": "opening_explorer",
        },
        {"title": "Archived notes"},
    ):
        _, response = await client.post("/api/courses", json=payload)
        courses.append(cast(dict[str, Any], response.json))
    await client.patch(
        f"/api/courses/{courses[2]['id']}",
        json={"expected_version": 1, "archived": True},
    )
    _, module = await client.post(
        "/api/course-modules",
        json={
            "course_id": courses[0]["id"],
            "title": "Najdorf",
            "start_fen": chess.STARTING_FEN,
        },
    )
    assert module.status == 201
    await client.post("/api/sources", json={"kind": "book", "title": "My System"})
    await client.post("/api/sources", json={"kind": "web", "title": "Chess article"})
    await client.post(
        "/api/knowledge-notes",
        json={
            "occurrence_id": module.json["start_occurrence_id"],
            "markdown": "Keep the initiative.",
        },
    )

    _, response = await client.get("/api/dashboard/summary")
    assert response.status == 200
    assert response.json == {
        **response.json,
        "course_count": 2,
        "traditional_course_count": 1,
        "explorer_course_count": 1,
        "module_count": 1,
        "source_count": 2,
        "knowledge_note_count": 1,
        "position_count": 1,
    }
    assert {item["id"] for item in response.json["recent_courses"]} == {
        courses[0]["id"],
        courses[1]["id"],
    }


async def test_course_catalog_and_sources_have_strict_search_filters(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    for payload in (
        {
            "title": "Zugzwang manual",
            "category": "Endgame",
            "tags": ["study"],
            "mode": "traditional",
        },
        {
            "title": "Alpha explorer",
            "description": "Find candidate moves",
            "tags": ["decision"],
            "mode": "opening_explorer",
            "status": "published",
        },
    ):
        await client.post("/api/courses", json=payload)

    _, searched = await client.get("/api/courses?q=candidate")
    _, filtered = await client.get(
        "/api/courses?mode=traditional&status=draft&tag=STUDY&sort=title_asc"
    )
    _, sorted_courses = await client.get("/api/courses?sort=title_asc")
    _, invalid = await client.get("/api/courses?mode=invalid")
    _, too_long = await client.get(f"/api/courses?q={'x' * 201}")
    assert [item["title"] for item in searched.json] == ["Alpha explorer"]
    assert [item["title"] for item in filtered.json] == ["Zugzwang manual"]
    assert [item["title"] for item in sorted_courses.json] == [
        "Alpha explorer",
        "Zugzwang manual",
    ]
    assert invalid.status == too_long.status == 422

    await client.post(
        "/api/sources",
        json={"kind": "book", "title": "Endgame Bible", "author": "Averbakh"},
    )
    await client.post(
        "/api/sources",
        json={"kind": "web", "title": "Annotated article", "author": "Editor"},
    )
    _, books = await client.get("/api/sources?kind=book&q=aver")
    _, invalid_kind = await client.get("/api/sources?kind=pdf")
    assert [item["title"] for item in books.json] == ["Endgame Bible"]
    assert invalid_kind.status == 422
