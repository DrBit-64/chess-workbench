"""Focused tests for the CCEF 1.1 provider-neutral decoder (8D-3D2A).

Covers the frozen 1.1 decode entry point: a fully valid synthetic annotated
score with interleaved annotations, an earlier-parent alternative and a later
mainline continuation; cross-version rejection in both directions; every
invalid 1.1 structure mapping to the sanitized ``invalid_package``; the JSON
trust boundary shared with v1; ``untrusted_validation`` on any 1.1 move; error
hygiene; and import purity. All content is invented (pages 1-2); no provider
call is ever made.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.decoder import (
    CcefDecodeError,
    decode_extraction_response,
    decode_extraction_response_v1_1,
)
from chess_workbench.extraction.provider import (
    GenerationFinishReason,
    StructuredGenerationResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

INVALID_JSON_MESSAGE = "Structured generation content is not valid JSON"
UNTRUSTED_MESSAGE = "Provider output may contain only unvalidated move nodes"
INVALID_PACKAGE_MESSAGE = "Structured generation content is not a valid CCEF package"


def _move(node_id: str, parent: str | None, sibling: int, text: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "parent_id": parent,
        "sibling_order": sibling,
        "move_text": text,
        "evidence": [{"page": 1}],
    }


def _annotated_score() -> dict[str, Any]:
    """Invented continuous score with an earlier-parent alternative and notes."""
    nodes = [
        _move("n1", None, 0, "e4"),
        _move("n2", "n1", 0, "e5"),
        _move("n3", "n2", 0, "Nf3"),
        _move("n4", "n3", 0, "Nc6"),
        _move("n5", "n4", 0, "d4"),
        _move("n6", "n5", 0, "exd4"),
        _move("n7", "n6", 0, "Nxd4"),
        _move("n8", "n7", 0, "Nf6"),
        _move("n9", "n8", 0, "Nc3"),
        _move("n10", "n9", 0, "Bb4"),
        _move("n11", "n10", 0, "Be3"),
        _move("n12", "n10", 1, "O-O"),
        _move("n13", "n12", 0, "d6"),
        _move("n14", "n13", 0, "c3"),
        _move("n15", "n13", 1, "b3"),
        _move("n16", "n11", 0, "O-O-O"),
    ]
    annotations = [
        {
            "id": "a1",
            "text": "The bishop steps aside to keep the long diagonal covered.",
            "anchor": {"kind": "move_node", "node_id": "n11", "relation": "after"},
            "evidence": [{"page": 2}],
        },
        {
            "id": "a2",
            "text": "A short note without a reliable board anchor.",
            "anchor": None,
            "evidence": [{"page": 1}],
        },
    ]
    reading_flow: list[dict[str, Any]] = [
        {"kind": "move", "node_id": f"n{index}"} for index in range(1, 17)
    ]
    reading_flow.insert(11, {"kind": "annotation", "annotation_id": "a1"})
    reading_flow.append({"kind": "annotation", "annotation_id": "a2"})
    return {
        "kind": "move_sequence",
        "id": "seq1",
        "evidence": [{"page": 1}],
        "initial_position": {"kind": "startpos"},
        "nodes": nodes,
        "annotations": annotations,
        "reading_flow": reading_flow,
    }


def _package_payload_v1_1() -> dict[str, Any]:
    return {
        "schema_version": "chess-content-extraction/1.1",
        "package_id": "6f0c6c8a-4f3d-4b2a-9c1e-5d8f7a2b3c4d",
        "source": {
            "source_ref": "opaque-synthetic-1",
            "media_type": "application/pdf",
            "page_range": {"start_page": 1, "end_page": 2},
        },
        "items": [_annotated_score()],
        "provenance": {
            "created_at": "2026-08-14T10:00:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "1.1",
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


def _decode_v1_1(payload: dict[str, Any], **kwargs: Any) -> None:
    decode_extraction_response_v1_1(_response(json.dumps(payload), **kwargs))


def test_valid_v1_1_package_decodes_with_defaults_and_response_unchanged() -> None:
    payload = _package_payload_v1_1()
    snapshot = copy.deepcopy(payload)
    package = decode_extraction_response_v1_1(_response(json.dumps(payload)))
    assert isinstance(package, ExtractionPackageV1_1)
    assert package.schema_version == "chess-content-extraction/1.1"
    sequence = next(item for item in package.items if item.kind == "move_sequence")
    assert [node.id for node in sequence.nodes][-1] == "n16"
    assert sequence.nodes[11].parent_id == "n10"
    assert sequence.nodes[11].sibling_order == 1
    assert sequence.nodes[15].parent_id == "n11"
    assert [annotation.id for annotation in sequence.annotations] == ["a1", "a2"]
    assert sequence.annotations[0].anchor is not None
    assert sequence.annotations[1].anchor is None
    assert sequence.annotations[0].text_format == "plain"
    assert sequence.annotations[0].warnings == []
    assert payload == snapshot


def test_cross_version_rejection_in_both_directions() -> None:
    v1_payload = {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": "6f0c6c8a-4f3d-4b2a-9c1e-5d8f7a2b3c4d",
        "source": {"source_ref": "opaque-ref-1", "media_type": "application/pdf"},
        "items": [
            {
                "kind": "move_sequence",
                "id": "seq1",
                "evidence": [{"page": 1}],
                "initial_position": {"kind": "startpos"},
                "nodes": [_move("n1", None, 0, "e4")],
            }
        ],
        "provenance": {
            "created_at": "2026-08-14T10:00:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "0.1.0",
        },
    }
    with pytest.raises(CcefDecodeError) as caught:
        decode_extraction_response_v1_1(_response(json.dumps(v1_payload)))
    assert caught.value.code == "invalid_package"

    v1_1_payload = _package_payload_v1_1()
    with pytest.raises(CcefDecodeError) as caught:
        decode_extraction_response(_response(json.dumps(v1_1_payload)))
    assert caught.value.code == "invalid_package"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["items"][0]["annotations"][0].update(
            {"anchor": {"kind": "move_node", "node_id": "ghost", "relation": "after"}}
        ),
        lambda payload: payload["items"][0]["reading_flow"][0].update({"node_id": "ghost"}),
        lambda payload: payload["items"][0]["reading_flow"].reverse(),
        lambda payload: payload.update({"extra": 1}),
        lambda payload: payload["items"][0]["annotations"][0].update({"surprise": True}),
    ],
)
def test_invalid_v1_1_structures_map_to_invalid_package(mutate: Any) -> None:
    payload = _package_payload_v1_1()
    mutate(payload)
    with pytest.raises(CcefDecodeError) as caught:
        _decode_v1_1(payload)
    assert caught.value.code == "invalid_package"
    assert str(caught.value) == INVALID_PACKAGE_MESSAGE


def test_json_trust_boundary_matches_v1() -> None:
    with pytest.raises(CcefDecodeError) as caught:
        decode_extraction_response_v1_1(_response("{broken", finish_reason="stop"))
    assert caught.value.code == "invalid_json"
    assert str(caught.value) == INVALID_JSON_MESSAGE

    with pytest.raises(CcefDecodeError) as caught:
        decode_extraction_response_v1_1(_response("[1, 2]", finish_reason="stop"))
    assert caught.value.code == "invalid_json"

    duplicate = '{"schema_version": "chess-content-extraction/1.1", "schema_version": "x"}'
    with pytest.raises(CcefDecodeError) as caught:
        decode_extraction_response_v1_1(_response(duplicate))
    assert caught.value.code == "invalid_json"

    with pytest.raises(CcefDecodeError) as caught:
        decode_extraction_response_v1_1(_response('{"v": NaN}'))
    assert caught.value.code == "invalid_json"

    with pytest.raises(CcefDecodeError) as caught:
        decode_extraction_response_v1_1(_response("{}", finish_reason="length"))
    assert caught.value.code == "truncated"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["items"][0]["nodes"][0].update({"validation_status": "valid"}),
        lambda payload: payload["items"][0]["nodes"][0].update({"san_candidate": "e4"}),
        lambda payload: payload["items"][0]["nodes"][0].update(
            {"fen_after": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"}
        ),
    ],
)
def test_validation_claims_on_v1_1_moves_are_untrusted(mutate: Any) -> None:
    payload = _package_payload_v1_1()
    mutate(payload)
    with pytest.raises(CcefDecodeError) as caught:
        _decode_v1_1(payload)
    assert caught.value.code == "untrusted_validation"
    assert str(caught.value) == UNTRUSTED_MESSAGE


MARKER = "RAW_PROVIDER_CONTENT_MARKER_1f9c"


def test_error_never_retains_raw_content() -> None:
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response_v1_1(_response("{" + MARKER + " broken"))
    error = excinfo.value
    assert MARKER not in str(error)
    assert MARKER not in repr(error)
    assert all(MARKER not in str(arg) for arg in error.args)
    assert MARKER not in error.code
    assert MARKER not in error.message
    assert not hasattr(error, "content")

    payload = _package_payload_v1_1()
    payload["schema_version"] = f"chess-content-extraction/{MARKER}"
    with pytest.raises(CcefDecodeError) as excinfo:
        decode_extraction_response_v1_1(_response(json.dumps(payload)))
    error = excinfo.value
    assert MARKER not in str(error)
    assert MARKER not in repr(error)
    assert all(MARKER not in str(arg) for arg in error.args)
    assert MARKER not in error.code
    assert MARKER not in error.message
    assert not hasattr(error, "content")


def test_decoder_module_imports_without_forbidden_modules() -> None:
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
