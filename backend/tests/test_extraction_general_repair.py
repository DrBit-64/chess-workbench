from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.general_repair import (
    CcefRepairError,
    apply_ccef_repair,
    apply_deterministic_ccef_repairs,
    build_ccef_repair_request,
    ccef_repair_diagnostics,
)
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.provider import StructuredGenerationResponse, TokenUsage

PACKAGE_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_AT = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _context() -> CcefPromptContext:
    box = NormalizedBox(x0=0.1, y0=0.2, x1=0.9, y1=0.3)
    text = "1. e4 e5"
    fragment = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=text,
        origin="embedded_text",
        confidence=None,
        engine_name="pdfium",
        engine_version="test",
        fragment_sha256=source_fragment_sha256(1, box, text, "embedded_text", "pdfium", "test"),
    )
    return CcefPromptContext(
        package_id=PACKAGE_ID,
        created_at=CREATED_AT,
        source_ref="source:synthetic",
        media_type="application/pdf",
        language="en",
        first_page=1,
        last_page=1,
        pages=[
            PromptEvidencePage(
                physical_page=1,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
            )
        ],
        max_output_tokens=128_000,
        max_prompt_chars=2_000_000,
    )


def _package(*, extra_node_field: bool = False) -> dict[str, Any]:
    context = _context()
    digest = context.pages[0].fragments[0].fragment.fragment_sha256
    first: dict[str, Any] = {
        "id": "n1",
        "parent_id": None,
        "sibling_order": 0,
        "move_text": "e4",
        "move_number": 1,
        "side_to_move": "w",
        "evidence": [{"page": 1, "fragment_sha256": digest}],
    }
    if extra_node_field:
        first["kind"] = "move"
    return {
        "schema_version": "chess-content-extraction/1.1",
        "package_id": str(PACKAGE_ID),
        "source": {
            "source_ref": "source:synthetic",
            "media_type": "application/pdf",
            "language": "en",
            "page_range": {"start_page": 1, "end_page": 1},
        },
        "items": [
            {
                "kind": "move_sequence",
                "id": "seq1",
                "evidence": [{"page": 1, "fragment_sha256": digest}],
                "initial_position": {"kind": "startpos"},
                "nodes": [
                    first,
                    {
                        "id": "n2",
                        "parent_id": "n1",
                        "sibling_order": 0 if extra_node_field else 1,
                        "move_text": "e5",
                        "move_number": 1,
                        "side_to_move": "b",
                        "evidence": [{"page": 1, "fragment_sha256": digest}],
                    },
                ],
                "annotations": [],
                "reading_flow": [
                    {"kind": "move", "node_id": "n1"},
                    {"kind": "move", "node_id": "n2"},
                ],
            }
        ],
        "diagnostics": [],
        "provenance": {
            "created_at": "2026-08-24T12:00:00.000000Z",
            "adapter_name": "chess-workbench-ccef-prompt",
            "adapter_version": "1.1",
            "provider": None,
            "model": None,
            "request_sha256": None,
            "response_sha256": None,
        },
        "extensions": {},
    }


def _response(package: dict[str, Any]) -> StructuredGenerationResponse:
    return StructuredGenerationResponse(
        content=json.dumps(package, ensure_ascii=False),
        provider="scripted",
        model="fixture",
        finish_reason="stop",
        usage=TokenUsage(),
    )


def _repair(
    original: StructuredGenerationResponse,
    operations: list[dict[str, Any]],
) -> StructuredGenerationResponse:
    diagnostics = ccef_repair_diagnostics(original)
    return StructuredGenerationResponse(
        content=json.dumps(
            {
                "repair_schema": "chess-workbench/ccef-repair/2.0",
                "base_response_sha256": hashlib.sha256(
                    original.content.encode("utf-8")
                ).hexdigest(),
                "resolves": [diagnostic.diagnostic_id for diagnostic in diagnostics],
                "operations": operations,
            }
        ),
        provider="scripted",
        model="fixture",
        finish_reason="stop",
        usage=TokenUsage(),
    )


def test_general_diagnostics_and_patch_fix_a_sibling_gap() -> None:
    original = _response(_package())
    diagnostics = ccef_repair_diagnostics(original)
    assert any(
        diagnostic.code == "non_contiguous_sibling_order"
        and diagnostic.path == "/items/0/nodes/1/sibling_order"
        for diagnostic in diagnostics
    )
    request = build_ccef_repair_request(original, _context())
    assert request.response_schema_name == "chess_workbench_ccef_repair_v2"

    repaired = apply_ccef_repair(
        original,
        _repair(
            original,
            [
                {
                    "op": "replace",
                    "path": "/items/0/nodes/1/sibling_order",
                    "value": 0,
                }
            ],
        ),
        _context(),
    )
    package = ExtractionPackageV1_1.model_validate_json(repaired.content)
    assert package.items[0].nodes[1].sibling_order == 0  # type: ignore[union-attr]
    assert json.loads(original.content)["items"][0]["nodes"][1]["sibling_order"] == 1


def test_general_patch_can_remove_a_non_topology_schema_field() -> None:
    original = _response(_package(extra_node_field=True))
    diagnostics = ccef_repair_diagnostics(original)
    extra = next(diagnostic for diagnostic in diagnostics if "extra_forbidden" in diagnostic.code)
    assert extra.path == "/items/0/nodes/0/kind"
    assert extra.item_index == 0
    assert extra.item_id == "seq1"
    assert extra.node_id == "n1"

    request = build_ccef_repair_request(original, _context())
    case = json.loads(request.messages[1].content)
    excerpt = case["affected_items"][0]
    values = excerpt["values_by_json_pointer"]
    assert values["/items/0/nodes/0"]["id"] == "n1"
    assert "/items/0/nodes/1" not in values
    assert values["/items/0/reading_flow/0"] == {"kind": "move", "node_id": "n1"}
    assert all("entry" not in value for value in values.values() if isinstance(value, dict))

    repaired = apply_ccef_repair(
        original,
        _repair(
            original,
            [{"op": "remove", "path": "/items/0/nodes/0/kind"}],
        ),
        _context(),
    )
    ExtractionPackageV1_1.model_validate_json(repaired.content)


def test_deterministic_repair_deduplicates_nags_without_model_judgment() -> None:
    package = _package(extra_node_field=True)
    del package["items"][0]["nodes"][0]["kind"]
    package["items"][0]["nodes"][0]["nags"] = [1, 1, 3, 1]
    original = _response(package)

    repaired, operations = apply_deterministic_ccef_repairs(original)

    assert operations == (
        {
            "rule": "deduplicate_nags",
            "path": "/items/0/nodes/0/nags",
            "removed_count": 2,
        },
    )
    parsed = ExtractionPackageV1_1.model_validate_json(repaired.content)
    assert parsed.items[0].nodes[0].nags == [1, 3]  # type: ignore[union-attr]
    assert json.loads(original.content)["items"][0]["nodes"][0]["nags"] == [1, 1, 3, 1]


def test_deterministic_repair_normalizes_the_evidence_page_alias() -> None:
    package = _package(extra_node_field=True)
    del package["items"][0]["nodes"][0]["kind"]
    sequence = package["items"][0]
    references = [sequence["evidence"][0]] + [node["evidence"][0] for node in sequence["nodes"]]
    for reference in references:
        reference["physical_page"] = reference.pop("page")
    original = _response(package)

    repaired, operations = apply_deterministic_ccef_repairs(original)

    assert [operation["rule"] for operation in operations] == [
        "canonicalize_evidence_page_alias",
        "canonicalize_evidence_page_alias",
        "canonicalize_evidence_page_alias",
    ]
    parsed = ExtractionPackageV1_1.model_validate_json(repaired.content)
    parsed_sequence = parsed.items[0]
    assert parsed_sequence.evidence[0].page == 1  # type: ignore[union-attr]
    assert all(node.evidence[0].page == 1 for node in parsed_sequence.nodes)  # type: ignore[union-attr]
    repaired_payload = json.loads(repaired.content)
    repaired_references = [repaired_payload["items"][0]["evidence"][0]] + [
        node["evidence"][0] for node in repaired_payload["items"][0]["nodes"]
    ]
    assert all("physical_page" not in reference for reference in repaired_references)
    original_payload = json.loads(original.content)
    assert all(
        "physical_page" in reference
        for reference in [
            original_payload["items"][0]["evidence"][0],
            *[node["evidence"][0] for node in original_payload["items"][0]["nodes"]],
        ]
    )


def test_deterministic_repair_refuses_conflicting_evidence_page_aliases() -> None:
    package = _package(extra_node_field=True)
    del package["items"][0]["nodes"][0]["kind"]
    reference = package["items"][0]["evidence"][0]
    reference["physical_page"] = 2
    original = _response(package)

    repaired, operations = apply_deterministic_ccef_repairs(original)

    assert repaired is original
    assert operations == ()
    with pytest.raises(ValidationError):
        ExtractionPackageV1_1.model_validate_json(repaired.content)


def test_deterministic_repair_aligns_an_exact_reading_flow_projection() -> None:
    package = _package(extra_node_field=True)
    del package["items"][0]["nodes"][0]["kind"]
    sequence = package["items"][0]
    sequence["nodes"].append(
        {
            "id": "n3",
            "parent_id": "n1",
            "sibling_order": 1,
            "move_text": "c5",
            "move_number": 1,
            "side_to_move": "b",
            "evidence": sequence["nodes"][0]["evidence"],
        }
    )
    sequence["reading_flow"] = [
        {"kind": "move", "node_id": "n1"},
        {"kind": "move", "node_id": "n3"},
        {"kind": "move", "node_id": "n2"},
    ]
    original = _response(package)

    repaired, operations = apply_deterministic_ccef_repairs(original)

    assert operations == (
        {
            "rule": "align_nodes_to_reading_flow",
            "path": "/items/0/nodes",
            "moved_count": 2,
        },
    )
    parsed = ExtractionPackageV1_1.model_validate_json(repaired.content)
    parsed_sequence = parsed.items[0]
    assert [node.id for node in parsed_sequence.nodes] == ["n1", "n3", "n2"]  # type: ignore[union-attr]
    assert [node["id"] for node in json.loads(original.content)["items"][0]["nodes"]] == [
        "n1",
        "n2",
        "n3",
    ]


def test_deterministic_repair_refuses_a_non_topological_flow_projection() -> None:
    package = _package(extra_node_field=True)
    del package["items"][0]["nodes"][0]["kind"]
    package["items"][0]["reading_flow"] = [
        {"kind": "move", "node_id": "n2"},
        {"kind": "move", "node_id": "n1"},
    ]
    original = _response(package)

    repaired, operations = apply_deterministic_ccef_repairs(original)

    assert repaired is original
    assert operations == ()


def test_model_patch_cannot_replace_a_reading_flow_entry() -> None:
    original = _response(_package())
    with pytest.raises(CcefRepairError, match="may not resize core content"):
        apply_ccef_repair(
            original,
            _repair(
                original,
                [
                    {
                        "op": "replace",
                        "path": "/items/0/reading_flow/0",
                        "value": {"kind": "move", "node_id": "n2"},
                    }
                ],
            ),
            _context(),
        )


def test_general_patch_cannot_delete_content_or_invent_evidence() -> None:
    original = _response(_package())
    with pytest.raises(CcefRepairError, match="may not resize core content"):
        apply_ccef_repair(
            original,
            _repair(original, [{"op": "remove", "path": "/items/0/nodes/1"}]),
            _context(),
        )
    with pytest.raises(CcefRepairError, match="untrusted evidence"):
        apply_ccef_repair(
            original,
            _repair(
                original,
                [
                    {
                        "op": "replace",
                        "path": "/items/0/nodes/1/evidence/0/fragment_sha256",
                        "value": "f" * 64,
                    }
                ],
            ),
            _context(),
        )
