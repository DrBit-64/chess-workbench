from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from test_extraction_coverage import _fixture, _response

from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.general_repair import CcefRepairError
from chess_workbench.extraction.prompting import CcefPromptContext
from chess_workbench.extraction.provider import (
    ScriptedStructuredGenerationProvider,
    StructuredGenerationResponse,
)
from chess_workbench.extraction.recovery import CcefRecoveryError, recover_ccef_response
from chess_workbench.extraction.structural_recovery import (
    STRUCTURAL_CHAIN,
    STRUCTURAL_SCHEMA,
    apply_structural_supplement,
    inspect_structural_gaps,
)
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1


def _missing() -> tuple[StructuredGenerationResponse, CcefPromptContext, dict[str, Any]]:
    package, context = _fixture()
    # This fixture focuses on source prose, without the other test's missing variation.
    page = context.pages[0].model_copy(update={"fragments": context.pages[0].fragments[:2]})
    context = context.model_copy(update={"pages": [page]})
    data = package.model_dump(mode="json")
    sequence = data["items"][0]
    del sequence["annotations"]
    sequence["reading_flow"] = [
        {"kind": "move", "node_id": "n1"},
        {"kind": "annotation", "annotation_id": "missing-note"},
    ]
    original = _response(data)
    supplement = {
        "supplement_schema": STRUCTURAL_SCHEMA,
        "base_response_sha256": hashlib.sha256(original.content.encode()).hexdigest(),
        "annotations": [
            {
                "sequence_id": "sequence-1",
                "annotation_id": "missing-note",
                "spans": [{"fragment_id": "p1-f1", "excerpt": None}],
            }
        ],
        "flow_insertions": [
            {"sequence_id": "sequence-1", "kind": "move", "ref_id": "n2", "after_flow_index": 1}
        ],
    }
    return original, context, supplement


async def _ignore_failure(
    response: StructuredGenerationResponse,
    code: str,
    message: str,
    diagnostics: tuple[str, ...],
) -> None:
    pass


async def test_missing_annotations_use_additive_recovery_and_full_validator() -> None:
    original, context, supplement = _missing()
    provider = ScriptedStructuredGenerationProvider([_response(supplement)])
    validated: list[ExtractionPackageV1_1] = []

    def validate(response: StructuredGenerationResponse) -> ExtractionPackageV1_1:
        package = normalize_chess_moves_v1_1(
            ExtractionPackageV1_1.model_validate_json(response.content)
        )
        validated.append(package)
        return package

    result = await recover_ccef_response(
        original,
        context,
        validate=validate,
        normalized_package=lambda value: value,
        repair_provider=provider,
        coverage_provider=provider,
        record_failure=_ignore_failure,
    )
    assert len(provider.calls) == 1
    schema: Any = provider.calls[0].response_schema
    assert schema["$defs"]["SourceSpan"]["properties"]["fragment_id"]["enum"] == ["p1-f0", "p1-f1"]
    assert provider.calls[0].response_schema_name == "chess_workbench_ccef_structural_supplement_v1"
    assert result.changed and len(validated) == 1
    accepted = json.loads(result.accepted_response.content)["items"][0]
    before = json.loads(original.content)["items"][0]
    assert accepted["nodes"] == before["nodes"]
    assert accepted["reading_flow"][:2] == before["reading_flow"]
    assert accepted["annotations"][0]["text"] == "The plan is 2.Nf3."
    assert (
        accepted["annotations"][0]["evidence"][0]["fragment_sha256"]
        == context.pages[0].fragments[1].fragment.fragment_sha256
    )
    assert isinstance(result.provider_document, dict)
    assert result.provider_document["artifact_schema"] == STRUCTURAL_CHAIN
    assert result.provider_document["base_generation"]["content"] == original.content


@pytest.mark.parametrize(
    "failure",
    ["incomplete", "invented_text", "wrong_hash", "overwrite", "unknown_fragment", "repeated_span"],
)
def test_structural_supplement_rejects_unbound_or_destructive_changes(failure: str) -> None:
    original, context, supplement = _missing()
    if failure == "incomplete":
        supplement["flow_insertions"] = []
    elif failure == "invented_text":
        supplement["annotations"][0]["spans"][0]["excerpt"] = "Invented source text"
    elif failure == "wrong_hash":
        supplement["base_response_sha256"] = "0" * 64
    elif failure == "unknown_fragment":
        supplement["annotations"][0]["spans"][0]["fragment_id"] = "p1-f999"
    elif failure == "repeated_span":
        supplement["annotations"][0]["spans"] *= 2
    else:
        supplement["flow_insertions"][0]["ref_id"] = "n1"
    with pytest.raises(CcefRepairError):
        apply_structural_supplement(
            original, _response(supplement), context, inspect_structural_gaps(original)
        )


async def test_unsupported_missing_move_body_stops_without_a_provider_call() -> None:
    original, context, _ = _missing()
    data = json.loads(original.content)
    data["items"][0]["reading_flow"][0]["node_id"] = "nonexistent"
    provider = ScriptedStructuredGenerationProvider([])
    with pytest.raises(CcefRecoveryError, match="missing move bodies") as error:
        await recover_ccef_response(
            _response(data),
            context,
            validate=lambda response: ExtractionPackageV1_1.model_validate_json(response.content),
            normalized_package=lambda value: value,
            repair_provider=provider,
            coverage_provider=provider,
            record_failure=_ignore_failure,
        )
    assert error.value.code == "ccef_recovery_unsupported"
    assert not provider.calls
