"""One bounded live Makogonov p7 nested-variation excerpt."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from chess_workbench.config import Settings, load_ccef_provider_api_key
from chess_workbench.extraction.deepseek import DeepSeekV4FlashProvider
from chess_workbench.extraction.evidence import SourceEvidenceFragment
from chess_workbench.extraction.interpretation import (
    build_semantic_request,
    resolve_semantic_response,
)
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.score import score_candidate
from chess_workbench.extraction.source_compiler import compile_semantic_events

DATA = Path("data")
OUTPUT = DATA / "debug/extraction-audit-20260924"
RUN_ID = "86294c50bbe7568fb51fdeb44df88e28"
AFTER_6_H3 = "rnbq1rk1/ppp1ppbp/3p1np1/8/2PPP3/2N2N1P/PP3PP1/R1BQKB1R b KQ - 0 6"


def load_context() -> CcefPromptContext:
    with sqlite3.connect(
        f"file:{DATA / 'database/chess-workbench.db'}?mode=ro", uri=True
    ) as db:
        row = db.execute(
            "SELECT relative_path FROM extraction_artifacts WHERE run_id = ? "
            "AND page_number = 7 AND kind = 'ocr_fragment'",
            (RUN_ID,),
        ).fetchone()
    if row is None:
        raise RuntimeError("saved Makogonov p7 evidence unavailable")
    artifact = json.loads((DATA / row[0]).read_text())
    entries = []
    for raw in artifact["fragments"][:12]:
        payload = {key: val for key, val in raw.items() if key not in {"order", "bbox"}}
        payload["box"] = dict(zip(("x0", "y0", "x1", "y1"), raw["bbox"], strict=True))
        entries.append(
            PromptEvidenceFragment(
                order=raw["order"],
                fragment=SourceEvidenceFragment.model_validate(payload),
            )
        )
    books = json.loads((OUTPUT / "books.json").read_text())
    digest = next(x["sha256"] for x in books if x["name"].startswith("The Makogonov"))
    return CcefPromptContext(
        package_id=UUID("c8501cf3-7b7d-47d8-a102-d77e067ea538"),
        created_at=datetime(2026, 9, 24, tzinfo=UTC),
        source_ref=f"sha256:{digest}",
        media_type="application/pdf",
        language="en",
        first_page=7,
        last_page=7,
        pages=[PromptEvidencePage(physical_page=7, fragments=entries)],
        max_output_tokens=6000,
        max_prompt_chars=20000,
    )


async def main() -> None:
    settings = Settings()
    secret = load_ccef_provider_api_key(settings)
    if secret is None:
        raise RuntimeError("DeepSeek key is unavailable in local configuration")
    context = load_context()
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
        OUTPUT / f"p3-makogonov-live-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
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
    seeds = {
        event["sequence"]: AFTER_6_H3
        for event in events
        if event.get("kind") == "move" and isinstance(event.get("sequence"), str)
    }
    candidate = compile_semantic_events(context, events, sequence_initial_fens=seeds)
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
