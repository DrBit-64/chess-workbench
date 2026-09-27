"""One bounded live DeepSeek run over a diagram-start Endgame excerpt."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from chess_workbench.config import Settings, load_ccef_provider_api_key
from chess_workbench.extraction.deepseek import DeepSeekV4FlashProvider
from chess_workbench.extraction.interpretation import (
    build_semantic_request,
    resolve_semantic_response,
)
from chess_workbench.extraction.prompting import CcefPromptContext, PromptEvidencePage
from chess_workbench.extraction.score import score_candidate
from chess_workbench.extraction.source_compiler import compile_semantic_events
from compile_pdf_endgame_sample import load_context

OUTPUT = Path("data/debug/extraction-audit-20260924")


async def main() -> None:
    settings = Settings()
    secret = load_ccef_provider_api_key(settings)
    if secret is None:
        raise RuntimeError("DeepSeek key is unavailable in local configuration")
    full = load_context()
    context = CcefPromptContext.model_validate(
        {
            **full.model_dump(),
            "pages": [
                PromptEvidencePage(
                    physical_page=19,
                    fragments=[
                        full.pages[0].fragments[18].model_copy(update={"order": 0})
                    ],
                ),
                PromptEvidencePage(
                    physical_page=20, fragments=full.pages[1].fragments[:11]
                ),
            ],
            "max_output_tokens": 6000,
            "max_prompt_chars": 20000,
        }
    )
    provider = DeepSeekV4FlashProvider(
        api_key=secret.get_secret_value(),
        endpoint=settings.ccef_provider_endpoint,
        model=settings.ccef_provider_model,
        timeout_seconds=180,
        max_output_tokens_limit=6000,
        thinking_enabled=False,
        json_output_enabled=True,
    )
    request = build_semantic_request(context)
    response = await provider.generate(request)
    run_dir = (
        OUTPUT / f"p3-endgame-live-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    run_dir.mkdir(parents=True)
    (run_dir / "request.json").write_text(request.model_dump_json(indent=2))
    (run_dir / "response.json").write_text(response.content)
    if response.finish_reason == "length":
        raise RuntimeError("DeepSeek response truncated; raw output retained")
    events = resolve_semantic_response(context, response.content)
    (run_dir / "events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2)
    )
    candidate = compile_semantic_events(context, events)
    (run_dir / "ccef.json").write_text(candidate.model_dump_json(indent=2))
    coverage = score_candidate(context, candidate)
    print(
        json.dumps(
            {
                "artifact_dir": str(run_dir),
                "model": response.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "events": len(events),
                "items": len(candidate.items),
                "figures": sum(item.kind == "figure" for item in candidate.items),
                "moves": sum(
                    len(item.nodes)
                    for item in candidate.items
                    if item.kind == "move_sequence"
                ),
                "valid_moves": sum(
                    node.validation_status == "valid"
                    for item in candidate.items
                    if item.kind == "move_sequence"
                    for node in item.nodes
                ),
                "unresolved": coverage.unresolved_items,
                "represented_fragments": coverage.represented_fragments,
                "total_fragments": coverage.total_fragments,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
