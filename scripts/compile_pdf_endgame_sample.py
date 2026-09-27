"""Compile a diagram-start Endgame p19–20 sample from saved local evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from chess_workbench.extraction.draft import find_diagram_seeds
from chess_workbench.extraction.evidence import SourceEvidenceFragment
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.score import score_candidate
from chess_workbench.extraction.source_compiler import compile_semantic_events

DATA = Path("data")
RUN_ID = "976c919ace51576bad77be9284d6ad47"


def load_context() -> CcefPromptContext:
    pages = []
    with sqlite3.connect(
        f"file:{DATA / 'database/chess-workbench.db'}?mode=ro", uri=True
    ) as db:
        for page in (19, 20):
            row = db.execute(
                "SELECT relative_path FROM extraction_artifacts WHERE run_id = ? "
                "AND page_number = ? AND kind = 'ocr_fragment'",
                (RUN_ID, page),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"Endgame p{page} saved evidence is unavailable")
            artifact = json.loads((DATA / row[0]).read_text())
            entries = []
            for raw in artifact["fragments"]:
                payload = {
                    key: val for key, val in raw.items() if key not in {"order", "bbox"}
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
    books = json.loads(
        (DATA / "debug/extraction-audit-20260924/books.json").read_text()
    )
    digest = next(
        book["sha256"] for book in books if book["name"].startswith("Endgame Strategy")
    )
    return CcefPromptContext(
        package_id=UUID("35b9eaa7-ded7-4164-835e-1520ad08414a"),
        created_at=datetime(2026, 9, 24, tzinfo=UTC),
        source_ref=f"sha256:{digest}",
        media_type="application/pdf",
        language="en",
        first_page=19,
        last_page=20,
        pages=pages,
        max_output_tokens=4000,
        max_prompt_chars=100000,
    )


def main() -> None:
    context = load_context()
    events: list[dict[str, object]] = []

    def add(event_id: str, kind: str, order: int, token: str, **extra: object) -> None:
        text = context.pages[1].fragments[order].fragment.text
        start = text.index(token)
        events.append(
            {
                "id": event_id,
                "kind": kind,
                "source": {
                    "page": 20,
                    "order": order,
                    "start": start,
                    "end": start + len(token),
                },
                **extra,
            }
        )

    add("mistake", "move", 2, "36.Rxe6?", sequence="game1", mainline=True)
    add("better", "move", 4, "36.Kf2!", sequence="game1")
    add("better_reply", "move", 4, "Ra3", sequence="game1", parent="better")
    add("better_next", "move", 4, "37.Ke3", sequence="game1", parent="better_reply")
    add("repeat", "annotation", 8, "36.Rxe6?", sequence="game1", anchor="mistake")
    add("punishment", "move", 8, "Kf5!", sequence="game1", parent="mistake")
    result = compile_semantic_events(context, events)
    output = (
        DATA / "debug/extraction-audit-20260924/p3-endgame-source-compiled-ccef.json"
    )
    output.write_text(result.model_dump_json(indent=2))
    sequence = next(item for item in result.items if item.kind == "move_sequence")
    coverage = score_candidate(context, result)
    print(
        json.dumps(
            {
                "diagram_seeds": len(find_diagram_seeds(context)),
                "figures": sum(item.kind == "figure" for item in result.items),
                "initial_position": sequence.initial_position.model_dump(),
                "moves": [
                    (
                        node.move_text,
                        node.parent_id,
                        node.sibling_order,
                        node.validation_status,
                    )
                    for node in sequence.nodes
                ],
                "annotations": len(sequence.annotations),
                "represented_fragments": coverage.represented_fragments,
                "total_fragments": coverage.total_fragments,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
