"""Immutable PDF asset upload and extraction-run HTTP boundary."""

from __future__ import annotations

import asyncio
import json as json_module
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sanic import Blueprint, Request
from sanic.response import HTTPResponse, json
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.schemas.domain import ErrorResponse
from chess_workbench.schemas.pdf import (
    PdfAssetEnvelope,
    PdfAssetList,
    PdfAssetRead,
    PdfAssetUploadMetadata,
    PdfEvidenceSummary,
    PdfExtractionCreate,
    PdfExtractionEnvelope,
    PdfExtractionList,
    PdfExtractionRead,
)
from chess_workbench.services.jobs import job_read
from chess_workbench.services.pdf import prepare_pdf_asset
from chess_workbench.services.pdf_persistence import (
    PdfAssetView,
    PdfExtractionView,
    PdfPersistenceService,
)
from chess_workbench.store.database import Database

pdf_blueprint = Blueprint("pdf", url_prefix="/api")

JOB_STATUSES: frozenset[str] = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})


def _media(model: type[BaseModel]) -> dict[str, Any]:
    return {"application/json": openapi_schema(model)}


ERROR_SCHEMA = _media(ErrorResponse)


@pdf_blueprint.post("/pdf-assets", name="create_pdf_asset")
@openapi.operation("createPdfAsset")
@openapi.summary("Upload and register one immutable PDF asset")
@openapi.tag("pdf")
@openapi.body(
    {
        "multipart/form-data": {
            "type": "object",
            "required": ["file"],
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "metadata": {"type": "string", "description": "JSON PdfAssetUploadMetadata"},
            },
            "additionalProperties": False,
        }
    },
    required=True,
)
@openapi.response(201, _media(PdfAssetEnvelope), "PDF asset created")
@openapi.response(200, _media(PdfAssetEnvelope), "Content-addressed replay")
@openapi.response(413, ERROR_SCHEMA, "PDF payload too large")
@openapi.response(415, ERROR_SCHEMA, "Unsupported media type")
@openapi.response(422, ERROR_SCHEMA, "Invalid PDF or multipart request")
@openapi.response(503, ERROR_SCHEMA, "Source storage unavailable")
async def create_pdf_asset(request: Request) -> HTTPResponse:
    raw_bytes, filename, declared_media_type, metadata = _multipart_upload(request)
    settings = request.app.ctx.settings
    prepared = await asyncio.to_thread(
        prepare_pdf_asset,
        raw_bytes,
        filename=filename,
        declared_media_type=declared_media_type,
        title=metadata.title,
        author=metadata.author,
        edition=metadata.edition,
        storage_root=settings.source_storage_root,
        max_bytes=settings.pdf_max_bytes,
    )
    database = cast(Database, request.app.ctx.database)
    async with request.app.ctx.pdf_persistence_lock, database.session() as session, session.begin():
        service = PdfPersistenceService(session)
        outcome = await service.register_asset(prepared)
        view = await service.get_asset(outcome.asset.id)
        if view is None:
            raise RuntimeError("registered PdfAsset source chain is missing")
        envelope = PdfAssetEnvelope(replayed=outcome.replayed, asset=_asset_read(view))
    status = 200 if outcome.replayed else 201
    return json(
        envelope.model_dump(mode="json"),
        status=status,
        headers={
            "Location": f"/api/pdf-assets/{outcome.asset.id}",
            "Idempotency-Replayed": "true" if outcome.replayed else "false",
        },
    )


@pdf_blueprint.get("/pdf-assets", name="list_pdf_assets")
@openapi.operation("listPdfAssets")
@openapi.summary("List registered immutable PDF assets")
@openapi.tag("pdf")
@openapi.response(200, _media(PdfAssetList), "PDF assets")
async def list_pdf_assets(request: Request) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        views = await PdfPersistenceService(session).list_assets()
    payload = PdfAssetList(items=[_asset_read(view) for view in views])
    return json(payload.model_dump(mode="json"))


@pdf_blueprint.get("/pdf-assets/<asset_id:uuid>", name="get_pdf_asset")
@openapi.operation("getPdfAsset")
@openapi.summary("Read one registered immutable PDF asset")
@openapi.tag("pdf")
@openapi.response(200, _media(PdfAssetRead), "PDF asset")
@openapi.response(404, ERROR_SCHEMA, "PDF asset not found")
async def get_pdf_asset(request: Request, asset_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        view = await PdfPersistenceService(session).get_asset(asset_id)
    if view is None:
        raise ApiError(404, "not_found", "PDF asset not found")
    return json(_asset_read(view).model_dump(mode="json"))


@pdf_blueprint.post("/pdf-extractions", name="create_pdf_extraction")
@openapi.operation("createPdfExtraction")
@openapi.summary("Queue an immutable physical-page extraction request")
@openapi.tag("pdf")
@openapi.parameter("Idempotency-Key", str, "header", required=False)
@openapi.body(_media(PdfExtractionCreate), required=True)
@openapi.response(202, _media(PdfExtractionEnvelope), "PDF extraction queued")
@openapi.response(200, _media(PdfExtractionEnvelope), "Idempotent replay")
@openapi.response(404, ERROR_SCHEMA, "PDF asset not found")
@openapi.response(409, ERROR_SCHEMA, "Idempotency conflict")
@openapi.response(422, ERROR_SCHEMA, "Invalid extraction request")
async def create_pdf_extraction(request: Request) -> HTTPResponse:
    body = parse_body(request, PdfExtractionCreate)
    database = cast(Database, request.app.ctx.database)
    async with request.app.ctx.pdf_persistence_lock, database.session() as session, session.begin():
        service = PdfPersistenceService(session)
        outcome = await service.enqueue_extraction(
            pdf_asset_id=body.pdf_asset_id,
            first_page=body.first_page,
            last_page=body.last_page,
            idempotency_key=request.headers.get("idempotency-key"),
            profile=body.profile,
        )
        view = await service.get_extraction(outcome.run.id)
        if view is None:
            raise RuntimeError("registered ExtractionRun Job is missing")
        envelope = PdfExtractionEnvelope(
            replayed=outcome.replayed,
            extraction=_extraction_read(view),
        )
    status = 200 if outcome.replayed else 202
    return json(
        envelope.model_dump(mode="json"),
        status=status,
        headers={
            "Location": f"/api/pdf-extractions/{outcome.run.id}",
            "Idempotency-Replayed": "true" if outcome.replayed else "false",
        },
    )


@pdf_blueprint.get("/pdf-extractions/<run_id:uuid>", name="get_pdf_extraction")
@openapi.operation("getPdfExtraction")
@openapi.summary("Read one immutable extraction request and its Job state")
@openapi.tag("pdf")
@openapi.response(200, _media(PdfExtractionRead), "PDF extraction")
@openapi.response(404, ERROR_SCHEMA, "PDF extraction not found")
async def get_pdf_extraction(request: Request, run_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        view = await PdfPersistenceService(session).get_extraction(run_id)
    if view is None:
        raise ApiError(404, "not_found", "PDF extraction not found")
    return json(_extraction_read(view).model_dump(mode="json"))


@pdf_blueprint.get("/pdf-extractions", name="list_pdf_extractions")
@openapi.operation("listPdfExtractions")
@openapi.summary("List PDF extraction requests by real Job state")
@openapi.tag("pdf")
@openapi.parameter("status", str, "query", required=False)
@openapi.parameter("has_conflicts", bool, "query", required=False)
@openapi.response(200, _media(PdfExtractionList), "PDF extractions")
@openapi.response(422, ERROR_SCHEMA, "Invalid query filter")
async def list_pdf_extractions(request: Request) -> HTTPResponse:
    status = _status_filter(request)
    has_conflicts = _boolean_filter(request, "has_conflicts")
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        views = await PdfPersistenceService(session).list_extractions(
            status=status,
            has_conflicts=has_conflicts,
        )
    payload = PdfExtractionList(items=[_extraction_read(view) for view in views])
    return json(payload.model_dump(mode="json"))


def _multipart_upload(
    request: Request,
) -> tuple[bytes, str, str | None, PdfAssetUploadMetadata]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "multipart/form-data":
        raise ApiError(
            415,
            "unsupported_media_type",
            "Content-Type must be multipart/form-data",
        )
    file_names = set(request.files.keys()) if request.files is not None else set()
    form_names = set(request.form.keys()) if request.form is not None else set()
    if file_names - {"file"} or form_names - {"metadata"}:
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
    metadata_values = request.form.getlist("metadata") if request.form is not None else []
    if len(metadata_values) > 1:
        raise ApiError(422, "validation_error", "multipart body has duplicate metadata parts")
    metadata = PdfAssetUploadMetadata()
    if metadata_values:
        try:
            metadata = PdfAssetUploadMetadata.model_validate(
                json_module.loads(str(metadata_values[0]))
            )
        except (ValidationError, json_module.JSONDecodeError, TypeError) as error:
            raise _metadata_error(error) from error
    upload = files[0]
    return bytes(upload.body), upload.name, upload.type, metadata


def _metadata_error(error: Exception) -> ApiError:
    details: dict[str, Any] = {}
    if isinstance(error, ValidationError):
        details["errors"] = [
            {
                "type": item["type"],
                "loc": [str(part) for part in item["loc"]],
                "msg": item["msg"],
            }
            for item in error.errors(include_url=False)
        ]
    return ApiError(
        422,
        "validation_error",
        "multipart metadata failed validation",
        details or None,
    )


def _status_filter(request: Request) -> str | None:
    values = [str(value) for value in request.args.getlist("status")]
    if not values:
        return None
    if len(values) != 1 or values[0] not in JOB_STATUSES:
        raise ApiError(422, "validation_error", "status filter is invalid")
    return str(values[0])


def _boolean_filter(request: Request, name: str) -> bool | None:
    values = [str(value) for value in request.args.getlist(name)]
    if not values:
        return None
    if len(values) != 1 or values[0] not in {"true", "false"}:
        raise ApiError(422, "validation_error", f"{name} filter must be true or false")
    return values[0] == "true"


def _asset_read(view: PdfAssetView) -> PdfAssetRead:
    return PdfAssetRead(
        id=view.asset.id,
        content_sha256=view.asset.content_sha256,
        byte_size=view.asset.byte_size,
        page_count=view.asset.page_count,
        source_id=view.asset.source_id,
        source_version_id=view.asset.source_version_id,
        source_file_id=view.asset.source_file_id,
        filename=view.source_file.filename,
        title=view.source.title,
        author=view.source.author,
        edition=view.source_version.edition,
        created_at=view.asset.created_at,
    )


def _extraction_read(view: PdfExtractionView) -> PdfExtractionRead:
    return PdfExtractionRead(
        id=view.run.id,
        pdf_asset_id=view.run.pdf_asset_id,
        first_page=view.run.first_page,
        last_page=view.run.last_page,
        pipeline_version=view.run.pipeline_version,
        profile=view.profile,
        job=job_read(view.job),
        evidence=_evidence_summary(view),
        has_conflicts=False,
        created_at=view.run.created_at,
    )


def _evidence_summary(view: PdfExtractionView) -> PdfEvidenceSummary | None:
    if view.job.status != "succeeded":
        return None
    result = view.job.result
    expected_result_fields = {
        "run_id",
        "render_manifest_sha256",
        "ocr_manifest_sha256",
        "page_count",
        "fragment_count",
        "warning_count",
    }
    if not isinstance(result, dict) or set(result) != expected_result_fields:
        return None
    if result.get("run_id") != str(view.run.id):
        return None

    page_count = view.run.last_page - view.run.first_page + 1
    page_range = set(range(view.run.first_page, view.run.last_page + 1))
    relevant = [
        artifact
        for artifact in view.artifacts
        if artifact.kind in {"rendered_page", "ocr_fragment", "render_manifest", "ocr_manifest"}
    ]
    rendered_pages = {
        artifact.page_number for artifact in relevant if artifact.kind == "rendered_page"
    }
    evidence_pages = {
        artifact.page_number for artifact in relevant if artifact.kind == "ocr_fragment"
    }
    render_manifests = [
        artifact
        for artifact in relevant
        if artifact.kind == "render_manifest" and artifact.page_number is None
    ]
    ocr_manifests = [
        artifact
        for artifact in relevant
        if artifact.kind == "ocr_manifest" and artifact.page_number is None
    ]
    if (
        len(relevant) != page_count * 2 + 2
        or rendered_pages != page_range
        or evidence_pages != page_range
        or len(render_manifests) != 1
        or len(ocr_manifests) != 1
        or render_manifests[0].content_sha256 != result.get("render_manifest_sha256")
        or ocr_manifests[0].content_sha256 != result.get("ocr_manifest_sha256")
        or result.get("page_count") != page_count
    ):
        return None
    try:
        return PdfEvidenceSummary.model_validate(
            {
                "status": "committed",
                "page_count": result["page_count"],
                "fragment_count": result["fragment_count"],
                "warning_count": result["warning_count"],
                "render_manifest_sha256": result["render_manifest_sha256"],
                "ocr_manifest_sha256": result["ocr_manifest_sha256"],
            }
        )
    except ValidationError:
        return None
