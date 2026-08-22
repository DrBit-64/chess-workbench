"""Focused CCEF 1.1 review-consumption oracles for Stage 8D-3D5."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.review.inspection import inspect_review_candidate
from chess_workbench.schemas.review import PdfReviewDocumentRead, PdfReviewPageRead

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _node(
    node_id: str,
    parent_id: str | None,
    sibling_order: int,
    move_text: str,
    page: int,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": sibling_order,
        "move_text": move_text,
        "evidence": [{"page": page}],
    }


def _package() -> ExtractionPackageV1_1:
    payload = {
        "schema_version": "chess-content-extraction/1.1",
        "package_id": str(RUN_ID),
        "source": {
            "source_ref": "synthetic-review-source",
            "media_type": "application/pdf",
            "page_range": {"start_page": 5, "end_page": 6},
        },
        "items": [
            {
                "kind": "move_sequence",
                "id": "seq1",
                "title": "Synthetic score",
                "initial_position": {"kind": "startpos"},
                "nodes": [
                    _node("n1", None, 0, "e4", 5),
                    _node("n2", "n1", 0, "e5", 6),
                    _node("n3", "n1", 1, "c5", 5),
                ],
                "annotations": [
                    {
                        "id": "a1",
                        "text": "A note displayed before the local alternative.",
                        "anchor": {
                            "kind": "move_node",
                            "node_id": "n1",
                            "relation": "after",
                        },
                        "evidence": [{"page": 5}],
                        "warnings": [
                            {
                                "code": "review_note",
                                "message": "Check this note",
                                "evidence": [{"page": 5}],
                            }
                        ],
                    },
                    {
                        "id": "a2",
                        "text": "A position-linked note.",
                        "anchor": {"kind": "position", "fen": START_FEN},
                        "evidence": [{"page": 6}],
                    },
                ],
                "reading_flow": [
                    {"kind": "move", "node_id": "n1"},
                    {"kind": "annotation", "annotation_id": "a1"},
                    {"kind": "move", "node_id": "n2"},
                    {"kind": "move", "node_id": "n3"},
                    {"kind": "annotation", "annotation_id": "a2"},
                ],
                "evidence": [{"page": 5}],
            }
        ],
        "provenance": {
            "created_at": "2026-08-20T10:00:00Z",
            "adapter_name": "synthetic-adapter",
            "adapter_version": "1.1",
        },
    }
    return normalize_chess_moves_v1_1(ExtractionPackageV1_1.model_validate(payload))


def _pages() -> list[PdfReviewPageRead]:
    return [
        PdfReviewPageRead(
            physical_page=page,
            byte_size=100 + page,
            content_sha256=str(page) * 64,
            content_url=f"/api/pdf-extractions/{RUN_ID}/review/pages/{page}",
        )
        for page in (5, 6)
    ]


def test_v1_1_inspection_counts_nodes_and_annotation_warnings() -> None:
    package = _package()
    inspection = inspect_review_candidate(package)

    assert inspection.item_count == 1
    assert inspection.move_node_count == 3
    assert [issue.issue_id for issue in inspection.issues] == ["annotation:seq1:a1:warning:0"]
    issue = inspection.issues[0]
    assert issue.scope == "annotation"
    assert issue.item_id == "seq1"
    assert issue.node_id == "n1"
    assert issue.blocking is False


def test_v1_1_review_document_round_trip_keeps_reading_flow() -> None:
    package = _package()
    document = PdfReviewDocumentRead(
        run_id=RUN_ID,
        normalized_ccef_sha256="a" * 64,
        package=package,
        inspection=inspect_review_candidate(package),
        pages=_pages(),
    )

    restored = PdfReviewDocumentRead.model_validate_json(document.model_dump_json())
    assert isinstance(restored.package, ExtractionPackageV1_1)
    sequence = restored.package.items[0]
    assert sequence.kind == "move_sequence"
    assert [entry.kind for entry in sequence.reading_flow] == [
        "move",
        "annotation",
        "move",
        "move",
        "annotation",
    ]
    assert [annotation.id for annotation in sequence.annotations] == ["a1", "a2"]
