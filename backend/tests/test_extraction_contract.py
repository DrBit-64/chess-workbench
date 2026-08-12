"""Focused contract tests for the portable CCEF v1 extraction package.

Covers the required behaviors of DS-STAGE8-PORTABLE-CONTRACT-01:
full valid packages, JSON round trips, deterministic JSON Schema drift,
every structural rejection, invalid scalar values, and import purity.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from chess_workbench.extraction.contracts import (
    CCEF_VERSION,
    Diagnostic,
    EvidenceRef,
    ExtractionPackage,
    FenPosition,
    FigureItem,
    HeadingItem,
    MoveNode,
    MoveNodeAnchor,
    MoveSequenceItem,
    PageRange,
    PositionAnchor,
    ProseItem,
    Provenance,
    SourceDescriptor,
    StartPosition,
    UnresolvedItem,
    ccef_schema_canonical_json,
    ccef_schema_document,
)
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "contracts" / "chess-content-extraction-v1.schema.json"
PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src"

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _evidence(page: int = 1, **kwargs: Any) -> EvidenceRef:
    return EvidenceRef(page=page, **kwargs)


def _provenance() -> Provenance:
    return Provenance(
        created_at=datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        adapter_name="test-adapter",
        adapter_version="0.1.0",
    )


def _valid_package() -> ExtractionPackage:
    """A structurally valid package with all five item kinds and both anchors."""
    items: list[HeadingItem | ProseItem | MoveSequenceItem | FigureItem | UnresolvedItem] = [
        HeadingItem(
            id="h1",
            kind="heading",
            level=1,
            text="Chapter 1",
            evidence=[_evidence()],
        ),
        ProseItem(
            id="p1",
            kind="prose",
            text="Narrative introduction.",
            evidence=[_evidence()],
            anchor=MoveNodeAnchor(kind="move_node", sequence_id="seq1", node_id="n1"),
        ),
        ProseItem(
            id="p2",
            kind="prose",
            text="Position note.",
            evidence=[_evidence()],
            anchor=PositionAnchor(kind="position", fen=START_FEN),
        ),
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
                MoveNode(
                    id="n3",
                    parent_id="n1",
                    sibling_order=1,
                    move_text="c5",
                    evidence=[_evidence()],
                ),
            ],
            evidence=[_evidence()],
        ),
        FigureItem(
            id="f1",
            kind="figure",
            figure_type="chessboard",
            evidence=[_evidence()],
        ),
        UnresolvedItem(
            id="u1",
            kind="unresolved",
            unresolved_type="text",
            reason_code="ocr_unclear",
            raw_text="???",
            evidence=[_evidence()],
        ),
    ]
    return ExtractionPackage(
        schema_version=CCEF_VERSION,
        package_id=uuid4(),
        source=SourceDescriptor(
            source_ref="opaque-ref-1",
            media_type="application/pdf",
            language="zh",
            page_range=PageRange(start_page=1, end_page=5),
        ),
        items=items,
        diagnostics=[
            Diagnostic(
                severity="info",
                code="tree_ok",
                message="all nodes structurally ordered",
                item_id="seq1",
                node_id="n1",
            )
        ],
        provenance=_provenance(),
        extensions={"org.example.import": {"batch": 7}},
    )


# ---------------------------------------------------------------------------
# Valid packages and round trips
# ---------------------------------------------------------------------------


def test_full_valid_package_contains_all_five_kinds_and_both_anchors() -> None:
    package = _valid_package()
    kinds = {item.kind for item in package.items}
    assert kinds == {"heading", "prose", "move_sequence", "figure", "unresolved"}
    prose_anchors = {
        item.anchor.kind for item in package.items if isinstance(item, ProseItem) and item.anchor
    }
    assert prose_anchors == {"move_node", "position"}


def test_json_round_trip_equality_and_defaults_appear() -> None:
    package = _valid_package()
    first = package.model_dump(mode="json", exclude_none=False)
    # Defaults must be present after the first dump.
    assert first["items"][0]["warnings"] == []
    assert first["items"][0]["extensions"] == {}
    assert first["items"][0]["confidence"] is None
    assert first["items"][3]["nodes"][0]["validation_status"] == "unvalidated"
    assert first["items"][1]["text_format"] == "plain"

    reloaded = ExtractionPackage.model_validate(first)
    second = reloaded.model_dump(mode="json", exclude_none=False)
    assert second == first


def test_json_schema_artifact_is_byte_for_byte_deterministic() -> None:
    generated = ccef_schema_canonical_json()
    checked_in = ARTIFACT.read_text(encoding="utf-8")
    assert generated == checked_in
    # Regeneration is stable across calls.
    assert ccef_schema_canonical_json() == generated


# ---------------------------------------------------------------------------
# Structural rejections (Required behavior item 6)
# ---------------------------------------------------------------------------


def test_rejects_unsupported_schema_version() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["schema_version"] = "chess-content-extraction/2.0"
    with pytest.raises(ValidationError):
        ExtractionPackage.model_validate(data)


def test_rejects_unknown_fields_at_every_object_boundary() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["bogus_top_level"] = True
    with pytest.raises(ValidationError):
        ExtractionPackage.model_validate(data)

    item_data = package.model_dump(mode="json")["items"][0]
    item_data["surprise"] = 1
    with pytest.raises(ValidationError):
        HeadingItem.model_validate(item_data)


def test_rejects_duplicate_item_ids() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    extra = HeadingItem(
        id="h1",
        kind="heading",
        level=2,
        text="Duplicate id",
        evidence=[_evidence()],
    )
    data["items"].append(extra.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="duplicate item id"):
        ExtractionPackage.model_validate(data)


def test_rejects_duplicate_node_ids() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    nodes = data["items"][3]["nodes"]
    nodes.append(
        MoveNode(
            id="n1",
            parent_id=None,
            sibling_order=1,
            move_text="d4",
            evidence=[_evidence()],
        ).model_dump(mode="json")
    )
    with pytest.raises(ValidationError, match="duplicate node id"):
        ExtractionPackage.model_validate(data)


def test_rejects_dangling_prose_anchor() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["items"][1]["anchor"] = {
        "kind": "move_node",
        "sequence_id": "missing-seq",
        "node_id": "n1",
    }
    with pytest.raises(ValidationError, match="dangling move_node anchor sequence"):
        ExtractionPackage.model_validate(data)


def test_rejects_dangling_node_parent() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["items"][3]["nodes"][1]["parent_id"] = "ghost"
    with pytest.raises(ValidationError, match="dangling or forward parent"):
        ExtractionPackage.model_validate(data)


def test_rejects_forward_node_parent() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    nodes = data["items"][3]["nodes"]
    # Make n2's parent a node that appears later.
    nodes[1]["parent_id"] = "n3"
    with pytest.raises(ValidationError, match="dangling or forward parent"):
        ExtractionPackage.model_validate(data)


def test_rejects_duplicate_sibling_order() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["items"][3]["nodes"].append(
        MoveNode(
            id="n4",
            parent_id="n1",
            sibling_order=0,  # collides with n2
            move_text="Nf3",
            evidence=[_evidence()],
        ).model_dump(mode="json")
    )
    with pytest.raises(ValidationError, match="non-contiguous sibling_order"):
        ExtractionPackage.model_validate(data)


def test_rejects_non_contiguous_sibling_order() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["items"][3]["nodes"][2]["sibling_order"] = 2  # gap: 0,2 instead of 0,1
    with pytest.raises(ValidationError, match="non-contiguous sibling_order"):
        ExtractionPackage.model_validate(data)


def test_rejects_evidence_outside_declared_page_range() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    # page_range is 1..5; place an item on page 9.
    data["items"].append(
        HeadingItem(
            id="h9",
            kind="heading",
            level=1,
            text="Out of range",
            evidence=[_evidence(page=9)],
        ).model_dump(mode="json")
    )
    with pytest.raises(ValidationError, match="outside declared page range"):
        ExtractionPackage.model_validate(data)


# ---------------------------------------------------------------------------
# Scalar and reference rejections
# ---------------------------------------------------------------------------


def test_rejects_invalid_bbox() -> None:
    with pytest.raises(ValidationError, match="positive area"):
        _evidence(bbox=[0.5, 0.5, 0.5, 0.5])
    with pytest.raises(ValidationError, match=r"\[0, 1\]"):
        _evidence(bbox=[1.5, 0.0, 1.0, 1.0])
    with pytest.raises(ValidationError, match="at least 4 items"):
        _evidence(bbox=[0.0, 0.0, 1.0])


def test_rejects_page_zero() -> None:
    with pytest.raises(ValidationError):
        _evidence(page=0)


def test_rejects_reversed_and_equal_offsets() -> None:
    with pytest.raises(ValidationError, match="start_offset must be less than"):
        _evidence(start_offset=10, end_offset=5)
    with pytest.raises(ValidationError, match="start_offset must be less than"):
        _evidence(start_offset=5, end_offset=5)
    with pytest.raises(ValidationError, match="both present or both absent"):
        _evidence(start_offset=1, end_offset=None)


def test_rejects_malformed_hash() -> None:
    with pytest.raises(ValidationError):
        _evidence(fragment_sha256="ABC123")
    with pytest.raises(ValidationError):
        _evidence(fragment_sha256="g" * 64)  # invalid hex character


def test_rejects_invalid_extension_key() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["extensions"] = {"BadKey": 1}
    with pytest.raises(ValidationError):
        ExtractionPackage.model_validate(data)


def test_rejects_invalid_local_id() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["items"][0]["id"] = "1starts-with-digit"
    with pytest.raises(ValidationError):
        ExtractionPackage.model_validate(data)


def test_rejects_non_utc_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Provenance(
            created_at=datetime(2026, 8, 11, 10, 0),  # naive
            adapter_name="x",
            adapter_version="1",
        )


def test_rejects_empty_whitespace_only_text() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["items"][0]["text"] = "   "
    with pytest.raises(ValidationError):
        ExtractionPackage.model_validate(data)


def test_valid_node_requires_normalization_fields() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["items"][3]["nodes"][0]["validation_status"] = "valid"
    with pytest.raises(ValidationError, match="valid node requires"):
        ExtractionPackage.model_validate(data)


def test_unvalidated_node_forbids_normalization_fields() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["items"][3]["nodes"][0]["san_candidate"] = "e4"
    with pytest.raises(ValidationError, match="unvalidated node forbids"):
        ExtractionPackage.model_validate(data)


def test_rejects_duplicate_nag_values() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["items"][3]["nodes"][0]["nags"] = [1, 1]
    with pytest.raises(ValidationError, match="NAG values must be unique"):
        ExtractionPackage.model_validate(data)


def test_rejects_dangling_diagnostic_item_ref() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["diagnostics"][0]["item_id"] = "missing"
    with pytest.raises(ValidationError, match="does not resolve"):
        ExtractionPackage.model_validate(data)


def test_rejects_dangling_diagnostic_node_ref() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["diagnostics"][0]["node_id"] = "missing-node"
    with pytest.raises(ValidationError, match="not in sequence"):
        ExtractionPackage.model_validate(data)


def test_rejects_unresolved_item_without_text_or_details() -> None:
    with pytest.raises(ValidationError, match="requires raw_text or details"):
        UnresolvedItem(
            id="u1",
            kind="unresolved",
            unresolved_type="mixed",
            reason_code="unclear",
            raw_text=None,
            details=None,
            evidence=[_evidence()],
        )


def test_fen_position_requires_six_fields() -> None:
    with pytest.raises(ValidationError, match="exactly six"):
        FenPosition(kind="fen", fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")
    with pytest.raises(ValidationError, match="exactly six"):
        PositionAnchor(kind="position", fen="incomplete")


def test_discriminator_fields_are_required_in_runtime_and_schema() -> None:
    with pytest.raises(ValidationError):
        MoveNodeAnchor.model_validate({"sequence_id": "seq1", "node_id": "n1"})
    with pytest.raises(ValidationError):
        PositionAnchor.model_validate({"fen": START_FEN})
    with pytest.raises(ValidationError):
        StartPosition.model_validate({})
    with pytest.raises(ValidationError):
        FenPosition.model_validate({"fen": START_FEN})

    definitions = ccef_schema_document()["$defs"]
    for name in ("MoveNodeAnchor", "PositionAnchor", "StartPosition", "FenPosition"):
        assert "kind" in definitions[name]["required"]


# ---------------------------------------------------------------------------
# Import purity
# ---------------------------------------------------------------------------


def test_extraction_package_imports_without_forbidden_modules() -> None:
    code = (
        "import sys; "
        "import chess_workbench.extraction.contracts; "
        "forbidden = ('chess_workbench.store', 'chess_workbench.services', "
        "'chess_workbench.api', 'chess_workbench.schemas.domain', "
        "'chess_workbench.extraction.deepseek', "
        "'chess_workbench.extraction.validation', "
        "'sqlalchemy', 'sanic', 'httpx', 'chess'); "
        "bad = [m for m in forbidden if m in sys.modules]; "
        "print('bad=', bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"forbidden modules imported: {result.stdout}{result.stderr}"


def test_source_does_not_mention_internal_concepts() -> None:
    contracts_source = (PACKAGE_ROOT / "chess_workbench" / "extraction" / "contracts.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "Course",
        "CourseModule",
        "CourseOccurrence",
        "KnowledgeNote",
        "Repertoire",
        "Exercise",
        "sqlalchemy",
        "sanic",
        "store",
    ):
        assert token not in contracts_source, f"contracts.py mentions {token!r}"


# ---------------------------------------------------------------------------
# R1 corrections: self-parent, strict scalar conversions, finite extensions
# ---------------------------------------------------------------------------


def test_rejects_self_parent() -> None:
    """A node naming itself as parent must be rejected (parent checked before
    the current id is added to the seen set)."""
    package = _valid_package()
    data = package.model_dump(mode="json")
    self_sequence = MoveSequenceItem(
        id="self-seq",
        kind="move_sequence",
        initial_position=StartPosition(kind="startpos"),
        nodes=[
            MoveNode(
                id="self",
                parent_id="self",
                sibling_order=0,
                move_text="e4",
                evidence=[_evidence()],
            )
        ],
        evidence=[_evidence()],
    )
    data["items"].append(self_sequence.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="dangling or forward parent"):
        ExtractionPackage.model_validate(data)


def test_confidence_accepts_numbers_and_rejects_strings_and_booleans() -> None:
    for value in (0, 0.5, 1):
        item = HeadingItem(
            id="h1",
            kind="heading",
            level=1,
            text="Conf",
            evidence=[_evidence()],
            confidence=value,
        )
        assert item.confidence in (0.0, 0.5, 1.0)

    for raw in ('"0.5"', "true", '"1"'):
        payload = (
            '{"id": "h1", "kind": "heading", "level": 1, "text": "Conf", '
            f'"evidence": [{{"page": 1}}], "confidence": {raw}}}'
        )
        with pytest.raises(ValidationError):
            HeadingItem.model_validate_json(payload)


def test_bbox_accepts_integer_numbers_and_rejects_tuple_strings_booleans() -> None:
    ref = _evidence(bbox=[0, 0, 1, 1])
    assert ref.bbox == [0.0, 0.0, 1.0, 1.0]

    with pytest.raises(ValidationError):
        EvidenceRef.model_validate({"page": 1, "bbox": (0.0, 0.0, 1.0, 1.0)})  # tuple
    for raw in ('["0", "0", "1", "1"]', "[true, false, true, false]"):
        with pytest.raises(ValidationError):
            EvidenceRef.model_validate_json(f'{{"page": 1, "bbox": {raw}}}')


def test_created_at_accepts_datetime_and_iso_string_only() -> None:
    # Valid: datetime instance and RFC3339 string.
    Provenance.model_validate(
        {
            "created_at": datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
            "adapter_name": "a",
            "adapter_version": "1",
        }
    )
    Provenance.model_validate(
        {
            "created_at": "2026-08-11T10:00:00Z",
            "adapter_name": "a",
            "adapter_version": "1",
        }
    )
    Provenance.model_validate(
        {
            "created_at": "2026-08-11T10:00:00.250+00:00",
            "adapter_name": "a",
            "adapter_version": "1",
        }
    )

    # Invalid: int, numeric string, date-only, boolean.
    for raw in ("0", '"0"', '"2026-08-11"', "true"):
        with pytest.raises(ValidationError):
            Provenance.model_validate_json(
                '{"created_at": ' + raw + ', "adapter_name": "a", "adapter_version": "1"}'
            )


def test_package_id_accepts_uuid_instance_and_string_only() -> None:
    package = _valid_package()
    assert isinstance(package.package_id, UUID)
    reloaded = ExtractionPackage.model_validate(package.model_dump(mode="json"))
    assert reloaded.package_id == package.package_id

    with pytest.raises(ValidationError):
        ExtractionPackage.model_validate(
            {**package.model_dump(mode="json"), "package_id": b"\x00" * 16}
        )


def test_extensions_reject_nested_non_finite_numbers() -> None:
    import copy

    package = _valid_package()
    data = package.model_dump(mode="json")
    locations = (
        ("extensions",),
        ("items", 0, "extensions"),
        ("items", 3, "nodes", 0, "extensions"),
    )
    for location in locations:
        for bad in (float("nan"), float("inf"), float("-inf")):
            mutated: Any = copy.deepcopy(data)
            target = mutated
            for key in location[:-1]:
                target = target[key]
            target[location[-1]] = {"org.example.test": {"nested": [1, bad]}}
            with pytest.raises(ValidationError, match="finite JSON numbers"):
                ExtractionPackage.model_validate(mutated)


def test_extensions_accept_ordinary_nested_json_values() -> None:
    package = _valid_package()
    data = package.model_dump(mode="json")
    data["extensions"] = {
        "org.example.test": {
            "list": [1, 2.5, "text", None, True, {"deep": [3, 4]}],
        }
    }
    reloaded = ExtractionPackage.model_validate(data)
    assert reloaded.extensions == {
        "org.example.test": {
            "list": [1, 2.5, "text", None, True, {"deep": [3, 4]}],
        }
    }


# ---------------------------------------------------------------------------
# R2 corrections: RFC3339 UTC date-time representation and Schema pattern
# ---------------------------------------------------------------------------


def test_created_at_accepts_all_utc_designator_spellings() -> None:
    for raw in (
        "2026-08-11T10:00:00Z",
        "2026-08-11t10:00:00Z",
        "2026-08-11T10:00:00z",
        "2026-08-11t10:00:00z",
        "2026-08-11T10:00:00+00:00",
        "2026-08-11T10:00:00.250Z",
        "2026-08-11t09:30:15.5+00:00",
    ):
        parsed = Provenance.model_validate(
            {"created_at": raw, "adapter_name": "a", "adapter_version": "1"}
        )
        assert parsed.created_at.utcoffset() is not None
        offset = parsed.created_at.utcoffset()
        assert offset is not None and offset.total_seconds() == 0


def test_created_at_rejects_surrounding_whitespace() -> None:
    for raw in (
        " 2026-08-11T10:00:00Z",
        "2026-08-11T10:00:00Z ",
        "\t2026-08-11T10:00:00Z",
        "2026-08-11T10:00:00+00:00\n",
    ):
        with pytest.raises(ValidationError):
            Provenance.model_validate(
                {"created_at": raw, "adapter_name": "a", "adapter_version": "1"}
            )


def test_created_at_rejects_unknown_local_offset() -> None:
    with pytest.raises(ValidationError):
        Provenance.model_validate(
            {
                "created_at": "2026-08-11T10:00:00-00:00",
                "adapter_name": "a",
                "adapter_version": "1",
            }
        )


def test_created_at_rejects_non_zero_offsets() -> None:
    for raw in ("2026-08-11T10:00:00+02:00", "2026-08-11T10:00:00-05:30"):
        with pytest.raises(ValidationError):
            Provenance.model_validate(
                {"created_at": raw, "adapter_name": "a", "adapter_version": "1"}
            )


def test_created_at_rejects_missing_timezone() -> None:
    with pytest.raises(ValidationError):
        Provenance.model_validate(
            {
                "created_at": "2026-08-11T10:00:00",
                "adapter_name": "a",
                "adapter_version": "1",
            }
        )


def test_schema_created_at_carries_utc_pattern_and_format() -> None:
    document = ccef_schema_document()
    created_at = document["$defs"]["Provenance"]["properties"]["created_at"]
    assert created_at["format"] == "date-time"
    pattern = created_at["pattern"]
    # The UTC-only restriction is exposed to schema-only consumers.
    import re as _re

    assert _re.match(pattern, "2026-08-11T10:00:00Z")
    assert _re.match(pattern, "2026-08-11t10:00:00z")
    assert _re.match(pattern, "2026-08-11T10:00:00.250+00:00")
    assert not _re.match(pattern, "2026-08-11T10:00:00-00:00")
    assert not _re.match(pattern, "2026-08-11T10:00:00+02:00")
    assert not _re.match(pattern, " 2026-08-11T10:00:00Z")


def test_schema_rejects_non_namespaced_extension_keys_at_every_location() -> None:
    document = ccef_schema_document()
    extension_maps: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            pattern_properties = value.get("patternProperties")
            if isinstance(pattern_properties, dict) and pattern_properties:
                extension_maps.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    assert len(extension_maps) == 7
    assert all(extension_map["additionalProperties"] is False for extension_map in extension_maps)
