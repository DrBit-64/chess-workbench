"""Stage 8B immutable PDF evidence artifacts and extraction Job handler."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from chess_workbench.config import Settings
from chess_workbench.extraction.evidence import (
    EvidenceOrigin,
    NormalizedBox,
    OcrAdapter,
    OcrRequest,
    PdfEvidenceError,
    PdfPageRenderer,
    RenderedPage,
    RenderProfile,
    SourceEvidenceFragment,
    TextFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.paddleocr import PaddleOcrJsonAdapter
from chess_workbench.extraction.pdfium import PdfiumPageRenderer
from chess_workbench.services.content import ServiceError
from chess_workbench.services.source_storage import (
    StoredSourceBlob,
    read_verified_content_addressed_bytes,
    store_content_addressed_bytes,
)
from chess_workbench.services.uci import EngineError
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    ExtractionArtifact,
    ExtractionRun,
    Job,
    PdfAsset,
    SourceFile,
)

PDF_EVIDENCE_ARTIFACT_SCHEMA = "chess-workbench/pdf-evidence/1.0"
_ARTIFACT_KINDS = frozenset({"rendered_page", "ocr_fragment", "render_manifest", "ocr_manifest"})
_MAX_RUN_FRAGMENTS = 200_000


@dataclass(frozen=True, slots=True)
class _ExtractionInput:
    run_id: UUID
    job_id: UUID
    pdf_asset_id: UUID
    first_page: int
    last_page: int
    pdf_sha256: str
    pdf_size: int
    relative_path: str
    profile: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class _ArtifactCandidate:
    kind: str
    page_number: int | None
    blob: StoredSourceBlob
    media_type: str

    @property
    def slot(self) -> tuple[str, int | None]:
        return self.kind, self.page_number


def _json_bytes(document: dict[str, object]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _snapshot_profile(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid") from None
    return cast(dict[str, JsonValue], decoded)


def _parse_uuid(value: object) -> UUID:
    if type(value) is not str:
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    try:
        return UUID(value)
    except ValueError:
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid") from None


def _parse_payload(
    payload: dict[str, Any],
) -> tuple[UUID, UUID, int, int, str, dict[str, JsonValue]]:
    expected_keys = {
        "schema_version",
        "run_id",
        "pdf_asset_id",
        "first_page",
        "last_page",
        "pipeline_version",
        "profile",
    }
    if type(payload) is not dict or set(payload) != expected_keys:
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    first_page = payload["first_page"]
    last_page = payload["last_page"]
    pipeline_version = payload["pipeline_version"]
    if (
        type(first_page) is not int
        or type(last_page) is not int
        or first_page < 1
        or last_page < first_page
        or type(pipeline_version) is not str
        or not pipeline_version
    ):
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    return (
        _parse_uuid(payload["run_id"]),
        _parse_uuid(payload["pdf_asset_id"]),
        first_page,
        last_page,
        pipeline_version,
        _snapshot_profile(payload["profile"]),
    )


async def _load_input(database: Database, payload: dict[str, Any]) -> _ExtractionInput:
    run_id, asset_id, first_page, last_page, pipeline_version, profile = _parse_payload(payload)
    async with database.session() as session:
        row = (
            await session.execute(
                select(ExtractionRun, PdfAsset, SourceFile, Job)
                .join(PdfAsset, PdfAsset.id == ExtractionRun.pdf_asset_id)
                .join(SourceFile, SourceFile.id == PdfAsset.source_file_id)
                .join(Job, Job.id == ExtractionRun.job_id)
                .where(ExtractionRun.id == run_id)
            )
        ).one_or_none()
    if row is None:
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    run, asset, source_file, job = row
    if (
        asset.id != asset_id
        or run.first_page != first_page
        or run.last_page != last_page
        or run.pipeline_version != pipeline_version
        or job.kind != "pdf_extraction"
        or job.payload != payload
        or source_file.sha256 != asset.content_sha256
        or source_file.size_bytes != asset.byte_size
    ):
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    return _ExtractionInput(
        run_id=run.id,
        job_id=job.id,
        pdf_asset_id=asset.id,
        first_page=run.first_page,
        last_page=run.last_page,
        pdf_sha256=asset.content_sha256,
        pdf_size=asset.byte_size,
        relative_path=source_file.relative_path,
        profile=profile,
    )


def _render_profile(profile: dict[str, JsonValue]) -> RenderProfile:
    candidate = profile.get("render", {})
    if not isinstance(candidate, dict):
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    try:
        return RenderProfile.model_validate(candidate)
    except ValidationError:
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid") from None


def _ocr_settings(profile: dict[str, JsonValue]) -> tuple[str, dict[str, JsonValue]]:
    language = profile.get("ocr_language", "")
    ocr_profile = profile.get("ocr", {})
    if type(language) is not str or not isinstance(ocr_profile, dict):
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    return language, ocr_profile


def _non_whitespace_count(page: RenderedPage) -> int:
    return sum(
        1
        for fragment in page.embedded_fragments
        for character in fragment.text
        if not character.isspace()
    )


def _source_fragments(
    fragments: list[TextFragment],
    *,
    physical_page: int,
    width: int,
    height: int,
    origin: EvidenceOrigin,
    engine_name: str,
    engine_version: str,
) -> list[SourceEvidenceFragment]:
    normalized: list[SourceEvidenceFragment] = []
    for fragment in fragments:
        box = NormalizedBox(
            x0=fragment.box.x0 / width,
            y0=fragment.box.y0 / height,
            x1=fragment.box.x1 / width,
            y1=fragment.box.y1 / height,
        )
        digest = source_fragment_sha256(
            physical_page,
            box,
            fragment.text,
            origin,
            engine_name,
            engine_version,
        )
        normalized.append(
            SourceEvidenceFragment(
                physical_page=physical_page,
                box=box,
                text=fragment.text,
                origin=origin,
                confidence=fragment.confidence,
                engine_name=engine_name,
                engine_version=engine_version,
                fragment_sha256=digest,
            )
        )
    return normalized


def _fragment_document(
    source: _ExtractionInput,
    page: RenderedPage,
    *,
    origin: EvidenceOrigin,
    engine_name: str,
    engine_version: str,
    fragments: list[SourceEvidenceFragment],
) -> bytes:
    return _json_bytes(
        {
            "artifact_schema": PDF_EVIDENCE_ARTIFACT_SCHEMA,
            "run_id": str(source.run_id),
            "pdf_asset_id": str(source.pdf_asset_id),
            "physical_page": page.physical_page,
            "width": page.width,
            "height": page.height,
            "origin": origin,
            "engine_name": engine_name,
            "engine_version": engine_version,
            "fragments": [
                {
                    "order": order,
                    "physical_page": fragment.physical_page,
                    "bbox": [
                        fragment.box.x0,
                        fragment.box.y0,
                        fragment.box.x1,
                        fragment.box.y1,
                    ],
                    "text": fragment.text,
                    "origin": fragment.origin,
                    "confidence": fragment.confidence,
                    "engine_name": fragment.engine_name,
                    "engine_version": fragment.engine_version,
                    "fragment_sha256": fragment.fragment_sha256,
                }
                for order, fragment in enumerate(fragments)
            ],
        }
    )


async def _store_blob(settings: Settings, *, suffix: str, raw_bytes: bytes) -> StoredSourceBlob:
    storage_error: ServiceError | None = None
    result: StoredSourceBlob | None = None
    try:
        result = await asyncio.to_thread(
            store_content_addressed_bytes,
            settings.source_storage_root,
            namespace="derived/extraction",
            suffix=suffix,
            raw_bytes=raw_bytes,
        )
    except ServiceError as error:
        storage_error = error
    if storage_error is not None or result is None:
        raise EngineError("source_storage_unavailable", "source storage is unavailable") from None
    return result


async def _register_artifacts(
    database: Database,
    source: _ExtractionInput,
    candidates: list[_ArtifactCandidate],
) -> None:
    expected = {candidate.slot: candidate for candidate in candidates}
    if len(expected) != len(candidates):
        raise EngineError("artifact_conflict", "Extraction artifact slots are not unique")
    try:
        async with database.session() as session, session.begin():
            locked_run = await session.scalar(
                select(ExtractionRun).where(ExtractionRun.id == source.run_id).with_for_update()
            )
            if locked_run is None:
                raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
            existing = list(
                await session.scalars(
                    select(ExtractionArtifact).where(
                        ExtractionArtifact.run_id == source.run_id,
                        ExtractionArtifact.kind.in_(_ARTIFACT_KINDS),
                    )
                )
            )
            seen: set[tuple[str, int | None]] = set()
            for artifact in existing:
                slot = (artifact.kind, artifact.page_number)
                candidate = expected.get(slot)
                if slot in seen or candidate is None:
                    raise EngineError(
                        "artifact_conflict",
                        "Extraction artifact conflicts with an existing immutable artifact",
                    )
                seen.add(slot)
                if (
                    artifact.relative_path != candidate.blob.relative_path
                    or artifact.content_sha256 != candidate.blob.sha256
                    or artifact.byte_size != candidate.blob.size_bytes
                    or artifact.media_type != candidate.media_type
                ):
                    raise EngineError(
                        "artifact_conflict",
                        "Extraction artifact conflicts with an existing immutable artifact",
                    )
            for slot, candidate in expected.items():
                if slot in seen:
                    continue
                session.add(
                    ExtractionArtifact(
                        run_id=source.run_id,
                        kind=candidate.kind,
                        page_number=candidate.page_number,
                        relative_path=candidate.blob.relative_path,
                        media_type=candidate.media_type,
                        byte_size=candidate.blob.size_bytes,
                        content_sha256=candidate.blob.sha256,
                    )
                )
            await session.flush()
    except IntegrityError:
        raise EngineError(
            "artifact_conflict",
            "Extraction artifact conflicts with an existing immutable artifact",
        ) from None


async def process_pdf_extraction_job(
    database: Database,
    settings: Settings,
    payload: dict[str, Any],
    *,
    renderer: PdfPageRenderer | None = None,
    ocr_adapter: OcrAdapter | None = None,
) -> dict[str, Any]:
    """Render one immutable run, write CAS blobs, then atomically register indexes."""
    source = await _load_input(database, payload)
    render_profile = _render_profile(source.profile)
    language, ocr_profile = _ocr_settings(source.profile)
    active_renderer = renderer or PdfiumPageRenderer()
    active_ocr = ocr_adapter or PaddleOcrJsonAdapter(
        None if settings.paddle_ocr_runner_path is None else [str(settings.paddle_ocr_runner_path)]
    )

    storage_error: ServiceError | None = None
    try:
        pdf_bytes = await asyncio.to_thread(
            read_verified_content_addressed_bytes,
            settings.source_storage_root,
            relative_path=source.relative_path,
            expected_sha256=source.pdf_sha256,
            expected_size=source.pdf_size,
            max_bytes=settings.pdf_max_bytes,
        )
    except ServiceError as error:
        storage_error = error
    if storage_error is not None:
        raise EngineError(storage_error.code, storage_error.message) from None

    candidates: list[_ArtifactCandidate] = []
    render_pages: list[dict[str, object]] = []
    evidence_pages: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    fragment_count = 0

    for physical_page in range(source.first_page, source.last_page + 1):
        evidence_error: PdfEvidenceError | None = None
        try:
            rendered = await asyncio.to_thread(
                active_renderer.render_page,
                pdf_bytes,
                physical_page,
                render_profile,
            )
            rendered_blob = await _store_blob(settings, suffix=".png", raw_bytes=rendered.png_bytes)
            if _non_whitespace_count(rendered) >= render_profile.embedded_text_min_chars:
                origin: EvidenceOrigin = "embedded_text"
                engine_name = rendered.renderer_name
                engine_version = rendered.renderer_version
                raw_fragments = rendered.embedded_fragments
            else:
                ocr_result = await active_ocr.recognize(
                    OcrRequest(
                        physical_page=physical_page,
                        width=rendered.width,
                        height=rendered.height,
                        png_bytes=rendered.png_bytes,
                        language=language,
                        profile=ocr_profile,
                    )
                )
                if (
                    ocr_result.physical_page != physical_page
                    or ocr_result.width != rendered.width
                    or ocr_result.height != rendered.height
                ):
                    raise PdfEvidenceError(
                        "ocr_invalid_output", "OCR runner returned invalid output", False
                    )
                origin = "ocr"
                engine_name = ocr_result.engine_name
                engine_version = ocr_result.engine_version
                raw_fragments = ocr_result.fragments
        except PdfEvidenceError as error:
            evidence_error = error
        if evidence_error is not None:
            raise EngineError(evidence_error.code, evidence_error.message) from None

        fragments = _source_fragments(
            raw_fragments,
            physical_page=physical_page,
            width=rendered.width,
            height=rendered.height,
            origin=origin,
            engine_name=engine_name,
            engine_version=engine_version,
        )
        fragment_count += len(fragments)
        if fragment_count > _MAX_RUN_FRAGMENTS:
            raise EngineError(
                "evidence_limit_exceeded", "PDF extraction produced too many text fragments"
            )
        if not fragments:
            warnings.append({"code": "empty_page", "physical_page": physical_page})
        evidence_blob = await _store_blob(
            settings,
            suffix=".json",
            raw_bytes=_fragment_document(
                source,
                rendered,
                origin=origin,
                engine_name=engine_name,
                engine_version=engine_version,
                fragments=fragments,
            ),
        )
        candidates.extend(
            [
                _ArtifactCandidate(
                    kind="rendered_page",
                    page_number=physical_page,
                    blob=rendered_blob,
                    media_type="image/png",
                ),
                _ArtifactCandidate(
                    kind="ocr_fragment",
                    page_number=physical_page,
                    blob=evidence_blob,
                    media_type="application/json",
                ),
            ]
        )
        render_pages.append(
            {
                "physical_page": physical_page,
                "width": rendered.width,
                "height": rendered.height,
                "dpi": rendered.dpi,
                "renderer_name": rendered.renderer_name,
                "renderer_version": rendered.renderer_version,
                "content_sha256": rendered_blob.sha256,
                "byte_size": rendered_blob.size_bytes,
                "media_type": "image/png",
            }
        )
        evidence_pages.append(
            {
                "physical_page": physical_page,
                "origin": origin,
                "engine_name": engine_name,
                "engine_version": engine_version,
                "fragment_count": len(fragments),
                "content_sha256": evidence_blob.sha256,
                "byte_size": evidence_blob.size_bytes,
                "media_type": "application/json",
            }
        )
        await asyncio.sleep(0)

    manifest_common: dict[str, object] = {
        "artifact_schema": PDF_EVIDENCE_ARTIFACT_SCHEMA,
        "run_id": str(source.run_id),
        "pdf_asset_id": str(source.pdf_asset_id),
        "pdf_content_sha256": source.pdf_sha256,
        "first_page": source.first_page,
        "last_page": source.last_page,
    }
    render_manifest = await _store_blob(
        settings,
        suffix=".json",
        raw_bytes=_json_bytes(
            {
                **manifest_common,
                "render_profile": render_profile.model_dump(mode="json"),
                "pages": render_pages,
            }
        ),
    )
    ocr_manifest = await _store_blob(
        settings,
        suffix=".json",
        raw_bytes=_json_bytes(
            {
                **manifest_common,
                "ocr_language": language,
                "ocr_profile": ocr_profile,
                "pages": evidence_pages,
                "fragment_count": fragment_count,
                "warnings": warnings,
            }
        ),
    )
    candidates.extend(
        [
            _ArtifactCandidate("render_manifest", None, render_manifest, "application/json"),
            _ArtifactCandidate("ocr_manifest", None, ocr_manifest, "application/json"),
        ]
    )
    await _register_artifacts(database, source, candidates)
    return {
        "run_id": str(source.run_id),
        "render_manifest_sha256": render_manifest.sha256,
        "ocr_manifest_sha256": ocr_manifest.sha256,
        "page_count": source.last_page - source.first_page + 1,
        "fragment_count": fragment_count,
        "warning_count": len(warnings),
    }


__all__ = ["PDF_EVIDENCE_ARTIFACT_SCHEMA", "process_pdf_extraction_job"]
