"""Focused tests for the CCEF 1.1 trusted candidate assembler (8D-3D2B1).

Covers the frozen 1.1 assembly behavior: valid annotated-score assembly with
interleaved atomic annotations, shared-prefix local branches and later mainline
continuation; exact trusted provenance binding and canonical trailing-newline
bytes/hashes; the separately versioned 1.1 provider-response artifact with an
explicit ``ccef_schema_version``; annotation warnings contributing to
``warning_count``/``has_conflicts``; deterministic re-assembly with no input
mutation; sanitized rejections (mismatched request, v1 response, wrong adapter
version, malformed content); root-package export identity and import purity.
All content is invented; no provider call.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from chess_workbench.extraction.candidates import (
    CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1,
    CcefCandidateArtifacts,
    CcefCandidateError,
    assemble_ccef_candidate_artifacts_v1_1,
    assemble_ccef_candidate_artifacts_v1_1_semantic,
)
from chess_workbench.extraction.contracts import (
    CCEF_VERSION_1_1,
    AnnotationFlowRef,
    ExtractionPackageV1_1,
    MoveFlowRef,
    MoveSequenceItemV1_1,
)
from chess_workbench.extraction.decoder import CcefDecodeError
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
    build_ccef_v1_1_generation_request,
    build_ccef_v1_1_semantic_generation_request,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    TokenUsage,
)

INIT = Path(__file__).parents[1] / "src/chess_workbench/extraction/__init__.py"
PACKAGE_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_AT = datetime(2026, 8, 14, 12, 34, 56, tzinfo=UTC)
CREATED_AT_JSON = "2026-08-14T12:34:56.000000Z"
BINDING_MESSAGE = "CCEF package metadata does not match the trusted request"


def context() -> CcefPromptContext:
    box = NormalizedBox(x0=0.1, y0=0.2, x1=0.9, y1=0.3)
    source_fragment = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text="synthetic evidence text",
        origin="embedded_text",
        confidence=None,
        engine_name="pdfium",
        engine_version="t",
        fragment_sha256=source_fragment_sha256(
            1, box, "synthetic evidence text", "embedded_text", "pdfium", "t"
        ),
    )
    box_two = NormalizedBox(x0=0.1, y0=0.2, x1=0.9, y1=0.3)
    source_fragment_two = SourceEvidenceFragment(
        physical_page=2,
        box=box_two,
        text="synthetic second page",
        origin="embedded_text",
        confidence=None,
        engine_name="pdfium",
        engine_version="t",
        fragment_sha256=source_fragment_sha256(
            2, box_two, "synthetic second page", "embedded_text", "pdfium", "t"
        ),
    )
    return CcefPromptContext(
        package_id=PACKAGE_ID,
        created_at=CREATED_AT,
        source_ref="source:synthetic:annotated-opening",
        media_type="application/pdf",
        language="en",
        first_page=1,
        last_page=2,
        pages=[
            PromptEvidencePage(
                physical_page=1,
                fragments=[PromptEvidenceFragment(order=0, fragment=source_fragment)],
            ),
            PromptEvidencePage(
                physical_page=2,
                fragments=[PromptEvidenceFragment(order=0, fragment=source_fragment_two)],
            ),
        ],
        max_output_tokens=128_000,
        max_prompt_chars=2_000_000,
    )


def _node(
    node_id: str,
    parent_id: str | None,
    order: int,
    move_text: str,
    **extra: Any,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": order,
        "move_text": move_text,
        "evidence": [{"page": 1}],
    }
    data.update(extra)
    return data


def _annotation(
    annotation_id: str,
    text: str,
    anchor: dict[str, Any] | None,
    **extra: Any,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": annotation_id,
        "text": text,
        "text_format": "plain",
        "anchor": anchor,
        "evidence": [{"page": 1}],
        "confidence": None,
        "warnings": [],
        "extensions": {},
    }
    data.update(extra)
    return data


def _annotated_tree() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Invented legal tree: mainline, earlier-parent alternative, nested
    alternative, later mainline continuation, interleaved annotations."""
    nodes = [
        _node("n1", None, 0, "e4"),
        _node("n2", "n1", 0, "e5"),
        _node("n3", "n2", 0, "Nf3"),
        _node("n4", "n3", 0, "Nc6"),
        _node("n5", "n4", 0, "d4"),
        _node("n6", "n5", 0, "exd4"),
        _node("n7", "n6", 0, "Nxd4"),
        _node("n8", "n7", 0, "Nf6"),
        _node("n9", "n8", 0, "Nc3"),
        _node("n10", "n9", 0, "Bb4"),
        _node("n11", "n10", 0, "Be3"),
        _node("n12", "n10", 1, "a3"),
        _node("n13", "n12", 0, "d6"),
        _node("n14", "n13", 0, "a4"),
        _node("n15", "n13", 1, "b3"),
        _node("n16", "n11", 0, "Be7"),
    ]
    annotations = [
        _annotation(
            "a1",
            "The bishop steps aside to keep the long diagonal covered.",
            {"kind": "move_node", "node_id": "n11", "relation": "after"},
        ),
        _annotation("a2", "A short note without a reliable board anchor.", None),
    ]
    reading_flow: list[dict[str, Any]] = [
        {"kind": "move", "node_id": f"n{index}"} for index in range(1, 17)
    ]
    reading_flow.insert(11, {"kind": "annotation", "annotation_id": "a1"})
    reading_flow.append({"kind": "annotation", "annotation_id": "a2"})
    return nodes, annotations, reading_flow


def package_document(**overrides: Any) -> dict[str, Any]:
    nodes, annotations, reading_flow = _annotated_tree()
    doc: dict[str, Any] = {
        "schema_version": CCEF_VERSION_1_1,
        "package_id": str(PACKAGE_ID),
        "source": {
            "source_ref": "source:synthetic:annotated-opening",
            "media_type": "application/pdf",
            "language": "en",
            "page_range": {"start_page": 1, "end_page": 2},
        },
        "items": [
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": "Synthetic opening chapter",
                "evidence": [{"page": 1}],
            },
            {
                "kind": "move_sequence",
                "id": "seq1",
                "evidence": [{"page": 1}],
                "initial_position": {"kind": "startpos"},
                "nodes": nodes,
                "annotations": annotations,
                "reading_flow": reading_flow,
            },
        ],
        "diagnostics": [],
        "provenance": {
            "created_at": CREATED_AT_JSON,
            "adapter_name": "chess-workbench-ccef-prompt",
            "adapter_version": "1.1",
            "provider": None,
            "model": None,
            "request_sha256": None,
            "response_sha256": None,
        },
        "extensions": {},
    }
    doc.update(overrides)
    return doc


def response(
    content: str | None = None,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    **extra: Any,
) -> StructuredGenerationResponse:
    values: dict[str, Any] = {
        "content": content if content is not None else json.dumps(package_document()),
        "provider": provider,
        "model": model,
        "finish_reason": "stop",
        "usage": TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30),
    }
    values.update(extra)
    return StructuredGenerationResponse.model_validate(values)


def assemble(
    ctx: CcefPromptContext | None = None,
    req: StructuredGenerationRequest | None = None,
    resp: StructuredGenerationResponse | None = None,
) -> CcefCandidateArtifacts:
    ctx = ctx if ctx is not None else context()
    req = req if req is not None else build_ccef_v1_1_generation_request(ctx)
    resp = resp if resp is not None else response()
    return assemble_ccef_candidate_artifacts_v1_1(ctx, req, resp)


def _compact_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _bind_all_evidence(value: Any, ctx: CcefPromptContext) -> Any:
    bound = copy.deepcopy(value)
    fragment = ctx.pages[0].fragments[0].fragment
    evidence = {
        "page": fragment.physical_page,
        "bbox": [fragment.box.x0, fragment.box.y0, fragment.box.x1, fragment.box.y1],
        "start_offset": None,
        "end_offset": None,
        "fragment_sha256": fragment.fragment_sha256,
    }

    def visit(candidate: Any) -> None:
        if isinstance(candidate, dict):
            for key, child in candidate.items():
                if key == "evidence" and isinstance(child, list):
                    candidate[key] = [copy.deepcopy(evidence) for _ in child]
                else:
                    visit(child)
        elif isinstance(candidate, list):
            for child in candidate:
                visit(child)

    visit(bound)
    return bound


# ---------------------------------------------------------------------------
# Valid assembly: provenance binding, canonical bytes, annotated tree survival
# ---------------------------------------------------------------------------


def test_valid_1_1_package_assembles_with_annotations_and_flow() -> None:
    artifacts = assemble()
    raw = ExtractionPackageV1_1.model_validate_json(artifacts.raw_ccef_bytes.decode("utf-8"))
    normalized = ExtractionPackageV1_1.model_validate_json(
        artifacts.normalized_ccef_bytes.decode("utf-8")
    )

    assert raw.provenance.provider == "deepseek"
    assert raw.provenance.model == "deepseek-v4-flash"
    assert raw.provenance.request_sha256 == artifacts.request_sha256
    assert raw.provenance.response_sha256 == artifacts.response_sha256

    raw_sequence = next(item for item in raw.items if isinstance(item, MoveSequenceItemV1_1))
    assert all(node.validation_status == "unvalidated" for node in raw_sequence.nodes)
    assert len(raw_sequence.annotations) == 2

    norm_sequence = next(
        item for item in normalized.items if isinstance(item, MoveSequenceItemV1_1)
    )
    assert len(norm_sequence.nodes) == 16
    node_map = {node.id: node for node in norm_sequence.nodes}
    assert node_map["n1"].validation_status == "valid"
    assert node_map["n1"].uci_candidate == "e2e4"
    assert node_map["n12"].parent_id == "n10"
    assert node_map["n16"].parent_id == "n11"

    # Annotation anchors and exact-cover flow survive consolidation.
    a1 = norm_sequence.annotations[0]
    assert a1.anchor is not None
    move_ids = [
        entry.node_id for entry in norm_sequence.reading_flow if isinstance(entry, MoveFlowRef)
    ]
    annotation_ids = [
        entry.annotation_id
        for entry in norm_sequence.reading_flow
        if isinstance(entry, AnnotationFlowRef)
    ]
    assert move_ids == [node.id for node in norm_sequence.nodes]
    assert annotation_ids == [annotation.id for annotation in norm_sequence.annotations]

    summary = artifacts.summary
    assert summary.item_count == 2
    assert summary.move_node_count == 16
    assert summary.figure_count == 0
    assert summary.unresolved_item_count == 0
    assert summary.warning_count == 0
    assert summary.error_count == 0
    assert summary.invalid_move_count == 0
    assert summary.ambiguous_move_count == 0
    assert summary.has_conflicts is False


def test_semantic_profile_requires_exact_fragment_bound_evidence() -> None:
    ctx = context()
    request = build_ccef_v1_1_semantic_generation_request(ctx)

    with pytest.raises(CcefCandidateError) as caught:
        assemble_ccef_candidate_artifacts_v1_1_semantic(ctx, request, response())
    assert caught.value.code == "semantic_incomplete"
    assert str(caught.value) == "CCEF package does not preserve exact supplied evidence bindings"
    assert caught.value.diagnostics[0].startswith("evidence_refs=")
    assert "missing_locator=0" not in caught.value.diagnostics

    bound_document = _bind_all_evidence(package_document(), ctx)
    artifacts = assemble_ccef_candidate_artifacts_v1_1_semantic(
        ctx,
        request,
        response(json.dumps(bound_document)),
    )
    normalized = ExtractionPackageV1_1.model_validate_json(artifacts.normalized_ccef_bytes)
    sequence = next(item for item in normalized.items if isinstance(item, MoveSequenceItemV1_1))
    assert (
        sequence.evidence[0].fragment_sha256 == ctx.pages[0].fragments[0].fragment.fragment_sha256
    )


def test_semantic_profile_replaces_provider_geometry_from_trusted_fragment_hash() -> None:
    ctx = context()
    request = build_ccef_v1_1_semantic_generation_request(ctx)
    document = _bind_all_evidence(package_document(), ctx)

    def corrupt_provider_geometry(candidate: Any) -> None:
        if isinstance(candidate, dict):
            for key, child in candidate.items():
                if key == "evidence" and isinstance(child, list):
                    for reference in child:
                        reference["bbox"] = [0.1, 0.9, 0.2, 0.3]
                        reference["start_offset"] = 40
                        reference["end_offset"] = 41
                else:
                    corrupt_provider_geometry(child)
        elif isinstance(candidate, list):
            for child in candidate:
                corrupt_provider_geometry(child)

    corrupt_provider_geometry(document)
    provider_response = response(json.dumps(document))
    response_snapshot = provider_response.model_dump(mode="json")
    artifacts = assemble_ccef_candidate_artifacts_v1_1_semantic(
        ctx,
        request,
        provider_response,
    )

    raw = ExtractionPackageV1_1.model_validate_json(artifacts.raw_ccef_bytes)
    sequence = next(item for item in raw.items if isinstance(item, MoveSequenceItemV1_1))
    trusted_box = [0.1, 0.2, 0.9, 0.3]
    for reference in (
        raw.items[0].evidence[0],
        sequence.evidence[0],
        sequence.nodes[0].evidence[0],
        sequence.annotations[0].evidence[0],
    ):
        assert reference.bbox == trusted_box
        assert reference.start_offset is None
        assert reference.end_offset is None
    assert provider_response.model_dump(mode="json") == response_snapshot


def test_semantic_profile_canonicalizes_safe_node_order_before_strict_validation() -> None:
    ctx = context()
    request = build_ccef_v1_1_semantic_generation_request(ctx)
    document = _bind_all_evidence(package_document(), ctx)
    sequence = document["items"][1]
    original_nodes = sequence["nodes"]
    sequence["nodes"] = [*original_nodes[:11], original_nodes[15], *original_nodes[11:15]]
    provider_response = response(json.dumps(document))
    response_snapshot = provider_response.model_dump(mode="json")

    artifacts = assemble_ccef_candidate_artifacts_v1_1_semantic(
        ctx,
        request,
        provider_response,
    )

    raw = ExtractionPackageV1_1.model_validate_json(artifacts.raw_ccef_bytes)
    raw_sequence = next(item for item in raw.items if isinstance(item, MoveSequenceItemV1_1))
    move_ids = [
        entry.node_id for entry in raw_sequence.reading_flow if isinstance(entry, MoveFlowRef)
    ]
    assert [node.id for node in raw_sequence.nodes] == move_ids
    normalized = ExtractionPackageV1_1.model_validate_json(artifacts.normalized_ccef_bytes)
    normalized_sequence = next(
        item for item in normalized.items if isinstance(item, MoveSequenceItemV1_1)
    )
    assert all(node.validation_status == "valid" for node in normalized_sequence.nodes)

    provider_document = json.loads(artifacts.provider_response_bytes)
    assert provider_document["artifact_schema"] == "chess-workbench/ccef-repair-chain/2.1"
    assert provider_document["deterministic_operations"] == [
        {
            "rule": "align_nodes_to_reading_flow",
            "path": "/items/1/nodes",
            "moved_count": 5,
        }
    ]
    assert provider_document["original_response"] == response_snapshot
    assert provider_response.model_dump(mode="json") == response_snapshot


def test_semantic_profile_rejects_unknown_fragment_hash_without_leaking_it() -> None:
    ctx = context()
    request = build_ccef_v1_1_semantic_generation_request(ctx)
    document = _bind_all_evidence(package_document(), ctx)
    private_hash = "f" * 64
    document["items"][0]["evidence"][0]["fragment_sha256"] = private_hash

    with pytest.raises(CcefCandidateError) as caught:
        assemble_ccef_candidate_artifacts_v1_1_semantic(
            ctx,
            request,
            response(json.dumps(document)),
        )
    assert caught.value.code == "semantic_incomplete"
    assert private_hash not in str(caught.value)
    assert "unmatched_locator=1" in caught.value.diagnostics
    assert all(private_hash not in item for item in caught.value.diagnostics)


def test_canonical_hashes_newlines_and_1_1_provider_document_are_exact() -> None:
    artifacts = assemble()
    request = build_ccef_v1_1_generation_request(context())
    resp = response()

    assert (
        artifacts.request_sha256
        == hashlib.sha256(_compact_json(request.model_dump(mode="json"))).hexdigest()
    )
    assert artifacts.response_sha256 == hashlib.sha256(resp.content.encode("utf-8")).hexdigest()
    assert artifacts.raw_ccef_sha256 == hashlib.sha256(artifacts.raw_ccef_bytes).hexdigest()
    assert (
        artifacts.normalized_ccef_sha256
        == hashlib.sha256(artifacts.normalized_ccef_bytes).hexdigest()
    )
    for blob in (
        artifacts.raw_ccef_bytes,
        artifacts.normalized_ccef_bytes,
        artifacts.provider_response_bytes,
    ):
        assert blob.endswith(b"\n")
        assert blob.count(b"\n") == 1

    provider_doc = json.loads(artifacts.provider_response_bytes.decode("utf-8"))
    assert set(provider_doc) == {
        "artifact_schema",
        "ccef_schema_version",
        "request_sha256",
        "response_sha256",
        "provider",
        "model",
        "finish_reason",
        "usage",
        "content",
    }
    assert provider_doc["artifact_schema"] == CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1
    assert provider_doc["ccef_schema_version"] == "chess-content-extraction/1.1"
    assert provider_doc["request_sha256"] == artifacts.request_sha256
    assert provider_doc["response_sha256"] == artifacts.response_sha256
    assert provider_doc["provider"] == "deepseek"
    assert provider_doc["model"] == "deepseek-v4-flash"
    assert provider_doc["finish_reason"] == "stop"
    assert provider_doc["usage"] == {
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
    }
    assert provider_doc["content"] == resp.content


def test_annotation_warnings_count_toward_warning_count_and_conflicts() -> None:
    annotated = package_document()
    sequence = annotated["items"][1]
    sequence["annotations"][0]["warnings"] = [
        {
            "code": "review_note",
            "message": "verify the bishop retreat",
            "evidence": [{"page": 1}],
        }
    ]
    artifacts = assemble(resp=response(content=json.dumps(annotated)))
    assert artifacts.summary.warning_count == 1
    assert artifacts.summary.has_conflicts is True


def test_deterministic_reassembly_and_input_non_mutation() -> None:
    ctx = context()
    request = build_ccef_v1_1_generation_request(ctx)
    resp = response()
    first = assemble_ccef_candidate_artifacts_v1_1(ctx, request, resp)
    second = assemble_ccef_candidate_artifacts_v1_1(ctx, request, resp)
    assert first.model_dump() == second.model_dump()

    resp_snapshot = resp.model_dump(mode="json")
    ctx_snapshot = ctx.model_dump(mode="json")
    request_snapshot = request.model_dump(mode="json")
    assemble_ccef_candidate_artifacts_v1_1(ctx, request, resp)
    assert resp.model_dump(mode="json") == resp_snapshot
    assert ctx.model_dump(mode="json") == ctx_snapshot
    assert request.model_dump(mode="json") == request_snapshot


def test_semantic_change_changes_raw_and_normalized_hashes() -> None:
    ctx = context()
    request = build_ccef_v1_1_generation_request(ctx)
    base = assemble_ccef_candidate_artifacts_v1_1(
        ctx, request, response(content=json.dumps(package_document()))
    )

    changed = package_document()
    changed["items"][1]["annotations"][0]["text"] = "A changed annotation text."
    altered = assemble_ccef_candidate_artifacts_v1_1(
        ctx, request, response(content=json.dumps(changed))
    )
    assert altered.raw_ccef_sha256 != base.raw_ccef_sha256
    assert altered.normalized_ccef_sha256 != base.normalized_ccef_sha256
    assert altered.response_sha256 != base.response_sha256


# ---------------------------------------------------------------------------
# Sanitized rejections
# ---------------------------------------------------------------------------


def test_mismatched_request_is_rejected() -> None:
    ctx = context()
    v1_request = build_ccef_v1_1_generation_request(ctx)
    wrong = v1_request.model_copy(deep=True)
    wrong.messages[0].content = "a tampered system message"
    with pytest.raises(CcefCandidateError) as caught:
        assemble_ccef_candidate_artifacts_v1_1(
            ctx, wrong, response(content=json.dumps(package_document()))
        )
    assert caught.value.code == "binding_mismatch"
    assert caught.value.message == BINDING_MESSAGE


def test_v1_response_is_rejected_by_the_1_1_assembler() -> None:
    v1_doc = package_document(
        schema_version="chess-content-extraction/1.0",
    )
    v1_doc["provenance"]["adapter_version"] = "1.0"
    v1_doc["items"][1].pop("annotations")
    v1_doc["items"][1].pop("reading_flow")
    with pytest.raises(CcefDecodeError) as caught:
        assemble(resp=response(content=json.dumps(v1_doc)))
    assert caught.value.code == "invalid_package"


def test_wrong_adapter_version_is_rejected() -> None:
    doc = package_document()
    doc["provenance"]["adapter_version"] = "1.0"
    with pytest.raises(CcefCandidateError) as caught:
        assemble(resp=response(content=json.dumps(doc)))
    assert caught.value.code == "binding_mismatch"
    assert caught.value.message == BINDING_MESSAGE


def test_malformed_provider_content_is_rejected_without_leakage() -> None:
    with pytest.raises(CcefDecodeError) as caught:
        assemble(resp=response(content="this is not json {"))
    assert caught.value.code == "invalid_json"
    assert "this is not json" not in str(caught.value)


# ---------------------------------------------------------------------------
# Root package exports and import purity
# ---------------------------------------------------------------------------


def test_root_package_exports_are_identity_equal() -> None:
    import chess_workbench.extraction as extraction
    import chess_workbench.extraction.candidates as candidates
    import chess_workbench.extraction.consolidation as consolidation
    import chess_workbench.extraction.validation as validation

    assert (
        extraction.CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1
        is candidates.CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1
    )
    assert (
        extraction.assemble_ccef_candidate_artifacts_v1_1
        is candidates.assemble_ccef_candidate_artifacts_v1_1
    )
    assert (
        extraction.consolidate_move_sequences_v1_1 is consolidation.consolidate_move_sequences_v1_1
    )
    assert extraction.normalize_chess_moves_v1_1 is validation.normalize_chess_moves_v1_1
    assert extraction.CCEF_VERSION_1_1 == "chess-content-extraction/1.1"
    assert extraction.SCHEMA_ID_1_1 == "urn:chess-content-extraction:schema:1.1"
    assert extraction.ExtractionPackageV1_1 is not None
    assert extraction.build_ccef_v1_1_generation_request is not None
    assert extraction.decode_extraction_response_v1_1 is not None


def test_fresh_root_import_keeps_import_purity() -> None:
    code = """
import sys
import chess_workbench.extraction as extraction
bad = [
    module
    for module in sys.modules
    if any(
        marker in module
        for marker in (
            "chess.",
            "httpx",
            "sqlalchemy",
            "sanic",
            "store.",
            "services",
            "worker",
            "review",
        )
    )
]
assert bad == [], bad
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd="backend"
    )
    assert result.returncode == 0, result.stderr


def test_init_module_has_no_forbidden_eager_imports() -> None:
    tree = ast.parse(INIT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any(
        forbidden in name
        for name in imported
        for forbidden in (
            "chess",
            "httpx",
            "sqlalchemy",
            "sanic",
            "store",
            "services",
            "worker",
            "review",
        )
    )
