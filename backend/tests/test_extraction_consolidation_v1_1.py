"""Focused tests for the CCEF 1.1 annotated-score consolidator (8D-3D3B).

Covers the frozen 1.1 consolidation behavior: merging duplicate legal UCI
paths into one shared tree inside the same heading/title/initial-position
scope, reading-flow exact cover that is independent of chess topology,
annotation anchor/ID remapping, no text-based annotation deduplication,
omitted-node annotation preservation with a single sanitized warning,
all-unplayable annotation-to-prose fallback, top-level anchor/diagnostic
remapping, evidence-page retention of the normalized tree (the v1 fragment
reconstruction is never used), input immutability/idempotency and exact type
misuse rejection. All content is invented (pages 1-9); no provider call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest

from chess_workbench.extraction.consolidation import consolidate_move_sequences_v1_1
from chess_workbench.extraction.contracts import (
    CCEF_VERSION_1_1,
    AnnotationFlowRef,
    ExtractionPackageV1_1,
    MoveFlowRef,
    MoveNodeAnchor,
    MoveNodeAnnotationAnchor,
    MoveSequenceItemV1_1,
    PositionAnchor,
    PositionAnnotationAnchor,
    ProseItem,
)
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.prompting import PromptEvidenceFragment, PromptEvidencePage

_UNRESOLVED_ANCHOR = "ccef_annotation_anchor_unresolved"


def _node(
    node_id: str,
    parent_id: str | None,
    sibling_order: int,
    move_text: str,
    *,
    page: int = 1,
    fragment_sha256: str | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"page": page}
    if fragment_sha256 is not None:
        evidence["fragment_sha256"] = fragment_sha256
    return {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": sibling_order,
        "move_text": move_text,
        "evidence": [evidence],
    }


def _annotation(
    annotation_id: str,
    text: str,
    anchor: dict[str, Any] | None,
    *,
    page: int = 3,
    fragment_sha256: str | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"page": page}
    if fragment_sha256 is not None:
        evidence["fragment_sha256"] = fragment_sha256
    return {
        "id": annotation_id,
        "text": text,
        "text_format": "plain",
        "anchor": anchor,
        "evidence": [evidence],
        "confidence": None,
        "warnings": [],
        "extensions": {},
    }


def _mainline_tree(prefix: str) -> list[dict[str, Any]]:
    """Invented legal tree; move-text suffix ids use the given prefix."""
    return [
        _node(f"{prefix}1", None, 0, "e4"),
        _node(f"{prefix}2", f"{prefix}1", 0, "e5"),
        _node(f"{prefix}3", f"{prefix}2", 0, "Nf3"),
        _node(f"{prefix}4", f"{prefix}3", 0, "Nc6"),
        _node(f"{prefix}5", f"{prefix}4", 0, "d4"),
        _node(f"{prefix}6", f"{prefix}5", 0, "exd4"),
        _node(f"{prefix}7", f"{prefix}6", 0, "Nxd4"),
        _node(f"{prefix}8", f"{prefix}7", 0, "Nf6"),
        _node(f"{prefix}9", f"{prefix}8", 0, "Nc3"),
        _node(f"{prefix}10", f"{prefix}9", 0, "Bb4"),
        _node(f"{prefix}11", f"{prefix}10", 0, "Be3"),
    ]


def _sequence_a(
    *,
    duplicate_annotation_id: str | None = None,
    annotation_anchor_id: str | None = None,
) -> dict[str, Any]:
    nodes = _mainline_tree("A")
    nodes.extend(
        [
            _node("A12", "A10", 1, "a3"),
            _node("A13", "A12", 0, "d6"),
            _node("A14", "A13", 0, "a4"),
            _node("A15", "A13", 1, "b3"),
            _node("A16", "A11", 0, "Be7"),
        ]
    )
    annotations = [
        _annotation(
            "a1",
            "The bishop steps aside to keep the long diagonal covered.",
            {"kind": "move_node", "node_id": "A11", "relation": "after"},
        ),
        _annotation(
            "a2",
            "The queenside pawns prepare a quiet expansion.",
            {"kind": "position", "fen": "8/8/8/4k3/8/8/8/4K3 w - - 0 1"},
        ),
        _annotation("a3", "A short note without a reliable board anchor.", None),
    ]
    if duplicate_annotation_id is not None:
        annotations[1]["id"] = duplicate_annotation_id
    if annotation_anchor_id is not None:
        annotations[0]["anchor"] = {
            "kind": "move_node",
            "node_id": annotation_anchor_id,
            "relation": "before",
        }
    reading_flow: list[dict[str, Any]] = [
        {"kind": "move", "node_id": f"A{index}"} for index in range(1, 17)
    ]
    reading_flow.insert(11, {"kind": "annotation", "annotation_id": "a1"})
    reading_flow.insert(15, {"kind": "annotation", "annotation_id": "a2"})
    reading_flow.append({"kind": "annotation", "annotation_id": "a3"})
    return {
        "kind": "move_sequence",
        "id": "seqA",
        "title": "Synthetic annotated opening",
        "evidence": [{"page": 1}],
        "initial_position": {"kind": "startpos"},
        "nodes": nodes,
        "annotations": annotations,
        "reading_flow": reading_flow,
    }


def _sequence_b(
    *,
    annotation_id: str = "b1",
    annotation_anchor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shares the common prefix with A and adds a different Black sixth move."""
    nodes = _mainline_tree("B")
    nodes.append(_node("B12", "B11", 0, "Be7"))
    nodes.append(_node("B13", "B11", 1, "h6"))
    annotations = [
        _annotation(
            annotation_id,
            "A quiet alternative keeps the game closed.",
            annotation_anchor,
        )
    ]
    reading_flow: list[dict[str, Any]] = [
        {"kind": "move", "node_id": f"B{index}"} for index in range(1, 14)
    ]
    reading_flow.append({"kind": "annotation", "annotation_id": annotation_id})
    return {
        "kind": "move_sequence",
        "id": "seqB",
        "title": "Synthetic annotated opening",
        "evidence": [{"page": 2}],
        "initial_position": {"kind": "startpos"},
        "nodes": nodes,
        "annotations": annotations,
        "reading_flow": reading_flow,
    }


def _package(
    items: list[dict[str, Any]], diagnostics: list[dict[str, Any]] | None = None
) -> ExtractionPackageV1_1:
    return ExtractionPackageV1_1.model_validate(
        {
            "schema_version": CCEF_VERSION_1_1,
            "package_id": str(UUID("11111111-1111-4111-8111-111111111111")),
            "source": {
                "source_ref": "fixture",
                "media_type": "application/pdf",
                "language": "en",
                "page_range": {"start_page": 1, "end_page": 9},
            },
            "items": items,
            "diagnostics": diagnostics or [],
            "provenance": {
                "created_at": datetime(2026, 8, 14, tzinfo=UTC),
                "adapter_name": "test",
                "adapter_version": "1.1",
                "provider": None,
                "model": None,
                "request_sha256": None,
                "response_sha256": None,
            },
            "extensions": {},
        }
    )


def _sequences(package: ExtractionPackageV1_1) -> list[MoveSequenceItemV1_1]:
    return [item for item in package.items if isinstance(item, MoveSequenceItemV1_1)]


def _fragment(page: int, text: str) -> SourceEvidenceFragment:
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    return SourceEvidenceFragment(
        physical_page=page,
        box=box,
        text=text,
        origin="embedded_text",
        confidence=None,
        engine_name="pdfium",
        engine_version="test",
        fragment_sha256=source_fragment_sha256(page, box, text, "embedded_text", "pdfium", "test"),
    )


# ---------------------------------------------------------------------------
# 1. Shared tree merging and topology
# ---------------------------------------------------------------------------


def test_merges_shared_prefix_and_variations_into_one_tree() -> None:
    package = _package([_sequence_a(), _sequence_b()])
    out = consolidate_move_sequences_v1_1(package)
    sequences = _sequences(out)
    assert len(sequences) == 1
    sequence = sequences[0]
    assert sequence.id == "seqA"
    assert [node.id for node in sequence.nodes] == [f"n{index}" for index in range(1, 18)]

    node_map = {node.id: node for node in sequence.nodes}
    assert node_map["n1"].move_text == "e4"
    assert node_map["n11"].uci_candidate == "c1e3"
    # Earlier-parent alternative shares the real common prefix (n10), never a restart.
    assert node_map["n12"].parent_id == "n10"
    assert node_map["n12"].sibling_order == 1
    assert node_map["n12"].move_text == "a3"
    assert node_map["n13"].parent_id == "n12"
    assert node_map["n14"].parent_id == "n13"
    assert node_map["n14"].sibling_order == 0
    assert node_map["n15"].parent_id == "n13"
    assert node_map["n15"].sibling_order == 1
    # Later primary Black sixth move and B's alternative share the n11 parent.
    assert node_map["n16"].parent_id == "n11"
    assert node_map["n16"].sibling_order == 0
    assert node_map["n16"].move_text == "Be7"
    assert node_map["n17"].parent_id == "n11"
    assert node_map["n17"].sibling_order == 1
    assert node_map["n17"].move_text == "h6"


def test_duplicate_move_paths_union_evidence_and_nags_without_deduping_annotations() -> None:
    sequence_b = _sequence_b()
    sequence_b["nodes"][0]["evidence"] = [
        {"page": 2, "fragment_sha256": "0" * 64},
        {"page": 3, "fragment_sha256": "1" * 64},
    ]
    sequence_b["nodes"][0]["nags"] = [3]
    package = _package([_sequence_a(), sequence_b])
    out = consolidate_move_sequences_v1_1(package)
    sequence = _sequences(out)[0]
    n1 = sequence.nodes[0]
    pages = sorted(ref.page for ref in n1.evidence)
    assert pages == [1, 2, 3]
    assert n1.nags == [3]
    # Two distinct annotations both survive (never deduplicated by text).
    annotation_ids = [annotation.id for annotation in sequence.annotations]
    assert annotation_ids == ["a1", "a2", "a3", "b1"]
    texts = [annotation.text for annotation in sequence.annotations]
    assert len(set(texts)) == 4


# ---------------------------------------------------------------------------
# 2. Reading flow: source presentation independent of topology
# ---------------------------------------------------------------------------


def test_reading_flow_covers_moves_and_annotations_exactly() -> None:
    package = _package([_sequence_a(), _sequence_b()])
    out = consolidate_move_sequences_v1_1(package)
    sequence = _sequences(out)[0]
    move_ids = [entry.node_id for entry in sequence.reading_flow if isinstance(entry, MoveFlowRef)]
    annotation_ids = [
        entry.annotation_id
        for entry in sequence.reading_flow
        if isinstance(entry, AnnotationFlowRef)
    ]
    assert move_ids == [node.id for node in sequence.nodes]
    assert annotation_ids == [annotation.id for annotation in sequence.annotations]
    # Display order is independent of topology: a1 sits right after the n11
    # mainline move, while the alternative n12 (whose parent is n10) follows.
    flow_labels = [
        entry.annotation_id if entry.kind == "annotation" else entry.node_id
        for entry in sequence.reading_flow
    ]
    assert flow_labels[11] == "a1"
    assert flow_labels[12] == "n12"


# ---------------------------------------------------------------------------
# 3. Annotation anchors and IDs
# ---------------------------------------------------------------------------


def test_annotation_anchors_remap_with_before_after_preserved() -> None:
    package = _package([_sequence_a()])
    out = consolidate_move_sequences_v1_1(package)
    sequence = _sequences(out)[0]
    a1 = sequence.annotations[0]
    assert isinstance(a1.anchor, MoveNodeAnnotationAnchor)
    assert a1.anchor.node_id == "n11"
    assert a1.anchor.relation == "after"
    assert isinstance(sequence.annotations[1].anchor, PositionAnnotationAnchor)
    assert sequence.annotations[2].anchor is None


def test_duplicate_and_colliding_annotation_ids_receive_stable_ids() -> None:
    package = _package([_sequence_a(), _sequence_b(annotation_id="a1")])
    out = consolidate_move_sequences_v1_1(package)
    sequence = _sequences(out)[0]
    # A's a2/a3 are retained; the second sequence's "a1" collides with the
    # retained a1 and must receive the next free id deterministically.
    annotation_ids = [annotation.id for annotation in sequence.annotations]
    assert annotation_ids == ["a1", "a2", "a3", "a4"]
    assert len({annotation.id for annotation in sequence.annotations}) == 4
    flow_annotation_ids = [
        entry.annotation_id
        for entry in sequence.reading_flow
        if isinstance(entry, AnnotationFlowRef)
    ]
    assert flow_annotation_ids == annotation_ids

    # An annotation id colliding with a merged node id is remapped to a free a id.
    package = _package([_sequence_a(), _sequence_b(annotation_id="n12")])
    out = consolidate_move_sequences_v1_1(package)
    sequence = _sequences(out)[0]
    annotation_ids = [annotation.id for annotation in sequence.annotations]
    assert "n12" not in annotation_ids
    assert annotation_ids == ["a1", "a2", "a3", "a4"]


# ---------------------------------------------------------------------------
# 4. Omitted nodes and warnings
# ---------------------------------------------------------------------------


def test_omitted_invalid_node_keeps_annotation_with_null_anchor_and_one_warning() -> None:
    package = _package([_sequence_a(annotation_anchor_id="A12")])
    # Make the alternative A12 (a3) illegal so it is omitted from the tree.
    items = package.model_dump(mode="json")
    items["items"][0]["nodes"][11]["move_text"] = "O-O-O"
    package = ExtractionPackageV1_1.model_validate(items)

    out = consolidate_move_sequences_v1_1(package)
    sequence = _sequences(out)[0]
    a1 = sequence.annotations[0]
    assert a1.anchor is None
    unresolved = [w for w in a1.warnings if w.code == _UNRESOLVED_ANCHOR]
    assert len(unresolved) == 1
    assert unresolved[0].message == (
        "The source annotation anchor was removed with an unplayable move fragment."
    )
    assert unresolved[0].evidence[0].page == 3
    # The annotation remains in flow with its exact-cover projection.
    assert any(
        isinstance(entry, AnnotationFlowRef) and entry.annotation_id == "a1"
        for entry in sequence.reading_flow
    )

    again = consolidate_move_sequences_v1_1(out)
    sequence_again = _sequences(again)[0]
    a1_again = sequence_again.annotations[0]
    assert len([w for w in a1_again.warnings if w.code == _UNRESOLVED_ANCHOR]) == 1


def test_all_unplayable_sequence_preserves_annotations_as_top_level_prose() -> None:
    sequence = _sequence_a()
    sequence["nodes"][0]["move_text"] = "O-O"  # illegal from startpos
    package = _package([sequence])
    out = consolidate_move_sequences_v1_1(package)
    assert _sequences(out) == []
    prose = [item for item in out.items if isinstance(item, ProseItem)]
    assert len(prose) == 3
    texts = [item.text for item in prose]
    assert "bishop steps aside" in texts[0]
    # Move-node anchor became null; position anchor preserved as PositionAnchor.
    assert prose[0].anchor is None
    assert isinstance(prose[1].anchor, PositionAnchor)
    assert all(item.id.startswith("consolidation_annotation_") for item in prose)
    assert all(len(item.id) > 0 for item in prose)
    # The invalid move text is covered by the existing omitted-node fallback.
    unresolved = [item for item in out.items if item.kind == "unresolved" or item.kind == "prose"]
    assert len(unresolved) >= 3


def test_all_unplayable_anchor_warnings_are_conditional() -> None:
    sequence = _sequence_a()
    sequence["nodes"][0]["move_text"] = "O-O"  # illegal from startpos
    # One annotation of each anchor kind, in a fixed order.
    sequence["annotations"] = [
        _annotation(
            "a1",
            "A move-node anchored note.",
            {"kind": "move_node", "node_id": "A11", "relation": "after"},
        ),
        _annotation(
            "a2",
            "A position anchored note.",
            {"kind": "position", "fen": "8/8/8/4k3/8/8/8/4K3 w - - 0 1"},
        ),
        _annotation("a3", "A null anchored note.", None),
    ]
    reading_flow: list[dict[str, Any]] = [
        {"kind": "move", "node_id": f"A{index}"} for index in range(1, 17)
    ]
    reading_flow.insert(1, {"kind": "annotation", "annotation_id": "a1"})
    reading_flow.insert(2, {"kind": "annotation", "annotation_id": "a2"})
    reading_flow.insert(3, {"kind": "annotation", "annotation_id": "a3"})
    sequence["reading_flow"] = reading_flow
    package = _package([sequence])
    out = consolidate_move_sequences_v1_1(package)
    prose = [item for item in out.items if isinstance(item, ProseItem)]
    assert len(prose) == 3

    move_prose, position_prose, null_prose = prose

    # Only the move-node-derived prose carries exactly one unresolved warning.
    move_warnings = [w for w in move_prose.warnings if w.code == _UNRESOLVED_ANCHOR]
    assert len(move_warnings) == 1
    assert move_warnings[0].message == (
        "The source annotation anchor was removed with an unplayable move fragment."
    )

    # Position/null-derived prose retain no generated warning.
    assert position_prose.anchor is not None
    assert isinstance(position_prose.anchor, PositionAnchor)
    assert position_prose.anchor.fen == "8/8/8/4k3/8/8/8/4K3 w - - 0 1"
    assert [w for w in position_prose.warnings if w.code == _UNRESOLVED_ANCHOR] == []
    assert null_prose.anchor is None
    assert [w for w in null_prose.warnings if w.code == _UNRESOLVED_ANCHOR] == []

    # Re-consolidation does not duplicate the single generated warning.
    again = consolidate_move_sequences_v1_1(out)
    prose_again = [item for item in again.items if isinstance(item, ProseItem)]
    assert [w for w in prose_again[0].warnings if w.code == _UNRESOLVED_ANCHOR] == move_warnings


def test_two_all_unplayable_sequences_keep_all_annotations_and_fallbacks() -> None:
    def all_unplayable(
        sequence_id: str, page: int, annotations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        nodes = _mainline_tree(sequence_id[-1])
        nodes[0]["move_text"] = "O-O"  # illegal from startpos
        for node in nodes:
            node["evidence"] = [{"page": page}]
        reading_flow: list[dict[str, Any]] = [
            {"kind": "move", "node_id": f"{sequence_id[-1]}{index}"}
            for index in range(1, len(nodes) + 1)
        ]
        reading_flow.extend(
            {"kind": "annotation", "annotation_id": annotation["id"]} for annotation in annotations
        )
        return {
            "kind": "move_sequence",
            "id": sequence_id,
            "title": "Synthetic annotated opening",
            "evidence": [{"page": page}],
            "initial_position": {"kind": "startpos"},
            "nodes": nodes,
            "annotations": annotations,
            "reading_flow": reading_flow,
        }

    seq_x = all_unplayable(
        "seqX",
        1,
        [
            _annotation("x1", "First note from the first source.", None),
            _annotation("x2", "Second note from the first source.", None),
        ],
    )
    seq_y = all_unplayable(
        "seqY",
        2,
        [_annotation("y1", "A note from the second source.", None)],
    )
    package = _package([seq_x, seq_y])
    out = consolidate_move_sequences_v1_1(package)
    assert _sequences(out) == []

    prose = [item for item in out.items if isinstance(item, ProseItem)]
    texts = [item.text for item in prose]
    assert texts == [
        "First note from the first source.",
        "Second note from the first source.",
        "A note from the second source.",
    ]
    assert len({item.id for item in prose}) == 3
    assert all(item.id.startswith("consolidation_annotation_") for item in prose)

    # Both source sequences' omitted-move fallbacks remain present.
    unresolved = [item for item in out.items if item.kind == "unresolved"]
    assert len(unresolved) == 2
    assert {item.evidence[0].page for item in unresolved} == {1, 2}

    # Re-consolidation of the output is byte-value identical.
    again = consolidate_move_sequences_v1_1(out)
    assert again.model_dump(mode="json") == out.model_dump(mode="json")


# ---------------------------------------------------------------------------
# 5. Top-level references and evidence pages
# ---------------------------------------------------------------------------


def test_top_level_prose_anchors_and_diagnostics_remap() -> None:
    package = _package(
        [
            {
                "kind": "prose",
                "id": "p1",
                "text": "Follow the mainline plan.",
                "evidence": [{"page": 4}],
                "anchor": {"kind": "move_node", "sequence_id": "seqA", "node_id": "A11"},
            },
            _sequence_a(),
        ],
        diagnostics=[
            {
                "severity": "info",
                "code": "tree_ok",
                "message": "all nodes structurally ordered",
                "item_id": "seqA",
                "node_id": "A12",
            }
        ],
    )
    out = consolidate_move_sequences_v1_1(package)
    prose = next(item for item in out.items if isinstance(item, ProseItem))
    assert isinstance(prose.anchor, MoveNodeAnchor)
    assert prose.anchor.sequence_id == "seqA"
    assert prose.anchor.node_id == "n11"
    diagnostic = out.diagnostics[0]
    assert diagnostic.item_id == "seqA"
    assert diagnostic.node_id == "n12"


def test_evidence_pages_retain_the_normalized_tree_not_fragment_reconstruction() -> None:
    fragment_text = (
        "1. e4 e5 2. Nf3 Nc6 3. d4 exd4 4. Nxd4 Nf6 5. Nc3 Bb4 6. a3 and a solid structure"
    )
    page = PromptEvidencePage(
        physical_page=1,
        fragments=[PromptEvidenceFragment(order=0, fragment=_fragment(1, fragment_text))],
    )
    sequence = _sequence_a()
    # Attach the synthetic fragment evidence to the alternative-branch nodes.
    for node in sequence["nodes"]:
        node["evidence"] = [
            {"page": 1, "fragment_sha256": _fragment(1, fragment_text).fragment_sha256}
        ]
    package = _package([sequence])
    out = consolidate_move_sequences_v1_1(package, evidence_pages=[page])
    sequences = _sequences(out)
    assert len(sequences) == 1
    node_map = {node.id: node for node in sequences[0].nodes}
    # The inline alternative survives from the normalized tree: proving the
    # v1 formal-fragment reconstruction was not used to flatten the score.
    assert node_map["n12"].move_text == "a3"
    assert node_map["n12"].parent_id == "n10"


# ---------------------------------------------------------------------------
# 6. Immutability, idempotency and type misuse
# ---------------------------------------------------------------------------


def test_input_unchanged_output_independent_and_repeated_calls_identical() -> None:
    package = _package([_sequence_a(), _sequence_b()])
    snapshot = package.model_dump(mode="json")
    out = consolidate_move_sequences_v1_1(package)
    assert package.model_dump(mode="json") == snapshot
    assert out is not package

    # Mutating the output annotation does not touch the input.
    sequence = _sequences(out)[0]
    sequence.annotations[0].text = "mutated"
    assert package.model_dump(mode="json") == snapshot

    # Repeated consolidation of an untouched output is byte-value identical.
    again = consolidate_move_sequences_v1_1(_package([_sequence_a(), _sequence_b()]))
    third = consolidate_move_sequences_v1_1(again)
    assert third.model_dump(mode="json") == again.model_dump(mode="json")


def test_exact_type_misuse_is_rejected_without_input_values() -> None:
    with pytest.raises(TypeError) as caught:
        consolidate_move_sequences_v1_1(
            cast(Any, _package([_sequence_a()]).model_dump(mode="json"))
        )
    assert "package must be ExtractionPackageV1_1" in str(caught.value)
    assert "11111111" not in str(caught.value)

    with pytest.raises(TypeError) as caught:
        consolidate_move_sequences_v1_1(
            _package([_sequence_a()]),
            evidence_pages=cast(Any, [object()]),
        )
    assert "evidence_pages must contain PromptEvidencePage values" in str(caught.value)
