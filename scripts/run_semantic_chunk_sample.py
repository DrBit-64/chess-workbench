"""Bounded live cross-page Scandinavian p321-322 chunk experiment."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from chess_workbench.config import Settings, load_ccef_provider_api_key
from chess_workbench.extraction.chunks import generate_semantic_page_chunks
from chess_workbench.extraction.deepseek import DeepSeekV4FlashProvider
from chess_workbench.extraction.evidence import SourceEvidenceFragment
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationRequest,
    StructuredGenerationResponse,
)
from chess_workbench.extraction.score import score_candidate

DATA = Path("data")
RUN_ID = "4b33f70ab6235ec3bc8e5ed6a2a28e4a"
OUTPUT = DATA / "debug/extraction-audit-20260924"


class LoggingProvider:
    def __init__(self, provider: DeepSeekV4FlashProvider, output: Path) -> None:
        self.provider = provider
        self.output = output
        self.calls = 0

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResponse:
        self.calls += 1
        number = self.calls
        (self.output / f"chunk{number}-request.json").write_text(request.model_dump_json(indent=2))
        response = await self.provider.generate(request)
        (self.output / f"chunk{number}-response.json").write_text(response.content)
        (self.output / f"chunk{number}-usage.json").write_text(
            json.dumps(
                {
                    "model": response.model,
                    "finish_reason": response.finish_reason,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                indent=2,
            )
        )
        return response


def load_context() -> CcefPromptContext:
    pages = []
    with sqlite3.connect(
        f"file:{DATA / 'database/chess-workbench.db'}?mode=ro", uri=True
    ) as db:
        for page in (321, 322):
            row = db.execute(
                "SELECT relative_path FROM extraction_artifacts WHERE run_id = ? "
                "AND page_number = ? AND kind = 'ocr_fragment'",
                (RUN_ID, page),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"Scandinavian p{page} evidence unavailable")
            artifact = json.loads((DATA / row[0]).read_text())
            entries = []
            for raw in artifact["fragments"]:
                payload = {k: v for k, v in raw.items() if k not in {"order", "bbox"}}
                payload["box"] = dict(zip(("x0", "y0", "x1", "y1"), raw["bbox"], strict=True))
                entries.append(
                    PromptEvidenceFragment(
                        order=raw["order"],
                        fragment=SourceEvidenceFragment.model_validate(payload),
                    )
                )
            pages.append(PromptEvidencePage(physical_page=page, fragments=entries))
    books = json.loads((OUTPUT / "books.json").read_text())
    digest = next(book["sha256"] for book in books if book["name"].startswith("Smerdons"))
    return CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000322"),
        created_at=datetime(2026, 9, 25, tzinfo=UTC),
        source_ref=f"sha256:{digest}",
        media_type="application/pdf",
        language="en",
        first_page=321,
        last_page=322,
        pages=pages,
        max_output_tokens=7000,
        max_prompt_chars=50000,
    )


async def main() -> None:
    settings = Settings()
    secret = load_ccef_provider_api_key(settings)
    if secret is None:
        raise RuntimeError("DeepSeek key unavailable in local configuration")
    output = OUTPUT / f"p4-scandinavian-chunks-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    output.mkdir(parents=True)
    provider = LoggingProvider(
        DeepSeekV4FlashProvider(
            api_key=secret.get_secret_value(),
            endpoint=settings.ccef_provider_endpoint,
            model=settings.ccef_provider_model,
            timeout_seconds=180,
            max_output_tokens_limit=7000,
            thinking_enabled=False,
            json_output_enabled=True,
        ),
        output,
    )
    context = load_context()
    result = await generate_semantic_page_chunks(context, provider)
    (output / "ccef.json").write_text(result.package.model_dump_json(indent=2))
    coverage = score_candidate(context, result.package)
    sequences = [item for item in result.package.items if item.kind == "move_sequence"]
    print(
        json.dumps(
            {
                "output": str(output),
                "chunks": len(result.chunks),
                "sequences": len(sequences),
                "moves": sum(len(item.nodes) for item in sequences),
                "valid": sum(
                    node.validation_status == "valid"
                    for item in sequences
                    for node in item.nodes
                ),
                "annotations": sum(len(item.annotations) for item in sequences),
                "unresolved": coverage.unresolved_items,
                "represented_fragments": coverage.represented_fragments,
                "total_fragments": coverage.total_fragments,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
