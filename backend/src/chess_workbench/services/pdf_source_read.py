"""Read PDF source pages and committed text independently of candidate success."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select

from chess_workbench.config import Settings
from chess_workbench.extraction.evidence import PdfEvidenceError
from chess_workbench.extraction.pdfium import PdfiumPageRenderer
from chess_workbench.extraction.relations import (
    RelationPatchResponse,
    RelationState,
    _resolve_quote,
    apply_relation_patches,
    apply_relations,
    canonicalize_continuation_games,
    parse_relation_response,
    reading_hints,
    reconcile_continuation_seed,
    source_tokens,
)
from chess_workbench.extraction.theory_outline import (
    build_theory_outline,
    build_theory_outline_from_fragments,
)
from chess_workbench.review.source_mentions import source_move_mentions
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf_extraction import (
    _CommittedEvidence,
    _ExtractionInput,
    _load_committed_evidence,
    _load_input,
    _read_artifact_bytes,
    _render_profile,
)
from chess_workbench.services.pdf_persistence import PdfExtractionView, PdfPersistenceService
from chess_workbench.services.source_storage import read_verified_content_addressed_bytes
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    ExtractionArtifact,
    PdfExtractionDocument,
    PdfExtractionDocumentSegment,
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PdfSourceReadService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    async def _state(
        self, run_id: UUID
    ) -> tuple[PdfExtractionView, _ExtractionInput, _CommittedEvidence | None]:
        async with self.database.session() as session:
            view = await PdfPersistenceService(session).get_extraction(run_id)
        if view is None:
            raise ServiceError("not_found", 404, "PDF extraction was not found")
        source = await _load_input(self.database, view.job.payload)
        committed = await _load_committed_evidence(self.database, self.settings, source)
        if committed is None and view.job.status != "failed":
            raise ServiceError("not_found", 404, "PDF source evidence is not ready")
        return view, source, committed

    async def read_source(self, run_id: UUID) -> dict[str, object]:
        async with self.database.session() as session:
            document = await session.get(PdfExtractionDocument, run_id)
            segments = (
                list(
                    await session.scalars(
                        select(PdfExtractionDocumentSegment)
                        .where(PdfExtractionDocumentSegment.document_id == run_id)
                        .order_by(PdfExtractionDocumentSegment.ordinal)
                    )
                )
                if document is not None
                else []
            )
        if document is not None:
            parts = [await self.read_source(segment.extraction_run_id) for segment in segments]
            combined_pages = [page for part in parts for page in cast(list[Any], part["pages"])]
            outline = build_theory_outline_from_fragments(
                (page["physical_page"], fragment["order"], fragment["text"], fragment["origin"])
                for page in combined_pages
                for fragment in page["fragments"]
            )
            if outline is not None:
                preview_refs = {ref for section in outline.sections for ref in section.preview_refs}
                for page in combined_pages:
                    for fragment in page["fragments"]:
                        if f"s{page['physical_page']}_{fragment['order']}" in preview_refs:
                            fragment["roles"] = sorted(set(fragment.get("roles", [])) | {"mention"})
            return {
                "run_id": str(run_id),
                "first_page": document.first_page,
                "last_page": document.last_page,
                "evidence_status": "ready"
                if all(part["evidence_status"] == "ready" for part in parts)
                else "unavailable",
                "error_code": next(
                    (part["error_code"] for part in parts if part["error_code"]), None
                ),
                "reading_hints": [
                    hint
                    for part in parts
                    for hint in cast(list[Any], part.get("reading_hints", []))
                ],
                "theory_sections": outline.as_input() if outline else [],
                "pages": combined_pages,
            }
        view, source, committed = await self._state(run_id)
        if committed is None:
            return {
                "run_id": str(run_id),
                "first_page": source.first_page,
                "last_page": source.last_page,
                "evidence_status": "unavailable",
                "error_code": view.job.last_error_code,
                "pages": [
                    {"physical_page": page, "fragments": []}
                    for page in range(source.first_page, source.last_page + 1)
                ],
            }
        role_map, hints, declared = await self._relation_preview(run_id, committed)
        outline = build_theory_outline(committed.context)
        if outline is not None:
            for section in outline.sections:
                for ref in section.preview_refs:
                    page, order = ref.removeprefix("s").split("_", 1)
                    role_map.setdefault((int(page), int(order)), set()).add("mention")
        mentions = source_move_mentions(committed.context)
        return {
            "run_id": str(run_id),
            "first_page": source.first_page,
            "last_page": source.last_page,
            "evidence_status": "ready",
            "error_code": None,
            "reading_hints": hints,
            "theory_sections": outline.as_input() if outline else [],
            "pages": [
                {
                    "physical_page": page.physical_page,
                    "fragments": [
                        {
                            "order": entry.order,
                            "text": entry.fragment.text,
                            "origin": entry.fragment.origin,
                            "bbox": entry.fragment.box.model_dump(mode="json"),
                            "fragment_sha256": entry.fragment.fragment_sha256,
                            "style_runs": [
                                run.model_dump(mode="json") for run in entry.fragment.style_runs
                            ],
                            "roles": sorted(role_map.get((page.physical_page, entry.order), set())),
                            "move_mentions": mentions.get((page.physical_page, entry.order), []),
                            "declared_move_spans": [
                                {"start": start, "end": end, "token_id": token_id}
                                for start, end, token_id in sorted(
                                    declared.get((page.physical_page, entry.order), set())
                                )
                            ],
                        }
                        for entry in page.fragments
                    ],
                }
                for page in committed.context.pages
            ],
        }

    async def _relation_preview(
        self, run_id: UUID, committed: _CommittedEvidence
    ) -> tuple[
        dict[tuple[int, int], set[str]],
        list[dict[str, object]],
        dict[tuple[int, int], set[tuple[int, int, str]]],
    ]:
        context = committed.context
        tokens = source_tokens(context)
        hints = reading_hints(context, tokens)
        token_by_id = {token.id: token for token in tokens}
        declared: dict[tuple[int, int], set[tuple[int, int, str]]] = {}
        async with self.database.session() as session:
            artifact = await session.scalar(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run_id,
                    ExtractionArtifact.kind == "semantic_manifest",
                )
            )
        if artifact is None:
            return {}, hints, declared
        try:
            manifest = json.loads(await _read_artifact_bytes(self.settings, artifact))
            parsed_windows = []
            continuation_anchors: list[dict[str, Any]] = []
            predecessor_tokens: list[dict[str, Any]] = []
            predecessor_spans: list[dict[str, Any]] = []
            patch_chunk = None
            for chunk in manifest["chunks"]:
                schema = chunk["request"]["response_schema_name"]
                if schema == "chess_source_relation_patch_v1":
                    patch_chunk = chunk
                    continue
                if schema != "chess_source_relations_v1":
                    continue
                request_body = json.loads(chunk["request"]["messages"][1]["content"])
                continuation_anchors = (
                    request_body.get("prior_structure", {}).get("continuation_anchors", [])
                    or continuation_anchors
                )
                predecessor_tokens = (
                    request_body.get("predecessor_move_tokens", []) or predecessor_tokens
                )
                predecessor_spans = (
                    request_body.get("predecessor_source_spans", []) or predecessor_spans
                )
                response = parse_relation_response(chunk["response"]["content"])
                # Count the original model declarations before a repair can demote
                # them into prose. This exposes blocked score without guessing that
                # every move-shaped phrase in the book is a missing move.
                for segment in response.segments:
                    for move_ref in segment.move_refs:
                        token = (
                            token_by_id.get(move_ref)
                            if isinstance(move_ref, str)
                            else _resolve_quote(move_ref, context)
                        )
                        if token is None:
                            continue
                        declared.setdefault((token.page, token.order), set()).add(
                            (token.start, token.end, token.id)
                        )
                        if token.leading_source is not None:
                            lead_page, lead_order, lead_start, lead_end = token.leading_source
                            declared.setdefault((lead_page, lead_order), set()).add(
                                (lead_start, lead_end, token.id)
                            )
                parsed_windows.append((response, set(request_body["window"]["owned_span_refs"])))
            responses = canonicalize_continuation_games(
                [
                    reconcile_continuation_seed(
                        response,
                        tokens,
                        continuation_anchors,
                        predecessor_tokens=predecessor_tokens,
                        predecessor_spans=predecessor_spans,
                    )
                    for response, _ in parsed_windows
                ]
            )
            if patch_chunk is not None and patch_chunk.get("applied"):
                patch = RelationPatchResponse.model_validate_json(
                    patch_chunk.get("applied_patch") or patch_chunk["response"]["content"]
                )
                responses = apply_relation_patches(
                    responses, patch, [owned for _, owned in parsed_windows]
                )
            state = RelationState(
                external_anchors={
                    anchor["id"]: ("0" * 64, anchor["position_fen"])
                    for anchor in continuation_anchors
                }
            )
            for response, (_, owned) in zip(responses, parsed_windows, strict=True):
                apply_relations(context, response, tokens, owned, state)
        except (KeyError, TypeError, ValueError):
            return {}, hints, declared
        role_map: dict[tuple[int, int], set[str]] = {}
        for event in state.events:
            if event.get("kind") != "move":
                continue
            source = event["source"]
            game = state.games.get(event["sequence"])
            role = (
                "example"
                if game is not None and game.kind == "example"
                else "mainline"
                if event.get("mainline")
                else "variation"
            )
            role_map.setdefault((source["page"], source["order"]), set()).add(role)
        for response in responses:
            for note in response.notes:
                if note.kind not in {"plan", "annotation", "mention"}:
                    continue
                for ref in note.source_refs:
                    try:
                        page, order = ref.removeprefix("s").split("_", 1)
                        role_map.setdefault((int(page), int(order)), set()).add(note.kind)
                    except ValueError:
                        continue
        return role_map, hints, declared

    async def read_page(self, run_id: UUID, physical_page: int) -> tuple[bytes, str]:
        async with self.database.session() as session:
            segment = await session.scalar(
                select(PdfExtractionDocumentSegment).where(
                    PdfExtractionDocumentSegment.document_id == run_id,
                    PdfExtractionDocumentSegment.first_page <= physical_page,
                    PdfExtractionDocumentSegment.last_page >= physical_page,
                )
            )
        if segment is not None:
            return await self.read_page(segment.extraction_run_id, physical_page)
        view, source, _ = await self._state(run_id)
        if not source.first_page <= physical_page <= source.last_page:
            raise ServiceError("not_found", 404, "PDF source page was not found")
        async with self.database.session() as session:
            artifact = await session.scalar(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run_id,
                    ExtractionArtifact.kind == "rendered_page",
                    ExtractionArtifact.page_number == physical_page,
                )
            )
        if artifact is not None:
            body = await _read_artifact_bytes(self.settings, artifact)
            if not body.startswith(_PNG_SIGNATURE):
                raise ServiceError("source_storage_unavailable", 503, "PDF source page is invalid")
            return body, artifact.content_sha256
        if view.job.status != "failed":
            raise ServiceError("not_found", 404, "PDF source page is not ready")
        async with self.database.session() as session:
            asset = await PdfPersistenceService(session).get_asset(view.run.pdf_asset_id)
        if asset is None:
            raise ServiceError("not_found", 404, "PDF asset was not found")
        pdf_bytes = await asyncio.to_thread(
            read_verified_content_addressed_bytes,
            self.settings.source_storage_root,
            relative_path=asset.source_file.relative_path,
            expected_sha256=asset.asset.content_sha256,
            expected_size=asset.asset.byte_size,
            max_bytes=self.settings.pdf_max_bytes,
        )
        try:
            rendered = await asyncio.to_thread(
                PdfiumPageRenderer().render_page,
                pdf_bytes,
                physical_page,
                _render_profile(view.profile),
            )
        except PdfEvidenceError:
            raise ServiceError(
                "source_storage_unavailable", 503, "PDF source page is unavailable"
            ) from None
        return rendered.png_bytes, sha256(rendered.png_bytes).hexdigest()
