"""Bounded, isolated v8 extraction of the next complete Catalan game, p18–24.

Runs only with --live. The saved result is reused on subsequent invocations;
no existing website review session or database is modified.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from chess_workbench.config import Settings, load_ccef_provider_api_key
from chess_workbench.extraction.deepseek import DeepSeekV4FlashProvider
from chess_workbench.extraction.provider import (
    StructuredGenerationRequest,
    StructuredGenerationResponse,
)
from chess_workbench.services.pdf import prepare_pdf_asset
from chess_workbench.services.pdf_extraction import process_pdf_extraction_job
from chess_workbench.services.pdf_persistence import (
    PDF_RELATION_EXTRACTION_PIPELINE_VERSION,
    PdfPersistenceService,
)
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import Job

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/debug/review-recovery-20260927/next-game-p18-24"
BOOK = next((ROOT / "data/books").glob("*Catalan*"))
PDF_SHA = "e498b61b902dda5339c1923c4aa619fcfaa09f6abb89818841dd6357ef2ca594"
MAX_CALLS = 6


class RecordedProvider:
    def __init__(self, provider: DeepSeekV4FlashProvider) -> None:
        self.provider = provider
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    async def generate(
        self, request: StructuredGenerationRequest
    ) -> StructuredGenerationResponse:
        if self.calls >= MAX_CALLS:
            raise ValueError(f"next-game extraction reached {MAX_CALLS} model calls")
        self.calls += 1
        folder = OUTPUT / f"call-{self.calls:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "request.json").write_text(request.model_dump_json(indent=2))
        try:
            response = await self.provider.generate(request)
        except Exception as error:
            (folder / "error.txt").write_text(f"{type(error).__name__}: {error}")
            raise
        (folder / "response.json").write_text(response.model_dump_json(indent=2))
        self.input_tokens += response.usage.input_tokens or 0
        self.output_tokens += response.usage.output_tokens or 0
        return response


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Allow bounded DeepSeek calls"
    )
    args = parser.parse_args()
    result_file = OUTPUT / "result.json"
    if result_file.exists():
        print(result_file.read_text())
        return
    if not args.live:
        raise SystemExit("Pass --live to allow the next complete-game extraction")
    raw = BOOK.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PDF_SHA:
        raise RuntimeError("Catalan PDF hash differs from the known local book")
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
        raise RuntimeError("DeepSeek key is unavailable")
    provider = RecordedProvider(
        DeepSeekV4FlashProvider(
            api_key=secret.get_secret_value(),
            endpoint=settings.ccef_provider_endpoint,
            model=settings.ccef_provider_model,
            timeout_seconds=settings.ccef_provider_timeout_seconds,
            max_output_tokens_limit=settings.ccef_max_output_tokens,
            thinking_enabled=False,
            json_output_enabled=True,
        )
    )
    db = Database(settings.database_url)
    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        prepared = await asyncio.to_thread(
            prepare_pdf_asset,
            raw,
            filename=BOOK.name,
            declared_media_type="application/pdf",
            title=BOOK.stem[:200],
            author=None,
            edition=None,
            storage_root=settings.source_storage_root,
            max_bytes=settings.pdf_max_bytes,
        )
        async with db.session() as session, session.begin():
            service = PdfPersistenceService(session)
            asset = await service.register_asset(prepared)
            extraction = await service.enqueue_extraction(
                pdf_asset_id=asset.asset.id,
                first_page=18,
                last_page=24,
                idempotency_key="recovery-real-next-catalan-p18-24",
                profile={
                    "render": {"dpi": 100, "embedded_text_min_chars": 32},
                    "ocr_language": "en",
                    "ocr": {},
                },
                pipeline_version=PDF_RELATION_EXTRACTION_PIPELINE_VERSION,
            )
        result = await process_pdf_extraction_job(
            db, settings, extraction.job.payload, provider=provider
        )
        async with db.session() as session, session.begin():
            job = await session.get(Job, extraction.job.id)
            assert job is not None
            job.status = "succeeded"
            job.result = result
        report = {
            "run_id": str(extraction.run.id),
            "pages": [18, 24],
            "game": "Giri–Topalov, Stavanger 2015",
            "calls": provider.calls,
            "input_tokens": provider.input_tokens,
            "output_tokens": provider.output_tokens,
            "summary": result["candidate"]["summary"],
        }
        result_file.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
