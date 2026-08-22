"""Focused contract tests for the portable CCEF v1.1 annotated move-sequence profile.

Covers the frozen behaviors of DS-STAGE8-ANNOTATED-SCORE-CONTRACT-01: a fully
valid synthetic 1.1 package with a primary line, atomic notes, an alternative
move, a nested variation and a later primary Black move; exact move/annotation
flow coverage; JSON round trips; every structural rejection in ADR 0017; the
deterministic 1.1 Schema artifact; and an explicit regression that the v1
Schema bytes and representative v1 packages remain unchanged.

All content is invented synthetic test material; no user-book text, page
numbers 319-323, real provider calls or screenshot move sequences are used.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from chess_workbench.extraction.contracts import (
    CCEF_VERSION,
    CCEF_VERSION_1_1,
    AnnotationFlowRef,
    EvidenceRef,
    ExtractionPackage,
    ExtractionPackageV1_1,
    MoveFlowRef,
    MoveNode,
    MoveNodeAnnotationAnchor,
    MoveSequenceItem,
    MoveSequenceItemV1_1,
    PageRange,
    PositionAnnotationAnchor,
    Provenance,
    SourceDescriptor,
    StartPosition,
    ccef_schema_canonical_json,
    ccef_v1_1_schema_canonical_json,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_V1 = REPO_ROOT / "contracts" / "chess-content-extraction-v1.schema.json"
ARTIFACT_V1_1 = REPO_ROOT / "contracts" / "chess-content-extraction-v1.1.schema.json"

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
ANCHOR_FEN = "8/8/8/4k3/8/8/8/4K3 w - - 0 1"


def _evidence(page: int = 1, **kwargs: Any) -> EvidenceRef:
    return EvidenceRef(page=page, **kwargs)


def _provenance() -> Provenance:
    return Provenance(
        created_at=datetime(2026, 8, 14, 9, 30, tzinfo=UTC),
        adapter_name="test-adapter",
        adapter_version="0.2.0",
    )


def _move(
    id: str,
    parent: str | None,
    sibling: int,
    text: str,
    move_number: int | None = None,
    side: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "parent_id": parent,
        "sibling_order": sibling,
        "move_text": text,
        "move_number": move_number,
        "side_to_move": side,
        "evidence": [{"page": 1}],
    }


# Invented synthetic tree: primary line through White's sixth move, an
# alternative White sixth move hanging from the common fifth-move node, one
# nested variation, and a later primary Black sixth move whose parent remains
# the primary White sixth move.
def _nodes() -> list[dict[str, Any]]:
    return [
        _move("n1", None, 0, "e4", 1, "w"),
        _move("n2", "n1", 0, "e5", 1, "b"),
        _move("n3", "n2", 0, "Nf3", 2, "w"),
        _move("n4", "n3", 0, "Nc6", 2, "b"),
        _move("n5", "n4", 0, "d4", 3, "w"),
        _move("n6", "n5", 0, "exd4", 3, "b"),
        _move("n7", "n6", 0, "Nxd4", 4, "w"),
        _move("n8", "n7", 0, "Nf6", 4, "b"),
        _move("n9", "n8", 0, "Nc3", 5, "w"),
        _move("n10", "n9", 0, "Bb4", 5, "b"),
        _move("n11", "n10", 0, "Be3", 6, "w"),
        _move("n12", "n10", 1, "O-O", 6, "w"),
        _move("n13", "n12", 0, "d6", 6, "b"),
        _move("n14", "n13", 0, "c3", 7, "w"),
        _move("n15", "n13", 1, "b3", 7, "w"),
        _move("n16", "n11", 0, "O-O-O", 6, "b"),
    ]


def _annotations() -> list[dict[str, Any]]:
    return [
        {
            "id": "a1",
            "text": "The bishop steps aside to keep the long diagonal covered.",
            "anchor": {"kind": "move_node", "node_id": "n11", "relation": "after"},
            "evidence": [{"page": 1}],
        },
        {
            "id": "a2",
            "text": "The queenside castling is already prepared.",
            "text_format": "markdown",
            "anchor": {"kind": "position", "fen": ANCHOR_FEN},
            "evidence": [{"page": 1}],
            "confidence": 0.9,
            "warnings": [],
        },
        {
            "id": "a3",
            "text": "A short note without a reliable board anchor.",
            "anchor": None,
            "evidence": [{"page": 1}],
        },
    ]


def _sequence(
    annotations: list[dict[str, Any]] | None = None,
    flow_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    annotations = _annotations() if annotations is None else annotations
    flow: list[dict[str, Any]] = [
        {"kind": "move", "node_id": f"n{index}"} for index in range(1, 17)
    ]
    # Insert annotation entries at fixed invented display positions when the
    # three-annotation oracle is used; otherwise append them in order.
    annotation_flow = [
        {"kind": "annotation", "annotation_id": annotation["id"]} for annotation in annotations
    ]
    if len(annotation_flow) >= 2:
        flow.insert(11, annotation_flow[0])
        flow.insert(15, annotation_flow[1])
        flow.extend(annotation_flow[2:])
    else:
        flow.extend(annotation_flow)
    if flow_override is not None:
        flow = flow_override
    return {
        "id": "seq1",
        "kind": "move_sequence",
        "title": "Synthetic opening study",
        "initial_position": {"kind": "startpos"},
        "nodes": _nodes(),
        "annotations": annotations,
        "reading_flow": flow,
        "evidence": [{"page": 1}],
    }


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": CCEF_VERSION_1_1,
        "package_id": uuid4(),
        "source": {
            "source_ref": "opaque-synthetic-1",
            "media_type": "application/pdf",
            "language": "zh",
            "page_range": {"start_page": 1, "end_page": 5},
        },
        "items": [
            {
                "id": "h1",
                "kind": "heading",
                "level": 1,
                "text": "Synthetic chapter",
                "evidence": [{"page": 1}],
            },
            _sequence(),
            {
                "id": "p1",
                "kind": "prose",
                "text": "A narrative paragraph that stays outside the score.",
                "evidence": [{"page": 1}],
            },
        ],
        "diagnostics": [
            {
                "severity": "info",
                "code": "tree_ok",
                "message": "all nodes structurally ordered",
                "item_id": "seq1",
                "node_id": "n1",
            }
        ],
        "provenance": {
            "created_at": "2026-08-14T09:30:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "0.2.0",
        },
        "extensions": {"org.example.import": {"batch": 3}},
    }
    payload.update(overrides)
    return payload


def _valid_package() -> ExtractionPackageV1_1:
    return ExtractionPackageV1_1.model_validate(_payload())


# ---------------------------------------------------------------------------
# Valid packages, round trips and flow coverage
# ---------------------------------------------------------------------------


def test_full_valid_v1_1_package_round_trips_and_preserves_flow() -> None:
    package = _valid_package()
    dumped = package.model_dump(mode="json")
    rebuilt = ExtractionPackageV1_1.model_validate(dumped)
    assert rebuilt.model_dump(mode="json") == dumped
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    move_ids = [entry.node_id for entry in sequence.reading_flow if isinstance(entry, MoveFlowRef)]
    annotation_ids = [
        entry.annotation_id
        for entry in sequence.reading_flow
        if isinstance(entry, AnnotationFlowRef)
    ]
    assert move_ids == [node.id for node in sequence.nodes]
    assert annotation_ids == [annotation.id for annotation in sequence.annotations]
    assert sequence.annotations[0].text_format == "plain"
    assert sequence.annotations[1].text_format == "markdown"
    assert sequence.annotations[1].confidence == 0.9
    assert sequence.annotations[2].anchor is None


def test_reading_flow_covers_all_nodes_when_annotations_empty() -> None:
    package = ExtractionPackageV1_1.model_validate(_payload(items=[_sequence(annotations=[])]))
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert sequence.annotations == []
    move_ids = [entry.node_id for entry in sequence.reading_flow if isinstance(entry, MoveFlowRef)]
    assert move_ids == [node.id for node in sequence.nodes]


def test_reading_flow_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(_payload(items=[_sequence(flow_override=[])]))


def test_input_payload_is_never_mutated() -> None:
    payload = _payload()
    snapshot = copy.deepcopy(payload)
    package = ExtractionPackageV1_1.model_validate(payload)
    assert package is not None
    assert payload == snapshot


# ---------------------------------------------------------------------------
# Frozen rejections
# ---------------------------------------------------------------------------


def test_rejects_duplicate_node_ids() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["nodes"][1]["id"] = sequence["nodes"][0]["id"]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_duplicate_annotation_ids() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["annotations"][1]["id"] = sequence["annotations"][0]["id"]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_node_annotation_id_collision() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["annotations"][0]["id"] = sequence["nodes"][0]["id"]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_dangling_annotation_anchor() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["annotations"][0]["anchor"]["node_id"] = "ghost"
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_dangling_flow_move_reference() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["reading_flow"][0]["node_id"] = "ghost"
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_dangling_flow_annotation_reference() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    for entry in sequence["reading_flow"]:
        if entry["kind"] == "annotation":
            entry["annotation_id"] = "ghost"
            break
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_duplicate_flow_move_reference() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["reading_flow"][0]["node_id"] = sequence["reading_flow"][1]["node_id"]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_duplicate_flow_annotation_reference() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    first = next(
        index
        for index, entry in enumerate(sequence["reading_flow"])
        if entry["kind"] == "annotation"
    )
    second = next(
        index
        for index, entry in enumerate(sequence["reading_flow"])
        if entry["kind"] == "annotation" and index != first
    )
    sequence["reading_flow"][second]["annotation_id"] = sequence["reading_flow"][first][
        "annotation_id"
    ]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_dangling_and_forward_and_self_parents() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["nodes"][2]["parent_id"] = "ghost"
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)

    payload = _payload()
    sequence = payload["items"][1]
    sequence["nodes"][2]["parent_id"] = sequence["nodes"][5]["id"]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)

    payload = _payload()
    sequence = payload["items"][1]
    sequence["nodes"][0]["parent_id"] = sequence["nodes"][0]["id"]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_non_contiguous_sibling_order() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["nodes"][11]["sibling_order"] = 2  # under parent n10: [0, 2]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_move_flow_projection_mismatch() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["reading_flow"][3], sequence["reading_flow"][4] = (
        sequence["reading_flow"][4],
        sequence["reading_flow"][3],
    )
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_annotation_flow_projection_mismatch() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    first = next(
        index
        for index, entry in enumerate(sequence["reading_flow"])
        if entry["kind"] == "annotation"
    )
    second = next(
        index
        for index, entry in enumerate(sequence["reading_flow"])
        if entry["kind"] == "annotation" and index != first
    )
    (
        sequence["reading_flow"][first]["annotation_id"],
        sequence["reading_flow"][second]["annotation_id"],
    ) = (
        sequence["reading_flow"][second]["annotation_id"],
        sequence["reading_flow"][first]["annotation_id"],
    )
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_duplicate_flow_references_still_rejected_with_clear_messages() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["reading_flow"][0]["node_id"] = sequence["reading_flow"][1]["node_id"]
    with pytest.raises(ValidationError) as exc:
        ExtractionPackageV1_1.model_validate(payload)
    assert "duplicate flow move reference" in exc.value.errors()[0]["msg"]

    payload = _payload()
    sequence = payload["items"][1]
    first = next(
        index
        for index, entry in enumerate(sequence["reading_flow"])
        if entry["kind"] == "annotation"
    )
    second = next(
        index
        for index, entry in enumerate(sequence["reading_flow"])
        if entry["kind"] == "annotation" and index != first
    )
    sequence["reading_flow"][second]["annotation_id"] = sequence["reading_flow"][first][
        "annotation_id"
    ]
    with pytest.raises(ValidationError) as exc:
        ExtractionPackageV1_1.model_validate(payload)
    assert "duplicate flow annotation reference" in exc.value.errors()[0]["msg"]


def test_projection_mismatch_messages_are_bounded_and_omit_id_collections() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["reading_flow"][3], sequence["reading_flow"][4] = (
        sequence["reading_flow"][4],
        sequence["reading_flow"][3],
    )
    with pytest.raises(ValidationError) as exc:
        ExtractionPackageV1_1.model_validate(payload)
    move_msg = exc.value.errors()[0]["msg"]
    assert "move flow projection differs from nodes in sequence 'seq1'" in move_msg
    assert "n1" not in move_msg
    assert len(move_msg) < 200

    payload = _payload()
    sequence = payload["items"][1]
    first = next(
        index
        for index, entry in enumerate(sequence["reading_flow"])
        if entry["kind"] == "annotation"
    )
    second = next(
        index
        for index, entry in enumerate(sequence["reading_flow"])
        if entry["kind"] == "annotation" and index != first
    )
    (
        sequence["reading_flow"][first]["annotation_id"],
        sequence["reading_flow"][second]["annotation_id"],
    ) = (
        sequence["reading_flow"][second]["annotation_id"],
        sequence["reading_flow"][first]["annotation_id"],
    )
    with pytest.raises(ValidationError) as exc:
        ExtractionPackageV1_1.model_validate(payload)
    annotation_msg = exc.value.errors()[0]["msg"]
    assert (
        "annotation flow projection differs from annotations in sequence 'seq1'" in annotation_msg
    )
    assert "a1" not in annotation_msg
    assert len(annotation_msg) < 200


def test_rejects_annotation_evidence_outside_page_range() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["annotations"][0]["evidence"][0]["page"] = 9
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_annotation_warning_evidence_outside_page_range() -> None:
    payload = _payload()
    sequence = payload["items"][1]
    sequence["annotations"][0]["warnings"] = [
        {
            "code": "note_long",
            "message": "annotation exceeds one sentence",
            "evidence": [{"page": 9}],
        }
    ]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_dangling_top_level_prose_anchor() -> None:
    payload = _payload()
    payload["items"][2]["anchor"] = {
        "kind": "move_node",
        "sequence_id": "seq1",
        "node_id": "ghost",
    }
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_dangling_diagnostic_node_reference() -> None:
    payload = _payload()
    payload["diagnostics"][0]["node_id"] = "ghost"
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_duplicate_item_ids() -> None:
    payload = _payload()
    payload["items"][2]["id"] = payload["items"][0]["id"]
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_unknown_fields_on_new_models() -> None:
    payload = _payload()
    payload["items"][1]["annotations"][0]["surprise"] = True
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)

    payload = _payload()
    payload["items"][1]["reading_flow"][0]["surprise"] = True
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)

    payload = _payload()
    payload["surprise"] = True
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_strict_scalar_and_container_types() -> None:
    payload = _payload()
    payload["items"][1]["annotations"][0]["confidence"] = "0.9"
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)

    payload = _payload()
    payload["items"][1]["annotations"][0]["text_format"] = "plain "
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)

    payload = _payload()
    payload["items"][1]["annotations"] = {}
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


def test_rejects_empty_annotation_evidence() -> None:
    payload = _payload()
    payload["items"][1]["annotations"][0]["evidence"] = []
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate(payload)


# ---------------------------------------------------------------------------
# Annotation anchors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relation", ["before", "after"])
def test_annotation_anchor_before_and_after_relations(relation: str) -> None:
    payload = _payload()
    payload["items"][1]["annotations"][0]["anchor"]["relation"] = relation
    package = ExtractionPackageV1_1.model_validate(payload)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    anchor = sequence.annotations[0].anchor
    assert isinstance(anchor, MoveNodeAnnotationAnchor)
    assert anchor.relation == relation


def test_annotation_position_anchor_and_null_anchor() -> None:
    payload = _payload()
    payload["items"][1]["annotations"][1]["anchor"] = {
        "kind": "position",
        "fen": ANCHOR_FEN,
    }
    package = ExtractionPackageV1_1.model_validate(payload)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    anchor = sequence.annotations[1].anchor
    assert isinstance(anchor, PositionAnnotationAnchor)
    assert anchor.fen == ANCHOR_FEN

    payload = _payload()
    payload["items"][1]["annotations"][1]["anchor"] = None
    package = ExtractionPackageV1_1.model_validate(payload)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert sequence.annotations[1].anchor is None


def test_annotation_evidence_and_defaults() -> None:
    package = _valid_package()
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    annotation = sequence.annotations[0]
    assert annotation.evidence[0].page == 1
    assert annotation.warnings == []
    assert annotation.extensions == {}
    assert annotation.confidence is None


# ---------------------------------------------------------------------------
# Schema artifact
# ---------------------------------------------------------------------------


def test_v1_1_schema_artifact_is_byte_for_byte_deterministic() -> None:
    first = ccef_v1_1_schema_canonical_json()
    second = ccef_v1_1_schema_canonical_json()
    assert first == second
    assert ARTIFACT_V1_1.read_text(encoding="utf-8") == first
    assert first.endswith("\n")


def test_v1_1_schema_identity_and_discriminators() -> None:
    import json

    schema = json.loads(ARTIFACT_V1_1.read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:chess-content-extraction:schema:1.1"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "Chess Content Extraction Format v1.1"
    assert schema["properties"]["schema_version"]["const"] == "chess-content-extraction/1.1"

    item_union = schema["properties"]["items"]["items"]
    assert item_union["discriminator"]["propertyName"] == "kind"
    mapping = item_union["discriminator"]["mapping"]
    assert mapping["move_sequence"].endswith("MoveSequenceItemV1_1")
    move_sequence = schema["$defs"]["MoveSequenceItemV1_1"]
    assert move_sequence["additionalProperties"] is False
    assert move_sequence["properties"]["annotations"]["items"]["$ref"].endswith(
        "SequenceAnnotation"
    )
    flow = move_sequence["properties"]["reading_flow"]
    assert flow["minItems"] == 1
    assert flow["items"]["discriminator"]["propertyName"] == "kind"

    annotation = schema["$defs"]["SequenceAnnotation"]
    assert annotation["additionalProperties"] is False
    assert annotation["properties"]["evidence"]["minItems"] == 1
    assert annotation["properties"]["text_format"]["default"] == "plain"
    anchor = annotation["properties"]["anchor"]
    anchor_union = anchor["anyOf"][0]
    assert anchor_union["discriminator"]["propertyName"] == "kind"
    assert set(anchor_union["discriminator"]["mapping"]) == {"move_node", "position"}
    for ref in anchor_union["discriminator"]["mapping"].values():
        member = schema["$defs"][ref.split("/")[-1]]
        assert member["additionalProperties"] is False

    for ref in flow["items"]["discriminator"]["mapping"].values():
        member = schema["$defs"][ref.split("/")[-1]]
        assert member["additionalProperties"] is False


def test_v1_schema_bytes_and_packages_stay_unchanged() -> None:
    assert ccef_schema_canonical_json() == ARTIFACT_V1.read_text(encoding="utf-8")

    # A representative v1 package (no annotations/reading flow) still validates.
    package = ExtractionPackage(
        schema_version=CCEF_VERSION,
        package_id=uuid4(),
        source=SourceDescriptor(
            source_ref="opaque-v1-ref",
            media_type="application/pdf",
            page_range=PageRange(start_page=1, end_page=2),
        ),
        items=[
            MoveSequenceItem(
                id="seq1",
                kind="move_sequence",
                initial_position=StartPosition(kind="startpos"),
                nodes=[
                    MoveNode(
                        id="n1",
                        parent_id=None,
                        sibling_order=0,
                        move_text="e4",
                        evidence=[_evidence()],
                    ),
                    MoveNode(
                        id="n2",
                        parent_id="n1",
                        sibling_order=0,
                        move_text="e5",
                        evidence=[_evidence()],
                    ),
                ],
                evidence=[_evidence()],
            )
        ],
        provenance=_provenance(),
    )
    assert package.schema_version == CCEF_VERSION
