#!/usr/bin/env python3
"""Create a human-readable offline Stage 8C consolidation artifact and report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from chess_workbench.extraction.consolidation import consolidate_move_sequences
from chess_workbench.extraction.contracts import (
    ExtractionPackage,
    MoveSequenceItem,
    ProseItem,
)
from chess_workbench.extraction.evidence import NormalizedBox, SourceEvidenceFragment
from chess_workbench.extraction.prompting import (
    PromptEvidenceFragment,
    PromptEvidencePage,
)


def _load_evidence_page(path: Path) -> PromptEvidencePage:
    document = json.loads(path.read_text(encoding="utf-8"))
    fragments = []
    for raw in document["fragments"]:
        x0, y0, x1, y1 = raw["bbox"]
        fragment = SourceEvidenceFragment(
            physical_page=raw["physical_page"],
            box=NormalizedBox(x0=x0, y0=y0, x1=x1, y1=y1),
            text=raw["text"],
            origin=raw["origin"],
            confidence=raw["confidence"],
            engine_name=raw["engine_name"],
            engine_version=raw["engine_version"],
            fragment_sha256=raw["fragment_sha256"],
        )
        fragments.append(PromptEvidenceFragment(order=raw["order"], fragment=fragment))
    return PromptEvidencePage(
        physical_page=document["physical_page"],
        fragments=fragments,
    )


def _sequence_paths(sequence: MoveSequenceItem) -> list[list[str]]:
    nodes = {node.id: node for node in sequence.nodes}
    parent_ids = {
        node.parent_id for node in sequence.nodes if node.parent_id is not None
    }
    paths: list[list[str]] = []
    for leaf in (node for node in sequence.nodes if node.id not in parent_ids):
        path: list[str] = []
        current = leaf
        while True:
            path.append(current.san_candidate or current.move_text)
            if current.parent_id is None:
                break
            current = nodes[current.parent_id]
        paths.append(list(reversed(path)))
    return paths


def _fragment_hashes(value: Any) -> set[str]:
    if isinstance(value, dict):
        hashes = {
            item
            for key, item in value.items()
            if key == "fragment_sha256" and isinstance(item, str)
        }
        for item in value.values():
            hashes.update(_fragment_hashes(item))
        return hashes
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_fragment_hashes(item))
        return result
    return set()


def _report(raw: ExtractionPackage, normalized: ExtractionPackage) -> dict[str, Any]:
    raw_sequences = [item for item in raw.items if isinstance(item, MoveSequenceItem)]
    sequences = [
        item for item in normalized.items if isinstance(item, MoveSequenceItem)
    ]
    statuses = Counter(
        node.validation_status for item in sequences for node in item.nodes
    )
    duplicate_paths = 0
    sequence_reports = []
    for sequence in sequences:
        unique_paths: set[tuple[str, ...]] = set()
        node_paths: dict[str, tuple[str, ...]] = {}
        for node in sequence.nodes:
            parent_path = () if node.parent_id is None else node_paths[node.parent_id]
            path = parent_path + ((node.uci_candidate or node.move_text),)
            if path in unique_paths:
                duplicate_paths += 1
            unique_paths.add(path)
            node_paths[node.id] = path
        sequence_reports.append(
            {
                "id": sequence.id,
                "node_count": len(sequence.nodes),
                "leaf_lines": [" ".join(path) for path in _sequence_paths(sequence)],
            }
        )
    raw_prose_chars = sum(
        len(item.text) for item in raw.items if isinstance(item, ProseItem)
    )
    normalized_prose_chars = sum(
        len(item.text) for item in normalized.items if isinstance(item, ProseItem)
    )
    raw_non_move_ids = {
        item.id for item in raw.items if not isinstance(item, MoveSequenceItem)
    }
    normalized_item_ids = {item.id for item in normalized.items}
    missing_non_move_ids = sorted(raw_non_move_ids - normalized_item_ids)
    raw_fragment_hashes = _fragment_hashes(raw.model_dump(mode="json"))
    normalized_fragment_hashes = _fragment_hashes(normalized.model_dump(mode="json"))
    missing_fragment_hashes = sorted(raw_fragment_hashes - normalized_fragment_hashes)
    report = {
        "raw": {
            "item_count": len(raw.items),
            "sequence_count": len(raw_sequences),
            "move_node_count": sum(len(item.nodes) for item in raw_sequences),
            "prose_chars": raw_prose_chars,
        },
        "normalized": {
            "item_count": len(normalized.items),
            "item_kinds": dict(Counter(item.kind for item in normalized.items)),
            "sequence_count": len(sequences),
            "move_node_count": sum(len(item.nodes) for item in sequences),
            "move_statuses": dict(statuses),
            "duplicate_uci_path_count": duplicate_paths,
            "prose_chars": normalized_prose_chars,
            "missing_raw_non_move_item_ids": missing_non_move_ids,
            "raw_evidence_fragment_count": len(raw_fragment_hashes),
            "preserved_raw_evidence_fragment_count": len(
                raw_fragment_hashes & normalized_fragment_hashes
            ),
            "missing_raw_evidence_fragment_count": len(missing_fragment_hashes),
            "sequences": sequence_reports,
        },
    }
    report["gate_passed"] = bool(
        sequences
        and statuses.get("invalid", 0) == 0
        and statuses.get("ambiguous", 0) == 0
        and statuses.get("unvalidated", 0) == 0
        and duplicate_paths == 0
        and normalized_prose_chars >= raw_prose_chars
        and not missing_non_move_ids
        and not missing_fragment_hashes
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_ccef", type=Path)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    raw = ExtractionPackage.model_validate_json(
        args.raw_ccef.read_text(encoding="utf-8")
    )
    pages = sorted(
        (_load_evidence_page(path) for path in args.evidence),
        key=lambda page: page.physical_page,
    )
    normalized = consolidate_move_sequences(raw, pages)
    report = _report(raw, normalized)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(normalized.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
