from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.coverage import (
    CCEF_COVERAGE_SUPPLEMENT_SCHEMA,
    CcefCoverageError,
    apply_ccef_coverage_supplement,
    inspect_ccef_move_coverage,
)
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.provider import StructuredGenerationResponse
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1

PACKAGE_ID = UUID("11111111-1111-4111-8111-111111111111")


def _fragment(order: int, text: str) -> PromptEvidenceFragment:
    box = NormalizedBox(x0=0.1, y0=0.1 + order * 0.1, x1=0.9, y1=0.15 + order * 0.1)
    digest = source_fragment_sha256(1, box, text, "embedded_text", "test", "1")
    return PromptEvidenceFragment(
        order=order,
        fragment=SourceEvidenceFragment(
            physical_page=1,
            box=box,
            text=text,
            origin="embedded_text",
            confidence=None,
            engine_name="test",
            engine_version="1",
            fragment_sha256=digest,
        ),
    )


def _fixture() -> tuple[ExtractionPackageV1_1, CcefPromptContext]:
    fragments = [
        _fragment(0, "1.e4 e5"),
        _fragment(1, "The plan is 2.Nf3."),
        _fragment(2, "A playable alternative is (1...c5 2.Nf3 d6)."),
    ]
    evidence = {
        "page": 1,
        "fragment_sha256": fragments[0].fragment.fragment_sha256,
    }
    package = ExtractionPackageV1_1.model_validate(
        {
            "schema_version": "chess-content-extraction/1.1",
            "package_id": str(PACKAGE_ID),
            "source": {
                "source_ref": "fixture.pdf",
                "media_type": "application/pdf",
                "language": "en",
                "page_range": {"start_page": 1, "end_page": 1},
            },
            "items": [
                {
                    "id": "sequence-1",
                    "kind": "move_sequence",
                    "title": "Example",
                    "initial_position": {"kind": "startpos"},
                    "nodes": [
                        {
                            "id": "n1",
                            "parent_id": None,
                            "sibling_order": 0,
                            "move_text": "1.e4",
                            "move_number": 1,
                            "side_to_move": "w",
                            "evidence": [evidence],
                        },
                        {
                            "id": "n2",
                            "parent_id": "n1",
                            "sibling_order": 0,
                            "move_text": "1...e5",
                            "move_number": 1,
                            "side_to_move": "b",
                            "evidence": [evidence],
                        },
                    ],
                    "annotations": [],
                    "reading_flow": [
                        {"kind": "move", "node_id": "n1"},
                        {"kind": "move", "node_id": "n2"},
                    ],
                    "evidence": [evidence],
                }
            ],
            "diagnostics": [],
            "provenance": {
                "created_at": "2026-01-01T00:00:00Z",
                "adapter_name": "chess-workbench-ccef-prompt",
                "adapter_version": "1.1",
            },
            "extensions": {},
        }
    )
    context = CcefPromptContext(
        package_id=PACKAGE_ID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="fixture.pdf",
        media_type="application/pdf",
        language="en",
        first_page=1,
        last_page=1,
        pages=[PromptEvidencePage(physical_page=1, fragments=fragments)],
        max_output_tokens=128_000,
        max_prompt_chars=2_000_000,
    )
    return package, context


def _response(content: object) -> StructuredGenerationResponse:
    return StructuredGenerationResponse(
        content=json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        provider="test",
        model="test",
        finish_reason="stop",
    )


def test_coverage_finds_numbered_parenthetical_line_but_ignores_single_prose_plan() -> None:
    package, context = _fixture()

    report = inspect_ccef_move_coverage(package, context)

    assert len(report.gaps) == 1
    assert [move.move_text for move in report.gaps[0].moves] == ["c5", "Nf3", "d6"]
    assert report.gaps[0].candidate_sequence_ids == ["sequence-1"]
    assert "The plan" not in report.gaps[0].source_text


def test_additive_supplement_fills_gap_without_changing_existing_content() -> None:
    package, context = _fixture()
    authority = normalize_chess_moves_v1_1(package)
    report = inspect_ccef_move_coverage(authority, context)
    original = _response(package.model_dump(mode="json"))
    supplement = _response(
        {
            "supplement_schema": CCEF_COVERAGE_SUPPLEMENT_SCHEMA,
            "base_response_sha256": hashlib.sha256(original.content.encode()).hexdigest(),
            "resolves": [report.gaps[0].gap_id],
            "additions": [
                {
                    "addition_id": "addition-1",
                    "resolves": [report.gaps[0].gap_id],
                    "sequence_id": "sequence-1",
                    "parent_node_id": "wrong-but-advisory",
                    "insert_after_flow_id": "n2",
                    "moves": ["1...c5", "2.Nf3", "2...d6"],
                }
            ],
        }
    )

    updated_response = apply_ccef_coverage_supplement(
        original, supplement, context, report, authority
    )
    updated = ExtractionPackageV1_1.model_validate_json(updated_response.content)

    assert updated.items[0].nodes[:2] == package.items[0].nodes
    assert inspect_ccef_move_coverage(updated, context).gaps == []


def test_supplement_rejects_line_that_has_no_legal_attachment() -> None:
    package, context = _fixture()
    authority = normalize_chess_moves_v1_1(package)
    report = inspect_ccef_move_coverage(authority, context)
    original = _response(package.model_dump(mode="json"))
    supplement = _response(
        {
            "supplement_schema": CCEF_COVERAGE_SUPPLEMENT_SCHEMA,
            "base_response_sha256": hashlib.sha256(original.content.encode()).hexdigest(),
            "resolves": [report.gaps[0].gap_id],
            "additions": [
                {
                    "addition_id": "addition-1",
                    "resolves": [report.gaps[0].gap_id],
                    "sequence_id": "sequence-1",
                    "parent_node_id": None,
                    "insert_after_flow_id": "n2",
                    "moves": ["1...c5", "2.Ke3", "2...d6"],
                }
            ],
        }
    )

    with pytest.raises(CcefCoverageError, match="unique legal position"):
        apply_ccef_coverage_supplement(original, supplement, context, report, authority)
