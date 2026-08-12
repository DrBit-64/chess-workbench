from __future__ import annotations

import asyncio
import json
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select

from chess_workbench.config import Settings
from chess_workbench.extraction.evidence import (
    OcrPageResult,
    PixelBox,
    RenderedPage,
    RenderProfile,
    ScriptedOcrAdapter,
    TextFragment,
)
from chess_workbench.services.jobs import JobService
from chess_workbench.services.pdf import prepare_pdf_asset
from chess_workbench.services.pdf_extraction import process_pdf_extraction_job
from chess_workbench.services.pdf_persistence import PdfPersistenceService
from chess_workbench.services.uci import EngineError
from chess_workbench.services.worker import SqlWorker
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import ExtractionArtifact, Job, KnowledgeNote, utc_now


def _pdf_bytes(page_count: int = 3) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=120, height=80)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class _Renderer:
    def __init__(self, *, delay: float = 0) -> None:
        self.calls: list[int] = []
        self.delay = delay

    def render_page(
        self, pdf_bytes: bytes, physical_page: int, profile: RenderProfile
    ) -> RenderedPage:
        assert pdf_bytes.startswith(b"%PDF-")
        if self.delay:
            time.sleep(self.delay)
        self.calls.append(physical_page)
        fragments = (
            [
                TextFragment(
                    order=0,
                    text="Embedded chapter text",
                    box=PixelBox(x0=10, y0=10, x1=80, y1=25),
                    confidence=None,
                )
            ]
            if physical_page == 1
            else []
        )
        return RenderedPage(
            physical_page=physical_page,
            width=120,
            height=80,
            dpi=profile.dpi,
            png_bytes=b"same-rendered-page",
            embedded_fragments=fragments,
            renderer_name="fixture-renderer",
            renderer_version="1",
        )


def _ocr_adapter() -> ScriptedOcrAdapter:
    return ScriptedOcrAdapter(
        [
            OcrPageResult(
                physical_page=2,
                width=120,
                height=80,
                fragments=[
                    TextFragment(
                        order=0,
                        text="OCR variation",
                        box=PixelBox(x0=20, y0=30, x1=100, y1=50),
                        confidence=0.9,
                    )
                ],
                engine_name="fixture-ocr",
                engine_version="3",
            ),
            OcrPageResult(
                physical_page=3,
                width=120,
                height=80,
                fragments=[],
                engine_name="fixture-ocr",
                engine_version="3",
            ),
        ]
    )


async def _setup(
    tmp_path: Path, name: str, *, key: str | None = None
) -> tuple[Database, Settings, Any]:
    settings = Settings(
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
            last_page=3,
            idempotency_key=key,
            profile={
                "render": {"dpi": 72, "embedded_text_min_chars": 5},
                "ocr_language": "en",
                "ocr": {"device": "cpu", "runner_protocol": "fixture/1"},
            },
        )
    return database, settings, extraction


async def _artifacts(database: Database, run_id: Any) -> list[ExtractionArtifact]:
    async with database.session() as session:
        return list(
            await session.scalars(
                select(ExtractionArtifact)
                .where(ExtractionArtifact.run_id == run_id)
                .order_by(ExtractionArtifact.kind, ExtractionArtifact.page_number)
            )
        )


@pytest.mark.asyncio
async def test_handler_writes_deterministic_artifacts_and_replays(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(tmp_path, "success")
    try:
        renderer = _Renderer()
        result = await process_pdf_extraction_job(
            database,
            settings,
            extraction.job.payload,
            renderer=renderer,
            ocr_adapter=_ocr_adapter(),
        )
        assert renderer.calls == [1, 2, 3]
        assert result["page_count"] == 3
        assert result["fragment_count"] == 2
        assert result["warning_count"] == 1
        first = await _artifacts(database, extraction.run.id)
        assert len(first) == 8
        assert [(row.kind, row.page_number) for row in first] == [
            ("ocr_fragment", 1),
            ("ocr_fragment", 2),
            ("ocr_fragment", 3),
            ("ocr_manifest", None),
            ("render_manifest", None),
            ("rendered_page", 1),
            ("rendered_page", 2),
            ("rendered_page", 3),
        ]
        # All three deterministic fixture pages intentionally share one PNG CAS blob.
        rendered = [row for row in first if row.kind == "rendered_page"]
        assert len({row.relative_path for row in rendered}) == 1
        page_two = next(row for row in first if row.kind == "ocr_fragment" and row.page_number == 2)
        document = json.loads((settings.source_storage_root / page_two.relative_path).read_bytes())
        assert document["artifact_schema"] == "chess-workbench/pdf-evidence/1.0"
        assert document["origin"] == "ocr"
        assert document["fragments"][0]["bbox"] == [1 / 6, 0.375, 5 / 6, 0.625]
        assert "relative_path" not in document

        replay = await process_pdf_extraction_job(
            database,
            settings,
            extraction.job.payload,
            renderer=_Renderer(),
            ocr_adapter=_ocr_adapter(),
        )
        assert replay == result
        second = await _artifacts(database, extraction.run.id)
        assert [row.id for row in second] == [row.id for row in first]
        async with database.session() as session:
            assert (await session.scalar(select(func.count()).select_from(KnowledgeNote))) == 0
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_artifact_conflict_does_not_overwrite_existing_row(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(tmp_path, "conflict")
    try:
        await process_pdf_extraction_job(
            database,
            settings,
            extraction.job.payload,
            renderer=_Renderer(),
            ocr_adapter=_ocr_adapter(),
        )
        async with database.session() as session, session.begin():
            row = await session.scalar(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == extraction.run.id,
                    ExtractionArtifact.kind == "rendered_page",
                    ExtractionArtifact.page_number == 1,
                )
            )
            assert row is not None
            row.content_sha256 = "f" * 64
        with pytest.raises(EngineError) as caught:
            await process_pdf_extraction_job(
                database,
                settings,
                extraction.job.payload,
                renderer=_Renderer(),
                ocr_adapter=_ocr_adapter(),
            )
        assert caught.value.code == "artifact_conflict"
        rows = await _artifacts(database, extraction.run.id)
        assert len(rows) == 8
        assert any(row.content_sha256 == "f" * 64 for row in rows)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_corrupt_source_fails_before_artifact_registration(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(tmp_path, "corrupt")
    try:
        source = next((settings.source_storage_root / "sources/pdf").rglob("*.pdf"))
        source.write_bytes(b"corrupt")
        with pytest.raises(EngineError) as caught:
            await process_pdf_extraction_job(
                database,
                settings,
                extraction.job.payload,
                renderer=_Renderer(),
                ocr_adapter=_ocr_adapter(),
            )
        assert caught.value.code == "source_storage_unavailable"
        assert await _artifacts(database, extraction.run.id) == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_pdf_worker_succeeds_with_compact_committed_result(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(tmp_path, "worker")

    async def handler(
        db: Database, configured: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await process_pdf_extraction_job(
            db,
            configured,
            payload,
            renderer=_Renderer(),
            ocr_adapter=_ocr_adapter(),
        )

    try:
        worker = SqlWorker(
            database,
            settings,
            worker_id="pdf-worker",
            handlers={"pdf_extraction": handler},
        )
        assert await worker.run_once()
        async with database.session() as session:
            job = await session.get(Job, extraction.job.id)
            assert job is not None
            assert job.status == "succeeded"
            assert job.attempt_count == 1
            assert job.result is not None and job.result["page_count"] == 3
        assert len(await _artifacts(database, extraction.run.id)) == 8
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_retryable_storage_failure_has_zero_rows_then_same_job_succeeds(
    tmp_path: Path,
) -> None:
    database, settings, extraction = await _setup(tmp_path, "retry")

    async def handler(
        db: Database, configured: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await process_pdf_extraction_job(
            db,
            configured,
            payload,
            renderer=_Renderer(),
            ocr_adapter=_ocr_adapter(),
        )

    try:
        source = next((settings.source_storage_root / "sources/pdf").rglob("*.pdf"))
        original = source.read_bytes()
        source.write_bytes(b"corrupt")
        worker = SqlWorker(
            database,
            settings,
            worker_id="retry-pdf-worker",
            handlers={"pdf_extraction": handler},
        )
        assert await worker.run_once()
        async with database.session() as session:
            failed_attempt = await session.get(Job, extraction.job.id)
            assert failed_attempt is not None
            assert failed_attempt.status == "queued"
            assert failed_attempt.attempt_count == 1
            assert failed_attempt.last_error_code == "source_storage_unavailable"
        assert await _artifacts(database, extraction.run.id) == []

        source.write_bytes(original)
        async with database.session() as session, session.begin():
            retry = await session.get(Job, extraction.job.id)
            assert retry is not None
            retry.available_at = utc_now()
        assert await worker.run_once()
        async with database.session() as session:
            succeeded = await session.get(Job, extraction.job.id)
            assert succeeded is not None
            assert succeeded.status == "succeeded"
            assert succeeded.attempt_count == 2
            assert succeeded.last_error_code == "source_storage_unavailable"
        assert len(await _artifacts(database, extraction.run.id)) == 8
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_running_cancel_interrupts_handler_before_registration(tmp_path: Path) -> None:
    database, settings, extraction = await _setup(tmp_path, "cancel")

    async def handler(
        db: Database, configured: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await process_pdf_extraction_job(
            db,
            configured,
            payload,
            renderer=_Renderer(delay=0.4),
            ocr_adapter=_ocr_adapter(),
        )

    try:
        worker = SqlWorker(
            database,
            settings,
            worker_id="cancel-pdf-worker",
            handlers={"pdf_extraction": handler},
        )
        worker_task = asyncio.create_task(worker.run_once())
        for _ in range(50):
            async with database.session() as session:
                job = await session.get(Job, extraction.job.id)
                if job is not None and job.status == "running":
                    break
            await asyncio.sleep(0.01)
        async with database.session() as session, session.begin():
            cancelled = await JobService(session).cancel(extraction.job.id)
            assert cancelled is not None and cancelled.cancel_requested_at is not None
        assert await worker_task
        async with database.session() as session:
            job = await session.get(Job, extraction.job.id)
            assert job is not None and job.status == "cancelled"
        assert await _artifacts(database, extraction.run.id) == []
    finally:
        await database.close()
