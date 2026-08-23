"""Server-side read-only review loader (packet DS-STAGE8D-REVIEW-LOADER-01).

Loads one completed reviewable extraction's normalized CCEF and rendered-page registry
from immutable CAS, verifies their bindings, and returns the accepted 8D-2A
document/page values.  This module adds no HTTP route, schema, SQL model,
migration, frontend or generated contract, never accepts a caller-supplied
path, and never writes to the database session.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackage, ExtractionPackageV1_1
from chess_workbench.extraction.evidence import MAX_PNG_BYTES
from chess_workbench.review.inspection import ReviewInspection, inspect_review_candidate
from chess_workbench.schemas.review import PdfReviewDocumentRead, PdfReviewPageRead
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf_extraction import (
    PDF_EVIDENCE_ARTIFACT_SCHEMA,
    PDF_EXTRACTION_RESULT_SCHEMA,
)
from chess_workbench.services.pdf_persistence import (
    PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
    PDF_EXTRACTION_PIPELINE_VERSION,
    PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
    PdfExtractionView,
    PdfPersistenceService,
)
from chess_workbench.services.source_storage import read_verified_content_addressed_bytes
from chess_workbench.store.models import (
    ExtractionArtifact,
    PdfAsset,
    PdfExtractionDocument,
    PdfExtractionDocumentRevision,
    PdfExtractionDocumentSegment,
)

_REVIEW_NOT_FOUND = "PDF extraction review was not found"
_REVIEW_UNAVAILABLE = "PDF extraction review is not available"
_PAGE_NOT_FOUND = "PDF review page was not found"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_JSON_ARTIFACT_BYTES = 64 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_RELEVANT_KINDS = frozenset({"normalized_ccef", "render_manifest", "rendered_page"})
_RESULT_KEYS = frozenset({"result_schema", "run_id", "evidence", "candidate"})
_CANDIDATE_KEYS = frozenset(
    {
        "provider_response_sha256",
        "request_sha256",
        "response_sha256",
        "raw_ccef_sha256",
        "normalized_ccef_sha256",
        "summary",
    }
)
_SUMMARY_KEYS = frozenset(
    {
        "item_count",
        "move_node_count",
        "figure_count",
        "unresolved_item_count",
        "warning_count",
        "error_count",
        "invalid_move_count",
        "ambiguous_move_count",
        "has_conflicts",
    }
)
_RENDER_MANIFEST_KEYS = frozenset(
    {
        "artifact_schema",
        "run_id",
        "pdf_asset_id",
        "pdf_content_sha256",
        "first_page",
        "last_page",
        "render_profile",
        "pages",
    }
)
_RENDER_PAGE_KEYS = frozenset(
    {
        "physical_page",
        "width",
        "height",
        "dpi",
        "renderer_name",
        "renderer_version",
        "content_sha256",
        "byte_size",
        "media_type",
    }
)


@dataclass(frozen=True, slots=True)
class PdfReviewPageContent:
    """Exact verified immutable PNG bytes for one rendered review page."""

    body: bytes
    media_type: Literal["image/png"]
    byte_size: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class _ResolvedReview:
    run_id: UUID
    first_page: int
    last_page: int
    normalized_ccef_sha256: str
    package: ExtractionPackage | ExtractionPackageV1_1
    inspection: ReviewInspection
    rendered_by_page: dict[int, ExtractionArtifact]


def _missing() -> ServiceError:
    return ServiceError("not_found", 404, _REVIEW_NOT_FOUND)


def _unavailable() -> ServiceError:
    return ServiceError("ambiguous_context", 409, _REVIEW_UNAVAILABLE)


def _page_missing() -> ServiceError:
    return ServiceError("not_found", 404, _PAGE_NOT_FOUND)


class PdfReviewReadService:
    """Read-only loader of one completed review document and its pages."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def read_document(self, run_id: UUID) -> PdfReviewDocumentRead:
        if type(run_id) is not UUID:
            raise TypeError("run_id must be UUID")
        resolved = await self._resolve_review(run_id)
        pages = [
            PdfReviewPageRead(
                physical_page=page,
                media_type="image/png",
                byte_size=artifact.byte_size,
                content_sha256=artifact.content_sha256,
                content_url=f"/api/pdf-extractions/{run_id}/review/pages/{page}",
            )
            for page, artifact in sorted(resolved.rendered_by_page.items())
        ]
        try:
            return PdfReviewDocumentRead(
                run_id=resolved.run_id,
                normalized_ccef_sha256=resolved.normalized_ccef_sha256,
                package=resolved.package,
                inspection=resolved.inspection,
                pages=pages,
            )
        except (ValidationError, ValueError):
            raise _unavailable() from None

    async def read_page(self, run_id: UUID, physical_page: int) -> PdfReviewPageContent:
        if type(run_id) is not UUID:
            raise TypeError("run_id must be UUID")
        if isinstance(physical_page, bool) or not isinstance(physical_page, int):
            raise TypeError("physical_page must be int")
        resolved = await self._resolve_review(run_id)
        if physical_page < resolved.first_page or physical_page > resolved.last_page:
            raise _page_missing() from None
        artifact = resolved.rendered_by_page[physical_page]
        body = await self._read_artifact_bytes(artifact, MAX_PNG_BYTES)
        if not body.startswith(_PNG_SIGNATURE):
            raise _unavailable() from None
        return PdfReviewPageContent(
            body=body,
            media_type="image/png",
            byte_size=artifact.byte_size,
            content_sha256=artifact.content_sha256,
        )

    async def _resolve_review(self, run_id: UUID) -> _ResolvedReview:
        persistence = PdfPersistenceService(self.session)
        view = await persistence.get_extraction(run_id)
        if view is None:
            return await self._resolve_document_review(run_id)
        run = view.run
        job = view.job
        if (
            run.pipeline_version
            not in (
                PDF_EXTRACTION_PIPELINE_VERSION,
                PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
                PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
            )
            or job.status != "succeeded"
        ):
            raise _unavailable() from None
        result = job.result
        if not isinstance(result, dict):
            raise _unavailable() from None
        if (
            set(result) != _RESULT_KEYS
            or result.get("result_schema") != PDF_EXTRACTION_RESULT_SCHEMA
            or result.get("run_id") != str(run_id)
        ):
            raise _unavailable() from None
        candidate = result.get("candidate")
        if not isinstance(candidate, dict) or set(candidate) != _CANDIDATE_KEYS:
            raise _unavailable() from None
        normalized_ccef_sha256 = candidate.get("normalized_ccef_sha256")
        if (
            not isinstance(normalized_ccef_sha256, str)
            or _SHA256_PATTERN.fullmatch(normalized_ccef_sha256) is None
        ):
            raise _unavailable() from None
        summary = candidate.get("summary")
        if not isinstance(summary, dict) or set(summary) != _SUMMARY_KEYS:
            raise _unavailable() from None
        evidence = result.get("evidence")
        if not isinstance(evidence, dict):
            raise _unavailable() from None
        render_manifest_sha256 = evidence.get("render_manifest_sha256")
        if (
            not isinstance(render_manifest_sha256, str)
            or _SHA256_PATTERN.fullmatch(render_manifest_sha256) is None
        ):
            raise _unavailable() from None

        expected_pages, first_page, last_page, asset = await self._bounded_run_pages(
            persistence, view
        )
        slots: dict[tuple[str, int | None], ExtractionArtifact] = {}
        for artifact in view.artifacts:
            if artifact.kind not in _RELEVANT_KINDS:
                continue
            slot = (artifact.kind, artifact.page_number)
            if slot in slots:
                raise _unavailable() from None
            slots[slot] = artifact
        expected_slots = frozenset(
            {("normalized_ccef", None), ("render_manifest", None)}
            | {("rendered_page", page) for page in expected_pages}
        )
        if set(slots) != expected_slots:
            raise _unavailable() from None
        normalized_artifact = slots[("normalized_ccef", None)]
        manifest_artifact = slots[("render_manifest", None)]
        rendered_by_page = {page: slots[("rendered_page", page)] for page in expected_pages}

        # Every registered relevant hash must be canonical lowercase 64-hex
        # before any descriptor is produced.
        for artifact in slots.values():
            if (
                not isinstance(artifact.content_sha256, str)
                or _SHA256_PATTERN.fullmatch(artifact.content_sha256) is None
            ):
                raise _unavailable() from None

        if (
            normalized_artifact.media_type != "application/json"
            or manifest_artifact.media_type != "application/json"
            or normalized_artifact.byte_size <= 0
            or normalized_artifact.byte_size > _MAX_JSON_ARTIFACT_BYTES
            or manifest_artifact.byte_size <= 0
            or manifest_artifact.byte_size > _MAX_JSON_ARTIFACT_BYTES
        ):
            raise _unavailable() from None
        for artifact in rendered_by_page.values():
            if (
                artifact.media_type != "image/png"
                or artifact.byte_size <= 0
                or artifact.byte_size > MAX_PNG_BYTES
            ):
                raise _unavailable() from None

        if (
            normalized_ccef_sha256 != normalized_artifact.content_sha256
            or render_manifest_sha256 != manifest_artifact.content_sha256
        ):
            raise _unavailable() from None

        manifest_bytes = await self._read_artifact_bytes(
            manifest_artifact, _MAX_JSON_ARTIFACT_BYTES
        )
        manifest_document = _parse_json_object(manifest_bytes)
        if manifest_document is None or set(manifest_document) != _RENDER_MANIFEST_KEYS:
            raise _unavailable() from None
        if (
            manifest_document.get("artifact_schema") != PDF_EVIDENCE_ARTIFACT_SCHEMA
            or manifest_document.get("run_id") != str(run_id)
            or manifest_document.get("pdf_asset_id") != str(view.run.pdf_asset_id)
            or manifest_document.get("pdf_content_sha256") != asset.content_sha256
            or manifest_document.get("first_page") != first_page
            or manifest_document.get("last_page") != last_page
        ):
            raise _unavailable() from None
        render_pages = _render_page_map(manifest_document.get("pages"), expected_pages)
        for page, entry in render_pages.items():
            artifact = rendered_by_page[page]
            if (
                entry.get("physical_page") != page
                or entry.get("content_sha256") != artifact.content_sha256
                or entry.get("byte_size") != artifact.byte_size
                or entry.get("media_type") != artifact.media_type
            ):
                raise _unavailable() from None

        normalized_bytes = await self._read_artifact_bytes(
            normalized_artifact, _MAX_JSON_ARTIFACT_BYTES
        )
        package = _parse_package(normalized_bytes, pipeline_version=run.pipeline_version)
        if package is None:
            raise _unavailable() from None
        source_range = package.source.page_range
        if (
            package.package_id != run_id
            or source_range is None
            or source_range.start_page != first_page
            or source_range.end_page != last_page
        ):
            raise _unavailable() from None
        try:
            inspection = inspect_review_candidate(package)
        except ValueError:
            raise _unavailable() from None

        return _ResolvedReview(
            run_id=run_id,
            first_page=first_page,
            last_page=last_page,
            normalized_ccef_sha256=normalized_ccef_sha256,
            package=package,
            inspection=inspection,
            rendered_by_page=rendered_by_page,
        )

    async def _resolve_document_review(self, document_id: UUID) -> _ResolvedReview:
        document = await self.session.get(PdfExtractionDocument, document_id)
        if document is None:
            raise _missing() from None
        revision = await self.session.scalar(
            select(PdfExtractionDocumentRevision).where(
                PdfExtractionDocumentRevision.document_id == document.id,
                PdfExtractionDocumentRevision.revision_number == document.version,
            )
        )
        segments = tuple(
            await self.session.scalars(
                select(PdfExtractionDocumentSegment)
                .where(PdfExtractionDocumentSegment.document_id == document.id)
                .order_by(PdfExtractionDocumentSegment.ordinal)
            )
        )
        if (
            revision is None
            or revision.normalized_ccef_sha256 != document.normalized_ccef_sha256
            or revision.first_page != document.first_page
            or revision.last_page != document.last_page
            or len(segments) != document.version
        ):
            raise _unavailable() from None
        expected_first = document.first_page
        run_ids: list[UUID] = []
        for ordinal, segment in enumerate(segments, start=1):
            if (
                segment.ordinal != ordinal
                or segment.first_page != expected_first
                or segment.last_page < segment.first_page
            ):
                raise _unavailable() from None
            expected_first = segment.last_page + 1
            run_ids.append(segment.extraction_run_id)
        if expected_first != document.last_page + 1:
            raise _unavailable() from None

        rendered = tuple(
            await self.session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id.in_(run_ids),
                    ExtractionArtifact.kind == "rendered_page",
                )
            )
        )
        rendered_by_page: dict[int, ExtractionArtifact] = {}
        for artifact in rendered:
            page = artifact.page_number
            if (
                type(page) is not int
                or page in rendered_by_page
                or page < document.first_page
                or page > document.last_page
                or artifact.media_type != "image/png"
                or artifact.byte_size <= 0
                or artifact.byte_size > MAX_PNG_BYTES
                or _SHA256_PATTERN.fullmatch(artifact.content_sha256) is None
            ):
                raise _unavailable() from None
            rendered_by_page[page] = artifact
        expected_pages = set(range(document.first_page, document.last_page + 1))
        if set(rendered_by_page) != expected_pages:
            raise _unavailable() from None

        try:
            normalized_bytes = await asyncio.to_thread(
                read_verified_content_addressed_bytes,
                self.settings.source_storage_root,
                relative_path=revision.relative_path,
                expected_sha256=revision.normalized_ccef_sha256,
                expected_size=revision.byte_size,
                max_bytes=_MAX_JSON_ARTIFACT_BYTES,
            )
        except ServiceError:
            raise
        except (TypeError, ValueError):
            raise _unavailable() from None
        package = _parse_package(
            normalized_bytes,
            pipeline_version=PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
        )
        if not isinstance(package, ExtractionPackageV1_1):
            raise _unavailable() from None
        source_range = package.source.page_range
        if (
            package.package_id != document.id
            or source_range is None
            or source_range.start_page != document.first_page
            or source_range.end_page != document.last_page
        ):
            raise _unavailable() from None
        try:
            inspection = inspect_review_candidate(package)
        except ValueError:
            raise _unavailable() from None
        return _ResolvedReview(
            run_id=document.id,
            first_page=document.first_page,
            last_page=document.last_page,
            normalized_ccef_sha256=document.normalized_ccef_sha256,
            package=package,
            inspection=inspection,
            rendered_by_page=rendered_by_page,
        )

    async def _bounded_run_pages(
        self, persistence: PdfPersistenceService, view: PdfExtractionView
    ) -> tuple[list[int], int, int, PdfAsset]:
        """Load the asset and validate the run range before any allocation.

        The page range is materialized only after exact-int bounds pass, so a
        corrupt run row can never allocate an unbounded list.
        """
        asset_view = await persistence.get_asset(view.run.pdf_asset_id)
        if asset_view is None:
            raise _unavailable() from None
        asset = asset_view.asset
        first_page = view.run.first_page
        last_page = view.run.last_page
        if (
            type(first_page) is not int
            or type(last_page) is not int
            or first_page < 1
            or last_page < first_page
            or last_page > asset.page_count
            or asset.page_count > 20_000
        ):
            raise _unavailable() from None
        return list(range(first_page, last_page + 1)), first_page, last_page, asset

    async def _read_artifact_bytes(self, artifact: ExtractionArtifact, max_bytes: int) -> bytes:
        try:
            return await asyncio.to_thread(
                read_verified_content_addressed_bytes,
                self.settings.source_storage_root,
                relative_path=artifact.relative_path,
                expected_sha256=artifact.content_sha256,
                expected_size=artifact.byte_size,
                max_bytes=max_bytes,
            )
        except ServiceError:
            # source_storage_unavailable from the verified CAS reader propagates
            # unchanged; no other ServiceError type originates here.
            raise
        except (TypeError, ValueError):
            raise _unavailable() from None


def _parse_json_object(raw_bytes: bytes) -> dict[str, Any] | None:
    try:
        document = json.loads(raw_bytes)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    return cast(dict[str, Any], document)


def _parse_package(
    raw_bytes: bytes, *, pipeline_version: str
) -> ExtractionPackage | ExtractionPackageV1_1 | None:
    try:
        if pipeline_version == PDF_EXTRACTION_PIPELINE_VERSION:
            return ExtractionPackage.model_validate_json(raw_bytes)
        if pipeline_version in (
            PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
            PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
        ):
            return ExtractionPackageV1_1.model_validate_json(raw_bytes)
        return None
    except (ValidationError, UnicodeDecodeError, ValueError):
        return None


def _render_page_map(pages: object, expected_pages: list[int]) -> dict[int, dict[str, Any]]:
    if not isinstance(pages, list):
        raise _unavailable() from None
    mapped: dict[int, dict[str, Any]] = {}
    for page in pages:
        if not isinstance(page, dict) or set(page) != _RENDER_PAGE_KEYS:
            raise _unavailable() from None
        physical_page = page.get("physical_page")
        if type(physical_page) is not int or physical_page in mapped:
            raise _unavailable() from None
        # Strict int: JSON true must never bind to database integer 1.
        if type(page.get("byte_size")) is not int:
            raise _unavailable() from None
        mapped[physical_page] = cast(dict[str, Any], page)
    if list(mapped) != expected_pages:
        raise _unavailable() from None
    return mapped


__all__ = ["PdfReviewPageContent", "PdfReviewReadService"]
