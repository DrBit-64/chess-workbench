from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from chess_workbench.config import Settings
from chess_workbench.extraction.evidence import (
    OcrPageResult,
    PixelBox,
    RenderedPage,
    RenderProfile,
    ScriptedOcrAdapter,
    TextFragment,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    TokenUsage,
)
from chess_workbench.services.jobs import JobService
from chess_workbench.services.pdf import prepare_pdf_asset
from chess_workbench.services.pdf_extraction import (
    PDF_EXTRACTION_RESULT_SCHEMA,
    process_pdf_extraction_job,
)
from chess_workbench.services.pdf_persistence import (
    PDF_EXTRACTION_PIPELINE_VERSION,
    PdfPersistenceService,
)
from chess_workbench.services.uci import EngineError
from chess_workbench.services.worker import SqlWorker
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import ExtractionArtifact, Job, utc_now


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
            png_bytes=b"stage-8c-page",
            embedded_fragments=[
                TextFragment(
                    order=0,
                    text="Chapter 8: 1. e4 is the main move.",
                    box=PixelBox(x0=10, y0=10, x1=110, y1=30),
                    confidence=None,
                )
            ],
            renderer_name="fixture-renderer",
            renderer_version="1",
        )


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


class _Provider:
    def __init__(
        self,
        failures: list[StructuredGenerationProviderError] | None = None,
        *,
        invalid_contents: list[str] | None = None,
        binding_mismatch: bool = False,
        release: asyncio.Event | None = None,
    ) -> None:
        self.failures = list(failures or [])
        self.invalid_contents = list(invalid_contents or [])
        self.binding_mismatch = binding_mismatch
        self.release = release
        self.started = asyncio.Event()
        self.calls: list[StructuredGenerationRequest] = []

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResponse:
        self.calls.append(request.model_copy(deep=True))
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.failures:
            raise self.failures.pop(0)
        if self.invalid_contents:
            return StructuredGenerationResponse(
                content=self.invalid_contents.pop(0),
                provider="deepseek",
                model="deepseek-v4-flash",
                finish_reason="stop",
                usage=TokenUsage(input_tokens=100, output_tokens=10, total_tokens=110),
            )
        user_message = request.messages[-1].content
        envelope = json.loads(user_message.split("\n", 1)[1])
        package = envelope["package"]
        package["items"] = [
            {
                "kind": "heading",
                "id": "heading-1",
                "level": 1,
                "text": "Chapter 8",
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
        if self.binding_mismatch:
            package["source"]["source_ref"] = "source-file:forged"
        return StructuredGenerationResponse(
            content=json.dumps(package, ensure_ascii=False),
            provider="deepseek",
            model="deepseek-v4-flash",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        )


async def _setup(tmp_path: Path, name: str) -> tuple[Database, Settings, Any]:
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
            profile={
                "render": {"dpi": 72, "embedded_text_min_chars": 5},
                "ocr_language": "en",
                "ocr": {},
            },
        )
    assert extraction.run.pipeline_version == PDF_EXTRACTION_PIPELINE_VERSION
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


def _handler(
    renderer: _Renderer,
    provider: _Provider | None,
) -> Any:
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


@pytest.mark.asyncio
async def test_v2_handler_calls_provider_once_and_atomically_commits_candidates(
    tmp_path: Path,
) -> None:
    database, settings, extraction = await _setup(tmp_path, "success")
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
        assert result["evidence"]["page_count"] == 1
        assert result["evidence"]["fragment_count"] == 1
        assert result["candidate"]["summary"] == {
            "item_count": 2,
            "move_node_count": 1,
            "figure_count": 0,
            "unresolved_item_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "invalid_move_count": 0,
            "ambiguous_move_count": 0,
            "has_conflicts": False,
        }
        assert len(provider.calls) == 1
        request_envelope = json.loads(provider.calls[0].messages[-1].content.split("\n", 1)[1])
        assert [page["physical_page"] for page in request_envelope["evidence_pages"]] == [1]

        rows = await _artifact_rows(database, extraction.run.id)
        assert len(rows) == 7
        ccef = [
            row for row in rows if row.kind in {"provider_response", "raw_ccef", "normalized_ccef"}
        ]
        assert [(row.kind, row.page_number) for row in ccef] == [
            ("normalized_ccef", None),
            ("provider_response", None),
            ("raw_ccef", None),
        ]
        normalized = next(row for row in ccef if row.kind == "normalized_ccef")
        raw = next(row for row in ccef if row.kind == "raw_ccef")
        provider_response = next(row for row in ccef if row.kind == "provider_response")
        assert normalized.content_sha256 == result["candidate"]["normalized_ccef_sha256"]
        assert raw.content_sha256 == result["candidate"]["raw_ccef_sha256"]
        assert provider_response.content_sha256 == result["candidate"]["provider_response_sha256"]
        normalized_doc = json.loads(
            (settings.source_storage_root / normalized.relative_path).read_bytes()
        )
        node = normalized_doc["items"][1]["nodes"][0]
        assert node["validation_status"] == "valid"
        assert node["uci_candidate"] == "e2e4"
    finally:
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure, expected_status",
    [
        (StructuredGenerationProviderError("authentication", "bad credentials", False), "failed"),
        (StructuredGenerationProviderError("rate_limited", "try later", True), "queued"),
    ],
)
async def test_worker_respects_provider_retryability(
    tmp_path: Path,
    failure: StructuredGenerationProviderError,
    expected_status: str,
) -> None:
    database, settings, extraction = await _setup(tmp_path, failure.code)
    provider = _Provider([failure])
    worker = SqlWorker(
        database,
        settings,
        worker_id="stage8c-retry",
        handlers={"pdf_extraction": _handler(_Renderer(), provider)},
    )
    try:
        assert await worker.run_once()
        async with database.session() as session:
            job = await session.get(Job, extraction.job.id)
            assert job is not None
            assert job.status == expected_status
            assert job.attempt_count == 1
            assert job.last_error_code == failure.code
        rows = await _artifact_rows(database, extraction.run.id)
        assert not any(
            row.kind in {"provider_response", "raw_ccef", "normalized_ccef"} for row in rows
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_retryable_provider_failure_then_same_job_succeeds(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(tmp_path, "retry-success")
    provider = _Provider(
        [StructuredGenerationProviderError("unavailable", "temporarily unavailable", True)]
    )
    renderer = _Renderer()
    worker = SqlWorker(
        database,
        settings,
        worker_id="stage8c-recover",
        handlers={"pdf_extraction": _handler(renderer, provider)},
    )
    try:
        assert await worker.run_once()
        async with database.session() as session, session.begin():
            job = await session.get(Job, extraction.job.id)
            assert job is not None and job.status == "queued"
            job.available_at = utc_now()
        assert await worker.run_once()
        async with database.session() as session:
            job = await session.get(Job, extraction.job.id)
            assert job is not None
            assert job.status == "succeeded"
            assert job.attempt_count == 2
            assert job.result is not None
            assert job.result["result_schema"] == PDF_EXTRACTION_RESULT_SCHEMA
        assert len(provider.calls) == 2
        assert renderer.calls == [1]
        rows = await _artifact_rows(database, extraction.run.id)
        assert (
            len(
                [
                    row
                    for row in rows
                    if row.kind.endswith("ccef") or row.kind == "provider_response"
                ]
            )
            == 3
        )
    finally:
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_content", ["{", "{}"])
async def test_retryable_model_format_failure_reuses_evidence_then_succeeds(
    tmp_path: Path, invalid_content: str
) -> None:
    database, settings, extraction = await _setup(tmp_path, f"model-format-{len(invalid_content)}")
    provider = _Provider(invalid_contents=[invalid_content])
    renderer = _Renderer()
    worker = SqlWorker(
        database,
        settings,
        worker_id="stage8c-model-format-retry",
        handlers={"pdf_extraction": _handler(renderer, provider)},
    )
    try:
        assert await worker.run_once()
        async with database.session() as session, session.begin():
            job = await session.get(Job, extraction.job.id)
            assert job is not None
            assert job.status == "queued"
            assert job.last_error_code in {"ccef_invalid_json", "ccef_invalid_package"}
            job.available_at = utc_now()
        assert await worker.run_once()
        async with database.session() as session:
            job = await session.get(Job, extraction.job.id)
            assert job is not None
            assert job.status == "succeeded"
            assert job.attempt_count == 2
            assert job.last_error_code is None
            assert job.last_error_message is None
        assert len(provider.calls) == 2
        assert renderer.calls == [1]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_candidate_artifact_conflict_never_overwrites_existing_row(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(tmp_path, "candidate-conflict")
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
        async with database.session() as session, session.begin():
            raw = await session.scalar(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == extraction.run.id,
                    ExtractionArtifact.kind == "raw_ccef",
                )
            )
            assert raw is not None
            raw.content_sha256 = "f" * 64
        with pytest.raises(EngineError) as caught:
            await process_pdf_extraction_job(
                database,
                settings,
                extraction.job.payload,
                renderer=_Renderer(),
                ocr_adapter=_unused_ocr(),
                provider=provider,
            )
        assert caught.value.code == "artifact_conflict"
        async with database.session() as session:
            raw = await session.scalar(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == extraction.run.id,
                    ExtractionArtifact.kind == "raw_ccef",
                )
            )
            assert raw is not None and raw.content_sha256 == "f" * 64
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_unconfigured_and_binding_failures_are_terminal_without_ccef_rows(
    tmp_path: Path,
) -> None:
    for suffix, provider, expected_code in (
        ("unconfigured", None, "provider_unconfigured"),
        ("binding", _Provider(binding_mismatch=True), "ccef_binding_mismatch"),
    ):
        database, settings, extraction = await _setup(tmp_path, suffix)
        worker = SqlWorker(
            database,
            settings,
            worker_id=f"stage8c-{suffix}",
            handlers={"pdf_extraction": _handler(_Renderer(), provider)},
        )
        try:
            assert await worker.run_once()
            async with database.session() as session:
                job = await session.get(Job, extraction.job.id)
                assert job is not None
                assert job.status == "failed"
                assert job.attempt_count == 1
                assert job.last_error_code == expected_code
            rows = await _artifact_rows(database, extraction.run.id)
            assert not any(
                row.kind in {"provider_response", "raw_ccef", "normalized_ccef"} for row in rows
            )
        finally:
            await database.close()


@pytest.mark.asyncio
async def test_insecure_provider_secret_file_fails_terminally_without_exposing_path(
    tmp_path: Path,
) -> None:
    database, settings, extraction = await _setup(tmp_path, "insecure-secret")
    secret_file = tmp_path / "visible-only-in-test-path"
    secret_file.write_text("sk-test", encoding="utf-8")
    secret_file.chmod(0o640)
    settings = settings.model_copy(update={"deepseek_api_key_file": secret_file})
    worker = SqlWorker(
        database,
        settings,
        worker_id="stage8c-insecure-secret",
        handlers={"pdf_extraction": _handler(_Renderer(), None)},
    )
    try:
        assert await worker.run_once()
        async with database.session() as session:
            job = await session.get(Job, extraction.job.id)
            assert job is not None
            assert job.status == "failed"
            assert job.last_error_code == "provider_secret_invalid"
            assert job.last_error_message is not None
            assert str(secret_file) not in job.last_error_message
        assert await _artifact_rows(database, extraction.run.id) == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_cancellation_during_provider_wait_commits_no_ccef_rows(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(tmp_path, "cancel")
    release = asyncio.Event()
    provider = _Provider(release=release)
    worker = SqlWorker(
        database,
        settings,
        worker_id="stage8c-cancel",
        handlers={"pdf_extraction": _handler(_Renderer(), provider)},
    )
    try:
        worker_task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(provider.started.wait(), timeout=3)
        async with database.session() as session, session.begin():
            cancelled = await JobService(session).cancel(extraction.job.id)
            assert cancelled is not None
        assert await asyncio.wait_for(worker_task, timeout=3)
        async with database.session() as session:
            job = await session.get(Job, extraction.job.id)
            assert job is not None and job.status == "cancelled"
        rows = await _artifact_rows(database, extraction.run.id)
        assert not any(
            row.kind in {"provider_response", "raw_ccef", "normalized_ccef"} for row in rows
        )
    finally:
        release.set()
        await database.close()
