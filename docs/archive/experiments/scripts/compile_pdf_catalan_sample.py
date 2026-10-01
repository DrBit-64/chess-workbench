"""Reproduce the P2 Catalan alternatives and incomplete-plan local example.

The p7 seed is reconstructed from the printed p6 opening moves and is explicit
here for audit. This is a hand-labelled slice, not automatic diagram recognition.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from chess_workbench.extraction.evidence import SourceEvidenceFragment
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.score import score_candidate
from chess_workbench.extraction.source_compiler import compile_semantic_events

DATA = Path("data")
RUN_ID = "1a9487829a7f5c978ac367bb18e958d9"
AFTER_9_E4 = "rn1q1rk1/pb2bppp/1pp1pn2/3p4/2PPP3/5NP1/PPQN1PBP/R1B2RK1 b - e3 0 9"


def main() -> None:
    pages = []
    with sqlite3.connect(
        f"file:{DATA / 'database/chess-workbench.db'}?mode=ro", uri=True
    ) as db:
        for page in (7, 8, 9):
            row = db.execute(
                "SELECT relative_path FROM extraction_artifacts WHERE run_id = ? "
                "AND page_number = ? AND kind = 'ocr_fragment'",
                (RUN_ID, page),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"saved Catalan p{page} evidence is unavailable")
            artifact = json.loads((DATA / row[0]).read_text())
            entries = []
            for raw in artifact["fragments"]:
                payload = {
                    key: val for key, val in raw.items() if key not in {"bbox", "order"}
                }
                payload["box"] = dict(
                    zip(("x0", "y0", "x1", "y1"), raw["bbox"], strict=True)
                )
                entries.append(
                    PromptEvidenceFragment(
                        order=raw["order"],
                        fragment=SourceEvidenceFragment.model_validate(payload),
                    )
                )
            pages.append(PromptEvidencePage(physical_page=page, fragments=entries))
    baseline = json.loads(
        (DATA / "debug/extraction-audit-20260924/p0-baseline.json").read_text()
    )
    digest = next(x["pdf_sha256"] for x in baseline if x["window"] == "catalan-dev1")
    context = CcefPromptContext(
        package_id=UUID("22ef5287-9c16-4e83-8274-362d049152a0"),
        created_at=datetime(2026, 9, 24, tzinfo=UTC),
        source_ref=f"sha256:{digest}",
        media_type="application/pdf",
        language="en",
        first_page=7,
        last_page=9,
        pages=pages,
        max_output_tokens=4000,
        max_prompt_chars=100000,
    )
    events: list[dict[str, object]] = []

    def add(
        event_id: str, kind: str, page: int, order: int, token: str, **extra: object
    ) -> None:
        value = context.pages[page - 7].fragments[order].fragment.text
        start = value.index(token)
        events.append(
            {
                "id": event_id,
                "kind": kind,
                "source": {
                    "page": page,
                    "order": order,
                    "start": start,
                    "end": start + len(token),
                },
                **extra,
            }
        )

    add("option_dxe4", "move", 7, 74, "9...dxe4", sequence="choice9")
    add("option_na6", "move", 7, 74, "9...Na6", sequence="choice9")
    add("actual_nbd7", "move", 7, 76, "9...Nbd7?!", sequence="choice9", mainline=True)
    add(
        "question_plan", "unresolved", 9, 2, context.pages[2].fragments[2].fragment.text
    )
    add("plan_continued", "prose", 9, 3, context.pages[2].fragments[3].fragment.text)
    add("answer", "prose", 9, 5, context.pages[2].fragments[5].fragment.text)
    candidate = compile_semantic_events(
        context, events, sequence_initial_fens={"choice9": AFTER_9_E4}
    )
    output = (
        DATA / "debug/extraction-audit-20260924/p2-catalan-source-compiled-ccef.json"
    )
    output.write_text(candidate.model_dump_json(indent=2))
    sequence = next(item for item in candidate.items if item.kind == "move_sequence")
    coverage = score_candidate(context, candidate)
    print(
        json.dumps(
            {
                "output": str(output),
                "moves": [
                    (node.move_text, node.sibling_order, node.validation_status)
                    for node in sequence.nodes
                ],
                "unresolved": sum(
                    item.kind == "unresolved" for item in candidate.items
                ),
                "represented_fragments": coverage.represented_fragments,
                "total_fragments": coverage.total_fragments,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
