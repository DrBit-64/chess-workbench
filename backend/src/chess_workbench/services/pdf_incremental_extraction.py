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
from chess_workbench.extraction.contracts import (
    ExtractionPackageV1_1,
    MoveSequenceItemV1_1,
    PageRange,
)
from chess_workbench.extraction.incremental import (
    CcefContinuationContext,
    build_ccef_continuation_context,
    compose_incremental_ccef,
)
from chess_workbench.extraction.pdfium import PdfiumPageRenderer
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidencePage,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationProvider,
)
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf_documents import (
    PDF_INCREMENTAL_EXTRACTION_JOB_KIND,
    PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    PDF_RELATION_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    PDF_SOURCE_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    PdfDocumentService,
)
from chess_workbench.services.pdf_extraction import (
    _CCEF_ARTIFACT_KINDS,
    _active_provider,
    _CommittedEvidence,
    _deepseek_invalid_response_recorder,
    _evidence_fragment,
    _ExtractionInput,
    _load_committed_evidence,
    _load_input,
    _read_artifact_bytes,
    _render_profile,
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
    PdfReviewRevision,
    PdfReviewSession,
    SourceFile,
)

_MAX_CCEF_BYTES = 64 * 1024 * 1024
_INCREMENTAL_RESULT_SCHEMA = "chess-workbench/pdf-incremental-extraction-result/1.0"


@dataclass(frozen=True, slots=True)
class _IncrementalInput:
    source: _ExtractionInput
    document_id: UUID
    base_package: ExtractionPackageV1_1
    base_sha256: str
    review_revision_id: UUID | None
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
        review_revision = None
        review_session = None
        if isinstance(payload.get("review_revision_id"), str):
            try:
                review_revision = await session.get(
                    PdfReviewRevision, UUID(payload["review_revision_id"])
                )
            except ValueError:
                raise _invalid_payload() from None
            if review_revision is not None:
                review_session = await session.get(PdfReviewSession, review_revision.session_id)
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
        or run.pipeline_version
        not in {
            PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
            PDF_SOURCE_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
            PDF_RELATION_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
        }
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
        or (
            (review_revision is None) != (payload.get("review_revision_id") is None)
        )
        or (
            review_revision is not None
            and (
                review_session is None
                or review_session.baseline_document_revision_id != predecessor.id
                or review_revision.package_sha256 != payload.get("review_package_sha256")
                or review_revision.revision_number != payload.get("review_session_version")
                or review_session.status not in {"open", "approved"}
            )
        )
    ):
        raise _invalid_payload()

    baseline_path = review_revision.relative_path if review_revision else predecessor.relative_path
    baseline_hash = (
        review_revision.package_sha256 if review_revision else predecessor.normalized_ccef_sha256
    )
    baseline_size = review_revision.byte_size if review_revision else predecessor.byte_size
    try:
        base_bytes = await asyncio.to_thread(
            read_verified_content_addressed_bytes,
            settings.source_storage_root,
            relative_path=baseline_path,
            expected_sha256=baseline_hash,
            expected_size=baseline_size,
            max_bytes=_MAX_CCEF_BYTES,
        )
        base_package = ExtractionPackageV1_1.model_validate_json(base_bytes)
        canonical_base = _json_bytes(base_package.model_dump(mode="json"))
        if (
            canonical_base != base_bytes
            or hashlib.sha256(canonical_base).hexdigest() != baseline_hash
            or (review_revision is not None and base_package.package_id != document_id)
            or base_package.source.page_range is None
            or base_package.source.page_range.end_page != predecessor.last_page
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
        base_sha256=baseline_hash,
        review_revision_id=review_revision.id if review_revision else None,
        previous_page_text=previous_page_text,
    )


def _active_source_sequence(
    package: ExtractionPackageV1_1,
    predecessor_context: CcefPromptContext | None = None,
) -> MoveSequenceItemV1_1 | None:
    """Pick the score appearing last in source reading order, even on a shared page."""
    source_order = {
        (page.physical_page, entry.fragment.fragment_sha256): entry.order
        for page in predecessor_context.pages
        for entry in page.fragments
    } if predecessor_context is not None else {}
    ranked: list[tuple[tuple[int, float, float, int], MoveSequenceItemV1_1]] = []
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        evidence = [ref for node in item.nodes for ref in node.evidence]
        if not evidence:
            continue
        latest = max(
            (
                (
                    ref.page,
                    float(source_order.get(
                        (ref.page, ref.fragment_sha256 or ""),
                        ref.bbox[1] if ref.bbox is not None else 0.0,
                    )),
                    ref.bbox[0] if ref.bbox is not None else 0.0,
                    ref.start_offset or 0,
                )
                for ref in evidence
            ),
        )
        ranked.append((latest, item))
    return max(ranked, key=lambda value: value[0])[1] if ranked else None


def _last_game_start(package: ExtractionPackageV1_1) -> int:
    """Read the current source score from its first cited page."""
    active = _active_source_sequence(package)
    if active is None:
        page_range = package.source.page_range
        assert page_range is not None
        return page_range.end_page
    return min(ref.page for node in active.nodes for ref in node.evidence)


async def _load_predecessor_context(
    database: Database,
    settings: Settings,
    inputs: _IncrementalInput,
    owned_context: CcefPromptContext,
) -> CcefPromptContext:
    """Load prior source pages as read-only model context from committed evidence."""
    first_page = _last_game_start(inputs.base_package)
    last_page = inputs.source.first_page - 1
    async with database.session() as session:
        artifacts = tuple(
            await session.scalars(
                select(ExtractionArtifact)
                .join(
                    PdfExtractionDocumentSegment,
                    PdfExtractionDocumentSegment.extraction_run_id == ExtractionArtifact.run_id,
                )
                .where(
                    PdfExtractionDocumentSegment.document_id == inputs.document_id,
                    ExtractionArtifact.kind == "ocr_fragment",
                    ExtractionArtifact.page_number >= first_page,
                    ExtractionArtifact.page_number <= last_page,
                )
            )
        )
    by_page = {artifact.page_number: artifact for artifact in artifacts}
    if len(by_page) != last_page - first_page + 1:
        raise EngineError(
            "incremental_context_invalid",
            "Predecessor source pages are unavailable",
            retryable=False,
        )
    pages: list[PromptEvidencePage] = []
    try:
        for page_number in range(first_page, last_page + 1):
            raw = await _read_artifact_bytes(settings, by_page[page_number])
            fragments = json.loads(raw)["fragments"]
            pages.append(
                PromptEvidencePage(
                    physical_page=page_number,
                    fragments=[
                        _evidence_fragment(value, physical_page=page_number, expected_order=index)
                        for index, value in enumerate(fragments)
                    ],
                )
            )
    except (KeyError, TypeError, ValueError, ServiceError):
        raise EngineError(
            "incremental_context_invalid",
            "Predecessor source pages are invalid",
            retryable=False,
        ) from None
    # Keep the newest continuous suffix if an unusually long game exceeds the
    # reader budget; the exact legal anchor catalog still names the earlier line.
    while len(pages) > 1 and sum(
        len(entry.fragment.text) for page in pages for entry in page.fragments
    ) > min(90_000, owned_context.max_prompt_chars // 2):
        pages.pop(0)
    return CcefPromptContext.model_validate(
        owned_context.model_copy(
            update={
                "first_page": pages[0].physical_page,
                "last_page": pages[-1].physical_page,
                "pages": pages,
            }
        ).model_dump(mode="python")
    )


def _continuation_catalog(
    package: ExtractionPackageV1_1,
    continuation: CcefContinuationContext,
    predecessor_context: CcefPromptContext,
) -> list[dict[str, Any]]:
    """Offer only anchors belonging to the last source score."""
    sequences = {item.id: item for item in package.items if isinstance(item, MoveSequenceItemV1_1)}
    active = _active_source_sequence(package, predecessor_context)
    selected = [
        sequence
        for sequence in continuation.sequences
        if active is not None and sequence.sequence_id == active.id
    ]
    catalog: list[dict[str, Any]] = []
    for sequence in selected:
        item = sequences[sequence.sequence_id]
        nodes = {node.id: node for node in item.nodes}
        for anchor in sequence.anchors:
            node = nodes.get(anchor.after_node_id) if anchor.after_node_id else None
            evidence = node.evidence[-1] if node and node.evidence else None
            mainline = node is not None
            current = node
            while current is not None:
                if current.sibling_order != 0:
                    mainline = False
                    break
                current = nodes.get(current.parent_id) if current.parent_id else None
            catalog.append(
                {
                    "id": anchor.id,
                    "sequence_id": sequence.sequence_id,
                    "sequence_title": sequence.title,
                    "after_node_id": anchor.after_node_id,
                    "source_occurrence": (
                        {
                            "page": evidence.page,
                            "fragment_ref": evidence.fragment_sha256,
                            "start_offset": evidence.start_offset,
                            "end_offset": evidence.end_offset,
                        }
                        if evidence
                        else None
                    ),
                    "position_fen": anchor.position_fen,
                    "path_tail": [
                        {"node_id": move.node_id, "san": move.san} for move in anchor.path_tail
                    ],
                    "move_number": node.move_number if node else None,
                    "side": node.side_to_move if node else None,
                    "mainline": mainline,
                }
            )
    return catalog


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
                    ExtractionArtifact.kind.in_(_CCEF_ARTIFACT_KINDS | {"semantic_manifest"}),
                )
            )
        )
    if not artifacts:
        return None
    slots = {(artifact.kind, artifact.page_number): artifact for artifact in artifacts}
    expected = {
        ("provider_response", None),
        ("raw_ccef", None),
        ("normalized_ccef", None),
    }
    if source.pipeline_version in {
        PDF_SOURCE_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
        PDF_RELATION_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    }:
        expected.add(("semantic_manifest", None))
    if len(slots) != len(expected) or set(slots) != expected:
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
    if inputs.source.pipeline_version in {
        PDF_SOURCE_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
        PDF_RELATION_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    }:
        # The document's source language is stable even if an append profile omits it.
        evidence = _CommittedEvidence(
            context=evidence.context.model_copy(
                update={"language": inputs.base_package.source.language}
            ),
            result=evidence.result,
        )
    continuation = build_ccef_continuation_context(
        inputs.base_package,
        base_normalized_ccef_sha256=inputs.base_sha256,
        next_page_range=PageRange(
            start_page=inputs.source.first_page,
            end_page=inputs.source.last_page,
        ),
    )
    if inputs.source.pipeline_version in {
        PDF_SOURCE_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
        PDF_RELATION_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    }:
        from chess_workbench.services.pdf_source_extraction import (
            process_source_candidate,
            restore_source_candidate,
        )

        restored = await restore_source_candidate(database, settings, inputs.source, evidence)
        if restored is None:
            anchors = [
                {
                    "event_id": anchor.id,
                    "fen_after": anchor.position_fen,
                    "external": "true",
                    "path": " ".join(move.san for move in anchor.path_tail),
                }
                for sequence in continuation.sequences
                for anchor in sequence.anchors
            ][-24:]
            relation_increment = (
                inputs.source.pipeline_version
                == PDF_RELATION_INCREMENTAL_EXTRACTION_PIPELINE_VERSION
            )
            predecessor_context = (
                await _load_predecessor_context(database, settings, inputs, evidence.context)
                if relation_increment
                else None
            )
            catalog = (
                _continuation_catalog(inputs.base_package, continuation, predecessor_context)
                if predecessor_context is not None
                else None
            )
            active_provider = _active_provider(
                settings,
                provider,
                thinking_enabled=relation_increment,
                json_output_enabled=not relation_increment,
                invalid_response_recorder=_deepseek_invalid_response_recorder(
                    settings, inputs.source
                ),
            )
            patch_provider = (
                _active_provider(
                    settings,
                    provider,
                    thinking_enabled=True,
                    json_output_enabled=False,
                    reasoning_effort_override="low",
                    invalid_response_recorder=_deepseek_invalid_response_recorder(
                        settings, inputs.source
                    ),
                )
                if relation_increment
                else None
            )
            await process_source_candidate(
                database,
                settings,
                inputs.source,
                evidence,
                active_provider,
                patch_provider=patch_provider,
                external_anchors=anchors,
                external_base_sha256=inputs.base_sha256,
                predecessor_context=predecessor_context,
                continuation_anchors=catalog,
            )
        candidate = await _load_normalized_candidate(database, settings, inputs.source)
        if candidate is None:
            raise RuntimeError("registered source candidate is missing")
    else:
        candidate = await _load_normalized_candidate(database, settings, inputs.source)
        if candidate is None:
            from chess_workbench.services import pdf_legacy_incremental

            candidate = await pdf_legacy_incremental._generate_candidate(
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
                    review_revision_id=inputs.review_revision_id,
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
