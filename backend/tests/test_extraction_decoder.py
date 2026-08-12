"""Focused tests for the provider-neutral CCEF decoder.

Covers the required behaviors of DS-STAGE8-CCEF-DECODER-01: valid decoding
with CCEF defaults and no response mutation, truncated-output rejection,
every ``invalid_json`` and ``invalid_package`` boundary, the
``untrusted_validation`` trust boundary, the public error contract
(including exception-chaining hygiene) and import purity.  Responses are
constructed directly; no network call is ever made.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, get_args

import pytest
from chess_workbench.extraction import (
    CcefDecodeError,
    CcefDecodeErrorCode,
    decode_extraction_response,
)
from chess_workbench.extraction.contracts import MoveSequenceItem
from chess_workbench.extraction.provider import (
    GenerationFinishReason,
    StructuredGenerationResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"

TRUNCATED_MESSAGE = "Structured generation was truncated"
INVALID_JSON_MESSAGE = "Structured generation content is not valid JSON"
UNTRUSTED_MESSAGE = "Provider output may contain only unvalidated move nodes"
INVALID_PACKAGE_MESSAGE = "Structured generation content is not a valid CCEF package"


def _package_payload() -> dict[str, Any]:
    """A minimal structurally valid CCEF package as JSON-ready dict."""
    return {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": "6f0c6c8a-4f3d-4b2a-9c1e-5d8f7a2b3c4d",
        "source": {"source_ref": "opaque-ref-1", "media_type": "application/pdf"},
        "items": [
            {
                "kind": "move_sequence",
                "id": "seq1",
                "evidence": [{"page": 1}],
                "initial_position": {"kind": "startpos"},
                "nodes": [
                    {
                        "id": "n1",
                        "parent_id": None,
                        "sibling_order": 0,
                        "move_text": "e4",
                        "evidence": [{"page": 1}],
                    },
                    {
                        "id": "n2",
                        "parent_id": "n1",
                        "sibling_order": 0,
                        "move_text": "e5",
                        "evidence": [{"page": 1}],
                    },
                ],
            }
        ],
        "provenance": {
            "created_at": "2026-08-11T10:00:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "0.1.0",
        },
    }


def _response(
    content: str, finish_reason: GenerationFinishReason | None = "stop"
) -> StructuredGenerationResponse:
    return StructuredGenerationResponse(
        content=content,
        provider="deepseek",
        model="deepseek-v4-flash",
        finish_reason=finish_reason,
    )


def _decode(payload: dict[str, Any], **kwargs: Any) -> None:
    decode_extraction_response(_response(json.dumps(payload), **kwargs))


# ---------------------------------------------------------------------------
# 1. Valid decoding with CCEF defaults and no response mutation
# ---------------------------------------------------------------------------


def test_valid_package_decodes_with_defaults_and_response_unchanged() -> None:
    payload = _package_payload()
    response = _response(json.dumps(payload))
    snapshot = response.model_dump()

    package = decode_extraction_response(response)

    assert package.schema_version == "chess-content-extraction/1.0"
    sequence = package.items[0]
    assert sequence.kind == "move_sequence"
    assert sequence.nodes[0].validation_status == "unvalidated"
    assert sequence.nodes[0].san_candidate is None
    assert sequence.nodes[0].uci_candidate is None
    assert sequence.nodes[0].fen_before is None
    assert sequence.nodes[0].fen_after is None
    # CCEF v1 defaults are applied by the model, not invented by the decoder.
    assert package.diagnostics == []
    assert package.extensions == {}
    assert sequence.nodes[0].nags == []
    assert sequence.nodes[0].warnings == []
    assert sequence.nodes[0].confidence is None
    assert sequence.nodes[0].sibling_order == 0
    # The response object is never mutated.
    assert response.model_dump() == snapshot


# ---------------------------------------------------------------------------
# 2. Truncated-output rejection
# ---------------------------------------------------------------------------


def test_truncated_finish_reason_wins_even_when_content_is_valid_json() -> None:
    response = _response(json.dumps(_package_payload()), finish_reason="length")
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response(response)
    assert excinfo.value.code == "truncated"
    assert excinfo.value.message == TRUNCATED_MESSAGE
    assert str(excinfo.value) == TRUNCATED_MESSAGE


def test_truncated_finish_reason_wins_even_when_content_is_garbage() -> None:
    response = _response("{not json at all", finish_reason="length")
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response(response)
    assert excinfo.value.code == "truncated"
    assert excinfo.value.message == TRUNCATED_MESSAGE


def test_excessively_nested_json_is_invalid_json_not_recursion_error() -> None:
    content = "[" * 2_000 + "0" + "]" * 2_000
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response(_response(content))
    assert excinfo.value.code == "invalid_json"
    assert excinfo.value.__context__ is None


# ---------------------------------------------------------------------------
# 3. invalid_json boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "{broken",
        '{"a": }',
        "{'single': 'quotes'}",
        "{unquoted: 1}",
        "42",  # scalar top level
        '"just a string"',
        "true",
        "null",
        "[]",  # list top level
        "[1, 2, 3]",
        "```json\n" + json.dumps(_package_payload()) + "\n```",  # Markdown fences
        '{"a": 1} trailing commentary',
        '{"a": 1} {"b": 2}',
        '{"a": NaN}',  # every non-standard numeric constant
        '{"a": Infinity}',
        '{"a": -Infinity}',
        "[NaN]",
        '{"a": 1, "a": 2}',  # duplicate key at root
        '{"a": {"b": 1, "b": 2}}',  # duplicate key nested
        '{"items": [{"kind": "heading", "id": "h", "a": 1, "a": 2}]}',  # deep nesting
    ],
)
def test_invalid_json_cases_are_rejected(content: str) -> None:
    response = _response(content)
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response(response)
    assert excinfo.value.code == "invalid_json"
    assert excinfo.value.message == INVALID_JSON_MESSAGE
    assert str(excinfo.value) == INVALID_JSON_MESSAGE


# ---------------------------------------------------------------------------
# 4. invalid_package boundary (ordinary CCEF validation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update({"bogus_top_level": True}),  # unknown field
        lambda data: data.update({"schema_version": "chess-content-extraction/2.0"}),
        lambda data: data["source"].update({"source_ref": 123}),  # wrong strict scalar type
        lambda data: data["items"][0]["nodes"][0].update({"sibling_order": "0"}),  # string int
        lambda data: data["items"].append(  # dangling prose anchor reference
            {
                "kind": "prose",
                "id": "p1",
                "text": "note",
                "evidence": [{"page": 1}],
                "anchor": {"kind": "move_node", "sequence_id": "ghost-seq", "node_id": "n1"},
            }
        ),
        lambda data: data["items"][0]["nodes"][0].update({"parent_id": "n1"}),  # self-parent
        lambda data: data["items"][0]["nodes"][1].update({"sibling_order": 2}),  # order gap
    ],
)
def test_invalid_package_cases_are_rejected(mutate: Any) -> None:
    payload = copy.deepcopy(_package_payload())
    mutate(payload)
    with pytest.raises(CcefDecodeError) as excinfo:
        _decode(payload)
    assert excinfo.value.code == "invalid_package"
    assert excinfo.value.message == INVALID_PACKAGE_MESSAGE
    assert str(excinfo.value) == INVALID_PACKAGE_MESSAGE


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update({"items": "not-a-list"}),
        lambda data: data["items"][0].update({"nodes": "not-a-list"}),
        lambda data: data["items"][0].update({"nodes": [{"id": "not-a-node-object"}]}),
        lambda data: data["items"][0].update({"kind": "mystery_item"}),
    ],
)
def test_malformed_items_and_nodes_shapes_are_left_to_ccef_validation(mutate: Any) -> None:
    """The decoder never guesses or repairs malformed shapes; CCEF rejects them."""
    payload = copy.deepcopy(_package_payload())
    mutate(payload)
    with pytest.raises(CcefDecodeError) as excinfo:
        _decode(payload)
    assert excinfo.value.code == "invalid_package"
    assert excinfo.value.message == INVALID_PACKAGE_MESSAGE


# ---------------------------------------------------------------------------
# 5. untrusted_validation trust boundary
# ---------------------------------------------------------------------------


def test_omitted_and_explicit_unvalidated_with_null_authoritative_fields_accepted() -> None:
    payload = _package_payload()  # omitted validation_status and fields
    decode_extraction_response(_response(json.dumps(payload)))

    node = payload["items"][0]["nodes"][0]
    node["validation_status"] = "unvalidated"
    node["san_candidate"] = None
    node["uci_candidate"] = None
    node["fen_before"] = None
    node["fen_after"] = None
    package = decode_extraction_response(_response(json.dumps(payload)))
    sequence = package.items[0]
    assert isinstance(sequence, MoveSequenceItem)
    assert sequence.nodes[0].validation_status == "unvalidated"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["items"][0]["nodes"][0].update({"validation_status": "valid"}),
        lambda data: data["items"][0]["nodes"][0].update({"validation_status": "invalid"}),
        lambda data: data["items"][0]["nodes"][0].update({"validation_status": "ambiguous"}),
        lambda data: data["items"][0]["nodes"][0].update({"validation_status": "pending"}),
        lambda data: data["items"][0]["nodes"][0].update({"san_candidate": "e4"}),
        lambda data: data["items"][0]["nodes"][0].update({"uci_candidate": "e2e4"}),
        lambda data: data["items"][0]["nodes"][0].update({"fen_before": START_FEN}),
        lambda data: data["items"][0]["nodes"][0].update({"fen_after": AFTER_E4_FEN}),
    ],
)
def test_any_validation_claim_is_untrusted(mutate: Any) -> None:
    payload = copy.deepcopy(_package_payload())
    mutate(payload)
    with pytest.raises(CcefDecodeError) as excinfo:
        _decode(payload)
    assert excinfo.value.code == "untrusted_validation"
    assert excinfo.value.message == UNTRUSTED_MESSAGE
    assert str(excinfo.value) == UNTRUSTED_MESSAGE


def test_complete_valid_node_that_would_satisfy_ccef_is_still_untrusted() -> None:
    """A fully normalized ``valid`` node is rejected before CCEF validation,
    so provider output can never claim a deterministic chess result."""
    payload = _package_payload()
    node = payload["items"][0]["nodes"][0]
    node["validation_status"] = "valid"
    node["san_candidate"] = "e4"
    node["uci_candidate"] = "e2e4"
    node["fen_before"] = START_FEN
    node["fen_after"] = AFTER_E4_FEN
    with pytest.raises(CcefDecodeError) as excinfo:
        _decode(payload)
    assert excinfo.value.code == "untrusted_validation"
    assert excinfo.value.message == UNTRUSTED_MESSAGE


def test_untrusted_claim_in_any_move_sequence_is_rejected() -> None:
    """The trust boundary applies to every move_sequence item, not the first."""
    payload = _package_payload()
    second = copy.deepcopy(payload["items"][0])
    second["id"] = "seq2"
    second["nodes"] = [
        {
            "id": "m1",
            "parent_id": None,
            "sibling_order": 0,
            "move_text": "d4",
            "evidence": [{"page": 1}],
            "validation_status": "valid",
        }
    ]
    payload["items"].append(second)
    with pytest.raises(CcefDecodeError) as excinfo:
        _decode(payload)
    assert excinfo.value.code == "untrusted_validation"


# ---------------------------------------------------------------------------
# 6. Public error contract: codes, constructor, exception-chaining hygiene
# ---------------------------------------------------------------------------


def test_constructor_accepts_all_four_codes_and_messages() -> None:
    for code in ("truncated", "invalid_json", "invalid_package", "untrusted_validation"):
        error = CcefDecodeError(code, f"message-{code}")
        assert error.code == code
        assert error.message == f"message-{code}"
        assert str(error) == f"message-{code}"
        assert error.args == (f"message-{code}",)


@pytest.mark.parametrize("bad_code", ["bogus", 123, None, b"truncated", ["truncated"]])
def test_constructor_rejects_invalid_code(bad_code: Any) -> None:
    with pytest.raises(ValueError):
        CcefDecodeError(bad_code, "message")


@pytest.mark.parametrize("bad_message", ["", "   \n\t", 123, None, b"message"])
def test_constructor_rejects_invalid_message(bad_message: Any) -> None:
    with pytest.raises(ValueError):
        CcefDecodeError("truncated", bad_message)


def test_all_four_codes_are_raised_by_the_decoder() -> None:
    claiming = copy.deepcopy(_package_payload())
    claiming["items"][0]["nodes"][0]["validation_status"] = "valid"
    cases: list[tuple[str, str, GenerationFinishReason]] = [
        ("truncated", "{}", "length"),
        ("invalid_json", "{broken", "stop"),
        ("invalid_package", json.dumps({**_package_payload(), "extra": 1}), "stop"),
        ("untrusted_validation", json.dumps(claiming), "stop"),
    ]

    for code, content, finish_reason in cases:
        with pytest.raises(CcefDecodeError) as excinfo:
            decode_extraction_response(_response(content, finish_reason=finish_reason))
        assert excinfo.value.code == code
        assert isinstance(excinfo.value.code, str)


MARKER = "RAW_PROVIDER_CONTENT_MARKER_7f3a"


def _assert_marker_absent(error: CcefDecodeError) -> None:
    assert MARKER not in str(error)
    assert MARKER not in repr(error)
    assert all(MARKER not in str(arg) for arg in error.args)
    assert MARKER not in error.code
    assert MARKER not in error.message
    assert not hasattr(error, "content")
    assert error.__cause__ is None
    assert error.__context__ is None


def test_error_never_retains_raw_content_or_chained_exceptions() -> None:
    invalid_json_payload = "{" + MARKER + " broken"
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response(_response(invalid_json_payload))
    _assert_marker_absent(excinfo.value)

    invalid_package_payload = {
        **_package_payload(),
        "schema_version": f"chess-content-extraction/{MARKER}",
    }
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response(_response(json.dumps(invalid_package_payload)))
    _assert_marker_absent(excinfo.value)

    untrusted_payload = copy.deepcopy(_package_payload())
    untrusted_payload["items"][0]["nodes"][0]["san_candidate"] = "e4" + MARKER
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response(_response(json.dumps(untrusted_payload)))
    _assert_marker_absent(excinfo.value)

    # truncated: content is never read, so the marker cannot leak either.
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response(_response(MARKER, finish_reason="length"))
    _assert_marker_absent(excinfo.value)


# ---------------------------------------------------------------------------
# 7. Import boundary proof
# ---------------------------------------------------------------------------


def test_decoder_module_imports_without_forbidden_modules() -> None:
    # Load provider.py, contracts.py and decoder.py standalone with a
    # synthetic package namespace so the real extraction __init__ (which
    # re-exports the DeepSeek httpx adapter) cannot pollute sys.modules.
    code = (
        "import importlib.util, sys, types\n"
        "from pathlib import Path\n"
        "root = types.ModuleType('chess_workbench')\n"
        "sys.modules['chess_workbench'] = root\n"
        "pkg = types.ModuleType('chess_workbench.extraction')\n"
        "pkg.__path__ = [str(Path('backend/src/chess_workbench/extraction'))]\n"
        "sys.modules['chess_workbench.extraction'] = pkg\n"
        "for name in ('provider', 'contracts', 'decoder'):\n"
        "    spec = importlib.util.spec_from_file_location(\n"
        "        f'chess_workbench.extraction.{name}',\n"
        "        f'backend/src/chess_workbench/extraction/{name}.py')\n"
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    sys.modules[spec.name] = mod\n"
        "    spec.loader.exec_module(mod)\n"
        "forbidden = ('httpx', 'chess_workbench.store', 'chess_workbench.services',\n"
        "             'chess_workbench.api', 'chess_workbench.schemas',\n"
        "             'chess_workbench.config', 'chess_workbench.domain',\n"
        "             'chess_workbench.extraction.deepseek',\n"
        "             'sqlalchemy', 'sanic', 'pydantic_settings')\n"
        "bad = [m for m in forbidden if m in sys.modules]\n"
        "print('bad=', bad)\n"
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"forbidden modules imported: {result.stdout}{result.stderr}"


def test_decoder_source_does_not_mention_forbidden_concepts() -> None:
    source = (
        REPO_ROOT / "backend" / "src" / "chess_workbench" / "extraction" / "decoder.py"
    ).read_text(encoding="utf-8")
    for token in (
        "httpx",
        "sanic",
        "sqlalchemy",
        "store",
        "services",
        "jobs",
        "Settings",
        "pydantic_settings",
        "deepseek",
    ):
        assert re.search(rf"\b{re.escape(token)}\b", source) is None, (
            f"decoder.py mentions {token!r}"
        )


def test_public_names_are_exported_from_the_package() -> None:
    from chess_workbench.extraction import __all__ as exported

    for name in ("CcefDecodeError", "CcefDecodeErrorCode", "decode_extraction_response"):
        assert name in exported
    # The literal union is exactly the four declared codes.
    assert set(get_args(CcefDecodeErrorCode)) == {
        "truncated",
        "invalid_json",
        "invalid_package",
        "untrusted_validation",
    }
