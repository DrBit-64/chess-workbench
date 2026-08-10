"""PGN import receipt and download HTTP boundary."""

from __future__ import annotations

import json as json_module
import re
from hashlib import sha256
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sanic import Blueprint, Request
from sanic.response import HTTPResponse, json, raw
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.logic.pgn_export import (
    PgnExportError,
    export_import_pgn,
    export_module_pgn,
)
from chess_workbench.schemas.domain import ErrorResponse
from chess_workbench.schemas.pgn import (
    NewCourseDestination,
    PgnImportEnvelope,
    PgnImportJson,
    PgnImportOptions,
    PgnImportRead,
)
from chess_workbench.services import PgnImportService, prepare_pgn_import
from chess_workbench.store.database import Database

pgn_blueprint = Blueprint("pgn", url_prefix="/api")


def _media(model: type[BaseModel]) -> dict[str, Any]:
    return {"application/json": openapi_schema(model)}


ERROR_SCHEMA = _media(ErrorResponse)
IMPORT_SCHEMA = _media(PgnImportEnvelope)
IMPORT_READ_SCHEMA = _media(PgnImportRead)


@pgn_blueprint.post("/pgn/imports", name="create_pgn_import")
@openapi.operation("createPgnImport")
@openapi.summary("Import every game in a PGN payload atomically")
@openapi.tag("pgn")
@openapi.parameter("Idempotency-Key", str, "header", required=False)
@openapi.body(
    {
        "application/json": openapi_schema(PgnImportJson),
        "text/plain": {"type": "string"},
        "application/x-chess-pgn": {"type": "string", "format": "binary"},
        "multipart/form-data": {
            "type": "object",
            "required": ["file"],
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "options": {"type": "string", "description": "JSON PgnImportOptions"},
            },
            "additionalProperties": False,
        },
    },
    required=True,
)
@openapi.response(201, IMPORT_SCHEMA, "Import created")
@openapi.response(200, IMPORT_SCHEMA, "Idempotent replay")
@openapi.response(409, ERROR_SCHEMA, "Idempotency, Course mode, or version conflict")
@openapi.response(413, ERROR_SCHEMA, "PGN payload too large")
@openapi.response(415, ERROR_SCHEMA, "Unsupported media type")
@openapi.response(422, ERROR_SCHEMA, "Invalid PGN or request")
@openapi.response(503, ERROR_SCHEMA, "Source storage unavailable")
async def create_pgn_import(request: Request) -> HTTPResponse:
    raw_bytes, options = _request_payload(request)
    prepared = prepare_pgn_import(
        raw_bytes,
        destination=options.destination,
        source_title=options.source_title,
        game_titles=options.game_titles,
        idempotency_key=request.headers.get("idempotency-key"),
        storage_root=request.app.ctx.settings.source_storage_root,
    )
    database = cast(Database, request.app.ctx.database)
    async with request.app.ctx.pgn_import_lock, database.session() as session, session.begin():
        outcome = await PgnImportService(session).import_prepared(prepared)
    envelope = PgnImportEnvelope(replayed=outcome.replayed, import_receipt=outcome.receipt)
    status = 200 if outcome.replayed else 201
    headers = {
        "Location": f"/api/pgn/imports/{outcome.receipt.id}",
        "Idempotency-Replayed": "true" if outcome.replayed else "false",
    }
    return json(envelope.model_dump(mode="json"), status=status, headers=headers)


@pgn_blueprint.get("/pgn/imports/<import_id:uuid>", name="get_pgn_import")
@openapi.operation("getPgnImport")
@openapi.summary("Read an immutable PGN import receipt")
@openapi.tag("pgn")
@openapi.response(200, IMPORT_READ_SCHEMA, "Import receipt")
@openapi.response(404, ERROR_SCHEMA, "Import receipt not found")
async def get_pgn_import(request: Request, import_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        receipt = await PgnImportService(session).get_import(import_id)
    return json(receipt.model_dump(mode="json"))


@pgn_blueprint.get("/courses/<course_id:uuid>/pgn", name="download_course_pgn")
@openapi.operation("downloadCoursePgn")
@openapi.summary("Download one Module tree or root-to-leaf path as PGN")
@openapi.tag("pgn")
@openapi.parameter("module_id", UUID, "query", required=True)
@openapi.parameter("leaf_occurrence_id", UUID, "query", required=False)
@openapi.response(200, {"application/x-chess-pgn": {"type": "string"}}, "PGN download")
@openapi.response(404, ERROR_SCHEMA, "Course, Module, or leaf not found")
@openapi.response(409, ERROR_SCHEMA, "Module occurrence structure is not exportable")
@openapi.response(422, ERROR_SCHEMA, "Query validation failed")
async def download_course_pgn(request: Request, course_id: UUID) -> HTTPResponse:
    module_id = _query_uuid(request, "module_id", required=True)
    assert module_id is not None
    leaf_id = _query_uuid(request, "leaf_occurrence_id", required=False)
    database = cast(Database, request.app.ctx.database)
    try:
        async with database.session() as session:
            text = await export_module_pgn(
                session,
                course_id,
                module_id,
                leaf_occurrence_id=leaf_id,
            )
    except PgnExportError as error:
        raise _export_error(error) from error
    return _download(text, f"course-{course_id}.pgn")


@pgn_blueprint.get("/pgn/imports/<import_id:uuid>/download", name="download_pgn_import")
@openapi.operation("downloadPgnImport")
@openapi.summary("Download every game in an import receipt")
@openapi.tag("pgn")
@openapi.response(200, {"application/x-chess-pgn": {"type": "string"}}, "PGN download")
@openapi.response(404, ERROR_SCHEMA, "Import receipt not found")
@openapi.response(409, ERROR_SCHEMA, "Imported occurrence structure is not exportable")
async def download_pgn_import(request: Request, import_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    try:
        async with database.session() as session:
            text = await export_import_pgn(session, import_id)
    except PgnExportError as error:
        raise _export_error(error) from error
    return _download(text, f"import-{import_id}.pgn")


def _request_payload(request: Request) -> tuple[bytes, PgnImportOptions]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        body = parse_body(request, PgnImportJson)
        return body.pgn.encode("utf-8"), PgnImportOptions(
            destination=body.destination,
            source_title=body.source_title,
            game_titles=body.game_titles,
        )
    if content_type in {"text/plain", "application/x-chess-pgn"}:
        return bytes(request.body), PgnImportOptions(destination=NewCourseDestination())
    if content_type == "multipart/form-data":
        return _multipart_payload(request)
    raise ApiError(
        415,
        "unsupported_media_type",
        "Content-Type must be application/json, text/plain, application/x-chess-pgn, "
        "or multipart/form-data",
    )


def _multipart_payload(request: Request) -> tuple[bytes, PgnImportOptions]:
    file_names = set(request.files.keys()) if request.files is not None else set()
    form_names = set(request.form.keys()) if request.form is not None else set()
    if file_names - {"file"} or form_names - {"options"}:
        raise ApiError(
            422,
            "validation_error",
            "multipart body contains an unknown part",
            {"parts": sorted(file_names | form_names)},
        )
    files = request.files.getlist("file") if request.files is not None else []
    if len(files) != 1:
        raise ApiError(
            422,
            "validation_error",
            "multipart body must contain exactly one file part",
        )
    option_values = request.form.getlist("options") if request.form is not None else []
    if len(option_values) > 1:
        raise ApiError(422, "validation_error", "multipart body has duplicate options parts")
    options = PgnImportOptions(destination=NewCourseDestination())
    if option_values:
        try:
            options = PgnImportOptions.model_validate(json_module.loads(str(option_values[0])))
        except (ValueError, ValidationError, json_module.JSONDecodeError) as error:
            raise _validation_error("multipart options failed validation", error) from error
    return bytes(files[0].body), options


def _validation_error(message: str, error: Exception) -> ApiError:
    details: dict[str, Any] = {}
    if isinstance(error, ValidationError):
        details["errors"] = error.errors(include_url=False)
    return ApiError(422, "validation_error", message, details or None)


def _query_uuid(request: Request, name: str, *, required: bool) -> UUID | None:
    value = request.args.get(name)
    if value is None:
        if required:
            raise ApiError(422, "validation_error", f"query parameter {name} is required")
        return None
    try:
        return UUID(value)
    except ValueError as error:
        raise ApiError(422, "validation_error", f"query parameter {name} must be a UUID") from error


def _export_error(error: PgnExportError) -> ApiError:
    if error.reason in {
        "course_not_found",
        "module_not_found",
        "leaf_not_found",
        "import_not_found",
    }:
        return ApiError(404, "not_found", str(error), {"reason": error.reason})
    return ApiError(409, "pgn_not_exportable", str(error), {"reason": error.reason})


def _download(text: str, filename: str) -> HTTPResponse:
    data = text.encode("utf-8")
    safe_filename = re.sub(r'[\x00-\x1f\x7f/\\"\r\n]+', "_", filename).strip("._")
    if not safe_filename:
        safe_filename = "chess-workbench.pgn"
    ascii_filename = (
        safe_filename.encode("ascii", errors="ignore").decode("ascii") or "download.pgn"
    )
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{quote(safe_filename, safe='')}"
        ),
        "Content-Length": str(len(data)),
        "ETag": f'"{sha256(data).hexdigest()}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    return raw(
        data,
        content_type="application/x-chess-pgn; charset=utf-8",
        headers=headers,
    )
