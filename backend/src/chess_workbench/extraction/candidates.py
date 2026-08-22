"""Pure Stage 8C trusted candidate assembler (packet DS-STAGE8C-TRUSTED-CANDIDATES-01).

Accepts one already-built trusted request and one provider response, strictly
decodes CCEF, verifies provider-supplied metadata against the trusted prompt
context, locally binds provenance, runs the accepted python-chess
normalization and returns deterministic immutable artifact bytes/hashes plus a
conflict summary.  It performs no I/O and never calls a provider.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Iterator
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .consolidation import consolidate_move_sequences, consolidate_move_sequences_v1_1
from .contracts import (
    EvidenceRef,
    ExtractionPackage,
    ExtractionPackageV1_1,
    FigureItem,
    MoveSequenceItem,
    MoveSequenceItemV1_1,
    PageRange,
    UnresolvedItem,
)
from .decoder import decode_extraction_response, decode_extraction_response_v1_1
from .prompting import (
    CcefPromptContext,
    build_ccef_generation_request,
    build_ccef_v1_1_generation_request,
    build_ccef_v1_1_semantic_generation_request,
)
from .provider import StructuredGenerationRequest, StructuredGenerationResponse

CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA = "chess-workbench/provider-response/1.0"
CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1 = "chess-workbench/provider-response/1.1"

_BINDING_ERROR_MESSAGE = "CCEF package metadata does not match the trusted request"
_SEMANTIC_ERROR_MESSAGE = "CCEF package does not preserve exact supplied evidence bindings"
_ADAPTER_NAME = "chess-workbench-ccef-prompt"
_ADAPTER_VERSION = "1.0"
_ADAPTER_VERSION_1_1 = "1.1"
_SHA256 = r"^[0-9a-f]{64}$"

CcefCandidateErrorCode = Literal["binding_mismatch", "semantic_incomplete"]
_ERROR_CODES = frozenset(get_args(CcefCandidateErrorCode))


class CcefCandidateError(ValueError):
    """Sanitized candidate-assembly failure.

    Rejected package values and nested exception context are never retained.
    Diagnostics contain only bounded aggregate binding counts.
    """

    def __init__(
        self,
        code: CcefCandidateErrorCode,
        message: str,
        *,
        diagnostics: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(code, str) or code not in _ERROR_CODES:
            raise ValueError(f"code must be one of {sorted(_ERROR_CODES)}, got {code!r}")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if type(diagnostics) is not tuple or any(
            type(item) is not str or not item or "\n" in item or len(item) > 512
            for item in diagnostics
        ):
            raise ValueError("diagnostics must contain bounded single-line strings")
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics

    def __str__(self) -> str:
        return self.message


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CcefCandidateSummary(_StrictModel):
    item_count: Annotated[int, Field(ge=0)]
    move_node_count: Annotated[int, Field(ge=0)]
    figure_count: Annotated[int, Field(ge=0)]
    unresolved_item_count: Annotated[int, Field(ge=0)]
    warning_count: Annotated[int, Field(ge=0)]
    error_count: Annotated[int, Field(ge=0)]
    invalid_move_count: Annotated[int, Field(ge=0)]
    ambiguous_move_count: Annotated[int, Field(ge=0)]
    has_conflicts: bool


class CcefCandidateArtifacts(_StrictModel):
    provider_response_bytes: Annotated[bytes, Field(min_length=1)]
    raw_ccef_bytes: Annotated[bytes, Field(min_length=1)]
    normalized_ccef_bytes: Annotated[bytes, Field(min_length=1)]
    request_sha256: Annotated[str, StringConstraints(pattern=_SHA256)]
    response_sha256: Annotated[str, StringConstraints(pattern=_SHA256)]
    raw_ccef_sha256: Annotated[str, StringConstraints(pattern=_SHA256)]
    normalized_ccef_sha256: Annotated[str, StringConstraints(pattern=_SHA256)]
    summary: CcefCandidateSummary


def _compact_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_ccef_bytes(package: ExtractionPackage | ExtractionPackageV1_1) -> bytes:
    return _compact_json_bytes(package.model_dump(mode="json")) + b"\n"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _package_matches_context(
    package: ExtractionPackage | ExtractionPackageV1_1,
    context: CcefPromptContext,
    adapter_version: str,
) -> bool:
    if package.package_id != context.package_id:
        return False
    if package.source.source_ref != context.source_ref:
        return False
    if package.source.media_type != context.media_type:
        return False
    if package.source.language != context.language:
        return False
    expected_range = PageRange(start_page=context.first_page, end_page=context.last_page)
    if package.source.page_range != expected_range:
        return False
    if package.provenance.created_at != context.created_at:
        return False
    if package.provenance.adapter_name != _ADAPTER_NAME:
        return False
    if package.provenance.adapter_version != adapter_version:
        return False
    if package.provenance.provider is not None:
        return False
    if package.provenance.model is not None:
        return False
    if package.provenance.request_sha256 is not None:
        return False
    if package.provenance.response_sha256 is not None:
        return False
    return package.extensions == {}


def _iter_evidence_refs(value: Any) -> Iterator[EvidenceRef]:
    if isinstance(value, EvidenceRef):
        yield value
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from _iter_evidence_refs(getattr(value, field_name))
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_evidence_refs(item)


def _bind_fragment_evidence(
    package: ExtractionPackageV1_1,
    context: CcefPromptContext,
) -> tuple[ExtractionPackageV1_1 | None, tuple[str, ...]]:
    supplied: dict[tuple[int, str], list[float]] = {}
    supplied_by_page: dict[int, list[tuple[str, list[float]]]] = {}
    for page in context.pages:
        for entry in page.fragments:
            key = (entry.fragment.physical_page, entry.fragment.fragment_sha256)
            box = [
                entry.fragment.box.x0,
                entry.fragment.box.y0,
                entry.fragment.box.x1,
                entry.fragment.box.y1,
            ]
            previous = supplied.get(key)
            if previous is not None and previous != box:
                return None, ("trusted_fragment_key_collision=1",)
            if previous is not None:
                continue
            supplied[key] = box
            supplied_by_page.setdefault(entry.fragment.physical_page, []).append(
                (entry.fragment.fragment_sha256, box)
            )

    bound_package = copy.deepcopy(package)
    evidence_refs = list(_iter_evidence_refs(bound_package))
    if not evidence_refs:
        return None, ("evidence_refs=0",)
    repaired_by_bbox = 0
    missing_locator = 0
    unmatched_locator = 0
    ambiguous_bbox = 0
    for evidence in evidence_refs:
        bbox_was_ambiguous = False
        trusted_hash = evidence.fragment_sha256
        trusted_box = None if trusted_hash is None else supplied.get((evidence.page, trusted_hash))
        if trusted_hash is None and evidence.bbox is not None:
            matches = [
                (fragment_hash, fragment_box)
                for fragment_hash, fragment_box in supplied_by_page.get(evidence.page, [])
                if max(
                    abs(actual - expected)
                    for actual, expected in zip(evidence.bbox, fragment_box, strict=True)
                )
                <= 0.001
            ]
            if len(matches) == 1:
                trusted_hash, trusted_box = matches[0]
                repaired_by_bbox += 1
            elif len(matches) > 1:
                bbox_was_ambiguous = True
                ambiguous_bbox += 1
        if trusted_hash is None or trusted_box is None:
            if evidence.fragment_sha256 is None and evidence.bbox is None:
                missing_locator += 1
            elif not bbox_was_ambiguous:
                unmatched_locator += 1
            continue
        # The model selects a trusted fragment by digest or an approximate box.
        # Hashes and coordinates are authoritative OCR metadata, so copy both
        # from the prompt context instead of trusting model-generated values.
        evidence.fragment_sha256 = trusted_hash
        evidence.bbox = list(trusted_box)
    diagnostics = (
        f"evidence_refs={len(evidence_refs)}",
        f"repaired_by_bbox={repaired_by_bbox}",
        f"missing_locator={missing_locator}",
        f"unmatched_locator={unmatched_locator}",
        f"ambiguous_bbox={ambiguous_bbox}",
    )
    if missing_locator or unmatched_locator or ambiguous_bbox:
        return None, diagnostics
    return (
        ExtractionPackageV1_1.model_validate(bound_package.model_dump(mode="json")),
        diagnostics,
    )


def _sequence_warning_count(sequence: MoveSequenceItem | MoveSequenceItemV1_1) -> int:
    """Item-level plus annotation-level warnings of one move sequence."""
    annotation_warnings = 0
    if isinstance(sequence, MoveSequenceItemV1_1):
        annotation_warnings = sum(len(annotation.warnings) for annotation in sequence.annotations)
    return len(sequence.warnings) + annotation_warnings


def _summarize(package: ExtractionPackage | ExtractionPackageV1_1) -> CcefCandidateSummary:
    move_node_count = 0
    figure_count = 0
    unresolved_count = 0
    item_warnings = 0
    node_warnings = 0
    invalid_moves = 0
    ambiguous_moves = 0
    for item in package.items:
        if isinstance(item, (MoveSequenceItem, MoveSequenceItemV1_1)):
            item_warnings += _sequence_warning_count(item)
            move_node_count += len(item.nodes)
            for node in item.nodes:
                node_warnings += len(node.warnings)
                if node.validation_status == "invalid":
                    invalid_moves += 1
                elif node.validation_status == "ambiguous":
                    ambiguous_moves += 1
        else:
            item_warnings += len(item.warnings)
            if isinstance(item, FigureItem):
                figure_count += 1
            elif isinstance(item, UnresolvedItem):
                unresolved_count += 1
    warning_count = (
        sum(1 for diagnostic in package.diagnostics if diagnostic.severity == "warning")
        + item_warnings
        + node_warnings
    )
    error_count = sum(1 for diagnostic in package.diagnostics if diagnostic.severity == "error")
    has_conflicts = bool(
        figure_count
        or unresolved_count
        or warning_count
        or error_count
        or invalid_moves
        or ambiguous_moves
    )
    return CcefCandidateSummary(
        item_count=len(package.items),
        move_node_count=move_node_count,
        figure_count=figure_count,
        unresolved_item_count=unresolved_count,
        warning_count=warning_count,
        error_count=error_count,
        invalid_move_count=invalid_moves,
        ambiguous_move_count=ambiguous_moves,
        has_conflicts=has_conflicts,
    )


def assemble_ccef_candidate_artifacts(
    context: CcefPromptContext,
    request: StructuredGenerationRequest,
    response: StructuredGenerationResponse,
) -> CcefCandidateArtifacts:
    """Assemble deterministic candidate artifacts from one trusted run.

    Raises ``TypeError`` on programmer misuse of input types, propagates the
    accepted decoder errors unchanged, and raises the sanitized
    ``CcefCandidateError`` (``binding_mismatch``) when the decoded package
    metadata or the rebuilt request do not match the trusted context.
    """
    if type(context) is not CcefPromptContext:
        raise TypeError("context must be CcefPromptContext")
    if type(request) is not StructuredGenerationRequest:
        raise TypeError("request must be StructuredGenerationRequest")
    if type(response) is not StructuredGenerationResponse:
        raise TypeError("response must be StructuredGenerationResponse")

    expected = build_ccef_generation_request(context)
    if request != expected:
        raise CcefCandidateError("binding_mismatch", _BINDING_ERROR_MESSAGE)

    decoded = decode_extraction_response(response)
    if not _package_matches_context(decoded, context, _ADAPTER_VERSION):
        raise CcefCandidateError("binding_mismatch", _BINDING_ERROR_MESSAGE)

    request_sha256 = _sha256_hex(_compact_json_bytes(request.model_dump(mode="json")))
    response_sha256 = _sha256_hex(response.content.encode("utf-8"))

    # Locally bind provenance on a fresh deep copy; decoded/context/request/
    # response are never mutated.
    raw_package = copy.deepcopy(decoded)
    raw_package.provenance.provider = response.provider
    raw_package.provenance.model = response.model
    raw_package.provenance.request_sha256 = request_sha256
    raw_package.provenance.response_sha256 = response_sha256
    raw_package = ExtractionPackage.model_validate(raw_package.model_dump(mode="json"))

    normalized_package = consolidate_move_sequences(raw_package, context.pages)

    raw_ccef_bytes = _canonical_ccef_bytes(raw_package)
    normalized_ccef_bytes = _canonical_ccef_bytes(normalized_package)

    provider_response_doc = {
        "artifact_schema": CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA,
        "request_sha256": request_sha256,
        "response_sha256": response_sha256,
        "provider": response.provider,
        "model": response.model,
        "finish_reason": response.finish_reason,
        "usage": response.usage.model_dump(mode="json"),
        "content": response.content,
    }
    provider_response_bytes = _compact_json_bytes(provider_response_doc) + b"\n"

    return CcefCandidateArtifacts(
        provider_response_bytes=provider_response_bytes,
        raw_ccef_bytes=raw_ccef_bytes,
        normalized_ccef_bytes=normalized_ccef_bytes,
        request_sha256=request_sha256,
        response_sha256=response_sha256,
        raw_ccef_sha256=_sha256_hex(raw_ccef_bytes),
        normalized_ccef_sha256=_sha256_hex(normalized_ccef_bytes),
        summary=_summarize(normalized_package),
    )


def _assemble_ccef_candidate_artifacts_v1_1(
    context: CcefPromptContext,
    request: StructuredGenerationRequest,
    response: StructuredGenerationResponse,
    *,
    expected_builder: Callable[[CcefPromptContext], StructuredGenerationRequest],
    require_fragment_bindings: bool,
) -> CcefCandidateArtifacts:
    """Assemble deterministic CCEF 1.1 candidate artifacts from one trusted run.

    Version-explicit twin of ``assemble_ccef_candidate_artifacts``: rebuilds
    the trusted request with the 1.1 prompt builder, decodes only through the
    1.1 decoder, binds context metadata with adapter version ``1.1``, runs the
    1.1 consolidator and emits a separately versioned provider-response
    artifact carrying an explicit ``ccef_schema_version`` binding. Never
    dispatches by response content, never mutates its inputs and performs no
    I/O or provider call.
    """
    if type(context) is not CcefPromptContext:
        raise TypeError("context must be CcefPromptContext")
    if type(request) is not StructuredGenerationRequest:
        raise TypeError("request must be StructuredGenerationRequest")
    if type(response) is not StructuredGenerationResponse:
        raise TypeError("response must be StructuredGenerationResponse")

    expected = expected_builder(context)
    if request != expected:
        raise CcefCandidateError("binding_mismatch", _BINDING_ERROR_MESSAGE)

    decoded = decode_extraction_response_v1_1(response)
    if not _package_matches_context(decoded, context, _ADAPTER_VERSION_1_1):
        raise CcefCandidateError("binding_mismatch", _BINDING_ERROR_MESSAGE)
    if require_fragment_bindings:
        raw_package, binding_diagnostics = _bind_fragment_evidence(decoded, context)
        if raw_package is None:
            raise CcefCandidateError(
                "semantic_incomplete",
                _SEMANTIC_ERROR_MESSAGE,
                diagnostics=binding_diagnostics,
            )
    else:
        raw_package = copy.deepcopy(decoded)

    request_sha256 = _sha256_hex(_compact_json_bytes(request.model_dump(mode="json")))
    response_sha256 = _sha256_hex(response.content.encode("utf-8"))

    # Locally bind provenance on a fresh deep copy; decoded/context/request/
    # response are never mutated.
    raw_package.provenance.provider = response.provider
    raw_package.provenance.model = response.model
    raw_package.provenance.request_sha256 = request_sha256
    raw_package.provenance.response_sha256 = response_sha256
    raw_package = ExtractionPackageV1_1.model_validate(raw_package.model_dump(mode="json"))

    normalized_package = consolidate_move_sequences_v1_1(raw_package, context.pages)

    raw_ccef_bytes = _canonical_ccef_bytes(raw_package)
    normalized_ccef_bytes = _canonical_ccef_bytes(normalized_package)

    provider_response_doc = {
        "artifact_schema": CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1,
        "ccef_schema_version": "chess-content-extraction/1.1",
        "request_sha256": request_sha256,
        "response_sha256": response_sha256,
        "provider": response.provider,
        "model": response.model,
        "finish_reason": response.finish_reason,
        "usage": response.usage.model_dump(mode="json"),
        "content": response.content,
    }
    provider_response_bytes = _compact_json_bytes(provider_response_doc) + b"\n"

    return CcefCandidateArtifacts(
        provider_response_bytes=provider_response_bytes,
        raw_ccef_bytes=raw_ccef_bytes,
        normalized_ccef_bytes=normalized_ccef_bytes,
        request_sha256=request_sha256,
        response_sha256=response_sha256,
        raw_ccef_sha256=_sha256_hex(raw_ccef_bytes),
        normalized_ccef_sha256=_sha256_hex(normalized_ccef_bytes),
        summary=_summarize(normalized_package),
    )


def assemble_ccef_candidate_artifacts_v1_1(
    context: CcefPromptContext,
    request: StructuredGenerationRequest,
    response: StructuredGenerationResponse,
) -> CcefCandidateArtifacts:
    """Assemble the immutable v3 CCEF 1.1 candidate profile."""
    return _assemble_ccef_candidate_artifacts_v1_1(
        context,
        request,
        response,
        expected_builder=build_ccef_v1_1_generation_request,
        require_fragment_bindings=False,
    )


def assemble_ccef_candidate_artifacts_v1_1_semantic(
    context: CcefPromptContext,
    request: StructuredGenerationRequest,
    response: StructuredGenerationResponse,
) -> CcefCandidateArtifacts:
    """Assemble v4 CCEF 1.1 with exact trusted evidence bindings."""
    return _assemble_ccef_candidate_artifacts_v1_1(
        context,
        request,
        response,
        expected_builder=build_ccef_v1_1_semantic_generation_request,
        require_fragment_bindings=True,
    )


__all__ = [
    "CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA",
    "CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1",
    "CcefCandidateArtifacts",
    "CcefCandidateError",
    "CcefCandidateErrorCode",
    "CcefCandidateSummary",
    "assemble_ccef_candidate_artifacts",
    "assemble_ccef_candidate_artifacts_v1_1",
    "assemble_ccef_candidate_artifacts_v1_1_semantic",
]
