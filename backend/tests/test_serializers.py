"""Exercise every persisted union discriminator at the public serializer boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from chess_workbench.api.contracts import _convert_to_openapi_30, _inline_local_references
from chess_workbench.api.serializers import (
    course_read,
    module_read,
    move_read,
    note_read,
    occurrence_read,
    position_read,
    source_file_read,
    source_read,
    source_span_read,
    source_version_read,
)


def _plain(**values: object) -> Any:
    return SimpleNamespace(**values)


def _mutable(**values: object) -> Any:
    now = datetime.now(UTC)
    return _plain(
        id=uuid4(),
        version=1,
        created_at=now,
        updated_at=now,
        archived_at=None,
        **values,
    )


def test_simple_orm_serializers_emit_strict_contracts() -> None:
    position_id = uuid4()
    edge_id = uuid4()
    course_id = uuid4()
    module_id = uuid4()
    assert (
        position_read(
            _plain(
                id=position_id,
                created_at=datetime.now(UTC),
                position_key="standard:v1:8/8/8/8/8/8/4K3/7k w - -",
                canonical_fen="8/8/8/8/8/8/4K3/7k w - - 0 1",
                piece_placement="8/8/8/8/8/8/4K3/7k",
                side_to_move="w",
                castling_rights="-",
                en_passant="-",
                material_signature="v1:w:K1|b:K1",
            )
        ).id
        == position_id
    )
    assert (
        move_read(
            _plain(
                id=edge_id,
                created_at=datetime.now(UTC),
                from_position_id=position_id,
                to_position_id=uuid4(),
                uci="e2e4",
                san="e4",
            )
        ).id
        == edge_id
    )
    assert (
        course_read(
            _mutable(
                title="Course",
                description="",
                category=None,
                tags=[],
                status="draft",
                mode="traditional",
            )
        ).title
        == "Course"
    )
    assert (
        module_read(
            _mutable(
                course_id=course_id,
                parent_id=None,
                title="Module",
                description="",
                sort_order=0,
            ),
            uuid4(),
        ).course_id
        == course_id
    )
    assert (
        occurrence_read(
            _mutable(
                course_id=course_id,
                module_id=module_id,
                position_id=position_id,
                parent_id=None,
                inbound_move_edge_id=None,
                full_fen="8/8/8/8/8/8/4K3/7k w - - 0 1",
                nag=None,
                sort_order=0,
                context={},
            )
        ).module_id
        == module_id
    )
    source_id = uuid4()
    assert (
        str(
            source_read(
                _mutable(
                    kind="web",
                    title="Source",
                    author=None,
                    description="",
                    external_url="https://example.test/source",
                )
            ).external_url
        )
        == "https://example.test/source"
    )
    version_id = uuid4()
    assert (
        source_version_read(
            _mutable(
                source_id=source_id,
                label="v1",
                edition=None,
                published_on=date(2026, 8, 9),
                external_url="https://example.test/version",
                extra_metadata={"language": "en"},
            )
        ).source_id
        == source_id
    )
    assert (
        source_file_read(
            _mutable(
                source_version_id=version_id,
                filename="source.pgn",
                relative_path="sources/source.pgn",
                media_type="application/x-chess-pgn",
                size_bytes=10,
                sha256="a" * 64,
            )
        ).source_version_id
        == version_id
    )


def test_span_and_note_union_serializers_cover_all_variants_and_corruption() -> None:
    version_id = uuid4()
    file_id = uuid4()
    base = dict(
        source_version_id=version_id,
        source_file_id=file_id,
        quote=None,
        ocr_text=None,
        confidence=None,
        page_number=None,
        bbox=None,
        start_value=None,
        end_value=None,
    )
    persisted = [
        _mutable(locator_kind="whole", **base),
        _mutable(
            locator_kind="page",
            **{**base, "page_number": 3, "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}},
        ),
        _mutable(locator_kind="video", **{**base, "start_value": 10, "end_value": 20}),
        _mutable(locator_kind="text", **{**base, "start_value": 1, "end_value": 9}),
    ]
    assert [source_span_read(value).locator.kind for value in persisted] == [
        "whole",
        "page",
        "video",
        "text",
    ]
    with pytest.raises(ValueError, match="unsupported persisted locator"):
        source_span_read(_mutable(locator_kind="unknown", **base))
    with pytest.raises(ValueError, match="page_number"):
        source_span_read(_mutable(locator_kind="page", **base))

    occurrence_id, position_id, move_id = uuid4(), uuid4(), uuid4()
    note_base: dict[str, object] = dict(
        occurrence_id=None,
        position_id=None,
        move_edge_id=None,
        source_note_id=None,
        note_type="general",
        markdown="note",
        citations=[],
        review_status="approved",
    )
    notes = [
        _mutable(target_kind="occurrence", **{**note_base, "occurrence_id": occurrence_id}),
        _mutable(target_kind="global_position", **{**note_base, "position_id": position_id}),
        _mutable(target_kind="global_move", **{**note_base, "move_edge_id": move_id}),
    ]
    assert [note_read(value).target.kind for value in notes] == [
        "occurrence",
        "global_position",
        "global_move",
    ]
    with pytest.raises(ValueError, match="unsupported persisted note target"):
        note_read(_mutable(target_kind="unknown", **note_base))
    with pytest.raises(ValueError, match="occurrence_id"):
        note_read(_mutable(target_kind="occurrence", **note_base))


def test_openapi_conversion_handles_recursive_and_multi_nullable_shapes() -> None:
    recursive = {"$ref": "#/$defs/Node"}
    with pytest.raises(ValueError, match="recursive OpenAPI schema"):
        _inline_local_references(
            recursive,
            {"Node": {"items": [{"$ref": "#/$defs/Node"}]}},
            frozenset(),
        )

    schema: dict[str, object] = {
        "const": "fixed",
        "anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}],
        "items": [{"type": "null"}],
    }
    _convert_to_openapi_30(schema)
    assert schema["enum"] == ["fixed"]
    assert schema["nullable"] is True
    assert schema["anyOf"] == [{"type": "string"}, {"type": "integer"}]
    assert schema["items"] == [{"enum": [None], "nullable": True}]
