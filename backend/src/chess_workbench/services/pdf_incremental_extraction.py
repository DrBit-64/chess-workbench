"""Queued incremental PDF extraction and document-head commit."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from chess_workbench.config import Settings
from chess_workbench.extraction.candidates import _decode_fragment_bound_response_v1_1
from chess_workbench.extraction.contracts import (
    ExtractionPackageV1_1,
    FenPosition,
    MoveSequenceItemV1_1,
    PageRange,
    ccef_v1_1_schema_document,
)
from chess_workbench.extraction.decoder import CcefDecodeError
from chess_workbench.extraction.general_repair import (
    CcefRepairError,
    apply_ccef_repair,
    build_ccef_repair_request,
    canonicalize_ccef_response,
    ccef_repair_chain_document,
)
from chess_workbench.extraction.incremental import (
    CcefContinuationContext,
    build_ccef_continuation_context,
    compose_incremental_ccef,
)
from chess_workbench.extraction.pdfium import PdfiumPageRenderer
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    build_ccef_v1_1_semantic_generation_request,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    StructuredMessage,
)
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf_documents import (
    PDF_INCREMENTAL_EXTRACTION_JOB_KIND,
    PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    PdfDocumentService,
)
from chess_workbench.services.pdf_extraction import (
    _CCEF_ARTIFACT_KINDS,
    _active_provider,
    _ArtifactCandidate,
    _capture_failed_generation,
    _CommittedEvidence,
    _deepseek_invalid_response_recorder,
    _ExtractionInput,
    _load_committed_evidence,
    _load_input,
    _read_artifact_bytes,
    _register_artifacts,
    _render_profile,
    _store_blob,
    process_pdf_extraction_job,
)
from chess_workbench.services.source_storage import read_verified_content_addressed_bytes
from chess_workbench.services.uci import EngineError
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    ExtractionArtifact,
    ExtractionRun,
    Job,
    PdfAsset,
    PdfExtractionDocument,
    PdfExtractionDocumentAppend,
    PdfExtractionDocumentRevision,
    PdfExtractionDocumentSegment,
    SourceFile,
)

_BINDING_EXTENSION_KEY = "chess-workbench.continuation"
_MAX_CCEF_BYTES = 64 * 1024 * 1024
_INCREMENTAL_RESULT_SCHEMA = "chess-workbench/pdf-incremental-extraction-result/1.0"
_INCREMENTAL_RULES = """\
This is an incremental extraction request. The evidence pages are new; the continuation context
and previous-page tail are trusted context-only data and must never be cited as new evidence.
Do not repeat moves already present in the continuation path tails.
For every move_sequence that continues a prior sequence, choose the exact legal anchor where its
first printed move is played. Set that sequence's initial_position to kind "fen" with exactly the
anchor position_fen, and set item.extensions["chess-workbench.continuation"] to exactly
{"base_normalized_ccef_sha256": <context hash>, "anchor_id": <chosen anchor id>}.
Different printed continuations may choose different anchors, including a main line and an earlier
alternative. Never merge them merely because they belong to the same game; the later local binder
will graft each sequence at its declared anchor.
For a genuinely new independent game or score, use its source-supported initial position and leave
item.extensions empty. All top-level package extensions must remain empty.
Only new-page source fragments may appear in EvidenceRef values. Return one CCEF 1.1 JSON object.
For each EvidenceRef, select evidence with only its exact page and fragment_sha256; omit bbox,
start_offset, and end_offset or set them to null because trusted local code supplies those fields.
Treat every local identifier as an opaque identity, not as a label derived only from move notation.
Within each move_sequence, every node id must be unique, every annotation id must be unique, and
node and annotation ids must not collide even when the same move or wording appears in different
branches. Every reading_flow reference must name its corresponding node or annotation exactly once.
Before returning JSON, compare the node-id and annotation-id counts with their distinct-id counts,
then verify that the ordered move and annotation projections in reading_flow exactly match the
nodes and annotations arrays.
"""


@dataclass(frozen=True, slots=True)
class _IncrementalInput:
    source: _ExtractionInput
    document_id: UUID
    base_package: ExtractionPackageV1_1
    base_sha256: str
    previous_page_text: tuple[str, ...]


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _invalid_payload() -> EngineError:
    return EngineError(
        "invalid_job_payload", "PDF incremental extraction Job payload is invalid", retryable=False
    )


async def _load_incremental_input(
    database: Database,
    settings: Settings,
    payload: dict[str, Any],
) -> _IncrementalInput:
    source = await _load_input(database, payload)
    try:
        document_id = UUID(payload["document_id"])
        predecessor_id = UUID(payload["predecessor_revision_id"])
    except (KeyError, TypeError, ValueError):
        raise _invalid_payload() from None

    async with database.session() as session:
        row = (
            await session.execute(
                select(
                    PdfExtractionDocumentAppend,
                    ExtractionRun,
                    Job,
                    PdfExtractionDocument,
                    PdfExtractionDocumentRevision,
                    PdfAsset,
                    SourceFile,
                )
                .join(
                    ExtractionRun,
                    ExtractionRun.id == PdfExtractionDocumentAppend.extraction_run_id,
                )
                .join(Job, Job.id == ExtractionRun.job_id)
                .join(
                    PdfExtractionDocument,
                    PdfExtractionDocument.id == PdfExtractionDocumentAppend.document_id,
                )
                .join(
                    PdfExtractionDocumentRevision,
                    PdfExtractionDocumentRevision.id
                    == PdfExtractionDocumentAppend.predecessor_revision_id,
                )
                .join(PdfAsset, PdfAsset.id == ExtractionRun.pdf_asset_id)
                .join(SourceFile, SourceFile.id == PdfAsset.source_file_id)
                .where(ExtractionRun.id == source.run_id)
            )
        ).one_or_none()
        if row is None:
            raise _invalid_payload()
        append, run, job, document, predecessor, asset, source_file = row
        terminal_segment = await session.get(
            PdfExtractionDocumentSegment, predecessor.terminal_segment_id
        )
        previous_artifacts: tuple[ExtractionArtifact, ...] = ()
        if terminal_segment is not None:
            previous_artifacts = tuple(
                await session.scalars(
                    select(ExtractionArtifact).where(
                        ExtractionArtifact.run_id == terminal_segment.extraction_run_id,
                        ExtractionArtifact.kind == "ocr_fragment",
                        ExtractionArtifact.page_number == predecessor.last_page,
                    )
                )
            )

    expected_version = payload.get("expected_document_version")
    predecessor_hash = payload.get("predecessor_normalized_ccef_sha256")
    if (
        job.kind != PDF_INCREMENTAL_EXTRACTION_JOB_KIND
        or job.payload != payload
        or run.pipeline_version != PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION
        or append.document_id != document_id
        or append.predecessor_revision_id != predecessor_id
        or append.expected_version != expected_version
        or append.predecessor_normalized_ccef_sha256 != predecessor_hash
        or predecessor.normalized_ccef_sha256 != predecessor_hash
        or document.pdf_asset_id != asset.id
        or run.pdf_asset_id != asset.id
        or source_file.id != source.source_file_id
        or run.first_page != predecessor.last_page + 1
        or run.last_page != append.last_page
        or terminal_segment is None
        or len(previous_artifacts) > 1
    ):
        raise _invalid_payload()

    try:
        base_bytes = await asyncio.to_thread(
            read_verified_content_addressed_bytes,
            settings.source_storage_root,
            relative_path=predecessor.relative_path,
            expected_sha256=predecessor.normalized_ccef_sha256,
            expected_size=predecessor.byte_size,
            max_bytes=_MAX_CCEF_BYTES,
        )
        base_package = ExtractionPackageV1_1.model_validate_json(base_bytes)
        canonical_base = _json_bytes(base_package.model_dump(mode="json"))
        if (
            canonical_base != base_bytes
            or hashlib.sha256(canonical_base).hexdigest() != predecessor_hash
        ):
            raise ValueError
        if previous_artifacts:
            previous_bytes = await _read_artifact_bytes(settings, previous_artifacts[0])
            previous_document = json.loads(previous_bytes)
            fragments = previous_document.get("fragments")
            if not isinstance(fragments, list):
                raise ValueError
            previous_page_text = tuple(
                fragment["text"]
                for fragment in fragments
                if isinstance(fragment, dict) and isinstance(fragment.get("text"), str)
            )
        else:
            pdf_bytes = await asyncio.to_thread(
                read_verified_content_addressed_bytes,
                settings.source_storage_root,
                relative_path=source_file.relative_path,
                expected_sha256=source_file.sha256,
                expected_size=source_file.size_bytes,
                max_bytes=settings.pdf_max_bytes,
            )
            rendered = await asyncio.to_thread(
                PdfiumPageRenderer().render_page,
                pdf_bytes,
                predecessor.last_page,
                _render_profile(source.profile),
            )
            previous_page_text = tuple(fragment.text for fragment in rendered.embedded_fragments)
    except (ServiceError, ValidationError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise EngineError(
            "incremental_context_invalid",
            "PDF incremental extraction context is unavailable",
            retryable=False,
        ) from None

    return _IncrementalInput(
        source=source,
        document_id=document_id,
        base_package=base_package,
        base_sha256=predecessor.normalized_ccef_sha256,
        previous_page_text=previous_page_text,
    )


def _incremental_request(
    prompt_context: CcefPromptContext,
    continuation_context: CcefContinuationContext,
    previous_page_text: tuple[str, ...],
) -> StructuredGenerationRequest:
    base = build_ccef_v1_1_semantic_generation_request(prompt_context)
    trusted_context = {
        "continuation_context": continuation_context.model_dump(mode="json"),
        "previous_page_tail_context_only": list(previous_page_text),
    }
    return StructuredGenerationRequest(
        messages=[
            base.messages[0],
            StructuredMessage(
                role="system",
                content=_INCREMENTAL_RULES
                + "\nTrusted context:\n"
                + json.dumps(
                    trusted_context,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
            base.messages[1],
        ],
        response_schema_name=base.response_schema_name,
        response_schema=ccef_v1_1_schema_document(),
        max_output_tokens=base.max_output_tokens,
    )


def _check_metadata(package: ExtractionPackageV1_1, context: CcefPromptContext) -> None:
    if (
        package.package_id != context.package_id
        or package.source.source_ref != context.source_ref
        or package.source.media_type != context.media_type
        or package.source.language != context.language
        or package.source.page_range
        != PageRange(start_page=context.first_page, end_page=context.last_page)
        or package.provenance.created_at != context.created_at
        or package.provenance.adapter_name != "chess-workbench-ccef-prompt"
        or package.provenance.adapter_version != "1.1"
        or package.provenance.provider is not None
        or package.provenance.model is not None
        or package.provenance.request_sha256 is not None
        or package.provenance.response_sha256 is not None
        or package.extensions != {}
    ):
        raise ValueError("incremental response metadata mismatch")


def _bind_continuations(
    package: ExtractionPackageV1_1,
    continuation_context: CcefContinuationContext,
) -> ExtractionPackageV1_1:
    bound_package = package.model_copy(deep=True)
    anchors = {
        anchor.id: anchor
        for sequence in continuation_context.sequences
        for anchor in sequence.anchors
    }
    for item in bound_package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        value = item.extensions.get(_BINDING_EXTENSION_KEY)
        if value is None:
            continue
        if not isinstance(value, dict) or set(value) != {
            "base_normalized_ccef_sha256",
            "anchor_id",
        }:
            raise ValueError("malformed continuation binding")
        anchor_id = value.get("anchor_id")
        anchor = anchors.get(anchor_id) if isinstance(anchor_id, str) else None
        if (
            value.get("base_normalized_ccef_sha256")
            != continuation_context.base_normalized_ccef_sha256
            or anchor is None
        ):
            raise ValueError("unknown continuation binding")
        item.initial_position = FenPosition(kind="fen", fen=anchor.position_fen)
    return ExtractionPackageV1_1.model_validate(bound_package.model_dump(mode="json"))


async def _load_normalized_candidate(
    database: Database,
    settings: Settings,
    source: _ExtractionInput,
) -> tuple[ExtractionPackageV1_1, str] | None:
    async with database.session() as session:
        artifacts = tuple(
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == source.run_id,
                    ExtractionArtifact.kind.in_(_CCEF_ARTIFACT_KINDS),
                )
            )
        )
    if not artifacts:
        return None
    slots = {(artifact.kind, artifact.page_number): artifact for artifact in artifacts}
    if len(slots) != 3 or set(slots) != {
        ("provider_response", None),
        ("raw_ccef", None),
        ("normalized_ccef", None),
    }:
        raise EngineError(
            "artifact_conflict", "Incremental extraction artifacts are incomplete", retryable=False
        )
    normalized_artifact = slots[("normalized_ccef", None)]
    try:
        raw = await _read_artifact_bytes(settings, normalized_artifact)
        package = ExtractionPackageV1_1.model_validate_json(raw)
        if _json_bytes(package.model_dump(mode="json")) != raw:
            raise ValueError
    except (ValidationError, ValueError):
        raise EngineError(
            "ccef_invalid_package", "Stored incremental CCEF package is invalid", retryable=False
        ) from None
    return package, normalized_artifact.content_sha256


async def _generate_candidate(
    database: Database,
    settings: Settings,
    source: _ExtractionInput,
    evidence: _CommittedEvidence,
    continuation: CcefContinuationContext,
    previous_page_text: tuple[str, ...],
    provider: StructuredGenerationProvider | None,
) -> tuple[ExtractionPackageV1_1, str]:
    request = _incremental_request(evidence.context, continuation, previous_page_text)
    active_provider = _active_provider(
        settings,
        provider,
        # Long continuation trees benefit materially from thinking mode. DeepSeek documents that
        # its separate JSON Output feature can occasionally return empty final content, which this
        # path has observed. Keep thinking and the strict local JSON/CCEF decoder, but omit that
        # provider-side response-format switch instead of treating private CoT as application data.
        thinking_enabled=True,
        json_output_enabled=False,
        invalid_response_recorder=_deepseek_invalid_response_recorder(settings, source),
    )
    try:
        response = await active_provider.generate(request)
    except StructuredGenerationProviderError as error:
        raise EngineError(error.code, str(error), retryable=error.retryable) from None

    def validate_response(
        candidate_response: StructuredGenerationResponse,
    ) -> tuple[ExtractionPackageV1_1, ExtractionPackageV1_1]:
        decoded, binding_diagnostics, fragment_bindings_complete = (
            _decode_fragment_bound_response_v1_1(candidate_response, evidence.context)
        )
        _check_metadata(decoded, evidence.context)
        if not fragment_bindings_complete:
            raise ValueError(
                "incremental evidence binding failed: " + ", ".join(binding_diagnostics)
            )
        continuation_bound = _bind_continuations(decoded, continuation)
        normalized = normalize_chess_moves_v1_1(continuation_bound)
        return continuation_bound, normalized

    repair_response: StructuredGenerationResponse | None = None
    repaired_response: StructuredGenerationResponse | None = None
    try:
        repair_base, deterministic_operations = canonicalize_ccef_response(response)
    except CcefDecodeError:
        repair_base = response
        deterministic_operations = ()
    try:
        continuation_bound, normalized = validate_response(repair_base)
    except (CcefDecodeError, ValidationError, ValueError) as initial_error:
        await _capture_failed_generation(
            settings,
            source,
            response,
            error_code="ccef_invalid_package",
            error_message=str(initial_error),
            diagnostics=tuple(getattr(initial_error, "diagnostics", ())),
        )
        repair_failure: BaseException = initial_error
        try:
            repair_request = build_ccef_repair_request(
                repair_base,
                evidence.context,
                failure=repair_failure,
                trusted_context={
                    "continuation": continuation.model_dump(mode="json"),
                    "previous_page_text": list(previous_page_text),
                },
            )
        except (CcefDecodeError, CcefRepairError):
            raise EngineError(
                "ccef_invalid_package",
                "Incremental generation content is not a valid CCEF package",
                retryable=False,
            ) from None

        repair_provider = active_provider
        if provider is None:
            # Diagnostics and a bounded source slice replace the original
            # extraction prompt.  A direct structured answer is cheaper
            # and easier to validate than a second full reasoning pass.
            repair_provider = _active_provider(
                settings,
                None,
                thinking_enabled=False,
                json_output_enabled=True,
                invalid_response_recorder=_deepseek_invalid_response_recorder(settings, source),
            )
        try:
            repair_response = await repair_provider.generate(repair_request)
        except StructuredGenerationProviderError:
            raise EngineError(
                "ccef_repair_failed",
                "Incremental CCEF repair could not be generated",
                retryable=False,
            ) from None
        if repair_response is not None:
            try:
                repaired_response = apply_ccef_repair(
                    repair_base,
                    repair_response,
                    evidence.context,
                    failure=repair_failure,
                )
                continuation_bound, normalized = validate_response(repaired_response)
            except (CcefDecodeError, CcefRepairError, ValidationError, ValueError) as repair_error:
                await _capture_failed_generation(
                    settings,
                    source,
                    repair_response,
                    error_code="ccef_repair_failed",
                    error_message=str(repair_error),
                    diagnostics=tuple(getattr(repair_error, "diagnostics", ())),
                )
                raise EngineError(
                    "ccef_repair_failed",
                    "Incremental CCEF repair did not pass local validation",
                    retryable=False,
                ) from None
    else:
        if deterministic_operations:
            repaired_response = repair_base

    provider_document: object = response.model_dump(mode="json")
    if repaired_response is not None:
        provider_document = ccef_repair_chain_document(
            response,
            repaired_response,
            deterministic_operations=deterministic_operations,
            repair=repair_response,
            repair_base=repair_base,
        )
    provider_blob = await _store_blob(
        settings, suffix=".json", raw_bytes=_json_bytes(provider_document)
    )
    raw_blob = await _store_blob(
        settings, suffix=".json", raw_bytes=_json_bytes(continuation_bound.model_dump(mode="json"))
    )
    normalized_blob = await _store_blob(
        settings, suffix=".json", raw_bytes=_json_bytes(normalized.model_dump(mode="json"))
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
    return normalized, normalized_blob.sha256


async def process_pdf_incremental_extraction_job(
    database: Database,
    settings: Settings,
    payload: dict[str, Any],
    *,
    provider: StructuredGenerationProvider | None = None,
) -> dict[str, Any]:
    """Extract one adjacent segment and atomically advance its logical document."""

    inputs = await _load_incremental_input(database, settings, payload)
    await process_pdf_extraction_job(database, settings, payload)
    evidence = await _load_committed_evidence(database, settings, inputs.source)
    if evidence is None:
        raise EngineError(
            "ccef_invalid_evidence", "Committed PDF evidence is unavailable", retryable=False
        )
    continuation = build_ccef_continuation_context(
        inputs.base_package,
        base_normalized_ccef_sha256=inputs.base_sha256,
        next_page_range=PageRange(
            start_page=inputs.source.first_page,
            end_page=inputs.source.last_page,
        ),
    )
    candidate = await _load_normalized_candidate(database, settings, inputs.source)
    if candidate is None:
        candidate = await _generate_candidate(
            database,
            settings,
            inputs.source,
            evidence,
            continuation,
            inputs.previous_page_text,
            provider,
        )
    incremental, segment_hash = candidate
    aggregate = compose_incremental_ccef(
        inputs.base_package,
        incremental,
        context=continuation,
        document_id=inputs.document_id,
    )
    committed = None
    for attempt in range(5):
        try:
            async with database.session() as session, session.begin():
                committed = await PdfDocumentService(session, settings).commit_verified_append(
                    run_id=inputs.source.run_id,
                    segment_normalized_ccef_sha256=segment_hash,
                    aggregate=aggregate,
                )
            break
        except OperationalError as error:
            if "database is locked" not in str(error).lower() or attempt == 4:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))
        except ServiceError as error:
            raise EngineError(error.code, error.message, retryable=False) from None
    if committed is None:
        raise EngineError(
            "database_busy", "PDF document commit could not acquire the database", retryable=True
        )
    return {
        "result_schema": _INCREMENTAL_RESULT_SCHEMA,
        "run_id": str(inputs.source.run_id),
        "document_id": str(committed.document.id),
        "revision_id": str(committed.revision.id),
        "revision_number": committed.revision.revision_number,
        "segment_normalized_ccef_sha256": segment_hash,
        "aggregate_normalized_ccef_sha256": committed.revision.normalized_ccef_sha256,
        "replayed": committed.replayed,
    }


__all__ = ["process_pdf_incremental_extraction_job"]
