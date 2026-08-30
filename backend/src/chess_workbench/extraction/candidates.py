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
    ExtractionPackage,
    ExtractionPackageV1_1,
    FigureItem,
    MoveSequenceItem,
    MoveSequenceItemV1_1,
    PageRange,
    UnresolvedItem,
)
from .decoder import (
    _parse_payload,
    _validate_payload,
    decode_extraction_response,
    decode_extraction_response_v1_1,
)
from .general_repair import (
    canonicalize_ccef_response,
    ccef_repair_chain_document,
)
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


def _iter_raw_owner_evidence(owner: dict[str, Any]) -> Iterator[dict[str, Any]]:
    evidence = owner.get("evidence")
    if isinstance(evidence, list):
        for reference in evidence:
            if isinstance(reference, dict):
                yield reference
    warnings = owner.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if isinstance(warning, dict):
                yield from _iter_raw_owner_evidence(warning)


def _iter_raw_evidence_refs(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield only CCEF-owned EvidenceRef slots, never similarly named extensions."""

    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            yield from _iter_raw_owner_evidence(item)
            if item.get("kind") != "move_sequence":
                continue
            for member_name in ("nodes", "annotations"):
                members = item.get(member_name)
                if not isinstance(members, list):
                    continue
                for member in members:
                    if isinstance(member, dict):
                        yield from _iter_raw_owner_evidence(member)
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, list):
        for diagnostic in diagnostics:
            if isinstance(diagnostic, dict):
                yield from _iter_raw_owner_evidence(diagnostic)


def _decode_fragment_bound_response_v1_1(
    response: StructuredGenerationResponse,
    context: CcefPromptContext,
) -> tuple[ExtractionPackageV1_1, tuple[str, ...], bool]:
    """Turn provider evidence selectors into authoritative CCEF references.

    The provider owns only ``page + fragment_sha256``. Coordinates and text
    offsets are local source metadata, so they are replaced before the strict
    CCEF model sees them. Unknown fields, malformed package structure and all
    chess trust-boundary checks remain the decoder's responsibility.
    """

    payload = _parse_payload(response)
    supplied: dict[tuple[int, str], list[float]] = {}
    trusted_fragment_key_collision = 0
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
                trusted_fragment_key_collision += 1
                continue
            supplied[key] = box

    evidence_refs = list(_iter_raw_evidence_refs(payload))
    bound_by_fragment_hash = 0
    missing_locator = 0
    unmatched_locator = 0
    for evidence in evidence_refs:
        # These fields are not part of the provider proposal. Discard them
        # unconditionally rather than guessing a coordinate convention or
        # trusting model-generated substring boundaries.
        evidence["bbox"] = None
        evidence["start_offset"] = None
        evidence["end_offset"] = None
        provider_page = evidence.get("page")
        fragment_sha256 = evidence.get("fragment_sha256")
        if fragment_sha256 is None:
            missing_locator += 1
            continue
        trusted_box = (
            supplied.get((provider_page, fragment_sha256))
            if type(provider_page) is int and type(fragment_sha256) is str
            else None
        )
        if trusted_box is None:
            unmatched_locator += 1
            continue
        evidence["bbox"] = list(trusted_box)
        bound_by_fragment_hash += 1

    package = _validate_payload(payload, ExtractionPackageV1_1)
    diagnostics = (
        f"evidence_refs={len(evidence_refs)}",
        f"bound_by_fragment_hash={bound_by_fragment_hash}",
        "repaired_by_bbox=0",
        f"missing_locator={missing_locator}",
        f"unmatched_locator={unmatched_locator}",
        "ambiguous_bbox=0",
        f"trusted_fragment_key_collision={trusted_fragment_key_collision}",
    )
    complete = bool(evidence_refs) and not (
        missing_locator or unmatched_locator or trusted_fragment_key_collision
    )
    return package, diagnostics, complete


def _sequence_warning_count(sequence: MoveSequenceItem | MoveSequenceItemV1_1) -> int:
    """Item-level plus annotation-level warnings of one move sequence."""
    annotation_warnings = 0
    if isinstance(sequence, MoveSequenceItemV1_1):
        annotation_warnings = sum(len(annotation.warnings) for annotation in sequence.annotations)
    return len(sequence.warnings) + annotation_warnings


def summarize_ccef_candidate(
    package: ExtractionPackage | ExtractionPackageV1_1,
) -> CcefCandidateSummary:
    """Rebuild the persisted candidate summary from one trusted package."""

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
        summary=summarize_ccef_candidate(normalized_package),
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
    the trusted request with the 1.1 prompt builder, first canonicalizes safe
    exact-cover node/annotation projections to the source reading flow, then
    decodes through the 1.1 contract, binds trusted context metadata, runs the
    1.1 consolidator and emits an auditable provider-response artifact. Never
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

    original_response = response
    response, deterministic_operations = canonicalize_ccef_response(response)

    binding_diagnostics: tuple[str, ...] = ()
    fragment_bindings_complete = True
    if require_fragment_bindings:
        decoded, binding_diagnostics, fragment_bindings_complete = (
            _decode_fragment_bound_response_v1_1(response, context)
        )
    else:
        decoded = decode_extraction_response_v1_1(response)
    if not _package_matches_context(decoded, context, _ADAPTER_VERSION_1_1):
        raise CcefCandidateError("binding_mismatch", _BINDING_ERROR_MESSAGE)
    if require_fragment_bindings:
        if not fragment_bindings_complete:
            raise CcefCandidateError(
                "semantic_incomplete",
                _SEMANTIC_ERROR_MESSAGE,
                diagnostics=binding_diagnostics,
            )
        raw_package = decoded
    else:
        raw_package = copy.deepcopy(decoded)

    request_sha256 = _sha256_hex(_compact_json_bytes(request.model_dump(mode="json")))
    response_sha256 = _sha256_hex(original_response.content.encode("utf-8"))

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

    if deterministic_operations:
        provider_response_doc = ccef_repair_chain_document(
            original_response,
            response,
            deterministic_operations=deterministic_operations,
        )
        provider_response_doc["request_sha256"] = request_sha256
        provider_response_doc["ccef_schema_version"] = "chess-content-extraction/1.1"
    else:
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
        summary=summarize_ccef_candidate(normalized_package),
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
    "summarize_ccef_candidate",
]
