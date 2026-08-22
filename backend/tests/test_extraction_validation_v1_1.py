"""Focused tests for the CCEF 1.1 chess move normalizer (8D-3D3A).

Covers the frozen 1.1 normalizer behavior: exact canonical SAN/UCI/before-
after FEN recomputation driven by ``parent_id`` topology (not reading-flow
adjacency) across mainline, earlier-parent alternatives, nested alternatives
and a later mainline continuation; byte-for-byte preservation of sequence
annotations, reading flow and every non-normalization field; input immutability
and output independence; stable warnings for illegal/context-mismatched/
disconnected nodes; idempotency without duplicate warnings; reviewable invalid
initial FENs; and import purity. All content is invented (pages 1-2).
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any

from chess_workbench.extraction.contracts import (
    ExtractionPackageV1_1,
    MoveNodeAnnotationAnchor,
    MoveSequenceItemV1_1,
)
from chess_workbench.extraction.validation import (
    normalize_chess_moves_v1_1,
)

MODULE = Path(__file__).parents[1] / "src/chess_workbench/extraction/validation.py"

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_N10_FEN = "r1bqk2r/pppp1ppp/2n2n2/8/1b1NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 3 6"
AFTER_N11_FEN = "r1bqk2r/pppp1ppp/2n2n2/8/1b1NP3/2N1B3/PPP2PPP/R2QKB1R b KQkq - 4 6"
AFTER_N12_FEN = "r1bqk2r/pppp1ppp/2n2n2/8/1b1NP3/P1N5/1PP2PPP/R1BQKB1R b KQkq - 0 6"
AFTER_N13_FEN = "r1bqk2r/ppp2ppp/2np1n2/8/1b1NP3/P1N5/1PP2PPP/R1BQKB1R w KQkq - 0 7"
AFTER_N14_FEN = "r1bqk2r/ppp2ppp/2np1n2/8/Pb1NP3/2N5/1PP2PPP/R1BQKB1R b KQkq - 0 7"
AFTER_N15_FEN = "r1bqk2r/ppp2ppp/2np1n2/8/1b1NP3/PPN5/2P2PPP/R1BQKB1R b KQkq - 0 7"
AFTER_N16_FEN = "r1bqk2r/ppppbppp/2n2n2/8/3NP3/2N1B3/PPP2PPP/R2QKB1R w KQkq - 5 7"

VALIDATOR_CODES = {
    "ccef_chess_invalid_initial_position",
    "ccef_chess_unresolved_parent",
    "ccef_chess_ambiguous_move",
    "ccef_chess_invalid_move",
    "ccef_chess_context_mismatch",
}


def _node(
    node_id: str,
    parent_id: str | None,
    order: int,
    move_text: str,
    **extra: Any,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": order,
        "move_text": move_text,
        "evidence": [{"page": 1}],
    }
    data.update(extra)
    return data


def _annotations() -> list[dict[str, Any]]:
    return [
        {
            "id": "a1",
            "text": "The bishop steps aside to keep the long diagonal covered.",
            "anchor": {"kind": "move_node", "node_id": "n11", "relation": "after"},
            "evidence": [{"page": 2}],
        },
        {
            "id": "a2",
            "text": "The queenside pawns prepare a quiet expansion.",
            "text_format": "markdown",
            "anchor": {"kind": "position", "fen": AFTER_N13_FEN},
            "evidence": [{"page": 2}],
            "confidence": 0.9,
        },
        {
            "id": "a3",
            "text": "A short note without a reliable board anchor.",
            "anchor": None,
            "evidence": [{"page": 1}],
        },
    ]


def _sequence_payload(nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    nodes = nodes if nodes is not None else _tree()
    reading_flow: list[dict[str, Any]] = [
        {"kind": "move", "node_id": f"n{index}"} for index in range(1, 17)
    ]
    reading_flow.insert(11, {"kind": "annotation", "annotation_id": "a1"})
    reading_flow.insert(15, {"kind": "annotation", "annotation_id": "a2"})
    reading_flow.append({"kind": "annotation", "annotation_id": "a3"})
    return {
        "kind": "move_sequence",
        "id": "seq1",
        "title": "Synthetic annotated opening",
        "evidence": [{"page": 1}],
        "initial_position": {"kind": "startpos"},
        "nodes": nodes,
        "annotations": _annotations(),
        "reading_flow": reading_flow,
    }


def _tree() -> list[dict[str, Any]]:
    """Invented legal tree: mainline, earlier-parent alternative, nested
    alternative and a later primary Black move whose parent stays n11."""
    return [
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


def _package_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "chess-content-extraction/1.1",
        "package_id": "6f0c6c8a-4f3d-4b2a-9c1e-5d8f7a2b3c4d",
        "source": {
            "source_ref": "opaque-synthetic-1",
            "media_type": "application/pdf",
            "page_range": {"start_page": 1, "end_page": 2},
        },
        "items": items,
        "provenance": {
            "created_at": "2026-08-14T10:00:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "1.1",
        },
    }


def _normalize(nodes: list[dict[str, Any]]) -> tuple[ExtractionPackageV1_1, MoveSequenceItemV1_1]:
    package = ExtractionPackageV1_1.model_validate(_package_payload([_sequence_payload(nodes)]))
    out = normalize_chess_moves_v1_1(package)
    sequence = next(item for item in out.items if isinstance(item, MoveSequenceItemV1_1))
    return out, sequence


def _node_map(sequence: MoveSequenceItemV1_1) -> dict[str, Any]:
    return {node.id: node for node in sequence.nodes}


def _without_normalization(seq_json: dict[str, Any]) -> dict[str, Any]:
    """Deep copy minus move-normalization fields and validator warnings."""
    cleaned = copy.deepcopy(seq_json)
    for node in cleaned["nodes"]:
        for key in (
            "san_candidate",
            "uci_candidate",
            "fen_before",
            "fen_after",
            "validation_status",
        ):
            node.pop(key, None)
        node["warnings"] = [
            warning
            for warning in node.get("warnings", [])
            if warning["code"] not in VALIDATOR_CODES
        ]
    return cleaned


# ---------------------------------------------------------------------------
# 1. Topology-driven normalization on the annotated tree
# ---------------------------------------------------------------------------


def test_v1_1_tree_normalizes_by_topology_not_flow_adjacency() -> None:
    out, sequence = _normalize(_tree())
    nodes = _node_map(sequence)

    n1 = nodes["n1"]
    assert n1.validation_status == "valid"
    assert n1.san_candidate == "e4"
    assert n1.uci_candidate == "e2e4"
    assert n1.fen_before == START_FEN
    assert n1.fen_after == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"

    n11 = nodes["n11"]
    assert n11.validation_status == "valid"
    assert n11.uci_candidate == "c1e3"
    assert n11.fen_after == AFTER_N11_FEN

    # Earlier-parent alternative: n12's board comes from n10, even though in
    # reading flow n12 follows the mainline n11 and an annotation.
    n12 = nodes["n12"]
    assert n12.validation_status == "valid"
    assert n12.san_candidate == "a3"
    assert n12.uci_candidate == "a2a3"
    assert n12.fen_before == AFTER_N10_FEN
    assert n12.fen_after == AFTER_N12_FEN

    n13 = nodes["n13"]
    assert n13.validation_status == "valid"
    assert n13.uci_candidate == "d7d6"
    assert n13.fen_after == AFTER_N13_FEN

    # Sibling alternatives share the same parent board.
    n14 = nodes["n14"]
    n15 = nodes["n15"]
    assert n14.validation_status == "valid"
    assert n14.uci_candidate == "a3a4"
    assert n14.fen_before == AFTER_N13_FEN
    assert n14.fen_after == AFTER_N14_FEN
    assert n15.validation_status == "valid"
    assert n15.uci_candidate == "b2b3"
    assert n15.fen_before == AFTER_N13_FEN
    assert n15.fen_after == AFTER_N15_FEN

    # Later primary Black sixth move: parent stays n11 (topology), not the
    # last flow entry (annotation a2 / node n15).
    n16 = nodes["n16"]
    assert n16.validation_status == "valid"
    assert n16.san_candidate == "Be7"
    assert n16.uci_candidate == "b4e7"
    assert n16.fen_before == AFTER_N11_FEN
    assert n16.fen_after == AFTER_N16_FEN
    assert out is not None


# ---------------------------------------------------------------------------
# 2. Annotations, flow and non-normalization fields preserved exactly
# ---------------------------------------------------------------------------


def test_annotations_reading_flow_and_non_normalization_fields_are_preserved() -> None:
    package = ExtractionPackageV1_1.model_validate(_package_payload([_sequence_payload()]))
    before = package.model_dump(mode="json")
    out = normalize_chess_moves_v1_1(package)
    after = out.model_dump(mode="json")

    assert after["items"][0]["annotations"] == before["items"][0]["annotations"]
    assert after["items"][0]["reading_flow"] == before["items"][0]["reading_flow"]
    assert _without_normalization(after["items"][0]) == _without_normalization(before["items"][0])


def test_input_unchanged_and_output_nested_objects_are_independent() -> None:
    package = ExtractionPackageV1_1.model_validate(_package_payload([_sequence_payload()]))
    snapshot = package.model_dump(mode="json")
    out = normalize_chess_moves_v1_1(package)
    assert package.model_dump(mode="json") == snapshot
    assert out is not package

    # Mutating the output annotation must not affect the input.
    sequence = next(item for item in out.items if isinstance(item, MoveSequenceItemV1_1))
    sequence.annotations[0].text = "mutated"
    assert package.model_dump(mode="json") == snapshot


def test_non_move_items_are_unchanged() -> None:
    heading = {
        "kind": "heading",
        "id": "h1",
        "level": 1,
        "text": "Synthetic chapter",
        "evidence": [{"page": 1}],
    }
    prose = {
        "kind": "prose",
        "id": "p1",
        "text": "A narrative paragraph outside the score.",
        "evidence": [{"page": 1}],
    }
    package = ExtractionPackageV1_1.model_validate(
        _package_payload([heading, _sequence_payload(), prose])
    )
    before = package.model_dump(mode="json")
    out = normalize_chess_moves_v1_1(package)
    after = out.model_dump(mode="json")
    assert after["items"][0] == before["items"][0]
    assert after["items"][2] == before["items"][2]


# ---------------------------------------------------------------------------
# 3. Illegal, context-mismatched and disconnected nodes
# ---------------------------------------------------------------------------


def test_illegal_and_disconnected_nodes_keep_warnings_and_flow() -> None:
    nodes = _tree()
    # n12 becomes illegal (queenside castling is blocked by the c1 bishop on
    # this branch) -> its children cannot resolve.
    nodes[11]["move_text"] = "O-O-O"
    out, sequence = _normalize(nodes)
    node_map = _node_map(sequence)

    n12 = node_map["n12"]
    assert n12.validation_status == "invalid"
    assert n12.uci_candidate is None
    assert [w.code for w in n12.warnings] == ["ccef_chess_invalid_move"]

    n13 = node_map["n13"]
    assert n13.validation_status == "invalid"
    assert [w.code for w in n13.warnings] == ["ccef_chess_unresolved_parent"]

    # The annotation anchored to n11 and the flow entries survive.
    anchor = sequence.annotations[0].anchor
    assert isinstance(anchor, MoveNodeAnnotationAnchor)
    assert anchor.node_id == "n11"
    assert len(sequence.reading_flow) == 19


def test_context_mismatch_keeps_warning_and_flow_present() -> None:
    nodes = _tree()
    nodes[0]["move_number"] = 7  # e4 cannot be move 7 from startpos
    out, sequence = _normalize(nodes)
    node_map = _node_map(sequence)
    assert node_map["n1"].validation_status == "invalid"
    assert [w.code for w in node_map["n1"].warnings] == ["ccef_chess_context_mismatch"]
    assert sequence.annotations[0].anchor is not None
    assert len(sequence.reading_flow) == 19


# ---------------------------------------------------------------------------
# 4. Idempotency and invalid initial FENs
# ---------------------------------------------------------------------------


def test_repeated_normalization_is_identical_without_duplicate_warnings() -> None:
    nodes = _tree()
    nodes[11]["move_text"] = "O-O-O"  # a warning-producing node
    package = ExtractionPackageV1_1.model_validate(_package_payload([_sequence_payload(nodes)]))
    once = normalize_chess_moves_v1_1(package)
    twice = normalize_chess_moves_v1_1(once)
    assert once.model_dump(mode="json") == twice.model_dump(mode="json")
    sequence = next(item for item in twice.items if isinstance(item, MoveSequenceItemV1_1))
    for node in sequence.nodes:
        validator_warnings = [
            warning for warning in node.warnings if warning.code in VALIDATOR_CODES
        ]
        assert len(validator_warnings) <= 1


def test_invalid_initial_fen_remains_reviewable() -> None:
    nodes = _tree()
    sequence_payload = _sequence_payload(nodes)
    sequence_payload["initial_position"] = {"kind": "fen", "fen": "8/8/8/8/8/8/8/8 w - - 0 1"}
    package = ExtractionPackageV1_1.model_validate(_package_payload([sequence_payload]))
    out = normalize_chess_moves_v1_1(package)
    sequence = next(item for item in out.items if isinstance(item, MoveSequenceItemV1_1))
    n1 = sequence.nodes[0]
    assert n1.validation_status == "invalid"
    assert [w.code for w in n1.warnings] == ["ccef_chess_invalid_initial_position"]
    assert n1.san_candidate is None
    assert len(sequence.reading_flow) == 19


# ---------------------------------------------------------------------------
# 5. Import purity
# ---------------------------------------------------------------------------


def test_import_boundary_is_pure() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imports: set[str] = set()
    relative_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
            if node.level:
                relative_imports.add(node.module or "")
    assert not any(
        forbidden in name
        for name in imports
        for forbidden in (
            "httpx",
            "sqlalchemy",
            "sanic",
            "chess_workbench.config",
            "chess_workbench.services",
            "chess_workbench.store",
            "chess_workbench.api",
            "chess_workbench.schemas",
            "deepseek",
            "provider",
            "prompting",
            "decoder",
        )
    )
    assert relative_imports == {"contracts"}
