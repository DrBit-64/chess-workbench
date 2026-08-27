"""Focused tests for the CCEF 1.1 annotated extraction execution (8D-3D2B2).

Covers the frozen v3 pipeline identity and execution behavior: persistence
still defaults to v2 while v3 is explicitly enqueueable; v2/v3 on the same
asset/pages/profile produce distinct logical fingerprints, runs and jobs and
replay only against themselves; a v3 job rebuilds the exact 1.1 prompt request,
is processed once by a scripted provider, and registers exactly the three
immutable CCEF slots under its own run (never touching v2 artifacts); committed-
evidence resume uses the 1.1 path without rerender; cross-version responses
fail sanitized without registering candidate artifacts; artifact conflicts stay
fail-closed; unsupported pipelines are rejected. All content is invented; no
real provider call.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackage, ExtractionPackageV1_1
from chess_workbench.extraction.evidence import (
    OcrPageResult,
    PixelBox,
    RenderedPage,
    RenderProfile,
    ScriptedOcrAdapter,
    TextFragment,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    TokenUsage,
)
from chess_workbench.services.pdf import prepare_pdf_asset
from chess_workbench.services.pdf_extraction import (
    PDF_EXTRACTION_RESULT_SCHEMA,
    process_pdf_extraction_job,
)
from chess_workbench.services.pdf_persistence import (
    PDF_ANNOTATED_EXTRACTION_FINGERPRINT_VERSION,
    PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
    PDF_EVIDENCE_PIPELINE_VERSION,
    PDF_EXTRACTION_FINGERPRINT_VERSION,
    PDF_EXTRACTION_PIPELINE_VERSION,
    PDF_SEMANTIC_EXTRACTION_FINGERPRINT_VERSION,
    PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
    PdfPersistenceService,
)
from chess_workbench.services.uci import EngineError
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import ExtractionArtifact

CCEF_KINDS = frozenset({"provider_response", "raw_ccef", "normalized_ccef"})


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=120, height=80)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class _Renderer:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def render_page(
        self, pdf_bytes: bytes, physical_page: int, profile: RenderProfile
    ) -> RenderedPage:
        assert pdf_bytes.startswith(b"%PDF-")
        self.calls.append(physical_page)
        return RenderedPage(
            physical_page=physical_page,
            width=120,
            height=80,
            dpi=profile.dpi,
            png_bytes=b"stage-8d-page",
            embedded_fragments=[
                TextFragment(
                    order=0,
                    text="Synthetic annotated opening: 1. e4 e5.",
                    box=PixelBox(x0=10, y0=10, x1=110, y1=30),
                    confidence=None,
                )
            ],
            renderer_name="fixture-renderer",
            renderer_version="1",
        )


class _FailingRenderer:
    def render_page(
        self, pdf_bytes: bytes, physical_page: int, profile: RenderProfile
    ) -> RenderedPage:
        raise AssertionError("renderer must not be called on resume")


def _unused_ocr() -> ScriptedOcrAdapter:
    return ScriptedOcrAdapter(
        [
            OcrPageResult(
                physical_page=1,
                width=120,
                height=80,
                fragments=[],
                engine_name="fixture-ocr",
                engine_version="1",
            )
        ]
    )


def _annotated_items() -> list[dict[str, Any]]:
    nodes = [
        {
            "id": "n1",
            "parent_id": None,
            "sibling_order": 0,
            "move_text": "e4",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n2",
            "parent_id": "n1",
            "sibling_order": 0,
            "move_text": "e5",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n3",
            "parent_id": "n2",
            "sibling_order": 0,
            "move_text": "Nf3",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n4",
            "parent_id": "n3",
            "sibling_order": 0,
            "move_text": "Nc6",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n5",
            "parent_id": "n4",
            "sibling_order": 0,
            "move_text": "d4",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n6",
            "parent_id": "n5",
            "sibling_order": 0,
            "move_text": "exd4",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n7",
            "parent_id": "n6",
            "sibling_order": 0,
            "move_text": "Nxd4",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n8",
            "parent_id": "n7",
            "sibling_order": 0,
            "move_text": "Nf6",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n9",
            "parent_id": "n8",
            "sibling_order": 0,
            "move_text": "Nc3",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n10",
            "parent_id": "n9",
            "sibling_order": 0,
            "move_text": "Bb4",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n11",
            "parent_id": "n10",
            "sibling_order": 0,
            "move_text": "Be3",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n12",
            "parent_id": "n10",
            "sibling_order": 1,
            "move_text": "a3",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n13",
            "parent_id": "n12",
            "sibling_order": 0,
            "move_text": "d6",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n14",
            "parent_id": "n13",
            "sibling_order": 0,
            "move_text": "a4",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n15",
            "parent_id": "n13",
            "sibling_order": 1,
            "move_text": "b3",
            "evidence": [{"page": 1}],
        },
        {
            "id": "n16",
            "parent_id": "n11",
            "sibling_order": 0,
            "move_text": "Be7",
            "evidence": [{"page": 1}],
        },
    ]
    annotations = [
        {
            "id": "a1",
            "text": "The bishop steps aside to keep the long diagonal covered.",
            "text_format": "plain",
            "anchor": {"kind": "move_node", "node_id": "n11", "relation": "after"},
            "evidence": [{"page": 1}],
            "confidence": None,
            "warnings": [],
            "extensions": {},
        },
        {
            "id": "a2",
            "text": "A short note without a reliable board anchor.",
            "text_format": "plain",
            "anchor": None,
            "evidence": [{"page": 1}],
            "confidence": None,
            "warnings": [],
            "extensions": {},
        },
    ]
    reading_flow: list[dict[str, Any]] = [
        {"kind": "move", "node_id": f"n{index}"} for index in range(1, 17)
    ]
    reading_flow.insert(11, {"kind": "annotation", "annotation_id": "a1"})
    reading_flow.append({"kind": "annotation", "annotation_id": "a2"})
    return [
        {
            "kind": "heading",
            "id": "h1",
            "level": 1,
            "text": "Synthetic opening chapter",
            "evidence": [{"page": 1}],
        },
        {
            "kind": "move_sequence",
            "id": "seq1",
            "title": "Synthetic annotated opening",
            "evidence": [{"page": 1}],
            "initial_position": {"kind": "startpos"},
            "nodes": nodes,
            "annotations": annotations,
            "reading_flow": reading_flow,
        },
    ]


def _v1_items() -> list[dict[str, Any]]:
    return [
        {
            "kind": "heading",
            "id": "h1",
            "level": 1,
            "text": "Synthetic chapter",
            "evidence": [{"page": 1}],
        },
        {
            "kind": "move_sequence",
            "id": "line-1",
            "initial_position": {"kind": "startpos"},
            "nodes": [
                {
                    "id": "move-1",
                    "parent_id": None,
                    "sibling_order": 0,
                    "move_text": "e4",
                    "evidence": [{"page": 1}],
                }
            ],
            "evidence": [{"page": 1}],
        },
    ]


class _Provider:
    """Scripted provider echoing the trusted envelope's 1.1 package skeleton."""

    def __init__(
        self,
        *,
        contents: list[str] | None = None,
        invalid_contents: list[str] | None = None,
    ) -> None:
        self.contents = list(contents or [])
        self.invalid_contents = list(invalid_contents or [])
        self.calls: list[StructuredGenerationRequest] = []

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResponse:
        self.calls.append(request.model_copy(deep=True))
        if self.contents:
            content = self.contents.pop(0)
        elif self.invalid_contents:
            content = self.invalid_contents.pop(0)
        else:
            user_message = request.messages[-1].content
            envelope = json.loads(user_message.split("\n", 1)[1])
            package = envelope["package"]
            if package["schema_version"] == "chess-content-extraction/1.1":
                package["items"] = _annotated_items()
                if envelope["prompt_version"] == "chess-workbench/ccef-prompt/1.6":
                    fragment = envelope["evidence_pages"][0]["fragments"][0]["fragment"]
                    evidence = {
                        "page": fragment["physical_page"],
                        "fragment_sha256": fragment["fragment_sha256"],
                    }

                    def bind(candidate: Any) -> None:
                        if isinstance(candidate, dict):
                            for key, child in candidate.items():
                                if key == "evidence" and isinstance(child, list):
                                    candidate[key] = [copy.deepcopy(evidence) for _ in child]
                                else:
                                    bind(child)
                        elif isinstance(candidate, list):
                            for child in candidate:
                                bind(child)

                    bind(package["items"])
            else:
                package["items"] = _v1_items()
            content = json.dumps(package, ensure_ascii=False)
        return StructuredGenerationResponse(
            content=content,
            provider="deepseek",
            model="deepseek-v4-flash",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        )


async def _setup(
    tmp_path: Path,
    name: str,
    *,
    pipeline_version: str = PDF_EXTRACTION_PIPELINE_VERSION,
    profile_override: dict[str, Any] | None = None,
) -> tuple[Database, Settings, Any]:
    settings = cast(Any, Settings)(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}",
        source_storage_root=tmp_path / f"{name}-storage",
        engine_worker_enabled=False,
        pdf_max_bytes=1024 * 1024,
    )
    database = Database(settings.database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    prepared = prepare_pdf_asset(
        _pdf_bytes(),
        filename="chapter.pdf",
        declared_media_type="application/pdf",
        title="Chapter",
        author=None,
        edition=None,
        storage_root=settings.source_storage_root,
        max_bytes=settings.pdf_max_bytes,
    )
    async with database.session() as session, session.begin():
        asset = await PdfPersistenceService(session).register_asset(prepared)
        extraction = await PdfPersistenceService(session).enqueue_extraction(
            pdf_asset_id=asset.asset.id,
            first_page=1,
            last_page=1,
            idempotency_key=None,
            profile=profile_override
            if profile_override is not None
            else {
                "render": {"dpi": 72, "embedded_text_min_chars": 5},
                "ocr_language": "en",
                "ocr": {},
            },
            pipeline_version=pipeline_version,
        )
    assert extraction.run.pipeline_version == pipeline_version
    return database, settings, extraction


async def _artifact_rows(database: Database, run_id: Any) -> list[ExtractionArtifact]:
    async with database.session() as session:
        return list(
            await session.scalars(
                select(ExtractionArtifact)
                .where(ExtractionArtifact.run_id == run_id)
                .order_by(ExtractionArtifact.kind, ExtractionArtifact.page_number)
            )
        )


async def _ccef_rows(database: Database, run_id: Any) -> list[ExtractionArtifact]:
    return [row for row in await _artifact_rows(database, run_id) if row.kind in CCEF_KINDS]


def _handler(renderer: Any, provider: _Provider | None) -> Any:
    async def handler(
        database: Database, settings: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await process_pdf_extraction_job(
            database,
            settings,
            payload,
            renderer=renderer,
            ocr_adapter=_unused_ocr(),
            provider=provider,
        )

    return handler


# ---------------------------------------------------------------------------
# 1. Persistence identities and replay isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_v3_and_v4_enqueue_distinct_runs_and_replay_their_own(
    tmp_path: Path,
) -> None:
    settings = cast(Any, Settings)(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'identities.db'}",
        source_storage_root=tmp_path / "identities-storage",
        engine_worker_enabled=False,
        pdf_max_bytes=1024 * 1024,
    )
    database = Database(settings.database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    prepared = prepare_pdf_asset(
        _pdf_bytes(),
        filename="chapter.pdf",
        declared_media_type="application/pdf",
        title="Chapter",
        author=None,
        edition=None,
        storage_root=settings.source_storage_root,
        max_bytes=settings.pdf_max_bytes,
    )
    profile: dict[str, Any] = {
        "render": {"dpi": 72, "embedded_text_min_chars": 5},
        "ocr_language": "en",
        "ocr": {},
    }
    try:
        async with database.session() as session, session.begin():
            asset = await PdfPersistenceService(session).register_asset(prepared)
            v2 = await PdfPersistenceService(session).enqueue_extraction(
                pdf_asset_id=asset.asset.id,
                first_page=1,
                last_page=1,
                idempotency_key=None,
                profile=profile,
                pipeline_version=PDF_EXTRACTION_PIPELINE_VERSION,
            )
            v3 = await PdfPersistenceService(session).enqueue_extraction(
                pdf_asset_id=asset.asset.id,
                first_page=1,
                last_page=1,
                idempotency_key=None,
                profile=profile,
                pipeline_version=PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
            )
            v4 = await PdfPersistenceService(session).enqueue_extraction(
                pdf_asset_id=asset.asset.id,
                first_page=1,
                last_page=1,
                idempotency_key=None,
                profile=profile,
                pipeline_version=PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
            )
        assert v2.run.id != v3.run.id
        assert len({v2.run.id, v3.run.id, v4.run.id}) == 3
        assert v2.job.id != v3.job.id
        assert len({v2.job.id, v3.job.id, v4.job.id}) == 3
        assert v2.run.logical_fingerprint != v3.run.logical_fingerprint
        assert (
            len(
                {v2.run.logical_fingerprint, v3.run.logical_fingerprint, v4.run.logical_fingerprint}
            )
            == 3
        )
        assert v2.run.effective_key_hash != v3.run.effective_key_hash
        assert (
            len({v2.run.effective_key_hash, v3.run.effective_key_hash, v4.run.effective_key_hash})
            == 3
        )

        # Re-enqueuing each version replays only its own run.
        async with database.session() as session, session.begin():
            asset_id = v2.run.pdf_asset_id
            v2_again = await PdfPersistenceService(session).enqueue_extraction(
                pdf_asset_id=asset_id,
                first_page=1,
                last_page=1,
                idempotency_key=None,
                profile=profile,
                pipeline_version=PDF_EXTRACTION_PIPELINE_VERSION,
            )
            v3_again = await PdfPersistenceService(session).enqueue_extraction(
                pdf_asset_id=asset_id,
                first_page=1,
                last_page=1,
                idempotency_key=None,
                profile=profile,
                pipeline_version=PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION,
            )
            v4_again = await PdfPersistenceService(session).enqueue_extraction(
                pdf_asset_id=asset_id,
                first_page=1,
                last_page=1,
                idempotency_key=None,
                profile=profile,
                pipeline_version=PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
            )
        assert v2_again.replayed is True
        assert v3_again.replayed is True
        assert v4_again.replayed is True
        assert v2_again.run.id == v2.run.id
        assert v3_again.run.id == v3.run.id
        assert v4_again.run.id == v4.run.id
        assert v3_again.run.id != v2.run.id
    finally:
        await database.close()


def test_persistence_default_is_still_v2_and_constants_are_frozen() -> None:
    assert PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION == "pdf-extraction:v3"
    assert PDF_ANNOTATED_EXTRACTION_FINGERPRINT_VERSION == (
        "pdfium-text-lines+ccef-annotated-consolidation:v6"
    )
    assert PDF_EXTRACTION_FINGERPRINT_VERSION == "pdfium-text-lines+ccef-formal-consolidation:v5"
    assert PDF_EXTRACTION_PIPELINE_VERSION == "pdf-extraction:v2"
    assert PDF_EVIDENCE_PIPELINE_VERSION == "pdf-extraction:v1"
    assert PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION == "pdf-extraction:v4"
    assert PDF_SEMANTIC_EXTRACTION_FINGERPRINT_VERSION == (
        "pdfium-text-lines+ccef-semantic-consolidation:v12"
    )


# ---------------------------------------------------------------------------
# 2. v3 execution: 1.1 request, annotated artifacts, no v2 overwrite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v3_job_uses_1_1_request_and_commits_three_slots(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(
        tmp_path, "v3", pipeline_version=PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION
    )
    provider = _Provider()
    try:
        result = await process_pdf_extraction_job(
            database,
            settings,
            extraction.job.payload,
            renderer=_Renderer(),
            ocr_adapter=_unused_ocr(),
            provider=provider,
        )
        assert result["result_schema"] == PDF_EXTRACTION_RESULT_SCHEMA
        assert result["run_id"] == str(extraction.run.id)

        # The v3 job sent the exact 1.1 prompt request.
        assert len(provider.calls) == 1
        envelope = json.loads(provider.calls[0].messages[-1].content.split("\n", 1)[1])
        assert envelope["prompt_version"] == "chess-workbench/ccef-prompt/1.4"
        assert envelope["package"]["schema_version"] == "chess-content-extraction/1.1"
        assert envelope["package"]["provenance"]["adapter_version"] == "1.1"

        ccef = await _ccef_rows(database, extraction.run.id)
        assert [(row.kind, row.page_number) for row in ccef] == [
            ("normalized_ccef", None),
            ("provider_response", None),
            ("raw_ccef", None),
        ]
        hashes = {
            row.kind: row.content_sha256
            for row in ccef
            if row.kind in {"provider_response", "raw_ccef", "normalized_ccef"}
        }
        assert hashes["provider_response"] == result["candidate"]["provider_response_sha256"]
        assert hashes["raw_ccef"] == result["candidate"]["raw_ccef_sha256"]
        assert hashes["normalized_ccef"] == result["candidate"]["normalized_ccef_sha256"]

        provider_doc = json.loads(
            (
                settings.source_storage_root
                / next(row for row in ccef if row.kind == "provider_response").relative_path
            ).read_bytes()
        )
        assert provider_doc["artifact_schema"] == "chess-workbench/provider-response/1.1"
        assert provider_doc["ccef_schema_version"] == "chess-content-extraction/1.1"

        normalized_doc = json.loads(
            (
                settings.source_storage_root
                / next(row for row in ccef if row.kind == "normalized_ccef").relative_path
            ).read_bytes()
        )
        assert normalized_doc["schema_version"] == "chess-content-extraction/1.1"
        sequence = normalized_doc["items"][1]
        node_map = {node["id"]: node for node in sequence["nodes"]}
        assert node_map["n1"]["validation_status"] == "valid"
        assert node_map["n12"]["parent_id"] == "n10"
        assert node_map["n16"]["parent_id"] == "n11"
        assert len(sequence["annotations"]) == 2
        assert len(sequence["reading_flow"]) == 18
        assert result["candidate"]["summary"]["move_node_count"] == 16
        assert result["candidate"]["summary"]["has_conflicts"] is False
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_v4_job_uses_semantic_prompt_and_exact_fragment_bindings(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(
        tmp_path,
        "v4",
        pipeline_version=PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
    )
    provider = _Provider()
    try:
        result = await process_pdf_extraction_job(
            database,
            settings,
            extraction.job.payload,
            renderer=_Renderer(),
            ocr_adapter=_unused_ocr(),
            provider=provider,
        )
        envelope = json.loads(provider.calls[0].messages[-1].content.split("\n", 1)[1])
        assert envelope["prompt_version"] == "chess-workbench/ccef-prompt/1.6"
        assert result["candidate"]["summary"]["move_node_count"] == 16

        normalized_row = next(
            row
            for row in await _ccef_rows(database, extraction.run.id)
            if row.kind == "normalized_ccef"
        )
        normalized = json.loads(
            (settings.source_storage_root / normalized_row.relative_path).read_bytes()
        )
        sequence = normalized["items"][1]
        expected_hash = envelope["evidence_pages"][0]["fragments"][0]["fragment"]["fragment_sha256"]
        assert sequence["nodes"][0]["evidence"][0]["fragment_sha256"] == expected_hash
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_v4_invalid_package_retains_response_without_committing_candidate(
    tmp_path: Path,
) -> None:
    database, settings, extraction = await _setup(
        tmp_path,
        "v4-invalid-capture",
        pipeline_version=PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
    )
    private_marker = "synthetic-failed-response-2d9e"
    failed_content = json.dumps({"private_marker": private_marker})
    try:
        with pytest.raises(EngineError) as caught:
            await process_pdf_extraction_job(
                database,
                settings,
                extraction.job.payload,
                renderer=_Renderer(),
                ocr_adapter=_unused_ocr(),
                provider=_Provider(contents=[failed_content]),
            )
        assert caught.value.code == "ccef_invalid_package"
        assert caught.value.retryable is False
        assert private_marker not in str(caught.value)
        assert len(await _ccef_rows(database, extraction.run.id)) == 0

        capture_root = (
            settings.source_storage_root
            / "debug"
            / "extraction-failures"
            / str(extraction.run.id)
            / "attempt-0"
        )
        response_paths = list(capture_root.glob("*/*.txt"))
        report_paths = list(capture_root.glob("*/*.json"))
        assert len(response_paths) == 1
        assert len(report_paths) == 1
        assert response_paths[0].read_text(encoding="utf-8") == failed_content

        report_bytes = report_paths[0].read_bytes()
        report = json.loads(report_bytes)
        assert report["failure"]["code"] == "ccef_invalid_package"
        assert "schema_version:missing" in report["failure"]["diagnostics"]
        assert report["response"]["byte_size"] == len(failed_content.encode("utf-8"))
        assert private_marker.encode() not in report_bytes
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_v4_unbound_evidence_retains_aggregate_binding_diagnostics(
    tmp_path: Path,
) -> None:
    database, settings, extraction = await _setup(
        tmp_path,
        "v4-unbound-capture",
        pipeline_version=PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
    )

    class UnboundEvidenceProvider:
        async def generate(
            self, request: StructuredGenerationRequest
        ) -> StructuredGenerationResponse:
            envelope = json.loads(request.messages[-1].content.split("\n", 1)[1])
            package = envelope["package"]
            package["items"] = _annotated_items()
            return StructuredGenerationResponse(
                content=json.dumps(package),
                provider="scripted-provider",
                model="scripted-model",
                finish_reason="stop",
                usage=TokenUsage(),
            )

    try:
        with pytest.raises(EngineError) as caught:
            await process_pdf_extraction_job(
                database,
                settings,
                extraction.job.payload,
                renderer=_Renderer(),
                ocr_adapter=_unused_ocr(),
                provider=UnboundEvidenceProvider(),
            )
        assert caught.value.code == "ccef_semantic_incomplete"
        assert caught.value.retryable is False
        assert len(await _ccef_rows(database, extraction.run.id)) == 0

        capture_root = (
            settings.source_storage_root
            / "debug"
            / "extraction-failures"
            / str(extraction.run.id)
            / "attempt-0"
        )
        report_paths = list(capture_root.glob("*/*.json"))
        assert len(report_paths) == 1
        diagnostics = json.loads(report_paths[0].read_bytes())["failure"]["diagnostics"]
        assert diagnostics[0].startswith("evidence_refs=")
        assert "missing_locator=0" not in diagnostics
        assert "unmatched_locator=0" in diagnostics
        assert "ambiguous_bbox=0" in diagnostics
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_v2_job_keeps_1_0_artifacts_without_ccef_schema_version(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(tmp_path, "v2")
    provider = _Provider()
    try:
        await process_pdf_extraction_job(
            database,
            settings,
            extraction.job.payload,
            renderer=_Renderer(),
            ocr_adapter=_unused_ocr(),
            provider=provider,
        )
        envelope = json.loads(provider.calls[0].messages[-1].content.split("\n", 1)[1])
        assert envelope["package"]["schema_version"] == "chess-content-extraction/1.0"
        assert envelope["package"]["provenance"]["adapter_version"] == "1.0"

        ccef = await _ccef_rows(database, extraction.run.id)
        assert len(ccef) == 3
        provider_doc = json.loads(
            (
                settings.source_storage_root
                / next(row for row in ccef if row.kind == "provider_response").relative_path
            ).read_bytes()
        )
        assert provider_doc["artifact_schema"] == "chess-workbench/provider-response/1.0"
        assert "ccef_schema_version" not in provider_doc
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_v3_resume_uses_1_1_path_without_rerender(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(
        tmp_path, "resume", pipeline_version=PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION
    )
    provider = _Provider()
    renderer = _Renderer()
    try:
        first = await process_pdf_extraction_job(
            database,
            settings,
            extraction.job.payload,
            renderer=renderer,
            ocr_adapter=_unused_ocr(),
            provider=provider,
        )
        assert renderer.calls == [1]
        # Second invocation resumes from committed evidence; the renderer must
        # not be called again and the provider processes the 1.1 request again.
        second = await process_pdf_extraction_job(
            database,
            settings,
            extraction.job.payload,
            renderer=_FailingRenderer(),
            ocr_adapter=_unused_ocr(),
            provider=provider,
        )
        assert second["run_id"] == first["run_id"]
        assert (
            second["candidate"]["normalized_ccef_sha256"]
            == first["candidate"]["normalized_ccef_sha256"]
        )
        assert renderer.calls == [1]
        assert len(provider.calls) == 2
        assert len(await _ccef_rows(database, extraction.run.id)) == 3
    finally:
        await database.close()


# ---------------------------------------------------------------------------
# 3. Cross-version rejection and fail-closed artifact behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_version_responses_fail_sanitized_without_candidate_artifacts(
    tmp_path: Path,
) -> None:
    # v3 with a genuine, model-validated 1.0 response.
    database, settings, extraction = await _setup(
        tmp_path, "cross-v3", pipeline_version=PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION
    )
    v1_marker = "private-marker-v3-9f4c2d"
    v1_items = _v1_items()
    v1_items[0]["text"] = f"Synthetic chapter {v1_marker}"
    v1_doc = {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": str(extraction.run.id),
        "source": {
            "source_ref": f"source-file:{extraction.job.payload['pdf_asset_id']}",
            "media_type": "application/pdf",
            "language": "en",
            "page_range": {"start_page": 1, "end_page": 1},
        },
        "items": v1_items,
        "diagnostics": [],
        "provenance": {
            "created_at": "2026-08-14T12:34:56Z",
            "adapter_name": "chess-workbench-ccef-prompt",
            "adapter_version": "1.0",
            "provider": None,
            "model": None,
            "request_sha256": None,
            "response_sha256": None,
        },
        "extensions": {},
    }
    # The submitted document must be a genuine CCEF 1.0 package before it is
    # sent to the wrong (v3) pipeline.
    v1_validated = ExtractionPackage.model_validate(v1_doc)
    v1_content = json.dumps(v1_validated.model_dump(mode="json"), ensure_ascii=False)
    try:
        with pytest.raises(EngineError) as caught:
            await process_pdf_extraction_job(
                database,
                settings,
                extraction.job.payload,
                renderer=_Renderer(),
                ocr_adapter=_unused_ocr(),
                provider=_Provider(contents=[v1_content]),
            )
        assert caught.value.code == "ccef_invalid_package"
        assert v1_marker not in str(caught.value)
        assert len(await _ccef_rows(database, extraction.run.id)) == 0
    finally:
        await database.close()

    # v2 with a genuine, model-validated 1.1 response.
    database, settings, extraction = await _setup(
        tmp_path, "cross-v2", pipeline_version=PDF_EXTRACTION_PIPELINE_VERSION
    )
    v2_marker = "private-marker-v2-1e8a5b"
    v1_1_items = _annotated_items()
    v1_1_items[1]["annotations"][1]["text"] = (
        f"A short note without a reliable board anchor. {v2_marker}"
    )
    v1_1_doc = {
        "schema_version": "chess-content-extraction/1.1",
        "package_id": str(extraction.run.id),
        "source": {
            "source_ref": f"source-file:{extraction.job.payload['pdf_asset_id']}",
            "media_type": "application/pdf",
            "language": "en",
            "page_range": {"start_page": 1, "end_page": 1},
        },
        "items": v1_1_items,
        "diagnostics": [],
        "provenance": {
            "created_at": "2026-08-14T12:34:56Z",
            "adapter_name": "chess-workbench-ccef-prompt",
            "adapter_version": "1.1",
            "provider": None,
            "model": None,
            "request_sha256": None,
            "response_sha256": None,
        },
        "extensions": {},
    }
    v1_1_validated = ExtractionPackageV1_1.model_validate(v1_1_doc)
    v1_1_content = json.dumps(v1_1_validated.model_dump(mode="json"), ensure_ascii=False)

    async def v2_11_response(
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResponse:
        del request
        return StructuredGenerationResponse(
            content=v1_1_content,
            provider="deepseek",
            model="deepseek-v4-flash",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        )

    try:
        with pytest.raises(EngineError) as caught:
            await process_pdf_extraction_job(
                database,
                settings,
                extraction.job.payload,
                renderer=_Renderer(),
                ocr_adapter=_unused_ocr(),
                provider=_V2Provider(v2_11_response),
            )
        assert caught.value.code == "ccef_invalid_package"
        assert v2_marker not in str(caught.value)
        assert len(await _ccef_rows(database, extraction.run.id)) == 0
    finally:
        await database.close()


class _V2Provider:
    def __init__(
        self,
        responder: Callable[[StructuredGenerationRequest], Awaitable[StructuredGenerationResponse]],
    ) -> None:
        self._responder = responder

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResponse:
        return await self._responder(request)


@pytest.mark.asyncio
async def test_v3_artifact_conflict_is_fail_closed_and_never_overwrites(
    tmp_path: Path,
) -> None:
    database, settings, extraction = await _setup(
        tmp_path, "conflict", pipeline_version=PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION
    )
    provider = _Provider()
    try:
        await process_pdf_extraction_job(
            database,
            settings,
            extraction.job.payload,
            renderer=_Renderer(),
            ocr_adapter=_unused_ocr(),
            provider=provider,
        )
        rows_before = await _ccef_rows(database, extraction.run.id)
        bindings_before = {(row.kind, row.content_sha256, row.byte_size) for row in rows_before}

        # A second run of the same v3 job with a semantically different but
        # trusted-binding package must fail closed: the existing immutable
        # slots are never overwritten.
        envelope = json.loads(provider.calls[0].messages[-1].content.split("\n", 1)[1])
        changed_package = copy.deepcopy(envelope["package"])
        changed_package["items"] = _annotated_items()
        changed_package["items"][1]["annotations"][0]["text"] = "A changed annotation text."
        try:
            await process_pdf_extraction_job(
                database,
                settings,
                extraction.job.payload,
                renderer=_Renderer(),
                ocr_adapter=_unused_ocr(),
                provider=_Provider(contents=[json.dumps(changed_package)]),
            )
            raise AssertionError("expected artifact_conflict")
        except EngineError as caught:
            assert caught.code == "artifact_conflict"
        rows_after = await _ccef_rows(database, extraction.run.id)
        assert {
            (row.kind, row.content_sha256, row.byte_size) for row in rows_after
        } == bindings_before
    finally:
        await database.close()


# ---------------------------------------------------------------------------
# 4. Unsupported pipelines and v1 regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_pipeline_version_is_rejected_at_enqueue(tmp_path: Path) -> None:
    settings = cast(Any, Settings)(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'unsupported.db'}",
        source_storage_root=tmp_path / "unsupported-storage",
        engine_worker_enabled=False,
        pdf_max_bytes=1024 * 1024,
    )
    database = Database(settings.database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    prepared = prepare_pdf_asset(
        _pdf_bytes(),
        filename="chapter.pdf",
        declared_media_type="application/pdf",
        title="Chapter",
        author=None,
        edition=None,
        storage_root=settings.source_storage_root,
        max_bytes=settings.pdf_max_bytes,
    )
    try:
        async with database.session() as session, session.begin():
            asset = await PdfPersistenceService(session).register_asset(prepared)
            with pytest.raises(ValueError):
                await PdfPersistenceService(session).enqueue_extraction(
                    pdf_asset_id=asset.asset.id,
                    first_page=1,
                    last_page=1,
                    idempotency_key=None,
                    profile=None,
                    pipeline_version="pdf-extraction:v9",
                )
    finally:
        await database.close()
