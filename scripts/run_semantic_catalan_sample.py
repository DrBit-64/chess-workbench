"""One bounded live interpretation of selected Catalan p7/p9 question fragments."""

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
RUN_ID = "1a9487829a7f5c978ac367bb18e958d9"
AFTER_9_E4 = "rn1q1rk1/pb2bppp/1pp1pn2/3p4/2PPP3/5NP1/PPQN1PBP/R1B2RK1 b - e3 0 9"
SELECT = {7: (72, 73, 74, 75, 76, 77), 8: (), 9: (1, 2, 3, 4, 5, 6)}


def load_context() -> CcefPromptContext:
    pages = []
    with sqlite3.connect(
        f"file:{DATA / 'database/chess-workbench.db'}?mode=ro", uri=True
    ) as db:
        for page, source_orders in SELECT.items():
            if not source_orders:
                pages.append(PromptEvidencePage(physical_page=page, fragments=[]))
                continue
            row = db.execute(
                "SELECT relative_path FROM extraction_artifacts WHERE run_id = ? "
                "AND page_number = ? AND kind = 'ocr_fragment'",
                (RUN_ID, page),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"saved Catalan p{page} evidence is unavailable")
            artifact = json.loads((DATA / row[0]).read_text())
            by_order = {raw["order"]: raw for raw in artifact["fragments"]}
            entries = []
            for local_order, source_order in enumerate(source_orders):
                raw = by_order[source_order]
                payload = {
                    key: val for key, val in raw.items() if key not in {"bbox", "order"}
                }
                payload["box"] = dict(
                    zip(("x0", "y0", "x1", "y1"), raw["bbox"], strict=True)
                )
                entries.append(
                    PromptEvidenceFragment(
                        order=local_order,
                        fragment=SourceEvidenceFragment.model_validate(payload),
                    )
                )
            pages.append(PromptEvidencePage(physical_page=page, fragments=entries))
    baseline = json.loads((OUTPUT / "p0-baseline.json").read_text())
    digest = next(x["pdf_sha256"] for x in baseline if x["window"] == "catalan-dev1")
    return CcefPromptContext(
        package_id=UUID("22ef5287-9c16-4e83-8274-362d049152a0"),
        created_at=datetime(2026, 9, 24, tzinfo=UTC),
        source_ref=f"sha256:{digest}",
        media_type="application/pdf",
        language="en",
        first_page=7,
        last_page=9,
        pages=pages,
        max_output_tokens=4000,
        max_prompt_chars=10000,
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
        timeout_seconds=120,
        max_output_tokens_limit=4000,
        thinking_enabled=False,
        json_output_enabled=True,
    )
    request = build_semantic_request(context)
    response = await provider.generate(request)
    run_dir = (
        OUTPUT / f"p2-catalan-live-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
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
    # The p7 options all share this manually reconstructed p6->9.e4 board.
    seeds = {
        event["sequence"]: AFTER_9_E4
        for event in events
        if event.get("kind") == "move"
        and event.get("source", {}).get("page") == 7
        and isinstance(event.get("sequence"), str)
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
