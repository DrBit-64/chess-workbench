"""Saved v5 CCEF continuation generation for historical incremental jobs."""

from __future__ import annotations

import json

from chess_workbench.config import Settings
from chess_workbench.extraction.candidates import _decode_fragment_bound_response_v1_1
from chess_workbench.extraction.contracts import (
    ExtractionPackageV1_1,
    FenPosition,
    MoveSequenceItemV1_1,
    PageRange,
    ccef_v1_1_schema_document,
)
from chess_workbench.extraction.incremental import CcefContinuationContext
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
from chess_workbench.extraction.recovery import CcefRecoveryError, recover_ccef_response
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.services.pdf_extraction import (
    _CCEF_ARTIFACT_KINDS,
    _active_provider,
    _ArtifactCandidate,
    _capture_failed_generation,
    _CommittedEvidence,
    _deepseek_invalid_response_recorder,
    _ExtractionInput,
    _register_artifacts,
    _store_blob,
)
from chess_workbench.services.pdf_incremental_extraction import _json_bytes
from chess_workbench.services.uci import EngineError
from chess_workbench.store.database import Database

_BINDING_EXTENSION_KEY = "chess-workbench.continuation"


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

    recovery_provider = active_provider
    if provider is None:
        # A bounded patch/supplement does not need another full reasoning pass.
        recovery_provider = _active_provider(
            settings,
            None,
            thinking_enabled=False,
            json_output_enabled=True,
            recovery=True,
            invalid_response_recorder=_deepseek_invalid_response_recorder(settings, source),
        )

    async def record_failure(
        failed_response: StructuredGenerationResponse,
        error_code: str,
        error_message: str,
        diagnostics: tuple[str, ...],
    ) -> None:
        await _capture_failed_generation(
            settings,
            source,
            failed_response,
            error_code=error_code,
            error_message=error_message,
            diagnostics=diagnostics,
        )

    try:
        recovery = await recover_ccef_response(
            response,
            evidence.context,
            validate=validate_response,
            normalized_package=lambda candidate: candidate[1],
            repair_provider=recovery_provider,
            coverage_provider=recovery_provider,
            record_failure=record_failure,
            trusted_context={
                "continuation": continuation.model_dump(mode="json"),
                "previous_page_text": list(previous_page_text),
            },
        )
    except CcefRecoveryError as error:
        raise EngineError(error.code, str(error), retryable=False) from None
    continuation_bound, normalized = recovery.value
    provider_document = recovery.provider_document
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
