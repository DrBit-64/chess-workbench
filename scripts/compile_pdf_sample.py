"""Reproduce the P1 Scandinavian source-compilation example from saved local evidence.

This is a hand-labelled semantic proposal, not a model-quality measurement.
It reads local artifacts only and writes an ignored debug candidate.
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

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RUN_ID = "4b33f70ab6235ec3bc8e5ed6a2a28e4a"
PAGE = 319


def load_context() -> CcefPromptContext:
    with sqlite3.connect(
        f"file:{DATA / 'database/chess-workbench.db'}?mode=ro", uri=True
    ) as db:
        row = db.execute(
            "SELECT relative_path FROM extraction_artifacts WHERE run_id = ? "
            "AND page_number = ? AND kind = 'ocr_fragment'",
            (RUN_ID, PAGE),
        ).fetchone()
    if row is None:
        raise RuntimeError("saved Scandinavian page evidence is unavailable")
    source = json.loads((DATA / row[0]).read_text())
    entries = []
    for raw in source["fragments"]:
        # Source artifact has an extra ``order`` and a ``bbox`` list.
        payload = {
            key: value for key, value in raw.items() if key not in {"order", "bbox"}
        }
        payload["box"] = dict(zip(("x0", "y0", "x1", "y1"), raw["bbox"], strict=True))
        fragment = SourceEvidenceFragment.model_validate(payload)
        entries.append(PromptEvidenceFragment(order=raw["order"], fragment=fragment))
    baseline = json.loads(
        (DATA / "debug/extraction-audit-20260924/p0-baseline.json").read_text()
    )
    digest = next(
        x["pdf_sha256"] for x in baseline if x["window"] == "scandinavian-dev1"
    )
    context = CcefPromptContext(
        package_id=UUID("b207467b-c949-43ae-a4d1-52ba3bf61d2b"),
        created_at=datetime(2026, 9, 24, tzinfo=UTC),
        source_ref=f"sha256:{digest}",
        media_type="application/pdf",
        language="en",
        first_page=PAGE,
        last_page=PAGE,
        pages=[PromptEvidencePage(physical_page=PAGE, fragments=entries)],
        max_output_tokens=4000,
        max_prompt_chars=20000,
    )
    return context


def main() -> None:
    context = load_context()
    entries = context.pages[0].fragments
    events: list[dict[str, object]] = []

    def add(event_id: str, kind: str, order: int, token: str, **relations: str) -> None:
        value = entries[order].fragment.text
        start = value.index(token)
        events.append(
            {
                "id": event_id,
                "kind": kind,
                "source": {
                    "page": PAGE,
                    "order": order,
                    "start": start,
                    "end": start + len(token),
                },
                **relations,
            }
        )

    add("chapter", "heading", 0, "Chapter Eight")
    add("title", "heading", 1, "The Classical")
    add("intro", "heading", 2, "Introduction")
    moves = ["e4", "d5", "exd5", "Nf6", "d4", "Bg4", "Nf3", "Qxd5"]
    line = entries[3].fragment.text
    cursor = 0
    for index, token in enumerate(moves):
        start = line.index(token, cursor)
        cursor = start + len(token)
        events.append(
            {
                "id": f"main{index}",
                "kind": "move",
                "sequence": "introduction",
                "parent": f"main{index - 1}" if index else None,
                "source": {"page": PAGE, "order": 3, "start": start, "end": cursor},
            }
        )
    add(
        "comment",
        "annotation",
        4,
        entries[4].fragment.text,
        sequence="introduction",
        anchor="main7",
    )
    branch = entries[5].fragment.text
    cursor = branch.index("3 Nf3")
    for index, token in enumerate(("Nf3", "Bg4", "d4")):
        start = branch.index(token, cursor)
        cursor = start + len(token)
        events.append(
            {
                "id": f"alternative{index}",
                "kind": "move",
                "sequence": "introduction",
                "parent": "main3" if index == 0 else f"alternative{index - 1}",
                "source": {"page": PAGE, "order": 5, "start": start, "end": cursor},
            }
        )
    result = compile_semantic_events(context, events)
    target = DATA / "debug/extraction-audit-20260924/p1-source-compiled-ccef.json"
    target.write_text(result.model_dump_json(indent=2))
    coverage = score_candidate(context, result)
    print(
        json.dumps(
            {
                "output": str(target.relative_to(ROOT)),
                "items": len(result.items),
                "moves": sum(
                    len(item.nodes)
                    for item in result.items
                    if item.kind == "move_sequence"
                ),
                "valid_moves": sum(
                    node.validation_status == "valid"
                    for item in result.items
                    if item.kind == "move_sequence"
                    for node in item.nodes
                ),
                "annotations": sum(
                    len(item.annotations)
                    for item in result.items
                    if item.kind == "move_sequence"
                ),
                "unresolved": sum(item.kind == "unresolved" for item in result.items),
                "represented_fragments": coverage.represented_fragments,
                "total_fragments": coverage.total_fragments,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
