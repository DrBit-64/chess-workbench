"""Read a v8 run's immutable source relations in the review transaction."""

from __future__ import annotations

import json
from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.config import Settings
from chess_workbench.extraction.prompting import CcefPromptContext, PromptEvidencePage
from chess_workbench.extraction.relations import (
    RelationPatchResponse,
    RelationResponse,
    apply_relation_patches,
    parse_relation_response,
    recover_completed_relation_prefix,
)
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf_extraction import _evidence_fragment, _read_artifact_bytes
from chess_workbench.store.models import ExtractionArtifact, ExtractionRun, PdfAsset


async def load_review_relations(
    session: AsyncSession, settings: Settings, run_id: UUID
) -> tuple[CcefPromptContext, list[RelationResponse], list[set[str]]]:
    """Read saved pages and responses using the caller's existing SQL session."""
    row = (
        await session.execute(
            select(ExtractionRun, PdfAsset)
            .join(PdfAsset, PdfAsset.id == ExtractionRun.pdf_asset_id)
            .where(ExtractionRun.id == run_id)
        )
    ).one_or_none()
    if row is None or row[0].pipeline_version != "pdf-extraction:v8":
        raise ServiceError(
            "validation_error", 422, "source relation replay requires a v8 extraction"
        )
    run, asset = row
    artifacts = list(
        await session.scalars(
            select(ExtractionArtifact).where(
                ExtractionArtifact.run_id == run_id,
                ExtractionArtifact.kind.in_(("ocr_fragment", "ocr_manifest", "semantic_manifest")),
            )
        )
    )
    by_kind = {(artifact.kind, artifact.page_number): artifact for artifact in artifacts}
    manifest_artifact = by_kind.get(("semantic_manifest", None))
    ocr_manifest_artifact = by_kind.get(("ocr_manifest", None))
    if manifest_artifact is None or ocr_manifest_artifact is None:
        raise ServiceError("validation_error", 422, "saved source relations are unavailable")
    ocr_manifest = json.loads(await _read_artifact_bytes(settings, ocr_manifest_artifact))
    pages = []
    for physical_page in range(run.first_page, run.last_page + 1):
        artifact = by_kind.get(("ocr_fragment", physical_page))
        if artifact is None:
            raise ServiceError("validation_error", 422, "saved PDF source page is unavailable")
        document = json.loads(await _read_artifact_bytes(settings, artifact))
        if document.get("run_id") != str(run_id) or document.get("physical_page") != physical_page:
            raise ServiceError(
                "validation_error", 422, "saved PDF source page does not match the run"
            )
        fragments = [
            _evidence_fragment(raw, physical_page=physical_page, expected_order=order)
            for order, raw in enumerate(document["fragments"])
        ]
        pages.append(PromptEvidencePage(physical_page=physical_page, fragments=fragments))
    created_at = run.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    context = CcefPromptContext(
        package_id=run_id,
        created_at=created_at,
        source_ref=f"source-file:{asset.source_file_id}",
        media_type="application/pdf",
        language=ocr_manifest.get("ocr_language") or None,
        first_page=run.first_page,
        last_page=run.last_page,
        pages=pages,
        max_output_tokens=settings.ccef_max_output_tokens,
        max_prompt_chars=settings.ccef_max_prompt_chars,
    )
    manifest = json.loads(await _read_artifact_bytes(settings, manifest_artifact))
    responses: list[RelationResponse] = []
    owned_spans: list[set[str]] = []
    patches: list[RelationPatchResponse] = []
    for chunk in manifest["chunks"]:
        request = chunk["request"]
        if request["response_schema_name"] == "chess_source_relation_patch_v1":
            if chunk.get("applied"):
                patches.append(
                    RelationPatchResponse.model_validate_json(
                        chunk.get("applied_patch") or chunk["response"]["content"]
                    )
                )
            continue
        if request["response_schema_name"] != "chess_source_relations_v1":
            continue
        response = chunk["response"]
        parsed = (
            recover_completed_relation_prefix(response["content"])
            if response["finish_reason"] == "length"
            else parse_relation_response(response["content"])
        )
        if parsed is None:
            continue
        owned = set(json.loads(request["messages"][1]["content"])["window"]["owned_span_refs"])
        responses.append(parsed)
        owned_spans.append(owned)
    if not responses:
        raise ServiceError("validation_error", 422, "saved source relations are unavailable")
    for patch in patches:
        responses = apply_relation_patches(responses, patch)
    return context, responses, owned_spans
