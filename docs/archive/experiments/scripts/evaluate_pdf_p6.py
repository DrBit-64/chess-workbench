"""Run the frozen P6 PDF windows once against the source-first Job path.

Book text, requests, responses, and CCEF stay in ignored local debug storage.
This is a diagnostic run, not a gold scorer. No existing user Job or DB is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chess_workbench.config import Settings, load_ccef_provider_api_key
from chess_workbench.extraction.deepseek import DeepSeekV4FlashProvider
from chess_workbench.extraction.provider import (
    StructuredGenerationRequest,
    StructuredGenerationResponse,
)
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf import prepare_pdf_asset
from chess_workbench.services.pdf_extraction import process_pdf_extraction_job
from chess_workbench.services.pdf_persistence import (
    PDF_SOURCE_EXTRACTION_PIPELINE_VERSION,
    PdfPersistenceService,
)
from chess_workbench.services.uci import EngineError
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import Job

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/pdf-extraction-evaluation-set-v1.json"
OUTPUT = ROOT / "data/debug/extraction-audit-20260924/p6"


class RecordingProvider:
    def __init__(self, provider: DeepSeekV4FlashProvider, directory: Path) -> None:
        self.provider = provider
        self.directory = directory
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    async def generate(
        self, request: StructuredGenerationRequest
    ) -> StructuredGenerationResponse:
        self.calls += 1
        slot = self.directory / f"chunk-{self.calls:03d}"
        slot.mkdir(parents=True, exist_ok=True)
        (slot / "request.json").write_text(request.model_dump_json(indent=2))
        response = await self.provider.generate(request)
        (slot / "response.json").write_text(response.model_dump_json(indent=2))
        self.tokens_in += response.usage.input_tokens or 0
        self.tokens_out += response.usage.output_tokens or 0
        return response


async def run_window(
    database: Database,
    settings: Settings,
    window: dict[str, Any],
    book: dict[str, Any],
    provider: RecordingProvider,
) -> dict[str, Any]:
    path = ROOT / "data/books" / book["local_filename"]
    raw = await asyncio.to_thread(path.read_bytes)
    if hashlib.sha256(raw).hexdigest() != book["pdf_sha256"]:
        raise ValueError("frozen PDF hash changed")
    prepared = await asyncio.to_thread(
        prepare_pdf_asset,
        raw,
        filename=path.name,
        declared_media_type="application/pdf",
        title=path.stem[:200],
        author=None,
        edition=None,
        storage_root=settings.source_storage_root,
        max_bytes=settings.pdf_max_bytes,
    )
    async with database.session() as session, session.begin():
        service = PdfPersistenceService(session)
        asset = await service.register_asset(prepared)
        extraction = await service.enqueue_extraction(
            pdf_asset_id=asset.asset.id,
            first_page=window["owned_pages"]["start"],
            last_page=window["owned_pages"]["end"],
            idempotency_key=f"p6-once-{window['window_id']}",
            profile={
                "render": {"dpi": 100, "embedded_text_min_chars": 32},
                "ocr_language": "en",
                "ocr": {},
            },
            pipeline_version=PDF_SOURCE_EXTRACTION_PIPELINE_VERSION,
        )
    started = datetime.now(UTC)
    try:
        result = await process_pdf_extraction_job(
            database, settings, extraction.job.payload, provider=provider
        )
        async with database.session() as session, session.begin():
            job = await session.get(Job, extraction.job.id)
            assert job is not None
            job.status = "succeeded"
            job.result = result
        summary = result["candidate"]["summary"]
        return {
            "window_id": window["window_id"],
            "split": window["split"],
            "status": "candidate",
            "run_id": str(extraction.run.id),
            "candidate": summary,
            "calls": provider.calls,
            "input_tokens": provider.tokens_in,
            "output_tokens": provider.tokens_out,
            "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 2),
        }
    except (EngineError, ServiceError) as error:
        async with database.session() as session, session.begin():
            job = await session.get(Job, extraction.job.id)
            assert job is not None
            job.status = "failed"
            job.result = None
            job.last_error_code = getattr(error, "code", type(error).__name__)
            job.last_error_message = str(error)[:2000]
        return {
            "window_id": window["window_id"],
            "split": window["split"],
            "status": "unavailable"
            if getattr(error, "code", "") == "ocr_unavailable"
            else "failed",
            "run_id": str(extraction.run.id),
            "error_code": getattr(error, "code", type(error).__name__),
            "error_message": str(error)[:500],
            "calls": provider.calls,
            "input_tokens": provider.tokens_in,
            "output_tokens": provider.tokens_out,
            "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 2),
        }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window", action="append", help="Run only a named frozen window"
    )
    parser.add_argument("--split", choices=("development", "holdout"))
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    books = {book["book_id"]: book for book in manifest["books"]}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{OUTPUT / 'evaluation.db'}",
        source_storage_root=OUTPUT / "storage",
        engine_worker_enabled=False,
        ccef_max_output_tokens=7000,
        ccef_provider_timeout_seconds=180.0,
    )
    secret = load_ccef_provider_api_key(settings)
    if secret is None:
        raise RuntimeError("DeepSeek API key is not configured")
    database = Database(settings.database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        for window in manifest["windows"]:
            if args.window and window["window_id"] not in args.window:
                continue
            if args.split and window["split"] != args.split:
                continue
            directory = OUTPUT / window["window_id"]
            directory.mkdir(parents=True, exist_ok=True)
            result_path = directory / "result.json"
            if result_path.exists():
                print(result_path.read_text(), flush=True)
                continue
            provider = RecordingProvider(
                DeepSeekV4FlashProvider(
                    api_key=secret.get_secret_value(),
                    endpoint=settings.ccef_provider_endpoint,
                    model=settings.ccef_provider_model,
                    timeout_seconds=settings.ccef_provider_timeout_seconds,
                    max_output_tokens_limit=settings.ccef_max_output_tokens,
                    thinking_enabled=False,
                    json_output_enabled=True,
                ),
                directory,
            )
            result = await run_window(
                database, settings, window, books[window["book_id"]], provider
            )
            result_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
