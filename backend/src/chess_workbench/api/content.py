"""HTTP CRUD boundary for Stage 2 course and source context."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sanic import Blueprint, Request
from sanic.response import HTTPResponse, json
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.schemas.domain import (
    CourseCreate,
    CourseModuleCreate,
    CourseModuleRead,
    CourseModuleUpdate,
    CourseRead,
    CourseUpdate,
    ErrorResponse,
    OccurrenceMoveCreate,
    OccurrenceRead,
    OccurrenceUpdate,
    RootOccurrenceCreate,
)
from chess_workbench.services import ContentService
from chess_workbench.store.database import Database

content_blueprint = Blueprint("content", url_prefix="/api")


def _media(model: type[BaseModel]) -> dict[str, Any]:
    return {"application/json": openapi_schema(model)}


def _collection_media(model: type[BaseModel]) -> dict[str, Any]:
    return {
        "application/json": {
            "type": "array",
            "items": openapi_schema(model),
        }
    }


ERROR_SCHEMA = _media(ErrorResponse)
COURSE_SCHEMA = _media(CourseRead)
COURSE_LIST_SCHEMA = _collection_media(CourseRead)
MODULE_SCHEMA = _media(CourseModuleRead)
MODULE_LIST_SCHEMA = _collection_media(CourseModuleRead)
OCCURRENCE_SCHEMA = _media(OccurrenceRead)
OCCURRENCE_LIST_SCHEMA = _collection_media(OccurrenceRead)


@content_blueprint.post("/courses", name="create_course")
@openapi.operation("createCourse")
@openapi.summary("Create a course")
@openapi.tag("courses")
@openapi.body({"application/json": openapi_schema(CourseCreate)}, required=True)
@openapi.response(201, COURSE_SCHEMA, "Course created")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def create_course(request: Request) -> HTTPResponse:
    body = parse_body(request, CourseCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_course(body)
    return _json(payload, status=201)


@content_blueprint.get("/courses", name="list_courses")
@openapi.operation("listCourses")
@openapi.summary("List courses")
@openapi.tag("courses")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, COURSE_LIST_SCHEMA, "Courses")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def list_courses(request: Request) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_courses(include_archived=include_archived)
    return _json(payload)


@content_blueprint.get("/courses/<course_id:uuid>", name="get_course")
@openapi.operation("getCourse")
@openapi.summary("Read a course")
@openapi.tag("courses")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, COURSE_SCHEMA, "Course")
@openapi.response(404, ERROR_SCHEMA, "Course not found")
async def get_course(request: Request, course_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_course(
            course_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.patch("/courses/<course_id:uuid>", name="update_course")
@openapi.operation("updateCourse")
@openapi.summary("Update, archive, or restore a course with optimistic locking")
@openapi.tag("courses")
@openapi.body({"application/json": openapi_schema(CourseUpdate)}, required=True)
@openapi.response(200, COURSE_SCHEMA, "Updated course")
@openapi.response(404, ERROR_SCHEMA, "Course not found")
@openapi.response(409, ERROR_SCHEMA, "Version is stale")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def update_course(request: Request, course_id: UUID) -> HTTPResponse:
    body = parse_body(request, CourseUpdate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).update_course(course_id, body)
    return _json(payload)


@content_blueprint.post("/course-modules", name="create_module")
@openapi.operation("createCourseModule")
@openapi.summary("Create a course module and optional root occurrence")
@openapi.tag("courses")
@openapi.body({"application/json": openapi_schema(CourseModuleCreate)}, required=True)
@openapi.response(201, MODULE_SCHEMA, "Module created")
@openapi.response(404, ERROR_SCHEMA, "Course or parent module not found")
@openapi.response(409, ERROR_SCHEMA, "Module context conflicts")
@openapi.response(422, ERROR_SCHEMA, "Request validation or FEN validation failed")
async def create_module(request: Request) -> HTTPResponse:
    body = parse_body(request, CourseModuleCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_module(body)
    return _json(payload, status=201)


@content_blueprint.get("/courses/<course_id:uuid>/modules", name="list_modules")
@openapi.operation("listCourseModules")
@openapi.summary("List modules in one course")
@openapi.tag("courses")
@openapi.parameter("parent_id", UUID, "query", required=False)
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, MODULE_LIST_SCHEMA, "Course modules")
@openapi.response(404, ERROR_SCHEMA, "Course not found")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def list_modules(request: Request, course_id: UUID) -> HTTPResponse:
    parent_id = _query_uuid(request, "parent_id")
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_modules(
            course_id,
            parent_id=parent_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.get("/course-modules/<module_id:uuid>", name="get_module")
@openapi.operation("getCourseModule")
@openapi.summary("Read a course module")
@openapi.tag("courses")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, MODULE_SCHEMA, "Course module")
@openapi.response(404, ERROR_SCHEMA, "Module not found")
@openapi.response(409, ERROR_SCHEMA, "Module has ambiguous root context")
async def get_module(request: Request, module_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_module(
            module_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.patch("/course-modules/<module_id:uuid>", name="update_module")
@openapi.operation("updateCourseModule")
@openapi.summary("Update, archive, or restore a module")
@openapi.tag("courses")
@openapi.body({"application/json": openapi_schema(CourseModuleUpdate)}, required=True)
@openapi.response(200, MODULE_SCHEMA, "Updated module")
@openapi.response(404, ERROR_SCHEMA, "Module or parent not found")
@openapi.response(409, ERROR_SCHEMA, "Stale version or invalid parent context")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def update_module(request: Request, module_id: UUID) -> HTTPResponse:
    body = parse_body(request, CourseModuleUpdate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).update_module(module_id, body)
    return _json(payload)


@content_blueprint.post("/occurrences", name="create_occurrence")
@openapi.operation("createCourseOccurrence")
@openapi.summary("Create a root occurrence or apply one legal move in path context")
@openapi.tag("course-occurrences")
@openapi.body(
    {
        "application/json": {
            "oneOf": [
                openapi_schema(RootOccurrenceCreate),
                openapi_schema(OccurrenceMoveCreate),
            ],
            "discriminator": {"propertyName": "kind"},
        }
    },
    required=True,
)
@openapi.response(201, OCCURRENCE_SCHEMA, "Occurrence created")
@openapi.response(404, ERROR_SCHEMA, "Course, module, or parent occurrence not found")
@openapi.response(409, ERROR_SCHEMA, "Occurrence context is ambiguous")
@openapi.response(422, ERROR_SCHEMA, "FEN or move is invalid or illegal")
async def create_occurrence(request: Request) -> HTTPResponse:
    kind = _body_kind(request)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        service = ContentService(session)
        if kind == "root":
            payload = await service.create_root_occurrence(
                parse_body(request, RootOccurrenceCreate)
            )
        elif kind == "move":
            payload = await service.create_move_occurrence(
                parse_body(request, OccurrenceMoveCreate)
            )
        else:
            raise ApiError(
                422,
                "validation_error",
                "request body failed validation",
                {"field": "kind", "expected": ["root", "move"]},
            )
    return _json(payload, status=201)


@content_blueprint.get("/courses/<course_id:uuid>/occurrences", name="list_occurrences")
@openapi.operation("listCourseOccurrences")
@openapi.summary("List occurrences while preserving course and path context")
@openapi.tag("course-occurrences")
@openapi.parameter("module_id", UUID, "query", required=False)
@openapi.parameter("parent_id", UUID, "query", required=False)
@openapi.parameter("roots_only", bool, "query", required=False)
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, OCCURRENCE_LIST_SCHEMA, "Course occurrences")
@openapi.response(404, ERROR_SCHEMA, "Course, module, or parent not found")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def list_occurrences(request: Request, course_id: UUID) -> HTTPResponse:
    module_id = _query_uuid(request, "module_id")
    parent_id = _query_uuid(request, "parent_id")
    roots_only = _query_bool(request, "roots_only")
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_occurrences(
            course_id,
            module_id=module_id,
            parent_id=parent_id,
            roots_only=roots_only,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.get("/occurrences/<occurrence_id:uuid>", name="get_occurrence")
@openapi.operation("getCourseOccurrence")
@openapi.summary("Read one occurrence with explicit path context")
@openapi.tag("course-occurrences")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, OCCURRENCE_SCHEMA, "Course occurrence")
@openapi.response(404, ERROR_SCHEMA, "Occurrence not found")
async def get_occurrence(request: Request, occurrence_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_occurrence(
            occurrence_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.patch("/occurrences/<occurrence_id:uuid>", name="update_occurrence")
@openapi.operation("updateCourseOccurrence")
@openapi.summary("Update occurrence-local context with optimistic locking")
@openapi.tag("course-occurrences")
@openapi.body({"application/json": openapi_schema(OccurrenceUpdate)}, required=True)
@openapi.response(200, OCCURRENCE_SCHEMA, "Updated occurrence")
@openapi.response(404, ERROR_SCHEMA, "Occurrence or module not found")
@openapi.response(409, ERROR_SCHEMA, "Stale version or invalid context")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def update_occurrence(request: Request, occurrence_id: UUID) -> HTTPResponse:
    body = parse_body(request, OccurrenceUpdate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).update_occurrence(occurrence_id, body)
    return _json(payload)


def _body_kind(request: Request) -> object:
    try:
        payload = request.json
    except Exception as exc:
        raise ApiError(
            422,
            "validation_error",
            "request body must contain valid JSON",
        ) from exc
    return payload.get("kind") if isinstance(payload, dict) else None


def _query_bool(request: Request, name: str, *, default: bool = False) -> bool:
    value = request.args.get(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ApiError(
        422,
        "validation_error",
        f"query parameter {name} must be true or false",
        {"field": name},
    )


def _query_uuid(request: Request, name: str) -> UUID | None:
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise ApiError(
            422,
            "validation_error",
            f"query parameter {name} must be a UUID",
            {"field": name},
        ) from exc


def _json(payload: BaseModel | Sequence[BaseModel], *, status: int = 200) -> HTTPResponse:
    body: Any
    if isinstance(payload, BaseModel):
        body = payload.model_dump(mode="json")
    else:
        body = [item.model_dump(mode="json") for item in payload]
    return json(body, status=status)
