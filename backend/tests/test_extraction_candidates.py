"""Focused tests for the pure Stage 8C trusted candidate assembler.

Covers DS-STAGE8C-TRUSTED-CANDIDATES-01: valid trusted assembly with exact
provenance binding and canonical artifact bytes/hashes, deterministic
re-assembly with no input mutation, every trusted-metadata binding mismatch,
decoder error propagation, legal/illegal/ambiguous/disconnected move
normalization, the conflict-summary truth table, strict frozen models,
sanitized errors, exact input types and AST import purity.  No filesystem,
network, clock, randomness, SQL or provider call is used.
"""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from chess_workbench.extraction.candidates import (
    CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA,
    CcefCandidateArtifacts,
    CcefCandidateError,
    CcefCandidateErrorCode,
    CcefCandidateSummary,
    assemble_ccef_candidate_artifacts,
)
from chess_workbench.extraction.contracts import (
    CCEF_VERSION,
    ExtractionPackage,
    MoveSequenceItem,
    UnresolvedItem,
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
    build_ccef_generation_request,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    TokenUsage,
)

MODULE = Path(__file__).parents[1] / "src/chess_workbench/extraction/candidates.py"
PACKAGE_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_AT = datetime(2026, 8, 11, 12, 34, 56, tzinfo=UTC)
CREATED_AT_JSON = "2026-08-11T12:34:56.000000Z"
BINDING_MESSAGE = "CCEF package metadata does not match the trusted request"

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def fragment(page: int, text: str = "  1. e4! 中文  ") -> SourceEvidenceFragment:
    box = NormalizedBox(x0=0.1, y0=0.2, x1=0.9, y1=0.3)
    return SourceEvidenceFragment(
        physical_page=page,
        box=box,
        text=text,
        origin="embedded_text",
        confidence=None,
        engine_name="pdfium",
        engine_version="1.2.3",
        fragment_sha256=source_fragment_sha256(page, box, text, "embedded_text", "pdfium", "1.2.3"),
    )


def context() -> CcefPromptContext:
    return CcefPromptContext(
        package_id=PACKAGE_ID,
        created_at=CREATED_AT,
        source_ref="source:scandinavian:chapter-8",
        media_type="application/pdf",
        language="en",
        first_page=319,
        last_page=319,
        pages=[
            PromptEvidencePage(
                physical_page=319,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment(319))],
            )
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
        "evidence": [{"page": 319}],
    }
    data.update(extra)
    return data


def package_document(**overrides: Any) -> dict[str, Any]:
    items = [
        {
            "kind": "heading",
            "id": "h1",
            "level": 1,
            "text": "Chapter 8",
            "evidence": [{"page": 319}],
        },
        {"kind": "prose", "id": "p1", "text": "Narrative 中文", "evidence": [{"page": 319}]},
        {
            "kind": "move_sequence",
            "id": "seq1",
            "evidence": [{"page": 319}],
            "initial_position": {"kind": "startpos"},
            "nodes": [
                _node("n1", None, 0, "e4"),
                _node("n2", "n1", 0, "e5"),
                _node("n3", "n1", 1, "c5"),
            ],
        },
    ]
    doc: dict[str, Any] = {
        "schema_version": CCEF_VERSION,
        "package_id": str(PACKAGE_ID),
        "source": {
            "source_ref": "source:scandinavian:chapter-8",
            "media_type": "application/pdf",
            "language": "en",
            "page_range": {"start_page": 319, "end_page": 319},
        },
        "items": items,
        "diagnostics": [],
        "provenance": {
            "created_at": CREATED_AT_JSON,
            "adapter_name": "chess-workbench-ccef-prompt",
            "adapter_version": "1.0",
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
    req = req if req is not None else build_ccef_generation_request(ctx)
    resp = resp if resp is not None else response()
    return assemble_ccef_candidate_artifacts(ctx, req, resp)


def _compact_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Valid assembly: trusted binding, provenance replacement, canonical bytes
# ---------------------------------------------------------------------------


def test_valid_package_assembles_trusted_provenance_and_summary() -> None:
    artifacts = assemble()
    raw = ExtractionPackage.model_validate_json(artifacts.raw_ccef_bytes.decode("utf-8"))
    normalized = ExtractionPackage.model_validate_json(
        artifacts.normalized_ccef_bytes.decode("utf-8")
    )

    assert raw.provenance.provider == "deepseek"
    assert raw.provenance.model == "deepseek-v4-flash"
    assert raw.provenance.request_sha256 == artifacts.request_sha256
    assert raw.provenance.response_sha256 == artifacts.response_sha256
    # Raw package keeps unvalidated nodes.
    sequence = raw.items[2]
    assert isinstance(sequence, MoveSequenceItem)
    assert all(node.validation_status == "unvalidated" for node in sequence.nodes)
    # Normalized package carries authoritative chess fields.
    norm_sequence = normalized.items[2]
    assert isinstance(norm_sequence, MoveSequenceItem)
    assert norm_sequence.nodes[0].validation_status == "valid"
    assert norm_sequence.nodes[0].san_candidate == "e4"
    assert norm_sequence.nodes[0].uci_candidate == "e2e4"

    summary = artifacts.summary
    assert summary.item_count == 3
    assert summary.move_node_count == 3
    assert summary.figure_count == 0
    assert summary.unresolved_item_count == 0
    assert summary.warning_count == 0
    assert summary.error_count == 0
    assert summary.invalid_move_count == 0
    assert summary.ambiguous_move_count == 0
    assert summary.has_conflicts is False


def test_canonical_documents_hashes_and_newlines_are_exact() -> None:
    artifacts = assemble()
    request = build_ccef_generation_request(context())
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
    assert artifacts.raw_ccef_bytes.endswith(b"\n")
    assert artifacts.normalized_ccef_bytes.endswith(b"\n")
    assert artifacts.provider_response_bytes.endswith(b"\n")
    assert artifacts.raw_ccef_bytes.count(b"\n") == 1
    assert artifacts.normalized_ccef_bytes.count(b"\n") == 1

    provider_doc = json.loads(artifacts.provider_response_bytes.decode("utf-8"))
    assert set(provider_doc) == {
        "artifact_schema",
        "request_sha256",
        "response_sha256",
        "provider",
        "model",
        "finish_reason",
        "usage",
        "content",
    }
    assert provider_doc["artifact_schema"] == CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA
    assert provider_doc["content"] == resp.content
    assert provider_doc["usage"] == resp.usage.model_dump(mode="json")


def test_response_content_unicode_and_outer_whitespace_are_preserved() -> None:
    content = "  \n" + json.dumps(package_document(), ensure_ascii=False) + "\n  "
    artifacts = assemble(resp=response(content=content))
    provider_doc = json.loads(artifacts.provider_response_bytes.decode("utf-8"))
    assert provider_doc["content"] == content
    assert "中文" in artifacts.raw_ccef_bytes.decode("utf-8")
    assert artifacts.response_sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_assembly_is_deterministic_and_never_mutates_inputs() -> None:
    ctx = context()
    request = build_ccef_generation_request(ctx)
    resp = response()
    context_snapshot = ctx.model_dump(mode="json")
    request_snapshot = request.model_dump(mode="json")
    response_snapshot = resp.model_dump(mode="json")

    first = assemble_ccef_candidate_artifacts(ctx, request, resp)
    second = assemble_ccef_candidate_artifacts(ctx, request, resp)

    assert first == second
    assert first.provider_response_bytes == second.provider_response_bytes
    assert first.raw_ccef_bytes == second.raw_ccef_bytes
    assert first.normalized_ccef_bytes == second.normalized_ccef_bytes
    assert ctx.model_dump(mode="json") == context_snapshot
    assert request.model_dump(mode="json") == request_snapshot
    assert resp.model_dump(mode="json") == response_snapshot


def test_response_content_change_changes_hashes_but_not_request_hash() -> None:
    ctx = context()
    request = build_ccef_generation_request(ctx)
    altered = package_document()
    altered["items"][0]["text"] = "Changed heading"
    base = assemble_ccef_candidate_artifacts(ctx, request, response())
    changed = assemble_ccef_candidate_artifacts(ctx, request, response(content=json.dumps(altered)))
    assert base.request_sha256 == changed.request_sha256
    assert base.response_sha256 != changed.response_sha256
    assert base.raw_ccef_sha256 != changed.raw_ccef_sha256
    assert base.normalized_ccef_sha256 != changed.normalized_ccef_sha256


# ---------------------------------------------------------------------------
# Trusted binding mismatches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"package_id": "22222222-2222-4222-8222-222222222222"},
        {
            "source": {
                "source_ref": "other",
                "media_type": "application/pdf",
                "language": "en",
                "page_range": {"start_page": 319, "end_page": 319},
            }
        },
        {
            "source": {
                "source_ref": "source:scandinavian:chapter-8",
                "media_type": "image/png",
                "language": "en",
                "page_range": {"start_page": 319, "end_page": 319},
            }
        },
        {
            "source": {
                "source_ref": "source:scandinavian:chapter-8",
                "media_type": "application/pdf",
                "language": None,
                "page_range": {"start_page": 319, "end_page": 319},
            }
        },
        {
            "source": {
                "source_ref": "source:scandinavian:chapter-8",
                "media_type": "application/pdf",
                "language": "en",
                "page_range": {"start_page": 319, "end_page": 320},
            }
        },
        {
            "source": {
                "source_ref": "source:scandinavian:chapter-8",
                "media_type": "application/pdf",
                "language": "en",
                "page_range": None,
            }
        },
        {
            "provenance": {
                "created_at": "2026-08-11T13:00:00.000000Z",
                "adapter_name": "chess-workbench-ccef-prompt",
                "adapter_version": "1.0",
                "provider": None,
                "model": None,
                "request_sha256": None,
                "response_sha256": None,
            }
        },
        {
            "provenance": {
                "created_at": CREATED_AT_JSON,
                "adapter_name": "other-adapter",
                "adapter_version": "1.0",
                "provider": None,
                "model": None,
                "request_sha256": None,
                "response_sha256": None,
            }
        },
        {
            "provenance": {
                "created_at": CREATED_AT_JSON,
                "adapter_name": "chess-workbench-ccef-prompt",
                "adapter_version": "2.0",
                "provider": None,
                "model": None,
                "request_sha256": None,
                "response_sha256": None,
            }
        },
        {
            "provenance": {
                "created_at": CREATED_AT_JSON,
                "adapter_name": "chess-workbench-ccef-prompt",
                "adapter_version": "1.0",
                "provider": "deepseek",
                "model": None,
                "request_sha256": None,
                "response_sha256": None,
            }
        },
        {
            "provenance": {
                "created_at": CREATED_AT_JSON,
                "adapter_name": "chess-workbench-ccef-prompt",
                "adapter_version": "1.0",
                "provider": None,
                "model": "m",
                "request_sha256": None,
                "response_sha256": None,
            }
        },
        {
            "provenance": {
                "created_at": CREATED_AT_JSON,
                "adapter_name": "chess-workbench-ccef-prompt",
                "adapter_version": "1.0",
                "provider": None,
                "model": None,
                "request_sha256": "a" * 64,
                "response_sha256": None,
            }
        },
        {
            "provenance": {
                "created_at": CREATED_AT_JSON,
                "adapter_name": "chess-workbench-ccef-prompt",
                "adapter_version": "1.0",
                "provider": None,
                "model": None,
                "request_sha256": None,
                "response_sha256": "b" * 64,
            }
        },
        {"extensions": {"org.example": {"x": 1}}},
    ],
)
def test_package_metadata_mismatches_raise_binding_error(overrides: dict[str, Any]) -> None:
    doc = package_document()
    for key, value in overrides.items():
        doc[key] = value
    with pytest.raises(CcefCandidateError) as caught:
        assemble(resp=response(content=json.dumps(doc)))
    assert caught.value.code == "binding_mismatch"
    assert str(caught.value) == BINDING_MESSAGE
    assert caught.value.__cause__ is None


def test_request_mismatch_raises_binding_error() -> None:
    ctx = context()
    request = build_ccef_generation_request(ctx).model_copy(update={"max_output_tokens": 64_000})
    with pytest.raises(CcefCandidateError) as caught:
        assemble_ccef_candidate_artifacts(ctx, request, response())
    assert caught.value.code == "binding_mismatch"
    assert str(caught.value) == BINDING_MESSAGE


# ---------------------------------------------------------------------------
# Decoder error propagation
# ---------------------------------------------------------------------------


def test_decoder_errors_propagate_unchanged() -> None:
    ctx = context()
    request = build_ccef_generation_request(ctx)
    with pytest.raises(CcefDecodeError) as caught:
        assemble_ccef_candidate_artifacts(ctx, request, response(finish_reason="length"))
    assert caught.value.code == "truncated"

    with pytest.raises(CcefDecodeError) as caught:
        assemble_ccef_candidate_artifacts(ctx, request, response(content="{not json"))
    assert caught.value.code == "invalid_json"

    untrusted = package_document()
    untrusted["items"][2]["nodes"][0]["validation_status"] = "valid"
    with pytest.raises(CcefDecodeError) as caught:
        assemble_ccef_candidate_artifacts(ctx, request, response(content=json.dumps(untrusted)))
    assert caught.value.code == "untrusted_validation"

    malformed = package_document()
    malformed["items"] = [{"kind": "heading", "id": "h1", "evidence": [{"page": 319}]}]
    with pytest.raises(CcefDecodeError) as caught:
        assemble_ccef_candidate_artifacts(ctx, request, response(content=json.dumps(malformed)))
    assert caught.value.code == "invalid_package"


# ---------------------------------------------------------------------------
# Move normalization outcomes feed the summary
# ---------------------------------------------------------------------------


def test_illegal_and_disconnected_moves_are_isolated_from_the_playable_tree() -> None:
    items = package_document()["items"]
    items[2] = {
        "kind": "move_sequence",
        "id": "seq1",
        "evidence": [{"page": 319}],
        "initial_position": {"kind": "startpos"},
        "nodes": [
            _node("n1", None, 0, "e4"),
            _node("n2", "n1", 0, "Ke5"),  # illegal move
            _node("n3", "n2", 0, "e5"),  # disconnected: parent board unresolved
            _node("n4", "n1", 1, "c5"),  # valid
        ],
    }
    artifacts = assemble(resp=response(content=json.dumps(package_document(items=items))))
    normalized = ExtractionPackage.model_validate_json(
        artifacts.normalized_ccef_bytes.decode("utf-8")
    )
    sequence = normalized.items[2]
    assert isinstance(sequence, MoveSequenceItem)
    assert [node.san_candidate for node in sequence.nodes] == ["e4", "c5"]
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    unresolved = next(item for item in normalized.items if isinstance(item, UnresolvedItem))
    assert unresolved.raw_text == "Ke5 e5"
    summary = artifacts.summary
    assert summary.invalid_move_count == 0
    assert summary.ambiguous_move_count == 0
    assert summary.unresolved_item_count == 1
    assert summary.has_conflicts is True
    assert summary.warning_count == 0


def test_ambiguous_move_becomes_unresolved_and_conflicts() -> None:
    items = package_document()["items"]
    items[2] = {
        "kind": "move_sequence",
        "id": "seq1",
        "evidence": [{"page": 319}],
        "initial_position": {
            "kind": "fen",
            "fen": "rnbqkbnr/ppp1pppp/8/4p3/6N1/5N2/PPPPPPPP/R1BQKB1R w KQkq - 0 2",
        },
        "nodes": [_node("n1", None, 0, "Ne5")],
    }
    artifacts = assemble(resp=response(content=json.dumps(package_document(items=items))))
    normalized = ExtractionPackage.model_validate_json(
        artifacts.normalized_ccef_bytes.decode("utf-8")
    )
    assert not any(isinstance(item, MoveSequenceItem) for item in normalized.items)
    unresolved = next(item for item in normalized.items if isinstance(item, UnresolvedItem))
    assert unresolved.raw_text == "Ne5"
    assert artifacts.summary.ambiguous_move_count == 0
    assert artifacts.summary.unresolved_item_count == 1
    assert artifacts.summary.has_conflicts is True


# ---------------------------------------------------------------------------
# Summary truth table: figures, unresolved, warnings, errors
# ---------------------------------------------------------------------------


def test_figures_unresolved_warnings_and_errors_set_conflicts() -> None:
    doc = package_document()
    doc["items"].append(
        {"kind": "figure", "id": "f1", "figure_type": "chessboard", "evidence": [{"page": 319}]}
    )
    doc["items"].append(
        {
            "kind": "unresolved",
            "id": "u1",
            "unresolved_type": "text",
            "reason_code": "ocr_unclear",
            "raw_text": "???",
            "evidence": [{"page": 319}],
        }
    )
    doc["diagnostics"] = [
        {"severity": "warning", "code": "low_confidence", "message": "low"},
        {"severity": "error", "code": "broken_tree", "message": "broken"},
        {"severity": "info", "code": "note", "message": "info"},
    ]
    artifacts = assemble(resp=response(content=json.dumps(doc)))
    summary = artifacts.summary
    assert summary.item_count == 5
    assert summary.figure_count == 1
    assert summary.unresolved_item_count == 1
    assert summary.warning_count == 1  # package warning diagnostic only
    assert summary.error_count == 1  # package error diagnostic only
    assert summary.has_conflicts is True

    clean = package_document()
    clean["diagnostics"] = [{"severity": "info", "code": "note", "message": "info"}]
    artifacts = assemble(resp=response(content=json.dumps(clean)))
    assert artifacts.summary.warning_count == 0
    assert artifacts.summary.error_count == 0
    assert artifacts.summary.has_conflicts is False


# ---------------------------------------------------------------------------
# Strict models and sanitized errors
# ---------------------------------------------------------------------------


def test_public_models_have_exact_fields_and_are_strict_frozen() -> None:
    assert set(CcefCandidateSummary.model_fields) == {
        "item_count",
        "move_node_count",
        "figure_count",
        "unresolved_item_count",
        "warning_count",
        "error_count",
        "invalid_move_count",
        "ambiguous_move_count",
        "has_conflicts",
    }
    assert set(CcefCandidateArtifacts.model_fields) == {
        "provider_response_bytes",
        "raw_ccef_bytes",
        "normalized_ccef_bytes",
        "request_sha256",
        "response_sha256",
        "raw_ccef_sha256",
        "normalized_ccef_sha256",
        "summary",
    }
    for model in (CcefCandidateSummary, CcefCandidateArtifacts):
        assert model.model_config.get("extra") == "forbid"
        assert model.model_config.get("strict") is True
        assert model.model_config.get("frozen") is True

    summary = CcefCandidateSummary.model_validate(
        {
            "item_count": 0,
            "move_node_count": 0,
            "figure_count": 0,
            "unresolved_item_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "invalid_move_count": 0,
            "ambiguous_move_count": 0,
            "has_conflicts": False,
        }
    )
    with pytest.raises(ValidationError):
        summary.item_count = 1  # frozen model rejects attribute mutation
    with pytest.raises(ValidationError):
        CcefCandidateSummary.model_validate(
            {
                "item_count": -1,
                "move_node_count": 0,
                "figure_count": 0,
                "unresolved_item_count": 0,
                "warning_count": 0,
                "error_count": 0,
                "invalid_move_count": 0,
                "ambiguous_move_count": 0,
                "has_conflicts": 1,  # bool as int rejected
            }
        )


def test_candidate_error_is_sanitized_and_sole_code() -> None:
    from typing import get_args

    assert get_args(CcefCandidateErrorCode) == ("binding_mismatch",)
    error = CcefCandidateError("binding_mismatch", BINDING_MESSAGE)
    assert error.code == "binding_mismatch"
    assert str(error) == BINDING_MESSAGE
    assert error.__cause__ is None
    assert error.args == (BINDING_MESSAGE,)
    with pytest.raises(ValueError):
        CcefCandidateError(cast(Any, "other_code"), "x")
    with pytest.raises(ValueError):
        CcefCandidateError("binding_mismatch", "   ")


def test_assembler_requires_exact_input_types() -> None:
    ctx = context()
    request = build_ccef_generation_request(ctx)
    resp = response()
    with pytest.raises(TypeError, match="context must be CcefPromptContext"):
        assemble_ccef_candidate_artifacts(object(), request, resp)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="request must be StructuredGenerationRequest"):
        assemble_ccef_candidate_artifacts(ctx, object(), resp)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="response must be StructuredGenerationResponse"):
        assemble_ccef_candidate_artifacts(ctx, request, object())  # type: ignore[arg-type]


def test_package_export_is_available_lazily() -> None:
    from chess_workbench import extraction as pkg

    assert pkg.assemble_ccef_candidate_artifacts is assemble_ccef_candidate_artifacts
    assert pkg.CcefCandidateError is CcefCandidateError
    assert pkg.CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA == CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA


# ---------------------------------------------------------------------------
# Import purity
# ---------------------------------------------------------------------------


def test_import_boundary_is_pure() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    assert not any(
        forbidden in name
        for name in imports
        for forbidden in (
            "httpx",
            "sqlalchemy",
            "sanic",
            "chess_workbench.config",
            "chess_workbench.services",
            "chess_workbench.store",
            "chess_workbench.api",
            "deepseek",
        )
    )
    assert "json" in imports
    assert "hashlib" in imports
