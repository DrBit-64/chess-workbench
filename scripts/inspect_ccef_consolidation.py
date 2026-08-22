#!/usr/bin/env python3
"""Create a human-readable offline Stage 8C/8D consolidation artifact and report.

Provider-free inspection of a raw CCEF package against its consolidated
normalized form. ``--ccef-version`` selects the public contract explicitly
(1.0 default for backward compatibility; 1.1 for annotated scores); version
selection never inspects untrusted JSON content. ``--committed-normalized``
optionally compares the offline recomputation with a worker-committed
normalized artifact using canonical JSON values.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chess_workbench.extraction.consolidation import (
    consolidate_move_sequences,
    consolidate_move_sequences_v1_1,
)
from chess_workbench.extraction.contracts import (
    ExtractionPackage,
    ExtractionPackageV1_1,
    MoveNodeAnnotationAnchor,
    MoveSequenceItem,
    MoveSequenceItemV1_1,
    PositionAnnotationAnchor,
    ProseItem,
)
from chess_workbench.extraction.evidence import NormalizedBox, SourceEvidenceFragment
from chess_workbench.extraction.prompting import (
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from pydantic import ValidationError


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


def _sequence_items(
    package: ExtractionPackage | ExtractionPackageV1_1, *, ccef_version: str
) -> list[Any]:
    """Sequence items of one package, selected by the explicit CCEF version."""
    if ccef_version == "1.1":
        return [
            item for item in package.items if isinstance(item, MoveSequenceItemV1_1)
        ]
    return [item for item in package.items if isinstance(item, MoveSequenceItem)]


def _sequence_paths(sequence: Any) -> list[list[str]]:
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


def _report(
    raw: ExtractionPackage | ExtractionPackageV1_1,
    normalized: ExtractionPackage | ExtractionPackageV1_1,
    *,
    ccef_version: str,
) -> dict[str, Any]:
    raw_sequences = _sequence_items(raw, ccef_version=ccef_version)
    sequences = _sequence_items(normalized, ccef_version=ccef_version)
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
        entry: dict[str, Any] = {
            "id": sequence.id,
            "node_count": len(sequence.nodes),
            "leaf_lines": [" ".join(path) for path in _sequence_paths(sequence)],
        }
        if ccef_version == "1.1":
            entry["annotation_count"] = len(sequence.annotations)
            entry["reading_flow_count"] = len(sequence.reading_flow)
        sequence_reports.append(entry)
    raw_prose_chars = sum(
        len(item.text) for item in raw.items if isinstance(item, ProseItem)
    )
    normalized_prose_chars = sum(
        len(item.text) for item in normalized.items if isinstance(item, ProseItem)
    )
    sequence_type: type[Any] = (
        MoveSequenceItemV1_1 if ccef_version == "1.1" else MoveSequenceItem
    )
    raw_non_move_ids = {
        item.id for item in raw.items if not isinstance(item, sequence_type)
    }
    normalized_item_ids = {item.id for item in normalized.items}
    missing_non_move_ids = sorted(raw_non_move_ids - normalized_item_ids)
    raw_fragment_hashes = _fragment_hashes(raw.model_dump(mode="json"))
    normalized_fragment_hashes = _fragment_hashes(normalized.model_dump(mode="json"))
    missing_fragment_hashes = sorted(raw_fragment_hashes - normalized_fragment_hashes)
    report: dict[str, Any] = {
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
    if ccef_version == "1.1":
        annotation_count = sum(len(item.annotations) for item in sequences)
        flow_entries = [entry for item in sequences for entry in item.reading_flow]
        move_refs = sum(1 for entry in flow_entries if entry.kind == "move")
        annotation_refs = sum(1 for entry in flow_entries if entry.kind == "annotation")
        variation_starts = sum(
            1 for item in sequences for node in item.nodes if node.sibling_order > 0
        )
        anchor_counts: dict[str, int] = {"move_node": 0, "position": 0, "null": 0}
        for item in sequences:
            for annotation in item.annotations:
                if isinstance(annotation.anchor, MoveNodeAnnotationAnchor):
                    anchor_counts["move_node"] += 1
                elif isinstance(annotation.anchor, PositionAnnotationAnchor):
                    anchor_counts["position"] += 1
                else:
                    anchor_counts["null"] += 1
        total_nodes = sum(len(item.nodes) for item in sequences)
        report["normalized"]["annotation_count"] = annotation_count
        report["normalized"]["reading_flow_entry_count"] = len(flow_entries)
        report["normalized"]["reading_flow_move_ref_count"] = move_refs
        report["normalized"]["reading_flow_annotation_ref_count"] = annotation_refs
        report["normalized"]["variation_start_count"] = variation_starts
        report["normalized"]["annotation_anchor_counts"] = anchor_counts
        report["gate_passed"] = bool(
            report["gate_passed"]
            and statuses.get("valid", 0) == total_nodes
            and move_refs == total_nodes
            and annotation_refs == annotation_count
        )
    return report


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _run(
    args: argparse.Namespace,
    *,
    ccef_version: str,
    model: type[ExtractionPackage | ExtractionPackageV1_1],
    consolidate: Callable[..., Any],
) -> int:
    try:
        raw = model.model_validate_json(args.raw_ccef.read_text(encoding="utf-8"))
    except ValidationError:
        return _fail(f"raw CCEF does not validate as a {ccef_version} package")
    pages = sorted(
        (_load_evidence_page(path) for path in args.evidence),
        key=lambda page: page.physical_page,
    )
    normalized = consolidate(raw, pages)
    report = _report(raw, normalized, ccef_version=ccef_version)
    committed_matches: bool | None = None
    if args.committed_normalized is not None:
        try:
            committed = model.model_validate_json(
                args.committed_normalized.read_text(encoding="utf-8")
            )
        except ValidationError:
            return _fail(
                f"committed normalized CCEF does not validate as a {ccef_version} package"
            )
        committed_matches = committed.model_dump(mode="json") == normalized.model_dump(
            mode="json"
        )
        if ccef_version == "1.1":
            report["gate_passed"] = bool(report["gate_passed"] and committed_matches)
    if ccef_version == "1.1" or args.committed_normalized is not None:
        report["committed_matches_offline"] = committed_matches
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_ccef", type=Path)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ccef-version", choices=("1.0", "1.1"), default="1.0")
    parser.add_argument("--committed-normalized", type=Path)
    args = parser.parse_args()

    if args.ccef_version == "1.1":
        return _run(
            args,
            ccef_version="1.1",
            model=ExtractionPackageV1_1,
            consolidate=consolidate_move_sequences_v1_1,
        )
    return _run(
        args,
        ccef_version="1.0",
        model=ExtractionPackage,
        consolidate=consolidate_move_sequences,
    )


if __name__ == "__main__":
    raise SystemExit(main())
