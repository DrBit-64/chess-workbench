"""PDF source, extraction, review-read and review-ledger HTTP boundary."""

from __future__ import annotations

import asyncio
import json as json_module
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sanic import Blueprint, Request
from sanic.response import HTTPResponse, empty, json, raw
from sanic_ext import openapi
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.schemas.domain import ErrorResponse
from chess_workbench.schemas.pdf import (
    PdfAssetEnvelope,
    PdfAssetList,
    PdfAssetRead,
    PdfAssetUploadMetadata,
    PdfCandidateSummary,
    PdfEvidenceSummary,
    PdfExtractionCreate,
    PdfExtractionEnvelope,
    PdfExtractionList,
    PdfExtractionRead,
)
from chess_workbench.schemas.pdf_documents import (
    PdfExtractionDocumentAppendCreate,
    PdfExtractionDocumentAppendEnvelope,
    PdfExtractionDocumentAppendRead,
    PdfExtractionDocumentCreate,
    PdfExtractionDocumentEnvelope,
    PdfExtractionDocumentList,
    PdfExtractionDocumentRead,
    PdfExtractionDocumentRevisionRead,
    PdfExtractionDocumentSegmentRead,
)
from chess_workbench.schemas.review import (
    PdfReviewCommandEnvelope,
    PdfReviewCommandRequest,
    PdfReviewDocumentRead,
    PdfReviewPublicationRead,
    PdfReviewPublishRequest,
    PdfReviewSessionEnvelope,
    PdfReviewSessionRead,
)
from chess_workbench.services.jobs import job_read
from chess_workbench.services.pdf import prepare_pdf_asset
from chess_workbench.services.pdf_documents import (
    PdfDocumentAppendView,
    PdfDocumentService,
    PdfDocumentView,
)
from chess_workbench.services.pdf_extraction import PDF_EXTRACTION_RESULT_SCHEMA
from chess_workbench.services.pdf_persistence import (
    PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
    PDF_EVIDENCE_PIPELINE_VERSION,
    PDF_EXTRACTION_PIPELINE_VERSION,
    PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
    PdfAssetView,
    PdfExtractionView,
    PdfPersistenceService,
)
from chess_workbench.services.pdf_review import PdfReviewReadService
from chess_workbench.services.pdf_review_ledger import PdfReviewLedgerService
from chess_workbench.services.pdf_review_publication import PdfReviewPublicationService
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
            pipeline_version=PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
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


@pdf_blueprint.delete("/pdf-extractions/<run_id:uuid>", name="archive_pdf_extraction")
@openapi.operation("archivePdfExtraction")
@openapi.summary("Cancel active work and archive one PDF extraction result")
@openapi.tag("pdf")
@openapi.response(204, None, "PDF extraction archived")
@openapi.response(404, ERROR_SCHEMA, "PDF extraction not found")
async def archive_pdf_extraction(request: Request, run_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)

    async def archive(session: AsyncSession) -> bool:
        return await PdfPersistenceService(session).archive_extraction(run_id) is not None

    if not await database.run_write(archive):
        raise ApiError(404, "not_found", "PDF extraction not found")
    return empty(status=204)


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
    items = [_extraction_read(view) for view in views]
    if has_conflicts is not None:
        items = [item for item in items if item.has_conflicts is has_conflicts]
    payload = PdfExtractionList(items=items)
    return json(payload.model_dump(mode="json"))


@pdf_blueprint.post("/pdf-extraction-documents", name="create_pdf_extraction_document")
@openapi.operation("createPdfExtractionDocument")
@openapi.summary("Adopt one verified CCEF 1.1 run as an incremental document")
@openapi.tag("pdf")
@openapi.body(_media(PdfExtractionDocumentCreate), required=True)
@openapi.response(201, _media(PdfExtractionDocumentEnvelope), "PDF extraction document created")
@openapi.response(200, _media(PdfExtractionDocumentEnvelope), "Existing document replayed")
@openapi.response(404, ERROR_SCHEMA, "PDF extraction run not found")
@openapi.response(409, ERROR_SCHEMA, "PDF extraction run is not compatible")
@openapi.response(503, ERROR_SCHEMA, "Source storage unavailable")
async def create_pdf_extraction_document(request: Request) -> HTTPResponse:
    body = parse_body(request, PdfExtractionDocumentCreate)
    database = cast(Database, request.app.ctx.database)
    async with request.app.ctx.pdf_persistence_lock, database.session() as session, session.begin():
        service = PdfDocumentService(session, request.app.ctx.settings)
        outcome = await service.adopt_run(body.initial_run_id)
        view = await service.get_document(outcome.document.id)
        if view is None:
            raise RuntimeError("registered PDF extraction document is missing")
        envelope = PdfExtractionDocumentEnvelope(
            replayed=outcome.replayed,
            document=_pdf_document_read(view),
        )
    status = 200 if outcome.replayed else 201
    return json(
        envelope.model_dump(mode="json"),
        status=status,
        headers={
            "Location": f"/api/pdf-extraction-documents/{outcome.document.id}",
            "Idempotency-Replayed": "true" if outcome.replayed else "false",
        },
    )


@pdf_blueprint.get("/pdf-extraction-documents", name="list_pdf_extraction_documents")
@openapi.operation("listPdfExtractionDocuments")
@openapi.summary("List grouped incremental PDF extraction documents")
@openapi.tag("pdf")
@openapi.response(200, _media(PdfExtractionDocumentList), "PDF extraction documents")
async def list_pdf_extraction_documents(request: Request) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        views = await PdfDocumentService(session, request.app.ctx.settings).list_documents()
    payload = PdfExtractionDocumentList(items=[_pdf_document_read(view) for view in views])
    return json(payload.model_dump(mode="json"))


@pdf_blueprint.get(
    "/pdf-extraction-documents/<document_id:uuid>", name="get_pdf_extraction_document"
)
@openapi.operation("getPdfExtractionDocument")
@openapi.summary("Read one grouped incremental PDF extraction document")
@openapi.tag("pdf")
@openapi.response(200, _media(PdfExtractionDocumentRead), "PDF extraction document")
@openapi.response(404, ERROR_SCHEMA, "PDF extraction document not found")
async def get_pdf_extraction_document(request: Request, document_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        view = await PdfDocumentService(session, request.app.ctx.settings).get_document(document_id)
    if view is None:
        raise ApiError(404, "not_found", "PDF extraction document not found")
    return json(_pdf_document_read(view).model_dump(mode="json"))


@pdf_blueprint.post(
    "/pdf-extraction-documents/<document_id:uuid>/appends",
    name="create_pdf_extraction_document_append",
)
@openapi.operation("createPdfExtractionDocumentAppend")
@openapi.summary("Register one adjacent hash-bound incremental extraction attempt")
@openapi.tag("pdf")
@openapi.parameter("Idempotency-Key", str, "header", required=False)
@openapi.body(_media(PdfExtractionDocumentAppendCreate), required=True)
@openapi.response(202, _media(PdfExtractionDocumentAppendEnvelope), "Append attempt queued")
@openapi.response(200, _media(PdfExtractionDocumentAppendEnvelope), "Append attempt replayed")
@openapi.response(404, ERROR_SCHEMA, "PDF extraction document not found")
@openapi.response(409, ERROR_SCHEMA, "Stale, conflicting or active append")
@openapi.response(422, ERROR_SCHEMA, "Invalid append request")
async def create_pdf_extraction_document_append(
    request: Request, document_id: UUID
) -> HTTPResponse:
    body = parse_body(request, PdfExtractionDocumentAppendCreate)
    database = cast(Database, request.app.ctx.database)
    async with request.app.ctx.pdf_persistence_lock, database.session() as session, session.begin():
        service = PdfDocumentService(session, request.app.ctx.settings)
        outcome = await service.register_append(
            document_id=document_id,
            expected_version=body.expected_version,
            first_page=body.first_page,
            last_page=body.last_page,
            profile=body.profile,
            idempotency_key=request.headers.get("idempotency-key"),
        )
        view = await service.get_document(document_id)
        if view is None:
            raise RuntimeError("registered PDF extraction document is missing")
        append_view = next(
            item for item in view.append_attempts if item.append.id == outcome.append.id
        )
        envelope = PdfExtractionDocumentAppendEnvelope(
            replayed=outcome.replayed,
            append=_pdf_document_append_read(append_view),
            document=_pdf_document_read(view),
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


@pdf_blueprint.get("/pdf-extractions/<run_id:uuid>/review", name="get_pdf_extraction_review")
@openapi.operation("getPdfExtractionReview")
@openapi.summary("Read one verified PDF extraction review document")
@openapi.tag("pdf")
@openapi.response(200, _media(PdfReviewDocumentRead), "PDF extraction review document")
@openapi.response(404, ERROR_SCHEMA, "PDF extraction review not found")
@openapi.response(409, ERROR_SCHEMA, "PDF extraction review is not available")
@openapi.response(503, ERROR_SCHEMA, "Source storage unavailable")
async def get_pdf_extraction_review(request: Request, run_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        document = await PdfReviewLedgerService(
            session, request.app.ctx.settings
        ).get_target_document(run_id)
    return json(document.model_dump(mode="json"))


@pdf_blueprint.get(
    "/pdf-extractions/<run_id:uuid>/review/pages/<physical_page:int>",
    name="get_pdf_extraction_review_page",
)
@openapi.operation("getPdfExtractionReviewPage")
@openapi.summary("Read one verified rendered PDF review page")
@openapi.tag("pdf")
@openapi.response(
    200,
    {"image/png": {"type": "string", "format": "binary"}},
    "Verified rendered PDF review page",
)
@openapi.response(404, ERROR_SCHEMA, "PDF extraction review not found")
@openapi.response(409, ERROR_SCHEMA, "PDF extraction review is not available")
@openapi.response(503, ERROR_SCHEMA, "Source storage unavailable")
async def get_pdf_extraction_review_page(
    request: Request, run_id: UUID, physical_page: int
) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        content = await PdfReviewReadService(session, request.app.ctx.settings).read_page(
            run_id, physical_page
        )
    return raw(
        content.body,
        status=200,
        content_type=content.media_type,
        headers={
            "Content-Length": str(content.byte_size),
            "ETag": f'"{content.content_sha256}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@pdf_blueprint.post(
    "/pdf-extractions/<target_id:uuid>/review/session",
    name="create_pdf_review_session",
)
@openapi.operation("createPdfReviewSession")
@openapi.summary("Open a hash-bound review session for the current verified candidate")
@openapi.tag("pdf")
@openapi.response(201, _media(PdfReviewSessionEnvelope), "PDF review session created")
@openapi.response(200, _media(PdfReviewSessionEnvelope), "Existing PDF review session replayed")
@openapi.response(404, ERROR_SCHEMA, "PDF extraction review not found")
@openapi.response(409, ERROR_SCHEMA, "PDF extraction review or session is unavailable")
@openapi.response(503, ERROR_SCHEMA, "Source storage unavailable")
async def create_pdf_review_session(request: Request, target_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with request.app.ctx.pdf_persistence_lock, database.session() as session, session.begin():
        outcome = await PdfReviewLedgerService(session, request.app.ctx.settings).open_session(
            target_id
        )
        envelope = PdfReviewSessionEnvelope(
            replayed=outcome.replayed,
            session=outcome.session,
        )
    return json(
        envelope.model_dump(mode="json"),
        status=200 if outcome.replayed else 201,
        headers={
            "Location": f"/api/pdf-review-sessions/{outcome.session.id}",
            "Idempotency-Replayed": "true" if outcome.replayed else "false",
        },
    )


@pdf_blueprint.get(
    "/pdf-review-sessions/<session_id:uuid>",
    name="get_pdf_review_session",
)
@openapi.operation("getPdfReviewSession")
@openapi.summary("Read one immutable PDF review ledger")
@openapi.tag("pdf")
@openapi.response(200, _media(PdfReviewSessionRead), "PDF review session")
@openapi.response(404, ERROR_SCHEMA, "PDF review session not found")
@openapi.response(409, ERROR_SCHEMA, "PDF review session is unavailable")
async def get_pdf_review_session(request: Request, session_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await PdfReviewLedgerService(session, request.app.ctx.settings).get_session(
            session_id
        )
    return json(payload.model_dump(mode="json"))


@pdf_blueprint.get(
    "/pdf-review-sessions/<session_id:uuid>/document",
    name="get_pdf_review_session_document",
)
@openapi.operation("getPdfReviewSessionDocument")
@openapi.summary("Read the current immutable package revision of a PDF review session")
@openapi.tag("pdf")
@openapi.response(200, _media(PdfReviewDocumentRead), "Current PDF review document")
@openapi.response(404, ERROR_SCHEMA, "PDF review session not found")
@openapi.response(409, ERROR_SCHEMA, "PDF review session is unavailable")
@openapi.response(503, ERROR_SCHEMA, "Source storage unavailable")
async def get_pdf_review_session_document(request: Request, session_id: UUID) -> HTTPResponse:
    database = cast(Database, request.app.ctx.database)
    async with database.session() as session:
        payload = await PdfReviewLedgerService(
            session, request.app.ctx.settings
        ).get_session_document(session_id)
    return json(payload.model_dump(mode="json"))


@pdf_blueprint.post(
    "/pdf-review-sessions/<session_id:uuid>/commands",
    name="apply_pdf_review_command",
)
@openapi.operation("applyPdfReviewCommand")
@openapi.summary("Append one expected-version PDF review command")
@openapi.tag("pdf")
@openapi.body(_media(PdfReviewCommandRequest), required=True)
@openapi.response(200, _media(PdfReviewCommandEnvelope), "PDF review command applied")
@openapi.response(404, ERROR_SCHEMA, "PDF review session not found")
@openapi.response(409, ERROR_SCHEMA, "Review state or expected version conflict")
@openapi.response(422, ERROR_SCHEMA, "Review command could not be applied")
@openapi.response(503, ERROR_SCHEMA, "Source storage unavailable")
async def apply_pdf_review_command(request: Request, session_id: UUID) -> HTTPResponse:
    body = parse_body(request, PdfReviewCommandRequest)
    database = cast(Database, request.app.ctx.database)
    async with request.app.ctx.pdf_persistence_lock, database.session() as session, session.begin():
        payload = await PdfReviewLedgerService(session, request.app.ctx.settings).apply_command(
            session_id, body
        )
    return json(payload.model_dump(mode="json"))


@pdf_blueprint.post(
    "/pdf-review-sessions/<session_id:uuid>/publications",
    name="publish_pdf_review_selection",
)
@openapi.operation("publishPdfReviewSelection")
@openapi.summary("Publish selected approved review score fragments into one draft book")
@openapi.tag("pdf")
@openapi.body(_media(PdfReviewPublishRequest), required=True)
@openapi.response(201, _media(PdfReviewPublicationRead), "Review selection published")
@openapi.response(200, _media(PdfReviewPublicationRead), "Publication plan replayed")
@openapi.response(404, ERROR_SCHEMA, "Review session or target book not found")
@openapi.response(409, ERROR_SCHEMA, "Review state, hierarchy or target conflict")
@openapi.response(422, ERROR_SCHEMA, "Publication selection is invalid")
@openapi.response(503, ERROR_SCHEMA, "Source storage unavailable")
async def publish_pdf_review_selection(request: Request, session_id: UUID) -> HTTPResponse:
    body = parse_body(request, PdfReviewPublishRequest)
    database = cast(Database, request.app.ctx.database)
    async with request.app.ctx.pdf_persistence_lock, database.session() as session, session.begin():
        outcome = await PdfReviewPublicationService(session, request.app.ctx.settings).publish(
            session_id, body
        )
    return json(
        outcome.publication.model_dump(mode="json"),
        status=200 if outcome.replayed else 201,
        headers={
            "Location": f"/api/courses/{outcome.publication.target_course_id}",
            "Idempotency-Replayed": "true" if outcome.replayed else "false",
        },
    )


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
    evidence = _evidence_summary(view)
    candidate = _candidate_summary(view) if evidence is not None else None
    return PdfExtractionRead(
        id=view.run.id,
        pdf_asset_id=view.run.pdf_asset_id,
        first_page=view.run.first_page,
        last_page=view.run.last_page,
        pipeline_version=view.run.pipeline_version,
        profile=view.profile,
        job=job_read(view.job),
        evidence=evidence,
        candidate=candidate,
        has_conflicts=candidate.has_conflicts if candidate is not None else False,
        created_at=view.run.created_at,
    )


def _pdf_document_read(view: PdfDocumentView) -> PdfExtractionDocumentRead:
    return PdfExtractionDocumentRead(
        id=view.document.id,
        pdf_asset_id=view.document.pdf_asset_id,
        version=view.document.version,
        first_page=view.document.first_page,
        last_page=view.document.last_page,
        normalized_ccef_sha256=view.document.normalized_ccef_sha256,
        segments=[
            PdfExtractionDocumentSegmentRead(
                id=item.id,
                run_id=item.extraction_run_id,
                ordinal=item.ordinal,
                first_page=item.first_page,
                last_page=item.last_page,
                normalized_ccef_sha256=item.normalized_ccef_sha256,
                created_at=item.created_at,
            )
            for item in view.segments
        ],
        revisions=[
            PdfExtractionDocumentRevisionRead(
                id=item.id,
                predecessor_revision_id=item.predecessor_revision_id,
                terminal_segment_id=item.terminal_segment_id,
                revision_number=item.revision_number,
                segment_count=item.segment_count,
                first_page=item.first_page,
                last_page=item.last_page,
                algorithm_version=item.algorithm_version,
                normalized_ccef_sha256=item.normalized_ccef_sha256,
                created_at=item.created_at,
            )
            for item in view.revisions
        ],
        append_attempts=[_pdf_document_append_read(item) for item in view.append_attempts],
        created_at=view.document.created_at,
        updated_at=view.document.updated_at,
    )


def _pdf_document_append_read(view: PdfDocumentAppendView) -> PdfExtractionDocumentAppendRead:
    return PdfExtractionDocumentAppendRead(
        id=view.append.id,
        run_id=view.run.id,
        predecessor_revision_id=view.append.predecessor_revision_id,
        expected_version=view.append.expected_version,
        predecessor_normalized_ccef_sha256=view.append.predecessor_normalized_ccef_sha256,
        first_page=view.append.first_page,
        last_page=view.append.last_page,
        pipeline_version=view.run.pipeline_version,
        profile=cast(dict[str, Any], view.append.profile),
        job=job_read(view.job),
        created_at=view.append.created_at,
    )


def _evidence_summary(view: PdfExtractionView) -> PdfEvidenceSummary | None:
    if view.job.status != "succeeded":
        return None
    result = _evidence_result(view)
    expected_result_fields = {
        "run_id",
        "render_manifest_sha256",
        "ocr_manifest_sha256",
        "page_count",
        "fragment_count",
        "warning_count",
    }
    if result is None or set(result) != expected_result_fields:
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


def _evidence_result(view: PdfExtractionView) -> dict[str, Any] | None:
    result = view.job.result
    if not isinstance(result, dict):
        return None
    if view.run.pipeline_version == PDF_EVIDENCE_PIPELINE_VERSION:
        if "result_schema" in result:
            return None
        return result
    if (
        view.run.pipeline_version
        not in {
            PDF_EXTRACTION_PIPELINE_VERSION,
            PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
            PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
        }
        or result.get("result_schema") != PDF_EXTRACTION_RESULT_SCHEMA
    ):
        return None
    if set(result) != {"result_schema", "run_id", "evidence", "candidate"}:
        return None
    evidence = result.get("evidence")
    if not isinstance(evidence, dict):
        return None
    return {"run_id": result.get("run_id"), **cast(dict[str, Any], evidence)}


def _candidate_summary(view: PdfExtractionView) -> PdfCandidateSummary | None:
    if view.job.status != "succeeded":
        return None
    result = view.job.result
    if (
        view.run.pipeline_version
        not in {
            PDF_EXTRACTION_PIPELINE_VERSION,
            PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
            PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
        }
        or not isinstance(result, dict)
        or result.get("result_schema") != PDF_EXTRACTION_RESULT_SCHEMA
        or set(result) != {"result_schema", "run_id", "evidence", "candidate"}
        or result.get("run_id") != str(view.run.id)
    ):
        return None
    candidate = result.get("candidate")
    if not isinstance(candidate, dict) or set(candidate) != {
        "provider_response_sha256",
        "request_sha256",
        "response_sha256",
        "raw_ccef_sha256",
        "normalized_ccef_sha256",
        "summary",
    }:
        return None
    summary = candidate.get("summary")
    if not isinstance(summary, dict) or set(summary) != {
        "item_count",
        "move_node_count",
        "figure_count",
        "unresolved_item_count",
        "warning_count",
        "error_count",
        "invalid_move_count",
        "ambiguous_move_count",
        "has_conflicts",
    }:
        return None
    artifacts = [
        artifact
        for artifact in view.artifacts
        if artifact.kind in {"provider_response", "raw_ccef", "normalized_ccef"}
    ]
    slots = {(artifact.kind, artifact.page_number): artifact for artifact in artifacts}
    if len(artifacts) != 3 or set(slots) != {
        ("provider_response", None),
        ("raw_ccef", None),
        ("normalized_ccef", None),
    }:
        return None
    if (
        slots[("provider_response", None)].content_sha256
        != candidate.get("provider_response_sha256")
        or slots[("raw_ccef", None)].content_sha256 != candidate.get("raw_ccef_sha256")
        or slots[("normalized_ccef", None)].content_sha256
        != candidate.get("normalized_ccef_sha256")
    ):
        return None
    try:
        return PdfCandidateSummary.model_validate(
            {
                "status": "committed",
                "provider_response_sha256": candidate["provider_response_sha256"],
                "request_sha256": candidate["request_sha256"],
                "response_sha256": candidate["response_sha256"],
                "raw_ccef_sha256": candidate["raw_ccef_sha256"],
                "normalized_ccef_sha256": candidate["normalized_ccef_sha256"],
                **cast(dict[str, Any], summary),
            }
        )
    except ValidationError:
        return None
