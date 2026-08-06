from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from chess_workbench.api.contracts import openapi_schema
from chess_workbench.schemas.domain import (
    CourseCreate,
    CourseModuleCreate,
    CourseModuleRead,
    CourseModuleUpdate,
    CourseRead,
    CourseUpdate,
    ErrorResponse,
    GlobalMoveNoteTarget,
    GlobalPositionNoteTarget,
    KnowledgeNoteCreate,
    KnowledgeNoteRead,
    KnowledgeNoteUpdate,
    MoveCreate,
    MoveRead,
    NormalizedBoundingBox,
    OccurrenceMoveCreate,
    OccurrenceNoteTarget,
    OccurrenceRead,
    OccurrenceUpdate,
    PageSpan,
    PositionCreate,
    PositionRead,
    RootOccurrenceCreate,
    SourceCreate,
    SourceFileCreate,
    SourceFileRead,
    SourceFileUpdate,
    SourceRead,
    SourceSpanCreate,
    SourceSpanRead,
    SourceSpanUpdate,
    SourceUpdate,
    SourceVersionCreate,
    SourceVersionRead,
    SourceVersionUpdate,
    TextSpan,
    VideoSpan,
    WholeSpan,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 6, 2, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
ID1 = UUID("00000000-0000-4000-8000-000000000001")
ID2 = UUID("00000000-0000-4000-8000-000000000002")
ID3 = UUID("00000000-0000-4000-8000-000000000003")
ID4 = UUID("00000000-0000-4000-8000-000000000004")


def lifecycle(identifier: UUID = ID1) -> dict[str, object]:
    return {
        "id": identifier,
        "version": 1,
        "created_at": NOW,
        "updated_at": LATER,
        "archived_at": None,
    }


def immutable(identifier: UUID = ID1) -> dict[str, object]:
    return {"id": identifier, "created_at": NOW}


def test_position_and_move_contracts_keep_derived_fields_server_owned() -> None:
    position = PositionCreate(fen=" 8/8/8/8/8/8/4K3/7k w - - 73 42 ")
    assert position.fen == "8/8/8/8/8/8/4K3/7k w - - 73 42"

    position_read = PositionRead.model_validate(
        {
            **immutable(),
            "position_key": "v1:example",
            "canonical_fen": "8/8/8/8/8/8/4K3/7k w - - 0 1",
            "piece_placement": "8/8/8/8/8/8/4K3/7k",
            "side_to_move": "w",
            "castling_rights": "-",
            "en_passant": "-",
            "material_signature": "v1:w:K1Q0R0B0N0P0|b:K1Q0R0B0N0P0",
        }
    )
    assert position_read.side_to_move == "w"

    move = MoveCreate(from_position_id=ID1, uci="e2e4")
    assert move.uci == "e2e4"
    move_read = MoveRead.model_validate(
        {
            **immutable(ID2),
            "from_position_id": ID1,
            "to_position_id": ID3,
            "uci": "e7e8q",
            "san": "e8=Q+",
        }
    )
    assert move_read.to_position_id == ID3

    with pytest.raises(ValidationError):
        PositionCreate(fen="valid-looking", canonical_fen="client-owned")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        MoveCreate(from_position_id=ID1, uci="e2e9")


def test_course_module_and_occurrence_contracts_preserve_path_context() -> None:
    course = CourseCreate(
        title="  Sicilian  ", description="Lines", category="Opening", tags=["Black", "Main"]
    )
    assert course.title == "Sicilian"
    assert course.status == "draft"
    assert CourseRead.model_validate({**lifecycle(), **course.model_dump()}).tags == [
        "Black",
        "Main",
    ]

    module = CourseModuleCreate(
        course_id=ID1,
        parent_id=None,
        title="Najdorf",
        start_fen="start fen",
        sort_order=0,
    )
    module_read = CourseModuleRead.model_validate(
        {
            **lifecycle(ID3),
            "course_id": module.course_id,
            "parent_id": module.parent_id,
            "title": module.title,
            "description": module.description,
            "start_occurrence_id": ID2,
            "sort_order": module.sort_order,
        }
    )
    assert module_read.start_occurrence_id == ID2

    root = RootOccurrenceCreate(
        course_id=ID1,
        module_id=ID3,
        fen="start fen",
        context={"role": "root"},
    )
    child = OccurrenceMoveCreate(
        parent_occurrence_id=ID2,
        uci="e2e4",
        nag=1,
        sort_order=2,
    )
    assert root.kind == "root"
    assert child.kind == "move"
    occurrence_read = OccurrenceRead.model_validate(
        {
            **lifecycle(ID4),
            "course_id": ID1,
            "module_id": ID3,
            "position_id": ID4,
            "parent_id": ID2,
            "inbound_move_edge_id": ID3,
            "full_fen": "child fen",
            "nag": child.nag,
            "sort_order": child.sort_order,
            "context": child.context,
        }
    )
    assert occurrence_read.nag == 1

    assert CourseUpdate(expected_version=2, title="Updated").title == "Updated"
    assert CourseModuleUpdate(expected_version=1, parent_id=None).model_fields_set == {
        "expected_version",
        "parent_id",
    }
    assert OccurrenceUpdate(expected_version=1, nag=None).model_fields_set == {
        "expected_version",
        "nag",
    }

    with pytest.raises(ValidationError):
        CourseCreate(title="Duplicate tags", tags=["same", "same"])
    with pytest.raises(ValidationError):
        OccurrenceRead.model_validate(
            {
                **lifecycle(ID4),
                "course_id": ID1,
                "position_id": ID4,
                "parent_id": ID2,
                "inbound_move_edge_id": None,
                "full_fen": "fen",
                "sort_order": 0,
                "context": {},
            }
        )


def test_source_is_split_into_work_version_and_immutable_file() -> None:
    source = SourceCreate.model_validate(
        {
            "kind": "book",
            "title": "My System",
            "author": "Aron Nimzowitsch",
            "external_url": "https://example.test/work",
        }
    )
    assert SourceRead.model_validate({**lifecycle(), **source.model_dump()}).kind == "book"
    assert SourceUpdate(expected_version=1, author=None).author is None

    version = SourceVersionCreate(
        source_id=ID1,
        label="2026 edition",
        published_on=date(2026, 8, 6),
        metadata={"language": "en"},
    )
    assert (
        SourceVersionRead.model_validate({**lifecycle(ID2), **version.model_dump()}).metadata[
            "language"
        ]
        == "en"
    )
    assert SourceVersionUpdate(expected_version=1, edition="second").edition == "second"

    source_file = SourceFileCreate(
        source_version_id=ID2,
        filename="book.pdf",
        relative_path="sources/ab/book.pdf",
        media_type="application/pdf",
        size_bytes=1024,
        sha256="a" * 64,
    )
    assert (
        SourceFileRead.model_validate({**lifecycle(ID3), **source_file.model_dump()}).sha256
        == "a" * 64
    )
    assert SourceFileUpdate(expected_version=1, archived=True).archived is True

    for unsafe_path in ("/etc/passwd", "../secret.pdf", "sources\\secret.pdf"):
        with pytest.raises(ValidationError):
            SourceFileCreate(
                source_version_id=ID2,
                filename="book.pdf",
                relative_path=unsafe_path,
                media_type="application/pdf",
                size_bytes=1,
                sha256="b" * 64,
            )


def test_source_span_locator_is_a_strict_discriminated_union() -> None:
    bbox = NormalizedBoundingBox(x0=0.1, y0=0.2, x1=0.8, y1=0.9)
    locators: list[WholeSpan | PageSpan | VideoSpan | TextSpan] = [
        WholeSpan(),
        PageSpan(page_number=12, bbox=bbox),
        VideoSpan(start_ms=1_000, end_ms=2_500),
        TextSpan(start_offset=3, end_offset=9),
    ]
    for locator in locators:
        span = SourceSpanCreate(
            source_version_id=ID1,
            source_file_id=ID2,
            locator=locator,
            quote="source quote",
            confidence=0.9,
        )
        read = SourceSpanRead.model_validate({**lifecycle(ID3), **span.model_dump()})
        assert read.locator.kind == locator.kind

    updated = SourceSpanUpdate.model_validate(
        {
            "expected_version": 1,
            "locator": {"kind": "video", "start_ms": 50, "end_ms": 60},
        }
    )
    assert updated.locator is not None and updated.locator.kind == "video"

    invalid_locators = [
        {"kind": "page", "page_number": 0},
        {"kind": "video", "start_ms": 10, "end_ms": 10},
        {"kind": "text", "start_offset": 4, "end_offset": 2},
        {"kind": "page", "page_number": 1, "start_ms": 0},
    ]
    for invalid_locator in invalid_locators:
        with pytest.raises(ValidationError):
            SourceSpanCreate.model_validate({"source_version_id": ID1, "locator": invalid_locator})
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(x0=0.8, y0=0, x1=0.2, y1=1)


def test_notes_are_local_by_default_and_global_only_when_explicit() -> None:
    local = KnowledgeNoteCreate(occurrence_id=ID1, markdown="Local explanation")
    assert local.target is None
    assert local.review_status == "approved"

    global_position = KnowledgeNoteCreate(
        target=GlobalPositionNoteTarget(position_id=ID2),
        markdown="Deliberately global",
        source_span_ids=[ID3, ID4],
    )
    global_move = KnowledgeNoteCreate(
        target=GlobalMoveNoteTarget(move_edge_id=ID3),
        markdown="Global move note",
    )
    assert global_position.target is not None
    assert global_move.target is not None

    note_read = KnowledgeNoteRead.model_validate(
        {
            **lifecycle(ID4),
            "target": OccurrenceNoteTarget(occurrence_id=ID1),
            "note_type": "explanation",
            "markdown": "Read contract",
            "source_span_ids": [ID2],
            "review_status": "approved",
        }
    )
    assert note_read.target.kind == "occurrence"
    assert KnowledgeNoteUpdate(expected_version=1, markdown="Revision").markdown == "Revision"

    for invalid in (
        {"markdown": "missing scope"},
        {
            "occurrence_id": ID1,
            "target": {"kind": "global_position", "position_id": ID2},
            "markdown": "both",
        },
        {"occurrence_id": ID1, "markdown": "duplicate", "source_span_ids": [ID2, ID2]},
    ):
        with pytest.raises(ValidationError):
            KnowledgeNoteCreate.model_validate(invalid)


def test_updates_errors_and_timestamps_have_stable_shapes() -> None:
    updates = (
        CourseUpdate,
        CourseModuleUpdate,
        SourceUpdate,
        SourceVersionUpdate,
        SourceSpanUpdate,
    )
    for update in updates:
        with pytest.raises(ValidationError):
            update(expected_version=1)
        with pytest.raises(ValidationError):
            update(expected_version=0, archived=True)

    error = ErrorResponse(
        code="stale_version",
        message="Expected version does not match",
        details={"expected": 2, "actual": 3},
    )
    assert error.model_dump(mode="json") == {
        "code": "stale_version",
        "message": "Expected version does not match",
        "details": {"expected": 2, "actual": 3},
    }

    with pytest.raises(ValidationError):
        ErrorResponse(code="made_up", message="bad")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ErrorResponse(code="not_found", message="missing", status=404)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        CourseRead.model_validate(
            {
                **lifecycle(),
                "updated_at": NOW - timedelta(seconds=1),
                "title": "Course",
                "description": "",
                "tags": [],
                "status": "draft",
            }
        )
    with pytest.raises(ValidationError):
        CourseRead.model_validate(
            {
                **lifecycle(),
                "created_at": datetime(2026, 8, 6, 2, 0),
                "title": "Course",
                "description": "",
                "tags": [],
                "status": "draft",
            }
        )


def test_nested_contract_schema_is_standalone_openapi_30() -> None:
    schema = openapi_schema(KnowledgeNoteRead)
    rendered = str(schema)

    assert "$defs" not in rendered
    assert "#/$defs" not in rendered
    assert "'const'" not in rendered
    assert "'enum': ['occurrence']" in rendered
