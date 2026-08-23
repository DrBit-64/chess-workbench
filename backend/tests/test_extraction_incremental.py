"""Focused oracles for DS-STAGE8-INCREMENTAL-CONTEXT-01 (8D-3E1).

Pure internal continuation-context value model and deterministic anchor
projection for incremental PDF extraction (ADR 0018).  All content is
invented synthetic chess; no provider, no real book, no network, no SQL.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from chess_workbench.extraction.contracts import (
    ExtractionPackage,
    ExtractionPackageV1_1,
    PageRange,
)
from chess_workbench.extraction.incremental import (
    CCEF_CONTINUATION_CONTEXT_VERSION,
    CcefContinuationContext,
    ContinuationAnchor,
    ContinuationMove,
    ContinuationSequence,
    build_ccef_continuation_context,
)
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1

REPO_ROOT = Path(__file__).resolve().parents[2]

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FEN_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
FEN_AFTER_E5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
AFTER_N11_FEN = "r1bqk2r/pppp1ppp/2n2n2/8/1b1NP3/2N1B3/PPP2PPP/R2QKB1R b KQkq - 4 6"
AFTER_N12_FEN = "r1bqk2r/pppp1ppp/2n2n2/8/1b1NP3/P1N5/1PP2PPP/R1BQKB1R b KQkq - 0 6"
AFTER_N16_FEN = "r1bqk2r/ppppbppp/2n2n2/8/3NP3/2N1B3/PPP2PPP/R2QKB1R w KQkq - 5 7"
RUY_N12_FEN = "r1bqk2r/2ppbppp/p1n2n2/1p2p3/B3P3/5N2/PPPP1PPP/RNBQR1K1 w kq b6 0 7"
TRANS_FEN = "rnbqkbnr/ppp2ppp/4p3/3p4/2PP4/5N2/PP2PPPP/RNBQKB1R b KQkq - 1 3"

PACKAGE_ID = "6f0c6c8a-4f3d-4b2a-9c1e-5d8f7a2b3c4d"
SOURCE_REF = "opaque-synthetic-1"
SHA_64 = "a" * 64


def _node(
    node_id: str, parent_id: str | None, sibling_order: int, move_text: str
) -> dict[str, object]:
    return {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": sibling_order,
        "move_text": move_text,
        "evidence": [{"page": 1}],
    }


def _sequence(
    nodes: list[dict[str, object]],
    *,
    sequence_id: str = "seq1",
    title: str | None = "Synthetic annotated opening",
    annotations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    annotations = [] if annotations is None else annotations
    reading_flow: list[dict[str, object]] = [
        {"kind": "move", "node_id": node["id"]} for node in nodes
    ]
    reading_flow.extend(
        {"kind": "annotation", "annotation_id": annotation["id"]} for annotation in annotations
    )
    return {
        "kind": "move_sequence",
        "id": sequence_id,
        "title": title,
        "evidence": [{"page": 1}],
        "initial_position": {"kind": "startpos"},
        "nodes": nodes,
        "annotations": annotations,
        "reading_flow": reading_flow,
    }


_UNSET = object()


def _package(
    items: list[dict[str, object]],
    *,
    page_range: dict[str, int] | None | object = _UNSET,
    package_id: str = PACKAGE_ID,
) -> dict[str, object]:
    if page_range is _UNSET:
        page_range = {"start_page": 1, "end_page": 2}
    source: dict[str, object] = {
        "source_ref": SOURCE_REF,
        "media_type": "application/pdf",
    }
    if page_range is not None:
        source["page_range"] = page_range
    return {
        "schema_version": "chess-content-extraction/1.1",
        "package_id": package_id,
        "source": source,
        "items": items,
        "provenance": {
            "created_at": "2026-08-14T10:00:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "1.1",
        },
    }


def _normalize(
    items: list[dict[str, object]],
    *,
    page_range: dict[str, int] | None | object = _UNSET,
    package_id: str = PACKAGE_ID,
) -> ExtractionPackageV1_1:
    package = ExtractionPackageV1_1.model_validate(
        _package(items, page_range=page_range, package_id=package_id)
    )
    return normalize_chess_moves_v1_1(package)


def _mainline_tree() -> list[dict[str, object]]:
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


def _ruy_line() -> list[dict[str, object]]:
    moves = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Re1", "b5"]
    return [
        _node(f"n{index}", None if index == 1 else f"n{index - 1}", 0, move)
        for index, move in enumerate(moves, start=1)
    ]


def _transposition_tree() -> list[dict[str, object]]:
    return [
        _node("n1", None, 0, "d4"),
        _node("n2", "n1", 0, "d5"),
        _node("n3", "n2", 0, "c4"),
        _node("n4", "n3", 0, "e6"),
        _node("n5", None, 1, "c4"),
        _node("n6", "n5", 0, "e6"),
        _node("n7", "n6", 0, "d4"),
        _node("n8", "n7", 0, "d5"),
        _node("n9", "n8", 0, "Nf3"),
        _node("n10", "n4", 0, "Nf3"),
    ]


def _mixed_tree() -> list[dict[str, object]]:
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
        _node("n10", "n9", 0, "d6"),
        _node("n11", "n10", 0, "Ne2"),
        _node("n12", "n10", 1, "Qh3"),
        _node("n13", "n11", 0, "Be7"),
        _node("n14", "n12", 0, "O-O"),
        _node("n15", "n10", 2, "Be2"),
        _node("n16", "n15", 0, "Be7"),
    ]


def _canonical_sha(package: ExtractionPackageV1_1) -> str:
    """Independently recompute the frozen canonical SHA-256 of a normalized package."""
    return hashlib.sha256(
        json.dumps(
            package.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    ).hexdigest()


def _build(
    items: list[dict[str, object]],
    *,
    next_page_range: PageRange | None = None,
    sha: str | None = None,
    page_range: dict[str, int] | None | object = _UNSET,
    package_id: str = PACKAGE_ID,
) -> tuple[ExtractionPackageV1_1, CcefContinuationContext]:
    package = _normalize(items, page_range=page_range, package_id=package_id)
    if next_page_range is None:
        next_page_range = PageRange(start_page=3, end_page=4)
    if sha is None:
        sha = _canonical_sha(package)
    return package, build_ccef_continuation_context(
        package,
        base_normalized_ccef_sha256=sha,
        next_page_range=next_page_range,
    )


def _moves(anchor: ContinuationAnchor) -> list[tuple[str, str, str]]:
    return [(move.node_id, move.san, move.uci) for move in anchor.path_tail]


def _move(node_id: str = "n1", san: str = "e4", uci: str = "e2e4") -> ContinuationMove:
    return ContinuationMove(node_id=node_id, san=san, uci=uci)


def _root_anchor(
    anchor_id: str = "anchor-1",
    sequence_id: str = "seq1",
    fen: str = START_FEN,
) -> ContinuationAnchor:
    return ContinuationAnchor(
        id=anchor_id,
        sequence_id=sequence_id,
        after_node_id=None,
        position_fen=fen,
        path_tail=[],
    )


def _node_anchor(
    anchor_id: str,
    after_node_id: str,
    sequence_id: str = "seq1",
    fen: str = FEN_AFTER_E4,
) -> ContinuationAnchor:
    return ContinuationAnchor(
        id=anchor_id,
        sequence_id=sequence_id,
        after_node_id=after_node_id,
        position_fen=fen,
        path_tail=[_move(node_id=after_node_id)],
    )


# ---------------------------------------------------------------------------
# Main projection
# ---------------------------------------------------------------------------


def test_version_constant_is_the_frozen_literal() -> None:
    assert CCEF_CONTINUATION_CONTEXT_VERSION == "chess-workbench/ccef-continuation-context/1.0"
    annotation = str(CcefContinuationContext.model_fields["schema_version"].annotation)
    assert "chess-workbench/ccef-continuation-context/1.0" in annotation


def test_mainline_projection_emits_exact_anchors_in_order() -> None:
    package, context = _build([_sequence(_mainline_tree())])
    assert context.base_package_id == UUID(PACKAGE_ID)
    assert context.base_normalized_ccef_sha256 == _canonical_sha(package)
    assert context.source_ref == SOURCE_REF
    assert (context.base_page_range.start_page, context.base_page_range.end_page) == (1, 2)
    assert (context.next_page_range.start_page, context.next_page_range.end_page) == (3, 4)

    assert len(context.sequences) == 1
    sequence = context.sequences[0]
    assert sequence.sequence_id == "seq1"
    assert sequence.title == "Synthetic annotated opening"
    assert [anchor.id for anchor in sequence.anchors] == [
        f"anchor-{index}" for index in range(1, 18)
    ]
    assert [anchor.after_node_id for anchor in sequence.anchors] == [
        None,
        "n1",
        "n2",
        "n3",
        "n4",
        "n5",
        "n6",
        "n7",
        "n8",
        "n9",
        "n10",
        "n11",
        "n12",
        "n13",
        "n14",
        "n15",
        "n16",
    ]

    root = sequence.anchors[0]
    assert root.after_node_id is None
    assert root.position_fen == START_FEN
    assert root.path_tail == []

    by_id = {anchor.after_node_id: anchor for anchor in sequence.anchors[1:]}
    assert by_id["n1"].position_fen == FEN_AFTER_E4
    assert _moves(by_id["n1"]) == [("n1", "e4", "e2e4")]
    assert by_id["n2"].position_fen == FEN_AFTER_E5
    assert _moves(by_id["n2"]) == [("n1", "e4", "e2e4"), ("n2", "e5", "e7e5")]
    assert by_id["n11"].position_fen == AFTER_N11_FEN
    assert _moves(by_id["n11"]) == [
        ("n4", "Nc6", "b8c6"),
        ("n5", "d4", "d2d4"),
        ("n6", "exd4", "e5d4"),
        ("n7", "Nxd4", "f3d4"),
        ("n8", "Nf6", "g8f6"),
        ("n9", "Nc3", "b1c3"),
        ("n10", "Bb4", "f8b4"),
        ("n11", "Be3", "c1e3"),
    ]
    assert by_id["n12"].position_fen == AFTER_N12_FEN
    assert _moves(by_id["n12"]) == [
        ("n4", "Nc6", "b8c6"),
        ("n5", "d4", "d2d4"),
        ("n6", "exd4", "e5d4"),
        ("n7", "Nxd4", "f3d4"),
        ("n8", "Nf6", "g8f6"),
        ("n9", "Nc3", "b1c3"),
        ("n10", "Bb4", "f8b4"),
        ("n12", "a3", "a2a3"),
    ]
    assert by_id["n16"].position_fen == AFTER_N16_FEN
    assert _moves(by_id["n16"]) == [
        ("n5", "d4", "d2d4"),
        ("n6", "exd4", "e5d4"),
        ("n7", "Nxd4", "f3d4"),
        ("n8", "Nf6", "g8f6"),
        ("n9", "Nc3", "b1c3"),
        ("n10", "Bb4", "f8b4"),
        ("n11", "Be3", "c1e3"),
        ("n16", "Be7", "b4e7"),
    ]

    # The context mirrors the normalized package exactly for every anchor.
    normalized_sequence = next(item for item in package.items if item.kind == "move_sequence")
    nodes = {node.id: node for node in normalized_sequence.nodes}
    for anchor in sequence.anchors[1:]:
        assert anchor.after_node_id is not None
        node = nodes[anchor.after_node_id]
        assert anchor.position_fen == node.fen_after
        assert anchor.path_tail[-1].node_id == node.id
        assert anchor.path_tail[-1].san == node.san_candidate
        assert anchor.path_tail[-1].uci == node.uci_candidate


def test_long_line_tail_is_capped_at_final_eight() -> None:
    _, context = _build([_sequence(_ruy_line(), title="Synthetic Ruy line")])
    sequence = context.sequences[0]
    by_id = {anchor.after_node_id: anchor for anchor in sequence.anchors[1:]}
    assert _moves(by_id["n7"]) == [
        ("n1", "e4", "e2e4"),
        ("n2", "e5", "e7e5"),
        ("n3", "Nf3", "g1f3"),
        ("n4", "Nc6", "b8c6"),
        ("n5", "Bb5", "f1b5"),
        ("n6", "a6", "a7a6"),
        ("n7", "Ba4", "b5a4"),
    ]
    assert _moves(by_id["n8"]) == [
        ("n1", "e4", "e2e4"),
        ("n2", "e5", "e7e5"),
        ("n3", "Nf3", "g1f3"),
        ("n4", "Nc6", "b8c6"),
        ("n5", "Bb5", "f1b5"),
        ("n6", "a6", "a7a6"),
        ("n7", "Ba4", "b5a4"),
        ("n8", "Nf6", "g8f6"),
    ]
    # ply 12: the tail keeps exactly the final eight moves, root-to-leaf.
    assert _moves(by_id["n12"]) == [
        ("n5", "Bb5", "f1b5"),
        ("n6", "a6", "a7a6"),
        ("n7", "Ba4", "b5a4"),
        ("n8", "Nf6", "g8f6"),
        ("n9", "O-O", "e1g1"),
        ("n10", "Be7", "f8e7"),
        ("n11", "Re1", "f1e1"),
        ("n12", "b5", "b7b5"),
    ]
    assert by_id["n12"].position_fen == RUY_N12_FEN


def test_transposed_equal_fens_remain_distinct_anchors() -> None:
    _, context = _build([_sequence(_transposition_tree(), title="Synthetic transposition")])
    sequence = context.sequences[0]
    anchors = sequence.anchors[1:]
    matches = [anchor for anchor in anchors if anchor.position_fen == TRANS_FEN]
    assert len(matches) == 2
    first, second = matches
    assert first.after_node_id in ("n9", "n10")
    assert second.after_node_id in ("n9", "n10")
    assert first.after_node_id != second.after_node_id
    assert first.id != second.id
    assert first.position_fen == second.position_fen == TRANS_FEN
    assert _moves(first) != _moves(second)
    # Same plies in a different order (node ids differ by design).
    assert {(move.san, move.uci) for move in first.path_tail} == {
        (move.san, move.uci) for move in second.path_tail
    }
    assert {move.node_id for move in first.path_tail} != {move.node_id for move in second.path_tail}


def test_invalid_ambiguous_and_descendant_nodes_are_excluded() -> None:
    _, context = _build([_sequence(_mixed_tree(), title="Synthetic mixed tree")])
    sequence = context.sequences[0]
    assert [anchor.after_node_id for anchor in sequence.anchors] == [
        None,
        "n1",
        "n2",
        "n3",
        "n4",
        "n5",
        "n6",
        "n7",
        "n8",
        "n9",
        "n10",
        "n15",
        "n16",
    ]
    assert [anchor.id for anchor in sequence.anchors] == [
        f"anchor-{index}" for index in range(1, 14)
    ]
    for excluded in ("n11", "n12", "n13", "n14"):
        assert all(anchor.after_node_id != excluded for anchor in sequence.anchors)
        assert all(
            move.node_id != excluded for anchor in sequence.anchors for move in anchor.path_tail
        )


def test_sequence_without_valid_root_is_skipped() -> None:
    bad = [
        _node("m1", None, 0, "Qh3"),
        _node("m2", "m1", 0, "e4"),
    ]
    items = [_sequence(_mainline_tree()), _sequence(bad, sequence_id="seq2", title="Bad line")]
    _, context = _build(items)
    assert [sequence.sequence_id for sequence in context.sequences] == ["seq1"]
    # Global anchor ids stay contiguous across the skipped sequence.
    assert context.sequences[0].anchors[-1].id == "anchor-17"


# ---------------------------------------------------------------------------
# Rejection of raw/tampered baselines
# ---------------------------------------------------------------------------


def test_raw_unvalidated_package_is_rejected_not_repaired() -> None:
    raw = ExtractionPackageV1_1.model_validate(_package([_sequence(_mainline_tree())]))
    with pytest.raises(ValueError, match="base package must be locally normalized"):
        build_ccef_continuation_context(
            raw,
            base_normalized_ccef_sha256=SHA_64,
            next_page_range=PageRange(start_page=3, end_page=4),
        )


def test_tampered_normalization_fields_are_rejected_not_repaired() -> None:
    package = _normalize([_sequence(_mainline_tree())])
    tampered_json = json.loads(package.model_dump_json())
    node = tampered_json["items"][0]["nodes"][2]
    assert node["san_candidate"] == "Nf3"
    node["san_candidate"] = "Nc3"  # keep the model structurally valid
    tampered = ExtractionPackageV1_1.model_validate(tampered_json)
    with pytest.raises(ValueError, match="base package must be locally normalized"):
        build_ccef_continuation_context(
            tampered,
            base_normalized_ccef_sha256=SHA_64,
            next_page_range=PageRange(start_page=3, end_page=4),
        )


# ---------------------------------------------------------------------------
# Range / type / SHA boundaries
# ---------------------------------------------------------------------------


def test_null_baseline_page_range_is_rejected() -> None:
    package = _normalize([_sequence(_mainline_tree())], page_range=None)
    with pytest.raises(ValueError, match="base package must declare a source page range"):
        build_ccef_continuation_context(
            package,
            base_normalized_ccef_sha256=SHA_64,
            next_page_range=PageRange(start_page=3, end_page=4),
        )


def test_next_range_must_be_adjacent_and_bounded() -> None:
    items = [_sequence(_mainline_tree())]
    with pytest.raises(ValueError, match="next page range overlaps the base page range"):
        _build(items, next_page_range=PageRange(start_page=2, end_page=3))
    with pytest.raises(ValueError, match="next page range is not adjacent to the base page range"):
        _build(items, next_page_range=PageRange(start_page=5, end_page=6))
    with pytest.raises(ValueError, match="next page range exceeds the maximum page number"):
        _build(items, next_page_range=PageRange(start_page=3, end_page=20_001))


def test_exact_type_misuse_is_rejected() -> None:
    package = _normalize([_sequence(_mainline_tree())])
    v1_package = ExtractionPackage.model_validate(
        {
            "schema_version": "chess-content-extraction/1.0",
            "package_id": PACKAGE_ID,
            "source": {"source_ref": SOURCE_REF, "media_type": "application/pdf"},
            "items": [
                {
                    "kind": "heading",
                    "id": "h1",
                    "level": 1,
                    "text": "One heading",
                    "evidence": [{"page": 1}],
                }
            ],
            "provenance": {
                "created_at": "2026-08-14T10:00:00Z",
                "adapter_name": "test-adapter",
                "adapter_version": "1.0",
            },
        }
    )
    with pytest.raises(TypeError, match="package must be ExtractionPackageV1_1"):
        build_ccef_continuation_context(
            cast(Any, v1_package),
            base_normalized_ccef_sha256=SHA_64,
            next_page_range=PageRange(start_page=3, end_page=4),
        )
    with pytest.raises(TypeError, match="next_page_range must be PageRange"):
        build_ccef_continuation_context(
            package,
            base_normalized_ccef_sha256=SHA_64,
            next_page_range=cast(Any, {"start_page": 3, "end_page": 4}),
        )


def test_malformed_sha_is_rejected_without_leaking_package_content() -> None:
    package = _normalize([_sequence(_mainline_tree())])
    with pytest.raises(ValidationError) as excinfo:
        build_ccef_continuation_context(
            package,
            base_normalized_ccef_sha256="not-a-sha",
            next_page_range=PageRange(start_page=3, end_page=4),
        )
    message = str(excinfo.value)
    assert "Synthetic annotated opening" not in message
    assert "e4" not in message
    assert "opaque-synthetic-1" not in message


# ---------------------------------------------------------------------------
# R1: canonical SHA binding and model-level range relations
# ---------------------------------------------------------------------------


def test_wrong_but_well_formed_sha_is_rejected_without_leak() -> None:
    package = _normalize([_sequence(_mainline_tree())])
    real = _canonical_sha(package)
    fake = "b" * 64
    assert fake != real
    with pytest.raises(
        ValueError, match="base normalized CCEF SHA-256 does not match package"
    ) as excinfo:
        build_ccef_continuation_context(
            package,
            base_normalized_ccef_sha256=fake,
            next_page_range=PageRange(start_page=3, end_page=4),
        )
    message = str(excinfo.value)
    assert "Synthetic annotated opening" not in message
    assert "e4" not in message
    assert "opaque-synthetic-1" not in message
    assert fake not in message
    assert real not in message


def test_unicode_package_canonical_hash_is_accepted() -> None:
    heading: dict[str, object] = {
        "kind": "heading",
        "id": "h1",
        "level": 1,
        "text": "序章：续接上下文（中文正文）",
        "evidence": [{"page": 1}],
    }
    items: list[dict[str, object]] = [
        heading,
        _sequence(_mainline_tree(), title="合成开局：续接示例"),
    ]
    package, context = _build(items)
    computed = hashlib.sha256(
        json.dumps(
            package.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    ).hexdigest()
    assert computed == _canonical_sha(package)
    assert context.base_normalized_ccef_sha256 == computed
    # The bytes are raw UTF-8 with a single trailing newline (not ASCII-escaped).
    raw = (
        json.dumps(
            package.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    assert raw.endswith(b"\n")
    assert "序章".encode() in raw
    assert "合成开局".encode() in raw


def test_direct_context_construction_rejects_overlap_gap_and_over_max() -> None:
    def _context(next_start: int, next_end: int) -> CcefContinuationContext:
        return CcefContinuationContext(
            schema_version=CCEF_CONTINUATION_CONTEXT_VERSION,
            base_package_id=UUID(PACKAGE_ID),
            base_normalized_ccef_sha256=SHA_64,
            source_ref=SOURCE_REF,
            base_page_range=PageRange(start_page=1, end_page=2),
            next_page_range=PageRange(start_page=next_start, end_page=next_end),
            sequences=[
                ContinuationSequence(
                    sequence_id="seq1",
                    title=None,
                    anchors=[_root_anchor("anchor-1"), _node_anchor("anchor-2", "n1")],
                )
            ],
        )

    with pytest.raises(ValueError, match="next page range overlaps the base page range"):
        _context(2, 3)
    with pytest.raises(ValueError, match="next page range is not adjacent to the base page range"):
        _context(4, 5)
    with pytest.raises(ValueError, match="next page range exceeds the maximum page number"):
        _context(3, 20_001)


# ---------------------------------------------------------------------------
# Relation validation (item 8)
# ---------------------------------------------------------------------------


def test_sequence_and_context_relations_are_rejected() -> None:
    def _valid_pair() -> list[ContinuationAnchor]:
        return [
            _root_anchor("anchor-1"),
            _node_anchor("anchor-2", "n1"),
        ]

    # duplicate sequence ids
    with pytest.raises(ValueError, match="duplicate sequence id"):
        CcefContinuationContext(
            schema_version=CCEF_CONTINUATION_CONTEXT_VERSION,
            base_package_id=UUID(PACKAGE_ID),
            base_normalized_ccef_sha256=SHA_64,
            source_ref=SOURCE_REF,
            base_page_range=PageRange(start_page=1, end_page=2),
            next_page_range=PageRange(start_page=3, end_page=4),
            sequences=[
                ContinuationSequence(sequence_id="seq1", title=None, anchors=_valid_pair()),
                ContinuationSequence(
                    sequence_id="seq1", title=None, anchors=[_root_anchor("anchor-3")]
                ),
            ],
        )
    # globally non-contiguous anchor ids
    with pytest.raises(ValueError, match="anchor ids must be globally contiguous and unique"):
        CcefContinuationContext(
            schema_version=CCEF_CONTINUATION_CONTEXT_VERSION,
            base_package_id=UUID(PACKAGE_ID),
            base_normalized_ccef_sha256=SHA_64,
            source_ref=SOURCE_REF,
            base_page_range=PageRange(start_page=1, end_page=2),
            next_page_range=PageRange(start_page=3, end_page=4),
            sequences=[
                ContinuationSequence(
                    sequence_id="seq1",
                    title=None,
                    anchors=[
                        _root_anchor("anchor-1"),
                        _node_anchor("anchor-3", "n1"),
                    ],
                )
            ],
        )
    # duplicate anchor ids
    with pytest.raises(ValueError, match="anchor ids must be globally contiguous and unique"):
        CcefContinuationContext(
            schema_version=CCEF_CONTINUATION_CONTEXT_VERSION,
            base_package_id=UUID(PACKAGE_ID),
            base_normalized_ccef_sha256=SHA_64,
            source_ref=SOURCE_REF,
            base_page_range=PageRange(start_page=1, end_page=2),
            next_page_range=PageRange(start_page=3, end_page=4),
            sequences=[
                ContinuationSequence(
                    sequence_id="seq1",
                    title=None,
                    anchors=[
                        _root_anchor("anchor-1"),
                        _node_anchor("anchor-1", "n1"),
                    ],
                )
            ],
        )
    # anchor/container sequence mismatch
    with pytest.raises(ValueError, match="anchor sequence mismatch"):
        CcefContinuationContext(
            schema_version=CCEF_CONTINUATION_CONTEXT_VERSION,
            base_package_id=UUID(PACKAGE_ID),
            base_normalized_ccef_sha256=SHA_64,
            source_ref=SOURCE_REF,
            base_page_range=PageRange(start_page=1, end_page=2),
            next_page_range=PageRange(start_page=3, end_page=4),
            sequences=[
                ContinuationSequence(
                    sequence_id="seq1",
                    title=None,
                    anchors=[
                        _root_anchor("anchor-1", sequence_id="seq2"),
                        _node_anchor("anchor-2", "n1"),
                    ],
                )
            ],
        )
    # first anchor must be the root anchor
    with pytest.raises(ValueError, match="sequence root anchor must come first"):
        ContinuationSequence(
            sequence_id="seq1",
            title=None,
            anchors=[_node_anchor("anchor-1", "n1")],
        )
    # exactly one root anchor per sequence
    with pytest.raises(ValueError, match="sequence must have exactly one root anchor"):
        ContinuationSequence(
            sequence_id="seq1",
            title=None,
            anchors=[
                _root_anchor("anchor-1"),
                _node_anchor("anchor-2", "n1"),
                _root_anchor("anchor-3"),
            ],
        )
    # duplicate after_node_id within one sequence
    with pytest.raises(ValueError, match="duplicate after_node_id within a sequence"):
        ContinuationSequence(
            sequence_id="seq1",
            title=None,
            anchors=[
                _root_anchor("anchor-1"),
                _node_anchor("anchor-2", "n1"),
                _node_anchor("anchor-3", "n1"),
            ],
        )


def test_anchor_tail_relations_are_rejected() -> None:
    with pytest.raises(ValueError, match="root anchor must have an empty path tail"):
        ContinuationAnchor(
            id="anchor-1",
            sequence_id="seq1",
            after_node_id=None,
            position_fen=START_FEN,
            path_tail=[_move()],
        )
    with pytest.raises(ValueError, match="node anchor path tail must end with the anchor node"):
        ContinuationAnchor(
            id="anchor-2",
            sequence_id="seq1",
            after_node_id="n1",
            position_fen=FEN_AFTER_E4,
            path_tail=[],
        )
    with pytest.raises(ValueError, match="node anchor path tail must end with the anchor node"):
        ContinuationAnchor(
            id="anchor-2",
            sequence_id="seq1",
            after_node_id="n1",
            position_fen=FEN_AFTER_E4,
            path_tail=[_move(node_id="n2", san="e5", uci="e7e5")],
        )


# ---------------------------------------------------------------------------
# Model shape / strict / frozen / round trip
# ---------------------------------------------------------------------------


def test_models_have_exact_fields_and_are_strict_frozen() -> None:
    assert set(ContinuationMove.model_fields) == {"node_id", "san", "uci"}
    assert set(ContinuationAnchor.model_fields) == {
        "id",
        "sequence_id",
        "after_node_id",
        "position_fen",
        "path_tail",
    }
    assert set(ContinuationSequence.model_fields) == {"sequence_id", "title", "anchors"}
    assert set(CcefContinuationContext.model_fields) == {
        "schema_version",
        "base_package_id",
        "base_normalized_ccef_sha256",
        "source_ref",
        "base_page_range",
        "next_page_range",
        "sequences",
    }
    for model in (
        ContinuationMove,
        ContinuationAnchor,
        ContinuationSequence,
        CcefContinuationContext,
    ):
        assert model.model_config.get("extra") == "forbid"
        assert model.model_config.get("strict") is True
        assert model.model_config.get("frozen") is True

    with pytest.raises(ValidationError):
        ContinuationMove(node_id="n1", san="e4", uci="e2e4", extra="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ContinuationMove(node_id=cast(Any, 1), san="e4", uci="e2e4")  # strict rejects int id
    move = ContinuationMove(node_id="n1", san="e4", uci="e2e4")
    with pytest.raises(ValidationError):
        move.san = "e5"  # frozen model rejects attribute mutation


def test_context_json_round_trip_preserves_values() -> None:
    _, context = _build([_sequence(_mainline_tree())])
    restored = CcefContinuationContext.model_validate_json(context.model_dump_json())
    assert restored.model_dump(mode="json") == context.model_dump(mode="json")


def test_build_is_deterministic_and_never_mutates_input() -> None:
    package, first = _build([_sequence(_mainline_tree())])
    snapshot = copy.deepcopy(package.model_dump(mode="json"))
    second = build_ccef_continuation_context(
        package,
        base_normalized_ccef_sha256=_canonical_sha(package),
        next_page_range=PageRange(start_page=3, end_page=4),
    )
    assert second.model_dump_json() == first.model_dump_json()
    assert package.model_dump(mode="json") == snapshot


def test_multi_sequence_order_titles_and_global_anchor_ids() -> None:
    heading: dict[str, object] = {
        "kind": "heading",
        "id": "h1",
        "level": 1,
        "text": "One heading",
        "evidence": [{"page": 1}],
    }
    prose: dict[str, object] = {
        "kind": "prose",
        "id": "p1",
        "text": "Some prose.",
        "text_format": "plain",
        "evidence": [{"page": 1}],
    }
    items: list[dict[str, object]] = [
        heading,
        _sequence(_mainline_tree(), sequence_id="seq1"),
        prose,
        _sequence(_ruy_line(), sequence_id="seq2", title="Synthetic Ruy line"),
    ]
    _, context = _build(items)
    assert [sequence.sequence_id for sequence in context.sequences] == ["seq1", "seq2"]
    assert [sequence.title for sequence in context.sequences] == [
        "Synthetic annotated opening",
        "Synthetic Ruy line",
    ]
    assert context.sequences[0].anchors[0].id == "anchor-1"
    assert context.sequences[0].anchors[-1].id == "anchor-17"
    assert context.sequences[1].anchors[0].id == "anchor-18"
    assert context.sequences[1].anchors[-1].id == "anchor-30"
    assert context.base_package_id == UUID(PACKAGE_ID)
    assert context.source_ref == SOURCE_REF
    assert (context.base_page_range.start_page, context.base_page_range.end_page) == (1, 2)
    assert (context.next_page_range.start_page, context.next_page_range.end_page) == (3, 4)


# ---------------------------------------------------------------------------
# Import purity
# ---------------------------------------------------------------------------


def test_module_imports_without_forbidden_modules() -> None:
    code = (
        "import importlib.util, sys, types\n"
        "from pathlib import Path\n"
        "root = types.ModuleType('chess_workbench')\n"
        "sys.modules['chess_workbench'] = root\n"
        "pkg = types.ModuleType('chess_workbench.extraction')\n"
        "pkg.__path__ = [str(Path('backend/src/chess_workbench/extraction'))]\n"
        "sys.modules['chess_workbench.extraction'] = pkg\n"
        "for name in ('contracts', 'validation', 'incremental'):\n"
        "    spec = importlib.util.spec_from_file_location(\n"
        "        f'chess_workbench.extraction.{name}',\n"
        "        f'backend/src/chess_workbench/extraction/{name}.py')\n"
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    sys.modules[spec.name] = mod\n"
        "    spec.loader.exec_module(mod)\n"
        "forbidden = ('sanic', 'sqlalchemy', 'httpx', 'requests',\n"
        "             'pydantic_settings', 'chess_workbench.store',\n"
        "             'chess_workbench.services', 'chess_workbench.api',\n"
        "             'chess_workbench.schemas', 'chess_workbench.config',\n"
        "             'chess_workbench.domain',\n"
        "             'chess_workbench.extraction.deepseek',\n"
        "             'chess_workbench.extraction.provider',\n"
        "             'chess_workbench.extraction.prompting',\n"
        "             'chess_workbench.extraction.candidates',\n"
        "             'chess_workbench.extraction.consolidation',\n"
        "             'chess_workbench.extraction.evidence')\n"
        "bad = [m for m in forbidden if m in sys.modules]\n"
        "print('bad=', bad)\n"
        "print('has_chess=', 'chess' in sys.modules)\n"
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"forbidden modules imported: {result.stdout}{result.stderr}"
    assert "has_chess= True" in result.stdout  # python-chess is the allowed dependency
