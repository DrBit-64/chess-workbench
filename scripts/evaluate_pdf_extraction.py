"""Local read-only baseline for the two initial PDF extraction windows.

This deliberately reads the operator's ignored data directory and never calls a provider.
It is a development aid, not a CI gate or a gold-label substitute.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

WINDOWS = {
    "catalan-dev1": ("The Catalan", 6, 9),
    "scandinavian-dev1": ("Smerdons Scandinavian", 319, 323),
}


def inspect_window(root: Path, name: str) -> dict[str, object]:
    book_prefix, first_page, last_page = WINDOWS[name]
    books = list((root / "books").glob(f"{book_prefix}*.pdf"))
    if len(books) != 1:
        raise ValueError(f"expected one local PDF for {name}")
    digest = hashlib.sha256(books[0].read_bytes()).hexdigest()
    with sqlite3.connect(
        f"file:{root / 'database/chess-workbench.db'}?mode=ro", uri=True
    ) as db:
        db.row_factory = sqlite3.Row
        runs = [
            dict(row)
            for row in db.execute(
                """SELECT r.id, r.pipeline_version, j.status, j.last_error_code,
                          j.attempt_count, r.created_at
                     FROM extraction_runs r
                     JOIN pdf_assets a ON a.id = r.pdf_asset_id
                     JOIN jobs j ON j.id = r.job_id
                    WHERE a.content_sha256 = ? AND r.first_page = ? AND r.last_page = ?
                    ORDER BY r.created_at""",
                (digest, first_page, last_page),
            )
        ]
        artifacts = {
            run["id"]: list(
                db.execute(
                    "SELECT kind, relative_path, page_number FROM extraction_artifacts WHERE run_id = ?",
                    (run["id"],),
                )
            )
            for run in runs
        }
    for run in runs:
        indexed = artifacts[run["id"]]
        run["evidence_pages"] = sum(row[0] == "ocr_fragment" for row in indexed)
        normalized = next((row for row in indexed if row[0] == "normalized_ccef"), None)
        if normalized is None:
            continue
        path = root / normalized[1]
        candidate = json.loads(path.read_text())
        sequences = [
            item for item in candidate["items"] if item["kind"] == "move_sequence"
        ]
        run["candidate"] = {
            "item_count": len(candidate["items"]),
            "sequence_count": len(sequences),
            "move_node_count": sum(len(item["nodes"]) for item in sequences),
            "annotation_count": sum(
                len(item.get("annotations", [])) for item in sequences
            ),
            "unresolved_count": sum(
                item["kind"] == "unresolved" for item in candidate["items"]
            ),
        }
    return {
        "window": name,
        "physical_pages": [first_page, last_page],
        "pdf_sha256": digest,
        "run_count": len(runs),
        "status_counts": dict(Counter(run["status"] for run in runs)),
        "runs": runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--window", choices=tuple(WINDOWS))
    arguments = parser.parse_args()
    names = [arguments.window] if arguments.window else list(WINDOWS)
    print(
        json.dumps(
            [inspect_window(arguments.data_root, name) for name in names], indent=2
        )
    )


if __name__ == "__main__":
    main()
