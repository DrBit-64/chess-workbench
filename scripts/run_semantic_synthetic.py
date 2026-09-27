"""Bounded live transport check using invented chess text, never user book content."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from chess_workbench.config import Settings, load_ccef_provider_api_key
from chess_workbench.extraction.deepseek import DeepSeekV4FlashProvider
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.interpretation import generate_semantic_candidate
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)

OUTPUT = Path("data/debug/extraction-audit-20260924/p1-synthetic-live-ccef.json")
TEXT = "1 e4 e5 2 Nf3 Nc6 3 Bb5 a6 (3...Nf6) 4 Ba4. The knight attacks the centre."


async def main() -> None:
    settings = Settings()
    secret = load_ccef_provider_api_key(settings)
    if secret is None:
        raise RuntimeError("DeepSeek key is unavailable in local configuration")
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    fragment = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=TEXT,
        origin="embedded_text",
        engine_name="synthetic",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(
            1, box, TEXT, "embedded_text", "synthetic", "1"
        ),
    )
    context = CcefPromptContext(
        package_id=UUID("3707b02d-9836-4bba-a3a0-99d0b4880471"),
        created_at=datetime(2026, 9, 24, tzinfo=UTC),
        source_ref="synthetic-chess-example",
        media_type="application/pdf",
        language="en",
        first_page=1,
        last_page=1,
        pages=[
            PromptEvidencePage(
                physical_page=1,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
            )
        ],
        max_output_tokens=4000,
        max_prompt_chars=10000,
    )
    provider = DeepSeekV4FlashProvider(
        api_key=secret.get_secret_value(),
        endpoint=settings.ccef_provider_endpoint,
        model=settings.ccef_provider_model,
        timeout_seconds=120,
        max_output_tokens_limit=4000,
        thinking_enabled=False,
        json_output_enabled=True,
    )
    result = await generate_semantic_candidate(context, provider)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(result.package.model_dump_json(indent=2))
    OUTPUT.with_name("p1-synthetic-live-response.json").write_text(
        result.response.content
    )
    print(
        json.dumps(
            {
                "model": result.response.model,
                "input_tokens": result.response.usage.input_tokens,
                "output_tokens": result.response.usage.output_tokens,
                "items": len(result.package.items),
                "moves": sum(
                    len(item.nodes)
                    for item in result.package.items
                    if item.kind == "move_sequence"
                ),
                "valid_moves": sum(
                    node.validation_status == "valid"
                    for item in result.package.items
                    if item.kind == "move_sequence"
                    for node in item.nodes
                ),
                "unresolved": sum(
                    item.kind == "unresolved" for item in result.package.items
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
