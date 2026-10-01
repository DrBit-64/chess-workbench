"""Replay saved P6 DeepSeek responses through the current local compiler, without network."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from chess_workbench.extraction.chunks import generate_semantic_page_chunks
from chess_workbench.extraction.evidence import NormalizedBox, SourceEvidenceFragment
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.provider import (
    ScriptedStructuredGenerationProvider,
    StructuredGenerationResponse,
)
from chess_workbench.extraction.score import score_candidate

ROOT = Path(__file__).resolve().parents[1] / "data/debug/extraction-audit-20260924/p6"


def _saved_context(name: str) -> CcefPromptContext:
    """Read immutable saved evidence without opening an application DB session."""
    directory = ROOT / name
    original = json.loads((directory / "result.json").read_text())
    run_id = original["run_id"].replace("-", "")
    with sqlite3.connect(f"file:{ROOT / 'evaluation.db'}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT page_number, relative_path FROM extraction_artifacts "
            "WHERE run_id = ? AND kind = 'ocr_fragment' ORDER BY page_number",
            (run_id,),
        ).fetchall()
        run = connection.execute(
            "SELECT r.first_page, r.last_page, r.created_at, a.source_file_id "
            "FROM extraction_runs r JOIN pdf_assets a ON a.id = r.pdf_asset_id "
            "WHERE r.id = ?",
            (run_id,),
        ).fetchone()
    if run is None or len(rows) != run[1] - run[0] + 1:
        raise ValueError("P6 saved source evidence is incomplete")
    pages = []
    for page_number, relative_path in rows:
        document = json.loads((ROOT / "storage" / relative_path).read_text())
        entries = []
        for position, value in enumerate(document["fragments"]):
            box = NormalizedBox.model_validate(
                dict(zip(("x0", "y0", "x1", "y1"), value["bbox"], strict=True))
            )
            fragment = SourceEvidenceFragment(
                physical_page=page_number,
                box=box,
                text=value["text"],
                origin=value["origin"],
                font_color=value.get("font_color"),
                confidence=value["confidence"],
                engine_name=value["engine_name"],
                engine_version=value["engine_version"],
                fragment_sha256=value["fragment_sha256"],
            )
            entries.append(PromptEvidenceFragment(order=position, fragment=fragment))
        pages.append(PromptEvidencePage(physical_page=page_number, fragments=entries))
    return CcefPromptContext(
        package_id=UUID(original["run_id"]),
        created_at=datetime.fromisoformat(run[2]).replace(tzinfo=UTC),
        source_ref=f"source-file:{UUID(run[3])}",
        media_type="application/pdf",
        language="en",
        first_page=run[0],
        last_page=run[1],
        pages=pages,
        max_output_tokens=7000,
        max_prompt_chars=1_000_000,
    )


async def replay(name: str) -> dict[str, object]:
    directory = ROOT / name
    context = _saved_context(name)
    responses = [
        StructuredGenerationResponse.model_validate_json(path.read_text())
        for path in sorted(directory.glob("chunk-*/response.json"))
    ]
    generated = await generate_semantic_page_chunks(
        context, ScriptedStructuredGenerationProvider(responses)
    )
    package = generated.package
    coverage = score_candidate(context, package)
    sequences = [item for item in package.items if item.kind == "move_sequence"]
    summary: dict[str, object] = {
        "window_id": name,
        "chunks": len(generated.chunks),
        "items": len(package.items),
        "move_nodes": sum(len(item.nodes) for item in sequences),
        "valid_moves": sum(
            node.validation_status == "valid" for item in sequences for node in item.nodes
        ),
        "invalid_moves": coverage.invalid_moves,
        "unresolved_items": coverage.unresolved_items,
        "represented_fragments": coverage.represented_fragments,
        "total_fragments": coverage.total_fragments,
        "figures": sum(item.kind == "figure" for item in package.items),
        "diagnostics": dict(Counter(item.code for item in package.diagnostics)),
    }
    (directory / "replayed-package.json").write_text(package.model_dump_json(indent=2))
    (directory / "replayed-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("window", nargs="+")
    names = parser.parse_args().window
    for name in names:
        print(json.dumps(asyncio.run(replay(name))))


if __name__ == "__main__":
    main()
