"""Source-first PDF candidate generation and immutable manifest recovery."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from sqlalchemy import select

from chess_workbench.config import Settings
from chess_workbench.extraction.candidates import summarize_ccef_candidate
from chess_workbench.extraction.chunks import (
    generate_relation_chunks,
    generate_semantic_page_chunks,
)
from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.provider import (
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
)
from chess_workbench.extraction.score import score_candidate
from chess_workbench.services.pdf_extraction import (
    PDF_EXTRACTION_RESULT_SCHEMA,
    _artifact_slots,
    _ArtifactCandidate,
    _CommittedEvidence,
    _ExtractionInput,
    _json_bytes,
    _read_artifact_bytes,
    _register_artifacts,
    _store_blob,
)
from chess_workbench.services.pdf_persistence import PDF_RELATION_EXTRACTION_PIPELINE_VERSION
from chess_workbench.services.source_storage import store_content_addressed_bytes
from chess_workbench.services.uci import EngineError
from chess_workbench.store.database import Database
from chess_workbench.store.models import ExtractionArtifact

SOURCE_MANIFEST_SCHEMA = "chess-workbench/source-extraction-manifest/1.0"
_SOURCE_KINDS = frozenset({"semantic_manifest", "provider_response", "raw_ccef", "normalized_ccef"})


def _result(
    source: _ExtractionInput,
    committed: _CommittedEvidence,
    package: ExtractionPackageV1_1,
    *,
    manifest_sha256: str,
    request_sha256: str,
    response_sha256: str,
    ccef_sha256: str,
) -> dict[str, Any]:
    return {
        "result_schema": PDF_EXTRACTION_RESULT_SCHEMA,
        "run_id": str(source.run_id),
        "evidence": {key: value for key, value in committed.result.items() if key != "run_id"},
        "candidate": {
            "provider_response_sha256": manifest_sha256,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
            "raw_ccef_sha256": ccef_sha256,
            "normalized_ccef_sha256": ccef_sha256,
            "summary": summarize_ccef_candidate(package).model_dump(mode="json"),
        },
    }


async def restore_source_candidate(
    database: Database,
    settings: Settings,
    source: _ExtractionInput,
    committed: _CommittedEvidence,
) -> dict[str, Any] | None:
    """Resume after artifact registration without paying for another model call."""
    async with database.session() as session:
        artifacts = list(
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == source.run_id,
                    ExtractionArtifact.kind.in_(_SOURCE_KINDS),
                )
            )
        )
    if not artifacts:
        return None
    slots = _artifact_slots(artifacts)
    if len(artifacts) != 4 or set(slots) != {(kind, None) for kind in _SOURCE_KINDS}:
        raise EngineError("artifact_conflict", "Source candidate artifacts are incomplete")
    manifest_artifact = slots[("semantic_manifest", None)]
    provider_artifact = slots[("provider_response", None)]
    raw_artifact = slots[("raw_ccef", None)]
    normalized_artifact = slots[("normalized_ccef", None)]
    if (
        manifest_artifact.content_sha256 != provider_artifact.content_sha256
        or raw_artifact.content_sha256 != normalized_artifact.content_sha256
    ):
        raise EngineError("artifact_conflict", "Source candidate artifacts conflict")
    manifest_bytes, ccef_bytes = await asyncio.gather(
        _read_artifact_bytes(settings, manifest_artifact),
        _read_artifact_bytes(settings, normalized_artifact),
    )
    try:
        manifest = json.loads(manifest_bytes)
        package = ExtractionPackageV1_1.model_validate_json(ccef_bytes)
    except (ValueError, TypeError):
        raise EngineError("artifact_conflict", "Source candidate artifacts are invalid") from None
    ccef_sha256 = hashlib.sha256(ccef_bytes).hexdigest()
    if (
        not isinstance(manifest, dict)
        or manifest.get("artifact_schema") != SOURCE_MANIFEST_SCHEMA
        or manifest.get("run_id") != str(source.run_id)
        or manifest.get("pipeline_version") != source.pipeline_version
        or manifest.get("ccef_sha256") != ccef_sha256
        or package.package_id != source.run_id
        or package.source.source_ref != committed.context.source_ref
        or package.source.page_range is None
        or package.source.page_range.start_page != source.first_page
        or package.source.page_range.end_page != source.last_page
        or package.provenance.request_sha256 != manifest.get("request_sha256")
        or package.provenance.response_sha256 != manifest.get("response_sha256")
    ):
        raise EngineError("artifact_conflict", "Source candidate artifacts do not match")
    return _result(
        source,
        committed,
        package,
        manifest_sha256=manifest_artifact.content_sha256,
        request_sha256=manifest["request_sha256"],
        response_sha256=manifest["response_sha256"],
        ccef_sha256=ccef_sha256,
    )


async def process_source_candidate(
    database: Database,
    settings: Settings,
    source: _ExtractionInput,
    committed: _CommittedEvidence,
    provider: StructuredGenerationProvider,
    *,
    patch_provider: StructuredGenerationProvider | None = None,
    external_anchors: list[dict[str, str]] | None = None,
    external_base_sha256: str | None = None,
) -> dict[str, Any]:
    """Run one page-owned semantic pipeline and commit its reviewable CCEF."""

    async def retain_response(chunk_number: int, request: Any, response: Any) -> None:
        # A later chunk may fail; each paid response remains in local ignored debug CAS.
        await asyncio.to_thread(
            store_content_addressed_bytes,
            settings.source_storage_root,
            namespace=(
                f"debug/source-extraction/{source.run_id}/attempt-{source.attempt_count}"
                f"/chunk-{chunk_number}"
            ),
            suffix=".json",
            raw_bytes=_json_bytes(
                {
                    "request": request.model_dump(mode="json"),
                    "response": response.model_dump(mode="json"),
                }
            ),
        )

    try:
        if source.pipeline_version == PDF_RELATION_EXTRACTION_PIPELINE_VERSION:
            generated = await generate_relation_chunks(
                committed.context,
                provider,
                patch_provider=patch_provider,
                on_response=retain_response,
            )
        else:
            generated = await generate_semantic_page_chunks(
                committed.context,
                provider,
                on_response=retain_response,
                external_anchors=external_anchors,
                external_base_sha256=external_base_sha256,
            )
    except StructuredGenerationProviderError as error:
        raise EngineError(error.code, str(error), retryable=error.retryable) from None
    except ValueError as error:
        raise EngineError("semantic_generation_failed", str(error), retryable=False) from None

    requests = [chunk.request.model_dump(mode="json") for chunk in generated.chunks]
    responses = [chunk.response.model_dump(mode="json") for chunk in generated.chunks]
    request_sha256 = hashlib.sha256(_json_bytes({"requests": requests})).hexdigest()
    response_sha256 = hashlib.sha256(_json_bytes({"responses": responses})).hexdigest()
    provider_name = generated.chunks[0].response.provider
    model_name = generated.chunks[0].response.model
    provenance = generated.package.provenance.model_copy(
        update={
            "provider": provider_name,
            "model": model_name,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
        }
    )
    package = ExtractionPackageV1_1.model_validate(
        generated.package.model_copy(update={"provenance": provenance}).model_dump(mode="json")
    )
    ccef_bytes = _json_bytes(package.model_dump(mode="json"))
    ccef_sha256 = hashlib.sha256(ccef_bytes).hexdigest()
    coverage = score_candidate(committed.context, package)
    manifest: dict[str, object] = {
        "artifact_schema": SOURCE_MANIFEST_SCHEMA,
        "run_id": str(source.run_id),
        "pipeline_version": source.pipeline_version,
        "semantic_protocol": (
            "chess-source-relations/1"
            if source.pipeline_version == PDF_RELATION_EXTRACTION_PIPELINE_VERSION
            else "chess-semantic-events/1"
        ),
        "ccef_sha256": ccef_sha256,
        "request_sha256": request_sha256,
        "response_sha256": response_sha256,
        "coverage": {
            "total_fragments": coverage.total_fragments,
            "represented_fragments": coverage.represented_fragments,
            "unrepresented_fragments": list(coverage.unrepresented_fragments),
            "invalid_moves": coverage.invalid_moves,
            "unresolved_items": coverage.unresolved_items,
        },
        "chunks": [
            {
                "first_page": chunk.first_page,
                "last_page": chunk.last_page,
                "event_count": chunk.event_count,
                **({"applied": chunk.applied} if chunk.applied is not None else {}),
                **({"applied_patch": chunk.applied_patch} if chunk.applied_patch else {}),
                "request": requests[index],
                "response": responses[index],
            }
            for index, chunk in enumerate(generated.chunks)
        ],
    }
    manifest_blob, ccef_blob = await asyncio.gather(
        _store_blob(settings, suffix=".json", raw_bytes=_json_bytes(manifest)),
        _store_blob(settings, suffix=".json", raw_bytes=ccef_bytes),
    )
    await _register_artifacts(
        database,
        source,
        [
            _ArtifactCandidate("semantic_manifest", None, manifest_blob, "application/json"),
            _ArtifactCandidate("provider_response", None, manifest_blob, "application/json"),
            _ArtifactCandidate("raw_ccef", None, ccef_blob, "application/json"),
            _ArtifactCandidate("normalized_ccef", None, ccef_blob, "application/json"),
        ],
        artifact_kinds=_SOURCE_KINDS,
    )
    return _result(
        source,
        committed,
        package,
        manifest_sha256=manifest_blob.sha256,
        request_sha256=request_sha256,
        response_sha256=response_sha256,
        ccef_sha256=ccef_sha256,
    )
