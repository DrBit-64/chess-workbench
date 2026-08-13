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
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .consolidation import consolidate_move_sequences
from .contracts import (
    ExtractionPackage,
    FigureItem,
    MoveSequenceItem,
    PageRange,
    UnresolvedItem,
)
from .decoder import decode_extraction_response
from .prompting import CcefPromptContext, build_ccef_generation_request
from .provider import StructuredGenerationRequest, StructuredGenerationResponse

CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA = "chess-workbench/provider-response/1.0"

_BINDING_ERROR_MESSAGE = "CCEF package metadata does not match the trusted request"
_ADAPTER_NAME = "chess-workbench-ccef-prompt"
_ADAPTER_VERSION = "1.0"
_SHA256 = r"^[0-9a-f]{64}$"

CcefCandidateErrorCode = Literal["binding_mismatch"]
_ERROR_CODES = frozenset(get_args(CcefCandidateErrorCode))


class CcefCandidateError(ValueError):
    """Sanitized candidate-assembly failure.

    ``message`` is the only textual payload: rejected package values and any
    nested exception context are never retained.
    """

    def __init__(self, code: CcefCandidateErrorCode, message: str) -> None:
        if not isinstance(code, str) or code not in _ERROR_CODES:
            raise ValueError(f"code must be one of {sorted(_ERROR_CODES)}, got {code!r}")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        super().__init__(message)
        self.code = code
        self.message = message

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


def _canonical_ccef_bytes(package: ExtractionPackage) -> bytes:
    return _compact_json_bytes(package.model_dump(mode="json")) + b"\n"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _package_matches_context(package: ExtractionPackage, context: CcefPromptContext) -> bool:
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
    if package.provenance.adapter_version != _ADAPTER_VERSION:
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


def _summarize(package: ExtractionPackage) -> CcefCandidateSummary:
    move_node_count = 0
    figure_count = 0
    unresolved_count = 0
    item_warnings = 0
    node_warnings = 0
    invalid_moves = 0
    ambiguous_moves = 0
    for item in package.items:
        item_warnings += len(item.warnings)
        if isinstance(item, MoveSequenceItem):
            move_node_count += len(item.nodes)
            for node in item.nodes:
                node_warnings += len(node.warnings)
                if node.validation_status == "invalid":
                    invalid_moves += 1
                elif node.validation_status == "ambiguous":
                    ambiguous_moves += 1
        elif isinstance(item, FigureItem):
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
    if not _package_matches_context(decoded, context):
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


__all__ = [
    "CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA",
    "CcefCandidateArtifacts",
    "CcefCandidateError",
    "CcefCandidateErrorCode",
    "CcefCandidateSummary",
    "assemble_ccef_candidate_artifacts",
]
