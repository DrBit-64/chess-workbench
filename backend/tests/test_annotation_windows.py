from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from test_extraction_coverage import _fixture, _fragment, _response

from chess_workbench.extraction.annotation_windows import locate_annotation_windows
from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.general_repair import CcefRepairError
from chess_workbench.extraction.prompting import CcefPromptContext
from chess_workbench.extraction.provider import (
    ScriptedStructuredGenerationProvider,
    StructuredGenerationResponse,
)
from chess_workbench.extraction.recovery import recover_ccef_response
from chess_workbench.extraction.structural_recovery import (
    STRUCTURAL_SCHEMA,
    apply_structural_supplement,
    build_structural_request,
    inspect_structural_gaps,
)


def _window_fixture() -> tuple[dict[str, Any], CcefPromptContext]:
    package, context = _fixture()
    fragments = [
        _fragment(i, text)
        for i, text in enumerate(
            ["1.e4", "White occupies the centre.", "1...e5", "Unrelated later commentary."]
        )
    ]
    page = context.pages[0].model_copy(update={"fragments": fragments})
    context = context.model_copy(update={"pages": [page]})
    data = package.model_dump(mode="json")
    sequence = data["items"][0]
    for node, fragment in zip(sequence["nodes"], (fragments[0], fragments[2]), strict=True):
        node["evidence"] = [{"page": 1, "fragment_sha256": fragment.fragment.fragment_sha256}]
    sequence["reading_flow"].insert(1, {"kind": "annotation", "annotation_id": "missing-note"})
    return data, context


async def test_single_source_interval_recovers_without_provider_call() -> None:
    data, context = _window_fixture()
    original = _response(data)
    provider = ScriptedStructuredGenerationProvider([])

    async def record(
        response: StructuredGenerationResponse,
        code: str,
        message: str,
        diagnostics: tuple[str, ...],
    ) -> None:
        pass

    result = await recover_ccef_response(
        original,
        context,
        validate=lambda response: ExtractionPackageV1_1.model_validate_json(response.content),
        normalized_package=lambda value: value,
        repair_provider=provider,
        coverage_provider=provider,
        record_failure=record,
    )
    assert not provider.calls
    accepted = json.loads(result.accepted_response.content)["items"][0]
    assert accepted["annotations"][0]["text"] == "White occupies the centre."
    assert accepted["nodes"] == data["items"][0]["nodes"]
    assert accepted["reading_flow"] == data["items"][0]["reading_flow"]
    assert isinstance(result.provider_document, dict)
    assert result.provider_document["supplement_response"]["provider"] == "local"
    assert result.provider_document["localization"]["deterministic_annotations"]


async def test_local_and_model_annotations_merge_without_resending_local_prose() -> None:
    data, context = _window_fixture()
    fragments = [
        *context.pages[0].fragments[:3],
        _fragment(3, "The queen waits. The bishop develops."),
        _fragment(4, "2.Nf3"),
    ]
    context = context.model_copy(
        update={"pages": [context.pages[0].model_copy(update={"fragments": fragments})]}
    )
    sequence = data["items"][0]
    sequence["nodes"].append(
        {
            "id": "n3",
            "parent_id": "n2",
            "sibling_order": 0,
            "move_text": "2.Nf3",
            "move_number": 2,
            "side_to_move": "w",
            "evidence": [{"page": 1, "fragment_sha256": fragments[4].fragment.fragment_sha256}],
        }
    )
    sequence["reading_flow"].extend(
        [
            {"kind": "annotation", "annotation_id": "second-note"},
            {"kind": "annotation", "annotation_id": "third-note"},
            {"kind": "move", "node_id": "n3"},
        ]
    )
    original = _response(data)
    supplement = _response(
        {
            "supplement_schema": STRUCTURAL_SCHEMA,
            "base_response_sha256": hashlib.sha256(original.content.encode()).hexdigest(),
            "annotations": [
                {
                    "sequence_id": "sequence-1",
                    "annotation_id": identity,
                    "spans": [{"fragment_id": "p1-f3", "excerpt": text}],
                }
                for identity, text in [
                    ("second-note", "The queen waits."),
                    ("third-note", "The bishop develops."),
                ]
            ],
            "flow_insertions": [],
        }
    )
    provider = ScriptedStructuredGenerationProvider([supplement])

    async def record(
        response: StructuredGenerationResponse,
        code: str,
        message: str,
        diagnostics: tuple[str, ...],
    ) -> None:
        pass

    result = await recover_ccef_response(
        original,
        context,
        validate=lambda response: ExtractionPackageV1_1.model_validate_json(response.content),
        normalized_package=lambda value: value,
        repair_provider=provider,
        coverage_provider=provider,
        record_failure=record,
    )
    assert len(provider.calls) == 1
    case = json.loads(provider.calls[0].messages[-1].content)
    assert case["sequences"][0]["missing_annotation_ids"] == ["second-note", "third-note"]
    assert "p1-f1" not in {f["fragment_id"] for f in case["source_fragments"]}
    accepted = json.loads(result.accepted_response.content)["items"][0]
    assert [a["text"] for a in accepted["annotations"]] == [
        "White occupies the centre.",
        "The queen waits.",
        "The bishop develops.",
    ]
    assert accepted["nodes"] == sequence["nodes"]
    assert accepted["reading_flow"] == sequence["reading_flow"]


@pytest.mark.parametrize("ambiguity", ["multiple_notes", "branch_transition", "source_jump"])
def test_ambiguous_intervals_remain_local_model_choices(ambiguity: str) -> None:
    data, context = _window_fixture()
    sequence = data["items"][0]
    if ambiguity == "multiple_notes":
        sequence["reading_flow"].insert(2, {"kind": "annotation", "annotation_id": "second-note"})
    elif ambiguity == "branch_transition":
        sequence["nodes"][1]["parent_id"] = None
    else:
        sequence["nodes"][0]["evidence"], sequence["nodes"][1]["evidence"] = (
            sequence["nodes"][1]["evidence"],
            sequence["nodes"][0]["evidence"],
        )
    windows = locate_annotation_windows(_response(data), context)
    assert all(not window.deterministic_fragment_ids for window in windows)
    assert all(window.candidate_fragment_ids for window in windows)


def test_prompt_and_application_enforce_each_annotations_local_window() -> None:
    data, context = _window_fixture()
    data["items"][0]["reading_flow"].insert(
        2, {"kind": "annotation", "annotation_id": "second-note"}
    )
    original = _response(data)
    gaps = inspect_structural_gaps(original)
    request = build_structural_request(original, context, gaps)
    case = json.loads(request.messages[-1].content)
    assert {f["fragment_id"] for f in case["source_fragments"]} == {"p1-f0", "p1-f1", "p1-f2"}
    assert case["sequences"][0]["annotation_windows"][0]["allowed_fragment_ids"] == [
        "p1-f0",
        "p1-f1",
        "p1-f2",
    ]
    supplement = _response(
        {
            "supplement_schema": STRUCTURAL_SCHEMA,
            "base_response_sha256": hashlib.sha256(original.content.encode()).hexdigest(),
            "annotations": [
                {
                    "sequence_id": "sequence-1",
                    "annotation_id": identity,
                    "spans": [{"fragment_id": fragment}],
                }
                for identity, fragment in [("missing-note", "p1-f1"), ("second-note", "p1-f3")]
            ],
            "flow_insertions": [],
        }
    )
    with pytest.raises(CcefRepairError, match="outside its local source window"):
        apply_structural_supplement(original, supplement, context, gaps)
