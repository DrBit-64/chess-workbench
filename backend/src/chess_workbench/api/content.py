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
    CitableSourceCreate,
    CitableSourceRead,
    ContentHistoryRead,
    CourseContentBlockCreate,
    CourseContentBlockRead,
    CourseContentBlockUpdate,
    CourseCreate,
    CourseKnowledgeNoteBlockCreate,
    CourseKnowledgeNoteBlockRead,
    CourseModuleArchiveTreeRead,
    CourseModuleArchiveTreeRequest,
    CourseModuleCreate,
    CourseModuleEditorRead,
    CourseModuleRead,
    CourseModuleUpdate,
    CourseRead,
    CourseUpdate,
    DashboardSummary,
    ErrorResponse,
    KnowledgeNoteCreate,
    KnowledgeNoteRead,
    KnowledgeNoteUpdate,
    OccurrenceCommandRead,
    OccurrenceCommandRequest,
    OccurrenceMoveCreate,
    OccurrenceRead,
    OccurrenceUpdate,
    PublishModulesRead,
    PublishModulesRequest,
    RootOccurrenceCreate,
    SourceCreate,
    SourceFileCreate,
    SourceFileRead,
    SourceFileUpdate,
    SourceRead,
    SourceSpanCreate,
    SourceSpanRead,
    SourceSpanUpdate,
    SourceUpdate,
    SourceVersionCreate,
    SourceVersionRead,
    SourceVersionUpdate,
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
DASHBOARD_SCHEMA = _media(DashboardSummary)
COURSE_SCHEMA = _media(CourseRead)
COURSE_LIST_SCHEMA = _collection_media(CourseRead)
CONTENT_BLOCK_SCHEMA = _media(CourseContentBlockRead)
CONTENT_BLOCK_LIST_SCHEMA = _collection_media(CourseContentBlockRead)
KNOWLEDGE_NOTE_BLOCK_SCHEMA = _media(CourseKnowledgeNoteBlockRead)
CITABLE_SOURCE_SCHEMA = _media(CitableSourceRead)
CITABLE_SOURCE_LIST_SCHEMA = _collection_media(CitableSourceRead)
CONTENT_HISTORY_SCHEMA = _media(ContentHistoryRead)
MODULE_SCHEMA = _media(CourseModuleRead)
MODULE_LIST_SCHEMA = _collection_media(CourseModuleRead)
MODULE_EDITOR_SCHEMA = _media(CourseModuleEditorRead)
MODULE_ARCHIVE_TREE_SCHEMA = _media(CourseModuleArchiveTreeRead)
OCCURRENCE_SCHEMA = _media(OccurrenceRead)
OCCURRENCE_LIST_SCHEMA = _collection_media(OccurrenceRead)
OCCURRENCE_COMMAND_SCHEMA = _media(OccurrenceCommandRead)
SOURCE_SCHEMA = _media(SourceRead)
SOURCE_LIST_SCHEMA = _collection_media(SourceRead)
SOURCE_VERSION_SCHEMA = _media(SourceVersionRead)
SOURCE_VERSION_LIST_SCHEMA = _collection_media(SourceVersionRead)
SOURCE_FILE_SCHEMA = _media(SourceFileRead)
SOURCE_FILE_LIST_SCHEMA = _collection_media(SourceFileRead)
SOURCE_SPAN_SCHEMA = _media(SourceSpanRead)
SOURCE_SPAN_LIST_SCHEMA = _collection_media(SourceSpanRead)
KNOWLEDGE_NOTE_SCHEMA = _media(KnowledgeNoteRead)
KNOWLEDGE_NOTE_LIST_SCHEMA = _collection_media(KnowledgeNoteRead)
PUBLISH_MODULES_SCHEMA = _media(PublishModulesRead)


@content_blueprint.get("/dashboard/summary", name="get_dashboard_summary")
@openapi.operation("getDashboardSummary")
@openapi.summary("Read real active-content counts and recent courses")
@openapi.tag("dashboard")
@openapi.response(200, DASHBOARD_SCHEMA, "Dashboard summary")
async def get_dashboard_summary(request: Request) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).dashboard_summary()
    return _json(payload)


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
@openapi.parameter("q", str, "query", required=False)
@openapi.parameter("mode", str, "query", required=False)
@openapi.parameter("status", str, "query", required=False)
@openapi.parameter("tag", str, "query", required=False)
@openapi.parameter("sort", str, "query", required=False)
@openapi.response(200, COURSE_LIST_SCHEMA, "Courses")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def list_courses(request: Request) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    query = _query_text(request, "q")
    mode = _query_choice(request, "mode", {"traditional", "opening_explorer"})
    status = _query_choice(request, "status", {"draft", "published"})
    tag = _query_text(request, "tag")
    sort = _query_choice(
        request,
        "sort",
        {"updated_desc", "created_desc", "title_asc"},
        default="updated_desc",
    )
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_courses(
            include_archived=include_archived,
            query=query,
            mode=mode,
            status=status,
            tag=tag,
            sort=sort or "updated_desc",
        )
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


@content_blueprint.post(
    "/courses/<course_id:uuid>/publish-modules",
    name="publish_modules_to_explorer",
)
@openapi.operation("publishModulesToExplorer")
@openapi.summary("Atomically and idempotently publish Traditional Modules to an Explorer")
@openapi.tag("courses")
@openapi.body({"application/json": openapi_schema(PublishModulesRequest)}, required=True)
@openapi.response(200, PUBLISH_MODULES_SCHEMA, "Publication receipts")
@openapi.response(404, ERROR_SCHEMA, "Course or Module not found")
@openapi.response(409, ERROR_SCHEMA, "Course mode, content, or idempotency conflict")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def publish_modules_to_explorer(request: Request, course_id: UUID) -> HTTPResponse:
    body = parse_body(request, PublishModulesRequest)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).publish_modules_to_explorer(
            course_id, body.module_ids
        )
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


@content_blueprint.post(
    "/course-modules/<module_id:uuid>/archive-tree",
    name="archive_course_module_tree",
)
@openapi.operation("archiveCourseModuleTree")
@openapi.summary("Archive one module subtree and invalidate its live reference cards")
@openapi.tag("courses")
@openapi.body({"application/json": openapi_schema(CourseModuleArchiveTreeRequest)}, required=True)
@openapi.response(200, MODULE_ARCHIVE_TREE_SCHEMA, "Module subtree archived")
@openapi.response(404, ERROR_SCHEMA, "Module not found")
@openapi.response(409, ERROR_SCHEMA, "Module version is stale")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def archive_course_module_tree(request: Request, module_id: UUID) -> HTTPResponse:
    body = parse_body(request, CourseModuleArchiveTreeRequest)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).archive_module_tree(module_id, body)
    return _json(payload)


@content_blueprint.get(
    "/courses/<course_id:uuid>/editor/<module_id:uuid>",
    name="get_course_module_editor",
)
@openapi.operation("getCourseModuleEditor")
@openapi.summary("Read one Module's blocks and occurrence tree for the editor")
@openapi.tag("courses")
@openapi.response(200, MODULE_EDITOR_SCHEMA, "Module editor state")
@openapi.response(404, ERROR_SCHEMA, "Course or Module not found")
@openapi.response(409, ERROR_SCHEMA, "Module belongs to another Course")
async def get_course_module_editor(
    request: Request,
    course_id: UUID,
    module_id: UUID,
) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_module_editor(course_id, module_id)
    return _json(payload)


@content_blueprint.post("/course-content-blocks", name="create_course_content_block")
@openapi.operation("createCourseContentBlock")
@openapi.summary("Create one ordered ADR 0006 Module content block")
@openapi.tag("courses")
@openapi.body({"application/json": openapi_schema(CourseContentBlockCreate)}, required=True)
@openapi.response(201, CONTENT_BLOCK_SCHEMA, "Content block created")
@openapi.response(404, ERROR_SCHEMA, "Module or referenced content not found")
@openapi.response(409, ERROR_SCHEMA, "Block order or reference conflicts")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def create_course_content_block(request: Request) -> HTTPResponse:
    body = parse_body(request, CourseContentBlockCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_content_block(body)
    return _json(payload, status=201)


@content_blueprint.post(
    "/course-modules/<module_id:uuid>/knowledge-note-blocks",
    name="create_course_knowledge_note_block",
)
@openapi.operation("createCourseKnowledgeNoteBlock")
@openapi.summary("Atomically create a local position note and append it to Module reading")
@openapi.tag("courses")
@openapi.body(
    {"application/json": openapi_schema(CourseKnowledgeNoteBlockCreate)},
    required=True,
)
@openapi.response(201, KNOWLEDGE_NOTE_BLOCK_SCHEMA, "Knowledge note and block created")
@openapi.response(404, ERROR_SCHEMA, "Module, occurrence, or source span not found")
@openapi.response(409, ERROR_SCHEMA, "Occurrence belongs to another Module")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def create_course_knowledge_note_block(
    request: Request,
    module_id: UUID,
) -> HTTPResponse:
    body = parse_body(request, CourseKnowledgeNoteBlockCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_course_knowledge_note_block(
            module_id,
            body,
        )
    return _json(payload, status=201)


@content_blueprint.get(
    "/course-modules/<module_id:uuid>/content-blocks",
    name="list_course_content_blocks",
)
@openapi.operation("listCourseContentBlocks")
@openapi.summary("List a Module's ordered mixed-content sequence")
@openapi.tag("courses")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, CONTENT_BLOCK_LIST_SCHEMA, "Content blocks")
@openapi.response(404, ERROR_SCHEMA, "Module not found")
async def list_course_content_blocks(request: Request, module_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_content_blocks(
            module_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.get("/course-content-blocks/<block_id:uuid>", name="get_course_content_block")
@openapi.operation("getCourseContentBlock")
@openapi.summary("Read one Module content block")
@openapi.tag("courses")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, CONTENT_BLOCK_SCHEMA, "Content block")
@openapi.response(404, ERROR_SCHEMA, "Content block not found")
async def get_course_content_block(request: Request, block_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_content_block(
            block_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.patch(
    "/course-content-blocks/<block_id:uuid>", name="update_course_content_block"
)
@openapi.operation("updateCourseContentBlock")
@openapi.summary("Edit, reorder, archive, or restore a Module content block")
@openapi.tag("courses")
@openapi.body({"application/json": openapi_schema(CourseContentBlockUpdate)}, required=True)
@openapi.response(200, CONTENT_BLOCK_SCHEMA, "Content block updated")
@openapi.response(404, ERROR_SCHEMA, "Content block not found")
@openapi.response(409, ERROR_SCHEMA, "Version, order, or block-kind conflict")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def update_course_content_block(request: Request, block_id: UUID) -> HTTPResponse:
    body = parse_body(request, CourseContentBlockUpdate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).update_content_block(block_id, body)
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


@content_blueprint.post(
    "/occurrences/<occurrence_id:uuid>/commands",
    name="apply_course_occurrence_command",
)
@openapi.operation("applyCourseOccurrenceCommand")
@openapi.summary("Apply one semantic course-score edit atomically")
@openapi.tag("course-occurrences")
@openapi.body({"application/json": openapi_schema(OccurrenceCommandRequest)}, required=True)
@openapi.response(200, OCCURRENCE_COMMAND_SCHEMA, "Course-score command applied")
@openapi.response(404, ERROR_SCHEMA, "Occurrence not found")
@openapi.response(409, ERROR_SCHEMA, "Version or tree context conflicts")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def apply_course_occurrence_command(
    request: Request,
    occurrence_id: UUID,
) -> HTTPResponse:
    body = parse_body(request, OccurrenceCommandRequest)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).execute_occurrence_command(occurrence_id, body)
    return _json(payload)


@content_blueprint.post("/sources", name="create_source")
@openapi.operation("createSource")
@openapi.summary("Create a conceptual source work")
@openapi.tag("sources")
@openapi.body({"application/json": openapi_schema(SourceCreate)}, required=True)
@openapi.response(201, SOURCE_SCHEMA, "Source created")
@openapi.response(409, ERROR_SCHEMA, "Source conflicts with an existing resource")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def create_source(request: Request) -> HTTPResponse:
    body = parse_body(request, SourceCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_source(body)
    return _json(payload, status=201)


@content_blueprint.post("/citable-sources", name="create_citable_source")
@openapi.operation("createCitableSource")
@openapi.summary("Atomically create a human source, version, and whole-work citation span")
@openapi.tag("sources")
@openapi.body({"application/json": openapi_schema(CitableSourceCreate)}, required=True)
@openapi.response(201, CITABLE_SOURCE_SCHEMA, "Citable source created")
@openapi.response(409, ERROR_SCHEMA, "Source chain conflicts")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def create_citable_source(request: Request) -> HTTPResponse:
    body = parse_body(request, CitableSourceCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_citable_source(body)
    return _json(payload, status=201)


@content_blueprint.get("/citable-sources", name="list_citable_sources")
@openapi.operation("listCitableSources")
@openapi.summary("List active source spans that can be linked to an editor note")
@openapi.tag("sources")
@openapi.response(200, CITABLE_SOURCE_LIST_SCHEMA, "Citable sources")
async def list_citable_sources(request: Request) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_citable_sources()
    return _json(payload)


@content_blueprint.get("/sources", name="list_sources")
@openapi.operation("listSources")
@openapi.summary("List conceptual source works")
@openapi.tag("sources")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.parameter("q", str, "query", required=False)
@openapi.parameter("kind", str, "query", required=False)
@openapi.response(200, SOURCE_LIST_SCHEMA, "Sources")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def list_sources(request: Request) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    query = _query_text(request, "q")
    kind = _query_choice(
        request,
        "kind",
        {"book", "video", "article", "web", "pgn", "game", "manual", "other"},
    )
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_sources(
            include_archived=include_archived,
            query=query,
            kind=kind,
        )
    return _json(payload)


@content_blueprint.get("/sources/<source_id:uuid>", name="get_source")
@openapi.operation("getSource")
@openapi.summary("Read a conceptual source work")
@openapi.tag("sources")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, SOURCE_SCHEMA, "Source")
@openapi.response(404, ERROR_SCHEMA, "Source not found")
async def get_source(request: Request, source_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_source(
            source_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.patch("/sources/<source_id:uuid>", name="update_source")
@openapi.operation("updateSource")
@openapi.summary("Update, archive, or restore a source work")
@openapi.tag("sources")
@openapi.body({"application/json": openapi_schema(SourceUpdate)}, required=True)
@openapi.response(200, SOURCE_SCHEMA, "Updated source")
@openapi.response(404, ERROR_SCHEMA, "Source not found")
@openapi.response(409, ERROR_SCHEMA, "Version is stale")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def update_source(request: Request, source_id: UUID) -> HTTPResponse:
    body = parse_body(request, SourceUpdate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).update_source(source_id, body)
    return _json(payload)


@content_blueprint.post("/source-versions", name="create_source_version")
@openapi.operation("createSourceVersion")
@openapi.summary("Create a version of a source work")
@openapi.tag("sources")
@openapi.body({"application/json": openapi_schema(SourceVersionCreate)}, required=True)
@openapi.response(201, SOURCE_VERSION_SCHEMA, "Source version created")
@openapi.response(404, ERROR_SCHEMA, "Source not found")
@openapi.response(409, ERROR_SCHEMA, "Source version conflicts with an existing resource")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def create_source_version(request: Request) -> HTTPResponse:
    body = parse_body(request, SourceVersionCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_source_version(body)
    return _json(payload, status=201)


@content_blueprint.get("/sources/<source_id:uuid>/versions", name="list_source_versions")
@openapi.operation("listSourceVersions")
@openapi.summary("List versions of one source work")
@openapi.tag("sources")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, SOURCE_VERSION_LIST_SCHEMA, "Source versions")
@openapi.response(404, ERROR_SCHEMA, "Source not found")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def list_source_versions(request: Request, source_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_source_versions(
            source_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.get("/source-versions/<version_id:uuid>", name="get_source_version")
@openapi.operation("getSourceVersion")
@openapi.summary("Read a source version")
@openapi.tag("sources")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, SOURCE_VERSION_SCHEMA, "Source version")
@openapi.response(404, ERROR_SCHEMA, "Source version not found")
async def get_source_version(request: Request, version_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_source_version(
            version_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.patch("/source-versions/<version_id:uuid>", name="update_source_version")
@openapi.operation("updateSourceVersion")
@openapi.summary("Update, archive, or restore a source version")
@openapi.tag("sources")
@openapi.body({"application/json": openapi_schema(SourceVersionUpdate)}, required=True)
@openapi.response(200, SOURCE_VERSION_SCHEMA, "Updated source version")
@openapi.response(404, ERROR_SCHEMA, "Source version not found")
@openapi.response(409, ERROR_SCHEMA, "Version is stale")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def update_source_version(request: Request, version_id: UUID) -> HTTPResponse:
    body = parse_body(request, SourceVersionUpdate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).update_source_version(version_id, body)
    return _json(payload)


@content_blueprint.post("/source-files", name="create_source_file")
@openapi.operation("createSourceFile")
@openapi.summary("Register an immutable source file")
@openapi.tag("sources")
@openapi.body({"application/json": openapi_schema(SourceFileCreate)}, required=True)
@openapi.response(201, SOURCE_FILE_SCHEMA, "Source file created")
@openapi.response(404, ERROR_SCHEMA, "Source version not found")
@openapi.response(409, ERROR_SCHEMA, "Source file conflicts with an existing resource")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def create_source_file(request: Request) -> HTTPResponse:
    body = parse_body(request, SourceFileCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_source_file(body)
    return _json(payload, status=201)


@content_blueprint.get(
    "/source-versions/<version_id:uuid>/files",
    name="list_source_files",
)
@openapi.operation("listSourceFiles")
@openapi.summary("List immutable files for one source version")
@openapi.tag("sources")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, SOURCE_FILE_LIST_SCHEMA, "Source files")
@openapi.response(404, ERROR_SCHEMA, "Source version not found")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def list_source_files(request: Request, version_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_source_files(
            version_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.get("/source-files/<file_id:uuid>", name="get_source_file")
@openapi.operation("getSourceFile")
@openapi.summary("Read immutable source file metadata")
@openapi.tag("sources")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, SOURCE_FILE_SCHEMA, "Source file")
@openapi.response(404, ERROR_SCHEMA, "Source file not found")
async def get_source_file(request: Request, file_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_source_file(
            file_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.patch("/source-files/<file_id:uuid>", name="update_source_file")
@openapi.operation("updateSourceFile")
@openapi.summary("Archive or restore immutable source file metadata")
@openapi.tag("sources")
@openapi.body({"application/json": openapi_schema(SourceFileUpdate)}, required=True)
@openapi.response(200, SOURCE_FILE_SCHEMA, "Updated source file")
@openapi.response(404, ERROR_SCHEMA, "Source file not found")
@openapi.response(409, ERROR_SCHEMA, "Version is stale")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def update_source_file(request: Request, file_id: UUID) -> HTTPResponse:
    body = parse_body(request, SourceFileUpdate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).update_source_file(file_id, body)
    return _json(payload)


@content_blueprint.post("/source-spans", name="create_source_span")
@openapi.operation("createSourceSpan")
@openapi.summary("Create a citable span in a source version")
@openapi.tag("sources")
@openapi.body({"application/json": openapi_schema(SourceSpanCreate)}, required=True)
@openapi.response(201, SOURCE_SPAN_SCHEMA, "Source span created")
@openapi.response(404, ERROR_SCHEMA, "Source version or file not found")
@openapi.response(409, ERROR_SCHEMA, "Source file belongs to another version")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def create_source_span(request: Request) -> HTTPResponse:
    body = parse_body(request, SourceSpanCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_source_span(body)
    return _json(payload, status=201)


@content_blueprint.get(
    "/source-versions/<version_id:uuid>/spans",
    name="list_source_spans",
)
@openapi.operation("listSourceSpans")
@openapi.summary("List citable spans for one source version")
@openapi.tag("sources")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, SOURCE_SPAN_LIST_SCHEMA, "Source spans")
@openapi.response(404, ERROR_SCHEMA, "Source version not found")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def list_source_spans(request: Request, version_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_source_spans(
            version_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.get("/source-spans/<span_id:uuid>", name="get_source_span")
@openapi.operation("getSourceSpan")
@openapi.summary("Read a citable source span")
@openapi.tag("sources")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, SOURCE_SPAN_SCHEMA, "Source span")
@openapi.response(404, ERROR_SCHEMA, "Source span not found")
async def get_source_span(request: Request, span_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_source_span(
            span_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.patch("/source-spans/<span_id:uuid>", name="update_source_span")
@openapi.operation("updateSourceSpan")
@openapi.summary("Update, archive, or restore a citable source span")
@openapi.tag("sources")
@openapi.body({"application/json": openapi_schema(SourceSpanUpdate)}, required=True)
@openapi.response(200, SOURCE_SPAN_SCHEMA, "Updated source span")
@openapi.response(404, ERROR_SCHEMA, "Source span not found")
@openapi.response(409, ERROR_SCHEMA, "Version is stale")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def update_source_span(request: Request, span_id: UUID) -> HTTPResponse:
    body = parse_body(request, SourceSpanUpdate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).update_source_span(span_id, body)
    return _json(payload)


@content_blueprint.post("/knowledge-notes", name="create_knowledge_note")
@openapi.operation("createKnowledgeNote")
@openapi.summary("Create an occurrence-local or explicitly global knowledge note")
@openapi.tag("knowledge-notes")
@openapi.body({"application/json": openapi_schema(KnowledgeNoteCreate)}, required=True)
@openapi.response(201, KNOWLEDGE_NOTE_SCHEMA, "Knowledge note created")
@openapi.response(404, ERROR_SCHEMA, "Target or source span not found")
@openapi.response(409, ERROR_SCHEMA, "Knowledge note context conflicts")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def create_knowledge_note(request: Request) -> HTTPResponse:
    body = parse_body(request, KnowledgeNoteCreate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).create_knowledge_note(body)
    return _json(payload, status=201)


@content_blueprint.get("/knowledge-notes", name="list_knowledge_notes")
@openapi.operation("listKnowledgeNotes")
@openapi.summary("List knowledge notes with an optional explicit target filter")
@openapi.tag("knowledge-notes")
@openapi.parameter("occurrence_id", UUID, "query", required=False)
@openapi.parameter("position_id", UUID, "query", required=False)
@openapi.parameter("move_edge_id", UUID, "query", required=False)
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, KNOWLEDGE_NOTE_LIST_SCHEMA, "Knowledge notes")
@openapi.response(404, ERROR_SCHEMA, "Filtered target not found")
@openapi.response(409, ERROR_SCHEMA, "More than one target filter supplied")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def list_knowledge_notes(request: Request) -> HTTPResponse:
    occurrence_id = _query_uuid(request, "occurrence_id")
    position_id = _query_uuid(request, "position_id")
    move_edge_id = _query_uuid(request, "move_edge_id")
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).list_knowledge_notes(
            occurrence_id=occurrence_id,
            position_id=position_id,
            move_edge_id=move_edge_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.get("/knowledge-notes/<note_id:uuid>", name="get_knowledge_note")
@openapi.operation("getKnowledgeNote")
@openapi.summary("Read a knowledge note")
@openapi.tag("knowledge-notes")
@openapi.parameter("include_archived", bool, "query", required=False)
@openapi.response(200, KNOWLEDGE_NOTE_SCHEMA, "Knowledge note")
@openapi.response(404, ERROR_SCHEMA, "Knowledge note not found")
async def get_knowledge_note(request: Request, note_id: UUID) -> HTTPResponse:
    include_archived = _query_bool(request, "include_archived")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_knowledge_note(
            note_id,
            include_archived=include_archived,
        )
    return _json(payload)


@content_blueprint.patch("/knowledge-notes/<note_id:uuid>", name="update_knowledge_note")
@openapi.operation("updateKnowledgeNote")
@openapi.summary("Update, archive, or restore a knowledge note")
@openapi.tag("knowledge-notes")
@openapi.body({"application/json": openapi_schema(KnowledgeNoteUpdate)}, required=True)
@openapi.response(200, KNOWLEDGE_NOTE_SCHEMA, "Updated knowledge note")
@openapi.response(404, ERROR_SCHEMA, "Knowledge note or source span not found")
@openapi.response(409, ERROR_SCHEMA, "Version is stale")
@openapi.response(422, ERROR_SCHEMA, "Request validation failed")
async def update_knowledge_note(request: Request, note_id: UUID) -> HTTPResponse:
    body = parse_body(request, KnowledgeNoteUpdate)
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session, session.begin():
        payload = await ContentService(session).update_knowledge_note(note_id, body)
    return _json(payload)


@content_blueprint.get(
    "/history/<entity_type:str>/<entity_id:uuid>",
    name="get_content_history",
)
@openapi.operation("getContentHistory")
@openapi.summary("Read immutable pre-edit snapshots for authoring content")
@openapi.tag("history")
@openapi.response(200, CONTENT_HISTORY_SCHEMA, "Content history")
@openapi.response(404, ERROR_SCHEMA, "Entity not found")
@openapi.response(422, ERROR_SCHEMA, "Unsupported entity type")
async def get_content_history(
    request: Request,
    entity_type: str,
    entity_id: UUID,
) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await ContentService(session).get_content_history(entity_type, entity_id)
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


def _query_text(request: Request, name: str) -> str | None:
    value = cast(str | None, request.args.get(name))
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 200:
        raise ApiError(
            422,
            "validation_error",
            f"query parameter {name} must be at most 200 characters",
            {"field": name},
        )
    return normalized


def _query_choice(
    request: Request,
    name: str,
    choices: set[str],
    *,
    default: str | None = None,
) -> str | None:
    value = cast(str | None, request.args.get(name))
    if value is None:
        return default
    if value not in choices:
        raise ApiError(
            422,
            "validation_error",
            f"query parameter {name} has an unsupported value",
            {"field": name, "expected": sorted(choices)},
        )
    return value


def _json(payload: BaseModel | Sequence[BaseModel], *, status: int = 200) -> HTTPResponse:
    body: Any
    if isinstance(payload, BaseModel):
        body = payload.model_dump(mode="json")
    else:
        body = [item.model_dump(mode="json") for item in payload]
    return json(body, status=status)
