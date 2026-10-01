"""Historical CCEF candidate generation for already-registered v2/v3/v4 jobs.

New extraction requests use the source-relation pipeline. This module remains
available for old queued jobs and saved candidate recovery; stored reviews and
publications are read through their existing services.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import select

from chess_workbench.config import Settings
from chess_workbench.extraction.candidates import (
    CcefCandidateArtifacts,
    CcefCandidateError,
    assemble_ccef_candidate_artifacts,
    assemble_ccef_candidate_artifacts_v1_1,
    assemble_ccef_candidate_artifacts_v1_1_semantic,
    assemble_recovered_ccef_candidate_artifacts_v1_1_semantic,
    summarize_ccef_candidate,
)
from chess_workbench.extraction.contracts import ExtractionPackage, ExtractionPackageV1_1
from chess_workbench.extraction.decoder import CcefDecodeError
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    CcefPromptError,
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
from chess_workbench.extraction.recovery import CcefRecoveryError, recover_ccef_response
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.services.pdf_extraction import (
    _CCEF_ARTIFACT_KINDS,
    _MAX_EVIDENCE_ARTIFACT_BYTES,
    PDF_EXTRACTION_RESULT_SCHEMA,
    _active_provider,
    _artifact_slots,
    _ArtifactCandidate,
    _capture_failed_generation,
    _CommittedEvidence,
    _deepseek_invalid_response_recorder,
    _ExtractionInput,
    _json_bytes,
    _read_artifact_bytes,
    _register_artifacts,
    _store_blob,
)
from chess_workbench.services.pdf_persistence import (
    PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
    PDF_EXTRACTION_PIPELINE_VERSION,
    PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
)
from chess_workbench.services.uci import EngineError
from chess_workbench.store.database import Database
from chess_workbench.store.models import ExtractionArtifact


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
    for _ in range(4):
        if not isinstance(provider_identity, dict):
            break
        schema = provider_identity.get("artifact_schema")
        if schema in {
            "chess-workbench/ccef-coverage-chain/1.0",
            "chess-workbench/ccef-structural-chain/1.0",
        }:
            provider_identity = provider_identity.get("base_generation")
        elif schema == "chess-workbench/ccef-repair-chain/2.1":
            provider_identity = provider_identity.get("original_response")
        else:
            break
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
    if source.pipeline_version == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION:
        allowed_provider_schemas.add("chess-workbench/ccef-coverage-chain/1.0")
        allowed_provider_schemas.add("chess-workbench/ccef-structural-chain/1.0")
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


async def _process_ccef_candidate(
    database: Database,
    settings: Settings,
    source: _ExtractionInput,
    committed: _CommittedEvidence,
    *,
    provider: StructuredGenerationProvider | None,
    recovery_provider: StructuredGenerationProvider | None,
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
    if source.pipeline_version == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION:
        if recovery_provider is None:
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

        def validate(
            candidate_response: StructuredGenerationResponse,
        ) -> CcefCandidateArtifacts:
            return assemble(committed.context, request, candidate_response)

        try:
            recovery = await recover_ccef_response(
                response,
                committed.context,
                validate=validate,
                normalized_package=lambda candidate: normalize_chess_moves_v1_1(
                    ExtractionPackageV1_1.model_validate_json(candidate.raw_ccef_bytes)
                ),
                repair_provider=recovery_provider,
                coverage_provider=recovery_provider,
                record_failure=record_failure,
            )
        except CcefRecoveryError as error:
            raise EngineError(error.code, str(error), retryable=False) from None
        artifacts = recovery.value
        if recovery.changed:
            if not isinstance(recovery.provider_document, dict):
                raise EngineError(
                    "ccef_repair_failed",
                    "CCEF recovery audit document is invalid",
                    retryable=False,
                )
            artifacts = assemble_recovered_ccef_candidate_artifacts_v1_1_semantic(
                committed.context,
                request,
                recovery.original_response,
                recovery.accepted_response,
                recovery.provider_document,
            )
    else:
        try:
            artifacts = assemble(committed.context, request, response)
        except CcefDecodeError as error:
            raise EngineError(
                f"ccef_{error.code}",
                str(error),
                retryable=error.code in {"invalid_json", "invalid_package"},
            ) from None
        except CcefCandidateError as error:
            raise EngineError(
                f"ccef_{error.code}",
                str(error),
                retryable=error.code == "semantic_incomplete",
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
