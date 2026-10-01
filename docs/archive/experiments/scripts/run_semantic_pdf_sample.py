"""One bounded live DeepSeek interpretation of saved Scandinavian p319 evidence."""

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
from chess_workbench.extraction.score import score_candidate
from chess_workbench.extraction.source_compiler import compile_semantic_events
from compile_pdf_sample import load_context

OUTPUT = Path("data/debug/extraction-audit-20260924")


async def main() -> None:
    settings = Settings()
    secret = load_ccef_provider_api_key(settings)
    if secret is None:
        raise RuntimeError("DeepSeek key is unavailable in local configuration")
    context = load_context().model_copy(update={"max_output_tokens": 6000})
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
    run_dir = OUTPUT / f"p1-live-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    run_dir.mkdir(parents=True)
    (run_dir / "request.json").write_text(request.model_dump_json(indent=2))
    (run_dir / "response.json").write_text(response.content)
    if response.finish_reason == "length":
        raise RuntimeError("DeepSeek response was truncated; raw output retained")
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
                "finish_reason": response.finish_reason,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "events": len(events),
                "items": len(candidate.items),
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
                "annotations": sum(
                    len(item.annotations)
                    for item in candidate.items
                    if item.kind == "move_sequence"
                ),
                "unresolved": coverage.unresolved_items,
                "invalid_moves": coverage.invalid_moves,
                "represented_fragments": coverage.represented_fragments,
                "total_fragments": coverage.total_fragments,
                "diagnostics": len(candidate.diagnostics),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
