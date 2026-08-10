"""Test Course.mode: create, read, update, and enum validation via API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings
from chess_workbench.store.base import Base
from chess_workbench.store.models import Course
from sqlalchemy.exc import IntegrityError


def build_test_app(tmp_path: Path) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-mode-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'mode.db'}",
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def test_create_course_defaults_to_traditional(tmp_path: Path) -> None:
    """A Course created without an explicit mode gets 'traditional'."""
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    _, response = await client.post(
        "/api/courses",
        json={"title": "A book about rook endgames"},
    )
    assert response.status == 201
    course = cast(dict[str, Any], response.json)
    assert course["mode"] == "traditional"


async def test_create_course_explicit_opening_explorer(tmp_path: Path) -> None:
    """A Course can be created with mode='opening_explorer'."""
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    _, response = await client.post(
        "/api/courses",
        json={
            "title": "Scandinavian Explorer",
            "mode": "opening_explorer",
        },
    )
    assert response.status == 201
    course = cast(dict[str, Any], response.json)
    assert course["mode"] == "opening_explorer"


async def test_create_course_rejects_invalid_mode(tmp_path: Path) -> None:
    """An unknown mode string is rejected with 422."""
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    _, response = await client.post(
        "/api/courses",
        json={
            "title": "Bad mode",
            "mode": "not-a-real-mode",
        },
    )
    assert response.status == 422


async def test_get_course_returns_mode(tmp_path: Path) -> None:
    """GET /api/courses/:id returns the mode field."""
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    _, create_resp = await client.post(
        "/api/courses",
        json={"title": "Read-back", "mode": "opening_explorer"},
    )
    course = cast(dict[str, Any], create_resp.json)

    _, get_resp = await client.get(f"/api/courses/{course['id']}")
    assert get_resp.status == 200
    assert cast(dict[str, Any], get_resp.json)["mode"] == "opening_explorer"


async def test_update_course_mode(tmp_path: Path) -> None:
    """PATCH /api/courses/:id can change the mode with optimistic concurrency."""
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    _, create_resp = await client.post(
        "/api/courses",
        json={"title": "Will change"},
    )
    course = cast(dict[str, Any], create_resp.json)
    assert course["mode"] == "traditional"

    _, patch_resp = await client.patch(
        f"/api/courses/{course['id']}",
        json={
            "expected_version": course["version"],
            "mode": "opening_explorer",
        },
    )
    assert patch_resp.status == 200
    assert cast(dict[str, Any], patch_resp.json)["mode"] == "opening_explorer"
    assert cast(dict[str, Any], patch_resp.json)["version"] == course["version"] + 1


async def test_list_courses_includes_mode(tmp_path: Path) -> None:
    """GET /api/courses returns mode on every course."""
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    await client.post(
        "/api/courses",
        json={"title": "Traditional one"},
    )
    await client.post(
        "/api/courses",
        json={"title": "Explorer one", "mode": "opening_explorer"},
    )

    _, list_resp = await client.get("/api/courses")
    assert list_resp.status == 200
    courses = cast(list[dict[str, Any]], list_resp.json)
    modes = {c["mode"] for c in courses}
    assert modes == {"traditional", "opening_explorer"}


async def test_database_rejects_invalid_course_mode(tmp_path: Path) -> None:
    """The database protects mode even when callers bypass Pydantic and HTTP."""
    app = build_test_app(tmp_path)
    await create_schema(app)

    async with app.ctx.database.session() as session, session.begin():
        session.add(Course(title="Invalid direct row", mode="not-a-real-mode"))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_course_mode_is_immutable_after_content_exists(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    _, create_response = await client.post(
        "/api/courses",
        json={"title": "Already populated"},
    )
    course = cast(dict[str, Any], create_response.json)
    _, module_response = await client.post(
        "/api/course-modules",
        json={"course_id": course["id"], "title": "Chapter"},
    )
    assert module_response.status == 201

    _, patch_response = await client.patch(
        f"/api/courses/{course['id']}",
        json={"expected_version": 1, "mode": "opening_explorer"},
    )
    assert patch_response.status == 409
    assert patch_response.json["code"] == "resource_referenced"
