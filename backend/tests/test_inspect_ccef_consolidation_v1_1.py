"""Focused tests for the offline CCEF consolidation inspector (8D-3D4A).

Runs `scripts/inspect_ccef_consolidation.py` as a subprocess with invented
synthetic CCEF/evidence only. Covers: explicit 1.1 mode with exact annotation/
reading-flow/branch/anchor facts and gate conditions; the committed-normalized
canonical comparison (true/false); literal version mismatch rejection; input
non-mutation; and a default-1.0 regression preserving the old report key set,
counts and exit convention. No real book data, provider call, database or
network access.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from chess_workbench.extraction.evidence import NormalizedBox, source_fragment_sha256

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/inspect_ccef_consolidation.py"
PACKAGE_ID = "11111111-1111-4111-8111-111111111111"


def _node(
    node_id: str,
    parent_id: str | None,
    sibling_order: int,
    move_text: str,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": sibling_order,
        "move_text": move_text,
        "evidence": [{"page": 1, "fragment_sha256": "a" * 64}],
    }


def _annotation(
    annotation_id: str,
    text: str,
    anchor: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "id": annotation_id,
        "text": text,
        "text_format": "plain",
        "anchor": anchor,
        "evidence": [{"page": 1, "fragment_sha256": "b" * 64}],
        "confidence": None,
        "warnings": [],
        "extensions": {},
    }


def _v1_1_sequence() -> dict[str, Any]:
    """Continuous main line, interleaved annotation, earlier-parent local
    variation, nested variation and a later main-line continuation."""
    nodes = [
        _node("n1", None, 0, "e4"),
        _node("n2", "n1", 0, "e5"),
        _node("n3", "n2", 0, "Nf3"),
        _node("n4", "n3", 0, "Nc6"),
        _node("n5", "n4", 0, "d4"),
        _node("n6", "n5", 0, "exd4"),
        _node("n7", "n6", 0, "Nxd4"),
        _node("n8", "n7", 0, "Nf6"),
        _node("n9", "n8", 0, "Nc3"),
        _node("n10", "n9", 0, "Bb4"),
        _node("n11", "n10", 0, "Be3"),
        _node("n12", "n10", 1, "a3"),
        _node("n13", "n12", 0, "d6"),
        _node("n14", "n13", 0, "a4"),
        _node("n15", "n13", 1, "b3"),
        _node("n16", "n11", 0, "Be7"),
    ]
    annotations = [
        _annotation(
            "a1",
            "The bishop steps aside to keep the long diagonal covered.",
            {"kind": "move_node", "node_id": "n11", "relation": "after"},
        ),
        _annotation("a2", "A short note without a reliable board anchor.", None),
    ]
    reading_flow: list[dict[str, Any]] = [
        {"kind": "move", "node_id": f"n{index}"} for index in range(1, 17)
    ]
    reading_flow.insert(11, {"kind": "annotation", "annotation_id": "a1"})
    reading_flow.append({"kind": "annotation", "annotation_id": "a2"})
    return {
        "kind": "move_sequence",
        "id": "seq1",
        "title": "Synthetic annotated opening",
        "evidence": [{"page": 1, "fragment_sha256": "c" * 64}],
        "initial_position": {"kind": "startpos"},
        "nodes": nodes,
        "annotations": annotations,
        "reading_flow": reading_flow,
    }


def _v1_1_package(*, annotation_text: str | None = None) -> dict[str, Any]:
    sequence = _v1_1_sequence()
    if annotation_text is not None:
        sequence["annotations"][0]["text"] = annotation_text
    return {
        "schema_version": "chess-content-extraction/1.1",
        "package_id": PACKAGE_ID,
        "source": {
            "source_ref": "source:synthetic:offline-inspector",
            "media_type": "application/pdf",
            "language": "en",
            "page_range": {"start_page": 1, "end_page": 1},
        },
        "items": [
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": "Synthetic chapter",
                "evidence": [{"page": 1}],
            },
            sequence,
        ],
        "diagnostics": [],
        "provenance": {
            "created_at": "2026-08-14T12:34:56Z",
            "adapter_name": "chess-workbench-ccef-prompt",
            "adapter_version": "1.1",
            "provider": None,
            "model": None,
            "request_sha256": None,
            "response_sha256": None,
        },
        "extensions": {},
    }


def _v1_package() -> dict[str, Any]:
    return {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": PACKAGE_ID,
        "source": {
            "source_ref": "source:synthetic:offline-inspector",
            "media_type": "application/pdf",
            "language": "en",
            "page_range": {"start_page": 1, "end_page": 1},
        },
        "items": [
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": "Synthetic chapter",
                "evidence": [{"page": 1}],
            },
            {
                "kind": "move_sequence",
                "id": "line-1",
                "initial_position": {"kind": "startpos"},
                "nodes": [
                    _node("move-1", None, 0, "e4"),
                    _node("move-2", "move-1", 0, "e5"),
                    _node("move-3", "move-1", 1, "c5"),
                ],
                "evidence": [{"page": 1}],
            },
        ],
        "diagnostics": [],
        "provenance": {
            "created_at": "2026-08-14T12:34:56Z",
            "adapter_name": "chess-workbench-ccef-prompt",
            "adapter_version": "1.0",
            "provider": None,
            "model": None,
            "request_sha256": None,
            "response_sha256": None,
        },
        "extensions": {},
    }


def _evidence_document() -> dict[str, Any]:
    evidence_text = "1. e4 e5 2. Nf3 Nc6 3. d4 exd4 4. Nxd4 Nf6 5. Nc3 Bb4"
    box = NormalizedBox(x0=0.1, y0=0.2, x1=0.9, y1=0.3)
    return {
        "physical_page": 1,
        "fragments": [
            {
                "order": 0,
                "physical_page": 1,
                "bbox": [0.1, 0.2, 0.9, 0.3],
                "text": evidence_text,
                "origin": "embedded_text",
                "confidence": None,
                "engine_name": "pdfium",
                "engine_version": "t",
                "fragment_sha256": source_fragment_sha256(
                    1, box, evidence_text, "embedded_text", "pdfium", "t"
                ),
            }
        ],
    }


def _write(tmp_path: Path, name: str, payload: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _run_script(tmp_path: Path, raw: Path, *args: str) -> subprocess.CompletedProcess[str]:
    output = tmp_path / "normalized.json"
    report = tmp_path / "report.json"
    command = [
        sys.executable,
        str(SCRIPT),
        str(raw),
        "--evidence",
        str(tmp_path / "evidence.json"),
        "--output",
        str(output),
        "--report",
        str(report),
        *args,
    ]
    return subprocess.run(command, capture_output=True, text=True, check=False, cwd=tmp_path)


# ---------------------------------------------------------------------------
# 1.1 inspection facts and gate
# ---------------------------------------------------------------------------


def test_1_1_mode_reports_exact_annotation_flow_branch_and_anchor_facts(
    tmp_path: Path,
) -> None:
    raw_path = _write(tmp_path, "raw-1-1.json", _v1_1_package())
    _write(tmp_path, "evidence.json", _evidence_document())
    result = _run_script(tmp_path, raw_path, "--ccef-version", "1.1")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)

    assert report["gate_passed"] is True
    normalized = report["normalized"]
    assert normalized["sequence_count"] == 1
    assert normalized["move_node_count"] == 16
    assert normalized["move_statuses"] == {"valid": 16}
    assert normalized["duplicate_uci_path_count"] == 0
    assert normalized["annotation_count"] == 2
    assert normalized["reading_flow_entry_count"] == 18
    assert normalized["reading_flow_move_ref_count"] == 16
    assert normalized["reading_flow_annotation_ref_count"] == 2
    # n12 (earlier-parent alternative) and n15 (nested alternative).
    assert normalized["variation_start_count"] == 2
    assert normalized["annotation_anchor_counts"] == {"move_node": 1, "position": 0, "null": 1}
    sequence_report = normalized["sequences"][0]
    assert sequence_report["id"] == "seq1"
    assert sequence_report["node_count"] == 16
    assert sequence_report["annotation_count"] == 2
    assert sequence_report["reading_flow_count"] == 18
    assert report.get("committed_matches_offline") is None

    # The pretty output preserves exact topology/annotation/flow data.
    pretty = json.loads((tmp_path / "normalized.json").read_text(encoding="utf-8"))
    seq = pretty["items"][1]
    node_map = {node["id"]: node for node in seq["nodes"]}
    assert node_map["n12"]["parent_id"] == "n10"
    assert node_map["n12"]["sibling_order"] == 1
    assert node_map["n15"]["parent_id"] == "n13"
    assert node_map["n15"]["sibling_order"] == 1
    assert node_map["n16"]["parent_id"] == "n11"
    assert [annotation["id"] for annotation in seq["annotations"]] == ["a1", "a2"]
    flow_kinds = [entry["kind"] for entry in seq["reading_flow"]]
    assert flow_kinds == ["move"] * 11 + ["annotation"] + ["move"] * 5 + ["annotation"]


def test_1_1_committed_comparison_true_and_false(tmp_path: Path) -> None:
    raw_path = _write(tmp_path, "raw-1-1.json", _v1_1_package())
    _write(tmp_path, "evidence.json", _evidence_document())
    # The offline recomputation is the canonical comparison baseline.
    baseline = _run_script(tmp_path, raw_path, "--ccef-version", "1.1")
    assert baseline.returncode == 0, baseline.stderr
    matching = _write(
        tmp_path, "committed-1-1.json", json.loads((tmp_path / "normalized.json").read_text())
    )
    result = _run_script(
        tmp_path,
        raw_path,
        "--ccef-version",
        "1.1",
        "--committed-normalized",
        str(matching),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["committed_matches_offline"] is True
    assert report["gate_passed"] is True

    different_payload = json.loads((tmp_path / "normalized.json").read_text())
    different_payload["items"][1]["annotations"][0]["text"] = "A changed text."
    different = _write(tmp_path, "committed-different.json", different_payload)
    result = _run_script(
        tmp_path,
        raw_path,
        "--ccef-version",
        "1.1",
        "--committed-normalized",
        str(different),
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["committed_matches_offline"] is False
    assert report["gate_passed"] is False


def test_version_mismatch_is_rejected_without_fallback(tmp_path: Path) -> None:
    _write(tmp_path, "evidence.json", _evidence_document())
    v1_1_raw = _write(tmp_path, "raw-1-1.json", _v1_1_package())
    result = _run_script(tmp_path, v1_1_raw)  # default 1.0 mode
    assert result.returncode == 2
    assert "does not validate as a 1.0 package" in result.stderr
    assert not (tmp_path / "report.json").exists()

    v1_raw = _write(tmp_path, "raw-1-0.json", _v1_package())
    result = _run_script(tmp_path, v1_raw, "--ccef-version", "1.1")
    assert result.returncode == 2
    assert "does not validate as a 1.1 package" in result.stderr


def test_inputs_remain_unchanged(tmp_path: Path) -> None:
    raw_path = _write(tmp_path, "raw-1-1.json", _v1_1_package())
    _write(tmp_path, "evidence.json", _evidence_document())
    committed = _write(tmp_path, "committed-1-1.json", _v1_1_package())
    raw_snapshot = raw_path.read_bytes()
    evidence_snapshot = (tmp_path / "evidence.json").read_bytes()
    committed_snapshot = committed.read_bytes()
    _run_script(
        tmp_path,
        raw_path,
        "--ccef-version",
        "1.1",
        "--committed-normalized",
        str(committed),
    )
    assert raw_path.read_bytes() == raw_snapshot
    assert (tmp_path / "evidence.json").read_bytes() == evidence_snapshot
    assert committed.read_bytes() == committed_snapshot


# ---------------------------------------------------------------------------
# Default 1.0 regression
# ---------------------------------------------------------------------------


def test_default_1_0_mode_preserves_report_keys_and_exit_convention(
    tmp_path: Path,
) -> None:
    raw_path = _write(tmp_path, "raw-1-0.json", _v1_package())
    _write(tmp_path, "evidence.json", _evidence_document())
    result = _run_script(tmp_path, raw_path)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert set(report) == {"raw", "normalized", "gate_passed"}
    assert set(report["raw"]) == {
        "item_count",
        "sequence_count",
        "move_node_count",
        "prose_chars",
    }
    assert set(report["normalized"]) == {
        "item_count",
        "item_kinds",
        "sequence_count",
        "move_node_count",
        "move_statuses",
        "duplicate_uci_path_count",
        "prose_chars",
        "missing_raw_non_move_item_ids",
        "raw_evidence_fragment_count",
        "preserved_raw_evidence_fragment_count",
        "missing_raw_evidence_fragment_count",
        "sequences",
    }
    assert set(report["normalized"]["sequences"][0]) == {
        "id",
        "node_count",
        "leaf_lines",
    }
    assert report["normalized"]["move_statuses"] == {"valid": 3}
    assert report["normalized"]["duplicate_uci_path_count"] == 0
    assert report["gate_passed"] is True
    # The 1.1-only facts never leak into default 1.0 output.
    assert "committed_matches_offline" not in report
    assert "annotation_count" not in report["normalized"]

    # Explicit --ccef-version 1.0 behaves identically.
    explicit = _run_script(tmp_path, raw_path, "--ccef-version", "1.0")
    assert explicit.returncode == 0
    assert json.loads(explicit.stdout) == report


def test_1_0_committed_comparison_reports_without_changing_gate(tmp_path: Path) -> None:
    raw_path = _write(tmp_path, "raw-1-0.json", _v1_package())
    _write(tmp_path, "evidence.json", _evidence_document())
    baseline = _run_script(tmp_path, raw_path)
    assert baseline.returncode == 0, baseline.stderr
    matching = _write(
        tmp_path, "committed-1-0.json", json.loads((tmp_path / "normalized.json").read_text())
    )
    result = _run_script(
        tmp_path,
        raw_path,
        "--committed-normalized",
        str(matching),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["committed_matches_offline"] is True
    assert report["gate_passed"] is True
