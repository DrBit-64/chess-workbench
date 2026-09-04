"""Focused regression tests for incremental extraction candidate binding."""

from uuid import UUID

from chess_workbench.extraction.contracts import ExtractionPackageV1_1, PageRange
from chess_workbench.extraction.incremental import (
    CCEF_CONTINUATION_CONTEXT_VERSION,
    CcefContinuationContext,
    ContinuationAnchor,
    ContinuationSequence,
)
from chess_workbench.services.pdf_incremental_extraction import _bind_continuations


def test_independent_diagram_started_score_does_not_require_continuation_binding() -> None:
    package = ExtractionPackageV1_1.model_validate(
        {
            "schema_version": "chess-content-extraction/1.1",
            "package_id": "fe51f17f-e4e8-44b4-aa62-431bd19ec83a",
            "source": {
                "source_ref": "synthetic-book",
                "media_type": "application/pdf",
                "page_range": {"start_page": 3, "end_page": 4},
            },
            "items": [
                {
                    "kind": "move_sequence",
                    "id": "new-game",
                    "title": "New diagram-started game",
                    "initial_position": {
                        "kind": "fen",
                        "fen": "8/8/8/4k3/8/8/8/4K3 w - - 0 1",
                    },
                    "nodes": [
                        {
                            "id": "new-game-1",
                            "sibling_order": 0,
                            "move_text": "Kd2",
                            "evidence": [{"page": 3}],
                        }
                    ],
                    "annotations": [],
                    "reading_flow": [{"kind": "move", "node_id": "new-game-1"}],
                    "evidence": [{"page": 3}],
                }
            ],
            "provenance": {
                "created_at": "2026-09-02T00:00:00Z",
                "adapter_name": "test-adapter",
                "adapter_version": "1.1",
            },
        }
    )
    context = CcefContinuationContext(
        schema_version=CCEF_CONTINUATION_CONTEXT_VERSION,
        base_package_id=UUID("21e3025d-c31a-44a8-a116-ebc4e37e9e18"),
        base_normalized_ccef_sha256="a" * 64,
        source_ref="synthetic-book",
        base_page_range=PageRange(start_page=1, end_page=2),
        next_page_range=PageRange(start_page=3, end_page=4),
        sequences=[
            ContinuationSequence(
                sequence_id="old-game",
                title="Previous independent game",
                anchors=[
                    ContinuationAnchor(
                        id="anchor-1",
                        sequence_id="old-game",
                        after_node_id=None,
                        position_fen="8/8/8/8/4k3/8/8/4K3 w - - 0 1",
                        path_tail=[],
                    )
                ],
            )
        ],
    )

    bound = _bind_continuations(package, context)

    assert bound.model_dump(mode="json") == package.model_dump(mode="json")
