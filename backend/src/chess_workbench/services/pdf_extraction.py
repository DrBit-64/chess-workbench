"""Stage 8B immutable PDF evidence artifacts and extraction Job handler."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.config import SecretFileError, Settings, load_deepseek_api_key
from chess_workbench.extraction.candidates import (
    CcefCandidateArtifacts,
    CcefCandidateError,
    assemble_ccef_candidate_artifacts,
    assemble_ccef_candidate_artifacts_v1_1,
    assemble_ccef_candidate_artifacts_v1_1_semantic,
    summarize_ccef_candidate,
)
from chess_workbench.extraction.contracts import ExtractionPackage, ExtractionPackageV1_1
from chess_workbench.extraction.decoder import CcefDecodeError
from chess_workbench.extraction.deepseek import (
    DeepSeekInvalidResponseRecorder,
    DeepSeekV4FlashProvider,
)
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
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    CcefPromptError,
    PromptEvidenceFragment,
    PromptEvidencePage,
    build_ccef_generation_request,
    build_ccef_v1_1_generation_request,
    build_ccef_v1_1_semantic_generation_request,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
)
from chess_workbench.services.ccef_failure_debug import (
    store_ccef_failure_capture,
    store_deepseek_invalid_response_capture,
)
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf_persistence import (
    PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
    PDF_EVIDENCE_PIPELINE_VERSION,
    PDF_EXTRACTION_PIPELINE_VERSION,
    PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
)
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
PDF_EXTRACTION_RESULT_SCHEMA = "chess-workbench/pdf-extraction-result/2.0"
_EVIDENCE_ARTIFACT_KINDS = frozenset(
    {"rendered_page", "ocr_fragment", "render_manifest", "ocr_manifest"}
)
_CCEF_ARTIFACT_KINDS = frozenset({"provider_response", "raw_ccef", "normalized_ccef"})
_SUPPORTED_PIPELINES = frozenset(
    {
        PDF_EVIDENCE_PIPELINE_VERSION,
        PDF_EXTRACTION_PIPELINE_VERSION,
        PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
        PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
        "pdf-extraction:v5",
    }
)
_MAX_RUN_FRAGMENTS = 200_000
_MAX_EVIDENCE_ARTIFACT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _ExtractionInput:
    run_id: UUID
    job_id: UUID
    pdf_asset_id: UUID
    source_file_id: UUID
    first_page: int
    last_page: int
    pdf_sha256: str
    pdf_size: int
    relative_path: str
    profile: dict[str, JsonValue]
    created_at: datetime
    pipeline_version: str
    attempt_count: int


@dataclass(frozen=True, slots=True)
class _ArtifactCandidate:
    kind: str
    page_number: int | None
    blob: StoredSourceBlob
    media_type: str

    @property
    def slot(self) -> tuple[str, int | None]:
        return self.kind, self.page_number


@dataclass(frozen=True, slots=True)
class _CommittedEvidence:
    context: CcefPromptContext
    result: dict[str, Any]


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
    common_keys = {
        "schema_version",
        "run_id",
        "pdf_asset_id",
        "first_page",
        "last_page",
        "pipeline_version",
        "profile",
    }
    pipeline_version = payload.get("pipeline_version") if type(payload) is dict else None
    expected_keys = common_keys
    if pipeline_version == "pdf-extraction:v5":
        expected_keys = common_keys | {
            "document_id",
            "expected_document_version",
            "predecessor_revision_id",
            "predecessor_normalized_ccef_sha256",
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
    expected_job_kind = (
        "pdf_incremental_extraction"
        if pipeline_version == "pdf-extraction:v5"
        else "pdf_extraction"
    )
    if (
        asset.id != asset_id
        or run.first_page != first_page
        or run.last_page != last_page
        or run.pipeline_version != pipeline_version
        or pipeline_version not in _SUPPORTED_PIPELINES
        or job.kind != expected_job_kind
        or job.payload != payload
        or source_file.sha256 != asset.content_sha256
        or source_file.size_bytes != asset.byte_size
    ):
        raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
    return _ExtractionInput(
        run_id=run.id,
        job_id=job.id,
        pdf_asset_id=asset.id,
        source_file_id=source_file.id,
        first_page=run.first_page,
        last_page=run.last_page,
        pdf_sha256=asset.content_sha256,
        pdf_size=asset.byte_size,
        relative_path=source_file.relative_path,
        profile=profile,
        created_at=run.created_at,
        pipeline_version=pipeline_version,
        attempt_count=job.attempt_count,
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
    *,
    artifact_kinds: frozenset[str],
) -> None:
    if any(candidate.kind not in artifact_kinds for candidate in candidates):
        raise EngineError(
            "artifact_conflict",
            "Extraction artifact kind is not allowed in this registration",
            retryable=False,
        )
    expected = {candidate.slot: candidate for candidate in candidates}
    if len(expected) != len(candidates):
        raise EngineError(
            "artifact_conflict",
            "Extraction artifact slots are not unique",
            retryable=False,
        )

    async def register(session: AsyncSession) -> None:
        locked_run = await session.scalar(
            select(ExtractionRun).where(ExtractionRun.id == source.run_id).with_for_update()
        )
        if locked_run is None:
            raise EngineError("invalid_job_payload", "PDF extraction Job payload is invalid")
        existing = list(
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == source.run_id,
                    ExtractionArtifact.kind.in_(artifact_kinds),
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
                    retryable=False,
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
                    retryable=False,
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

    try:
        await database.run_write(register)
    except IntegrityError:
        raise EngineError(
            "artifact_conflict",
            "Extraction artifact conflicts with an existing immutable artifact",
            retryable=False,
        ) from None


def _invalid_evidence() -> EngineError:
    return EngineError(
        "ccef_invalid_evidence",
        "Committed PDF evidence is invalid",
        retryable=False,
    )


def _parse_artifact_document(raw_bytes: bytes) -> dict[str, Any]:
    try:
        document = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _invalid_evidence() from None
    if not isinstance(document, dict):
        raise _invalid_evidence()
    return cast(dict[str, Any], document)


async def _read_artifact_bytes(
    settings: Settings,
    artifact: ExtractionArtifact,
) -> bytes:
    storage_error: ServiceError | None = None
    raw_bytes: bytes | None = None
    try:
        raw_bytes = await asyncio.to_thread(
            read_verified_content_addressed_bytes,
            settings.source_storage_root,
            relative_path=artifact.relative_path,
            expected_sha256=artifact.content_sha256,
            expected_size=artifact.byte_size,
            max_bytes=_MAX_EVIDENCE_ARTIFACT_BYTES,
        )
    except ServiceError as error:
        storage_error = error
    if storage_error is not None or raw_bytes is None:
        raise EngineError(
            "source_storage_unavailable",
            "source storage is unavailable",
            retryable=True,
        ) from None
    return raw_bytes


def _artifact_slots(
    artifacts: list[ExtractionArtifact],
) -> dict[tuple[str, int | None], ExtractionArtifact]:
    slots: dict[tuple[str, int | None], ExtractionArtifact] = {}
    for artifact in artifacts:
        slot = (artifact.kind, artifact.page_number)
        if slot in slots:
            raise _invalid_evidence()
        slots[slot] = artifact
    return slots


def _manifest_common_matches(document: dict[str, Any], source: _ExtractionInput) -> bool:
    return (
        document.get("artifact_schema") == PDF_EVIDENCE_ARTIFACT_SCHEMA
        and document.get("run_id") == str(source.run_id)
        and document.get("pdf_asset_id") == str(source.pdf_asset_id)
        and document.get("pdf_content_sha256") == source.pdf_sha256
        and document.get("first_page") == source.first_page
        and document.get("last_page") == source.last_page
    )


def _manifest_page_map(
    document: dict[str, Any],
    *,
    expected_pages: list[int],
) -> dict[int, dict[str, Any]]:
    pages = document.get("pages")
    if not isinstance(pages, list):
        raise _invalid_evidence()
    mapped: dict[int, dict[str, Any]] = {}
    for page in pages:
        if not isinstance(page, dict) or type(page.get("physical_page")) is not int:
            raise _invalid_evidence()
        physical_page = page["physical_page"]
        if physical_page in mapped:
            raise _invalid_evidence()
        mapped[physical_page] = cast(dict[str, Any], page)
    if list(mapped) != expected_pages:
        raise _invalid_evidence()
    return mapped


def _evidence_fragment(
    value: object,
    *,
    physical_page: int,
    expected_order: int,
) -> PromptEvidenceFragment:
    if not isinstance(value, dict) or set(value) != {
        "order",
        "physical_page",
        "bbox",
        "text",
        "origin",
        "confidence",
        "engine_name",
        "engine_version",
        "fragment_sha256",
    }:
        raise _invalid_evidence()
    if value.get("order") != expected_order or value.get("physical_page") != physical_page:
        raise _invalid_evidence()
    bbox = value.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise _invalid_evidence()
    try:
        box = NormalizedBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3])
        fragment = SourceEvidenceFragment(
            physical_page=physical_page,
            box=box,
            text=value["text"],
            origin=value["origin"],
            confidence=value["confidence"],
            engine_name=value["engine_name"],
            engine_version=value["engine_version"],
            fragment_sha256=value["fragment_sha256"],
        )
    except (ValidationError, KeyError, TypeError):
        raise _invalid_evidence() from None
    expected_hash = source_fragment_sha256(
        physical_page,
        fragment.box,
        fragment.text,
        fragment.origin,
        fragment.engine_name,
        fragment.engine_version,
    )
    if fragment.fragment_sha256 != expected_hash:
        raise _invalid_evidence()
    return PromptEvidenceFragment(order=expected_order, fragment=fragment)


async def _load_committed_evidence(
    database: Database,
    settings: Settings,
    source: _ExtractionInput,
) -> _CommittedEvidence | None:
    async with database.session() as session:
        artifacts = list(
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == source.run_id,
                    ExtractionArtifact.kind.in_(_EVIDENCE_ARTIFACT_KINDS),
                )
            )
        )
    if not artifacts:
        return None
    slots = _artifact_slots(artifacts)
    expected_pages = list(range(source.first_page, source.last_page + 1))
    expected_slots = {
        *(("rendered_page", page) for page in expected_pages),
        *(("ocr_fragment", page) for page in expected_pages),
        ("render_manifest", None),
        ("ocr_manifest", None),
    }
    if set(slots) != expected_slots:
        raise _invalid_evidence()

    render_manifest = _parse_artifact_document(
        await _read_artifact_bytes(settings, slots[("render_manifest", None)])
    )
    ocr_manifest = _parse_artifact_document(
        await _read_artifact_bytes(settings, slots[("ocr_manifest", None)])
    )
    if not _manifest_common_matches(render_manifest, source) or not _manifest_common_matches(
        ocr_manifest, source
    ):
        raise _invalid_evidence()
    render_pages = _manifest_page_map(render_manifest, expected_pages=expected_pages)
    ocr_pages = _manifest_page_map(ocr_manifest, expected_pages=expected_pages)

    prompt_pages: list[PromptEvidencePage] = []
    total_fragments = 0
    for physical_page in expected_pages:
        rendered_artifact = slots[("rendered_page", physical_page)]
        evidence_artifact = slots[("ocr_fragment", physical_page)]
        render_entry = render_pages[physical_page]
        evidence_entry = ocr_pages[physical_page]
        if (
            render_entry.get("content_sha256") != rendered_artifact.content_sha256
            or render_entry.get("byte_size") != rendered_artifact.byte_size
            or render_entry.get("media_type") != rendered_artifact.media_type
            or evidence_entry.get("content_sha256") != evidence_artifact.content_sha256
            or evidence_entry.get("byte_size") != evidence_artifact.byte_size
            or evidence_entry.get("media_type") != evidence_artifact.media_type
        ):
            raise _invalid_evidence()
        document = _parse_artifact_document(await _read_artifact_bytes(settings, evidence_artifact))
        fragments = document.get("fragments")
        if (
            set(document)
            != {
                "artifact_schema",
                "run_id",
                "pdf_asset_id",
                "physical_page",
                "width",
                "height",
                "origin",
                "engine_name",
                "engine_version",
                "fragments",
            }
            or document.get("artifact_schema") != PDF_EVIDENCE_ARTIFACT_SCHEMA
            or document.get("run_id") != str(source.run_id)
            or document.get("pdf_asset_id") != str(source.pdf_asset_id)
            or document.get("physical_page") != physical_page
            or not isinstance(fragments, list)
            or evidence_entry.get("fragment_count") != len(fragments)
        ):
            raise _invalid_evidence()
        entries = [
            _evidence_fragment(value, physical_page=physical_page, expected_order=order)
            for order, value in enumerate(fragments)
        ]
        total_fragments += len(entries)
        prompt_pages.append(PromptEvidencePage(physical_page=physical_page, fragments=entries))
    if ocr_manifest.get("fragment_count") != total_fragments:
        raise _invalid_evidence()
    language = ocr_manifest.get("ocr_language")
    if type(language) is not str:
        raise _invalid_evidence()
    warnings = ocr_manifest.get("warnings")
    if not isinstance(warnings, list):
        raise _invalid_evidence()
    try:
        context = CcefPromptContext(
            package_id=source.run_id,
            created_at=source.created_at,
            source_ref=f"source-file:{source.source_file_id}",
            media_type="application/pdf",
            language=language or None,
            first_page=source.first_page,
            last_page=source.last_page,
            pages=prompt_pages,
            max_output_tokens=settings.ccef_max_output_tokens,
            max_prompt_chars=settings.ccef_max_prompt_chars,
        )
    except ValidationError:
        raise _invalid_evidence() from None
    return _CommittedEvidence(
        context=context,
        result={
            "run_id": str(source.run_id),
            "render_manifest_sha256": slots[("render_manifest", None)].content_sha256,
            "ocr_manifest_sha256": slots[("ocr_manifest", None)].content_sha256,
            "page_count": len(expected_pages),
            "fragment_count": total_fragments,
            "warning_count": len(warnings),
        },
    )


async def _load_committed_candidate_result(
    database: Database,
    settings: Settings,
    source: _ExtractionInput,
    committed: _CommittedEvidence,
) -> dict[str, Any] | None:
    """Recover a fully persisted candidate without another provider call."""

    async with database.session() as session:
        artifacts = list(
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == source.run_id,
                    ExtractionArtifact.kind.in_(_CCEF_ARTIFACT_KINDS),
                )
            )
        )
    if not artifacts:
        return None
    slots = _artifact_slots(artifacts)
    expected_slots = {
        ("provider_response", None),
        ("raw_ccef", None),
        ("normalized_ccef", None),
    }
    if len(artifacts) != 3 or set(slots) != expected_slots:
        raise EngineError(
            "artifact_conflict",
            "Extraction candidate artifacts are incomplete or conflicting",
            retryable=False,
        )
    if any(
        artifact.media_type != "application/json"
        or artifact.byte_size <= 0
        or artifact.byte_size > _MAX_EVIDENCE_ARTIFACT_BYTES
        or artifact.relative_path
        != (f"derived/extraction/{artifact.content_sha256[:2]}/{artifact.content_sha256}.json")
        for artifact in slots.values()
    ):
        raise EngineError(
            "artifact_conflict",
            "Extraction candidate artifacts are incomplete or conflicting",
            retryable=False,
        )

    provider_bytes, raw_bytes, normalized_bytes = await asyncio.gather(
        _read_artifact_bytes(settings, slots[("provider_response", None)]),
        _read_artifact_bytes(settings, slots[("raw_ccef", None)]),
        _read_artifact_bytes(settings, slots[("normalized_ccef", None)]),
    )
    package_type: type[ExtractionPackage] | type[ExtractionPackageV1_1]
    expected_adapter_version: str
    if source.pipeline_version == PDF_EXTRACTION_PIPELINE_VERSION:
        package_type = ExtractionPackage
        expected_adapter_version = "1.0"
    else:
        package_type = ExtractionPackageV1_1
        expected_adapter_version = "1.1"
    try:
        raw_package = package_type.model_validate_json(raw_bytes)
        normalized_package = package_type.model_validate_json(normalized_bytes)
        provider_document = json.loads(provider_bytes)
    except (ValidationError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise EngineError(
            "artifact_conflict",
            "Extraction candidate artifacts are incomplete or conflicting",
            retryable=False,
        ) from None
    if not isinstance(provider_document, dict):
        raise EngineError(
            "artifact_conflict",
            "Extraction candidate artifacts are incomplete or conflicting",
            retryable=False,
        )
    if (
        _json_bytes(cast(dict[str, object], provider_document)) != provider_bytes
        or _json_bytes(cast(dict[str, object], raw_package.model_dump(mode="json"))) != raw_bytes
        or _json_bytes(cast(dict[str, object], normalized_package.model_dump(mode="json")))
        != normalized_bytes
    ):
        raise EngineError(
            "artifact_conflict",
            "Extraction candidate artifacts are incomplete or conflicting",
            retryable=False,
        )

    expected_source_ref = f"source-file:{source.source_file_id}"
    for package in (raw_package, normalized_package):
        page_range = package.source.page_range
        if (
            package.package_id != source.run_id
            or package.source.source_ref != expected_source_ref
            or package.source.media_type != "application/pdf"
            or page_range is None
            or page_range.start_page != source.first_page
            or page_range.end_page != source.last_page
            or package.provenance.created_at != source.created_at
            or package.provenance.adapter_name != "chess-workbench-ccef-prompt"
            or package.provenance.adapter_version != expected_adapter_version
            or package.provenance.provider is None
            or package.provenance.model is None
            or package.provenance.request_sha256 is None
            or package.provenance.response_sha256 is None
            or package.extensions != {}
        ):
            raise EngineError(
                "artifact_conflict",
                "Extraction candidate artifacts are incomplete or conflicting",
                retryable=False,
            )
    if raw_package.provenance != normalized_package.provenance:
        raise EngineError(
            "artifact_conflict",
            "Extraction candidate artifacts are incomplete or conflicting",
            retryable=False,
        )
    request_sha256 = normalized_package.provenance.request_sha256
    response_sha256 = normalized_package.provenance.response_sha256
    provider_schema = provider_document.get("artifact_schema")
    provider_identity: object = provider_document
    if provider_schema == "chess-workbench/ccef-repair-chain/2.1":
        provider_identity = provider_document.get("original_response")
    if not isinstance(provider_identity, dict):
        raise EngineError(
            "artifact_conflict",
            "Extraction candidate artifacts are incomplete or conflicting",
            retryable=False,
        )
    expected_provider_schema = (
        "chess-workbench/provider-response/1.0"
        if source.pipeline_version == PDF_EXTRACTION_PIPELINE_VERSION
        else "chess-workbench/provider-response/1.1"
    )
    allowed_provider_schemas = {expected_provider_schema}
    if source.pipeline_version != PDF_EXTRACTION_PIPELINE_VERSION:
        allowed_provider_schemas.add("chess-workbench/ccef-repair-chain/2.1")
    content = provider_identity.get("content")
    if (
        provider_schema not in allowed_provider_schemas
        or provider_document.get("request_sha256") != request_sha256
        or provider_identity.get("provider") != normalized_package.provenance.provider
        or provider_identity.get("model") != normalized_package.provenance.model
        or not isinstance(content, str)
        or hashlib.sha256(content.encode("utf-8")).hexdigest() != response_sha256
        or (
            provider_schema == expected_provider_schema
            and provider_document.get("response_sha256") != response_sha256
        )
    ):
        raise EngineError(
            "artifact_conflict",
            "Extraction candidate artifacts are incomplete or conflicting",
            retryable=False,
        )
    provider_response_sha256 = slots[("provider_response", None)].content_sha256
    raw_ccef_sha256 = slots[("raw_ccef", None)].content_sha256
    normalized_ccef_sha256 = slots[("normalized_ccef", None)].content_sha256
    return {
        "result_schema": PDF_EXTRACTION_RESULT_SCHEMA,
        "run_id": str(source.run_id),
        "evidence": {key: value for key, value in committed.result.items() if key != "run_id"},
        "candidate": {
            "provider_response_sha256": provider_response_sha256,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
            "raw_ccef_sha256": raw_ccef_sha256,
            "normalized_ccef_sha256": normalized_ccef_sha256,
            "summary": summarize_ccef_candidate(normalized_package).model_dump(mode="json"),
        },
    }


def _active_provider(
    settings: Settings,
    provider: StructuredGenerationProvider | None,
    *,
    thinking_enabled: bool = False,
    json_output_enabled: bool = True,
    invalid_response_recorder: DeepSeekInvalidResponseRecorder | None = None,
) -> StructuredGenerationProvider:
    if provider is not None:
        return provider
    try:
        api_key = load_deepseek_api_key(settings)
    except SecretFileError:
        raise EngineError(
            "provider_secret_invalid",
            "AI extraction provider secret file is unavailable or insecure",
            retryable=False,
        ) from None
    if api_key is None:
        raise EngineError(
            "provider_unconfigured",
            "AI extraction provider is not configured",
            retryable=False,
        )
    return DeepSeekV4FlashProvider(
        api_key=api_key.get_secret_value(),
        timeout_seconds=settings.ccef_provider_timeout_seconds,
        max_output_tokens_limit=settings.ccef_max_output_tokens,
        thinking_enabled=thinking_enabled,
        json_output_enabled=json_output_enabled,
        invalid_response_recorder=invalid_response_recorder,
    )


def _deepseek_invalid_response_recorder(
    settings: Settings,
    source: _ExtractionInput,
) -> DeepSeekInvalidResponseRecorder:
    async def record(
        response_bytes: bytes,
        status_code: int,
        diagnostics: tuple[str, ...],
    ) -> None:
        await asyncio.to_thread(
            store_deepseek_invalid_response_capture,
            settings.source_storage_root,
            run_id=source.run_id,
            job_id=source.job_id,
            attempt_count=source.attempt_count,
            pipeline_version=source.pipeline_version,
            response_bytes=response_bytes,
            status_code=status_code,
            diagnostics=diagnostics,
        )

    return record


async def _process_ccef_candidate(
    database: Database,
    settings: Settings,
    source: _ExtractionInput,
    committed: _CommittedEvidence,
    *,
    provider: StructuredGenerationProvider | None,
) -> dict[str, Any]:
    builder, assemble = _ccef_pipeline_functions(source.pipeline_version)
    try:
        request = builder(committed.context)
    except CcefPromptError as error:
        raise EngineError(f"ccef_{error.code}", str(error), retryable=False) from None
    active_provider = _active_provider(
        settings,
        provider,
        thinking_enabled=source.pipeline_version == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
        json_output_enabled=source.pipeline_version != PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
    )
    try:
        response = await active_provider.generate(request)
    except StructuredGenerationProviderError as error:
        raise EngineError(error.code, str(error), retryable=error.retryable) from None
    try:
        artifacts = assemble(committed.context, request, response)
    except CcefDecodeError as error:
        if source.pipeline_version == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION:
            await _capture_failed_generation(
                settings,
                source,
                response,
                error_code=f"ccef_{error.code}",
                error_message=str(error),
                diagnostics=error.diagnostics,
            )
        raise EngineError(
            f"ccef_{error.code}",
            str(error),
            retryable=(
                source.pipeline_version != PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION
                and error.code in {"invalid_json", "invalid_package"}
            ),
        ) from None
    except CcefCandidateError as error:
        if source.pipeline_version == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION:
            await _capture_failed_generation(
                settings,
                source,
                response,
                error_code=f"ccef_{error.code}",
                error_message=str(error),
                diagnostics=error.diagnostics,
            )
        raise EngineError(
            f"ccef_{error.code}",
            str(error),
            retryable=(
                source.pipeline_version != PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION
                and error.code == "semantic_incomplete"
            ),
        ) from None

    provider_blob = await _store_blob(
        settings, suffix=".json", raw_bytes=artifacts.provider_response_bytes
    )
    raw_blob = await _store_blob(settings, suffix=".json", raw_bytes=artifacts.raw_ccef_bytes)
    normalized_blob = await _store_blob(
        settings, suffix=".json", raw_bytes=artifacts.normalized_ccef_bytes
    )
    await _register_artifacts(
        database,
        source,
        [
            _ArtifactCandidate("provider_response", None, provider_blob, "application/json"),
            _ArtifactCandidate("raw_ccef", None, raw_blob, "application/json"),
            _ArtifactCandidate("normalized_ccef", None, normalized_blob, "application/json"),
        ],
        artifact_kinds=_CCEF_ARTIFACT_KINDS,
    )
    return {
        "result_schema": PDF_EXTRACTION_RESULT_SCHEMA,
        "run_id": str(source.run_id),
        "evidence": {key: value for key, value in committed.result.items() if key != "run_id"},
        "candidate": {
            "provider_response_sha256": provider_blob.sha256,
            "request_sha256": artifacts.request_sha256,
            "response_sha256": artifacts.response_sha256,
            "raw_ccef_sha256": artifacts.raw_ccef_sha256,
            "normalized_ccef_sha256": artifacts.normalized_ccef_sha256,
            "summary": artifacts.summary.model_dump(mode="json"),
        },
    }


async def _capture_failed_generation(
    settings: Settings,
    source: _ExtractionInput,
    response: StructuredGenerationResponse,
    *,
    error_code: str,
    error_message: str,
    diagnostics: tuple[str, ...],
) -> None:
    try:
        await asyncio.to_thread(
            store_ccef_failure_capture,
            settings.source_storage_root,
            run_id=source.run_id,
            job_id=source.job_id,
            attempt_count=source.attempt_count,
            pipeline_version=source.pipeline_version,
            response=response,
            error_code=error_code,
            error_message=error_message,
            diagnostics=diagnostics,
        )
    except (ServiceError, OSError, ValueError):
        raise EngineError(
            "ccef_failure_capture_failed",
            "Failed CCEF response could not be retained for local diagnosis",
            retryable=False,
        ) from None


def _ccef_pipeline_functions(
    pipeline_version: str,
) -> tuple[
    Callable[[CcefPromptContext], StructuredGenerationRequest],
    Callable[
        [CcefPromptContext, StructuredGenerationRequest, StructuredGenerationResponse],
        CcefCandidateArtifacts,
    ],
]:
    """Version-explicit builder/assembler selection from the trusted pipeline.

    The choice comes only from the persisted pipeline identity; response
    content, provider metadata and artifact presence are never inspected.
    """
    if pipeline_version == PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION:
        return build_ccef_v1_1_generation_request, assemble_ccef_candidate_artifacts_v1_1
    if pipeline_version == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION:
        return (
            build_ccef_v1_1_semantic_generation_request,
            assemble_ccef_candidate_artifacts_v1_1_semantic,
        )
    if pipeline_version == PDF_EXTRACTION_PIPELINE_VERSION:
        return build_ccef_generation_request, assemble_ccef_candidate_artifacts
    raise EngineError(
        "invalid_job_payload", "PDF extraction Job payload is invalid", retryable=False
    )


async def process_pdf_extraction_job(
    database: Database,
    settings: Settings,
    payload: dict[str, Any],
    *,
    renderer: PdfPageRenderer | None = None,
    ocr_adapter: OcrAdapter | None = None,
    provider: StructuredGenerationProvider | None = None,
) -> dict[str, Any]:
    """Render one immutable run, write CAS blobs, then atomically register indexes."""
    source = await _load_input(database, payload)
    active_provider: StructuredGenerationProvider | None = provider
    if payload["pipeline_version"] == "pdf-extraction:v5":
        committed = await _load_committed_evidence(database, settings, source)
        if committed is not None:
            return committed.result
    if payload["pipeline_version"] in {
        PDF_EXTRACTION_PIPELINE_VERSION,
        PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
        PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
    }:
        is_semantic_v4 = payload["pipeline_version"] == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION
        committed = await _load_committed_evidence(database, settings, source)
        if committed is not None:
            restored = await _load_committed_candidate_result(database, settings, source, committed)
            if restored is not None:
                return restored
            active_provider = _active_provider(
                settings,
                provider,
                thinking_enabled=is_semantic_v4,
                json_output_enabled=not is_semantic_v4,
                invalid_response_recorder=(
                    _deepseek_invalid_response_recorder(settings, source)
                    if is_semantic_v4
                    else None
                ),
            )
            return await _process_ccef_candidate(
                database,
                settings,
                source,
                committed,
                provider=active_provider,
            )
        active_provider = _active_provider(
            settings,
            provider,
            thinking_enabled=is_semantic_v4,
            json_output_enabled=not is_semantic_v4,
            invalid_response_recorder=(
                _deepseek_invalid_response_recorder(settings, source) if is_semantic_v4 else None
            ),
        )
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
            raise EngineError(
                evidence_error.code,
                evidence_error.message,
                retryable=evidence_error.retryable,
            ) from None

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
                "evidence_limit_exceeded",
                "PDF extraction produced too many text fragments",
                retryable=False,
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
    await _register_artifacts(
        database,
        source,
        candidates,
        artifact_kinds=_EVIDENCE_ARTIFACT_KINDS,
    )
    committed = await _load_committed_evidence(database, settings, source)
    if committed is None:
        raise RuntimeError("registered evidence artifacts are missing")
    if payload["pipeline_version"] in {
        PDF_EVIDENCE_PIPELINE_VERSION,
        "pdf-extraction:v5",
    }:
        return committed.result
    return await _process_ccef_candidate(
        database,
        settings,
        source,
        committed,
        provider=active_provider,
    )


__all__ = [
    "PDF_EVIDENCE_ARTIFACT_SCHEMA",
    "PDF_EXTRACTION_RESULT_SCHEMA",
    "process_pdf_extraction_job",
]
