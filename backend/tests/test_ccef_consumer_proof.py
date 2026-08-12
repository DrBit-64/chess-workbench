"""Focused tests for DS-STAGE8-CONSUMER-PROOF-01 (8P-5).

Proves the CCEF output boundary is consumer-neutral: the standalone example
reader validates the published Schema, consumes the checked-in normalized
sample package, produces a byte-stable golden reader projection, and never
imports ChessWorkbench, Pydantic, python-chess, provider, HTTP, SQL or config
code. Also verifies the Codex-frozen one-way ChessWorkbench mapping document.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from chess_workbench.extraction.contracts import ExtractionPackage
from chess_workbench.extraction.validation import normalize_chess_moves
from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSUMER = REPO_ROOT / "examples" / "ccef_consumer" / "consumer.py"
SCHEMA = REPO_ROOT / "contracts" / "chess-content-extraction-v1.schema.json"
SAMPLE = REPO_ROOT / "contracts" / "examples" / "chess-content-extraction-v1.sample.json"
GOLDEN = REPO_ROOT / "contracts" / "examples" / "chess-content-extraction-v1.reader.json"
MAPPING = REPO_ROOT / "docs" / "architecture" / "ccef-chess-workbench-mapping.md"

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Load the standalone example as an isolated module (it is not part of the
# chess_workbench package and must never import it).
_consumer_spec = importlib.util.spec_from_file_location("ccef_consumer_example", CONSUMER)
assert _consumer_spec is not None and _consumer_spec.loader is not None
consumer_module = importlib.util.module_from_spec(_consumer_spec)
_consumer_spec.loader.exec_module(consumer_module)
project_reader_document: Any = consumer_module.project_reader_document
consumer_main: Any = consumer_module.main

_VALID_SCHEMA = json.loads(SCHEMA.read_text(encoding="utf-8"))
_VALID_PACKAGE = json.loads(SAMPLE.read_text(encoding="utf-8"))

_WRONG_DIALECT = dict(_VALID_SCHEMA)
_WRONG_DIALECT["$schema"] = "https://json-schema.org/draft/07/schema"
_WRONG_ID = dict(_VALID_SCHEMA)
_WRONG_ID["$id"] = "urn:chess-content-extraction:schema:9.9"
_INVALID_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:chess-content-extraction:schema:1.0",
    "type": "not-a-type",
}
_REMOTE_REF_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:chess-content-extraction:schema:1.0",
    "$ref": "https://example.invalid/ccef.json",
}
_UNKNOWN_FIELD = dict(_VALID_PACKAGE)
_UNKNOWN_FIELD["bogus"] = 1
_UNKNOWN_EXTENSION_KEY = copy.deepcopy(_VALID_PACKAGE)
_UNKNOWN_EXTENSION_KEY["extensions"] = {"not_namespaced": True}
_UNSUPPORTED_VERSION = dict(_VALID_PACKAGE)
_UNSUPPORTED_VERSION["schema_version"] = "chess-content-extraction/9.9"
_BAD_UUID = dict(_VALID_PACKAGE)
_BAD_UUID["package_id"] = "not-a-uuid"
_BAD_DATETIME = dict(_VALID_PACKAGE)
_BAD_DATETIME["provenance"] = dict(_VALID_PACKAGE["provenance"])
_BAD_DATETIME["provenance"]["created_at"] = "2026-08-11T10:00:00"

REJECTED_STDERR = "CCEF consumer rejected the input\n"

_DRIVER = """\
import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout

consumer_path, schema_path, package_path, golden_path, report_path = sys.argv[1:6]
spec = importlib.util.spec_from_file_location("ccef_consumer_proof", consumer_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

buffer = io.StringIO()
with redirect_stdout(buffer):
    rc = module.main(["--schema", schema_path, "--package", package_path])

golden = open(golden_path, encoding="utf-8").read()
forbidden = [
    "chess_workbench",
    "pydantic",
    "chess",
    "httpx",
    "sanic",
    "sqlalchemy",
    "store",
    "services",
    "jobs",
    "config",
]
loaded = sorted(sys.modules)
hits = [
    name
    for name in loaded
    if any(name == entry or name.startswith(entry + ".") for entry in forbidden)
]
report = {"rc": rc, "stdout_ok": buffer.getvalue() == golden, "forbidden_modules": hits}
with open(report_path, "w", encoding="utf-8") as handle:
    json.dump(report, handle)
"""


# ---------------------------------------------------------------------------
# 1. Checked-in Schema, sample validity and normalization idempotency
# ---------------------------------------------------------------------------


def test_schema_and_sample_are_valid_and_normalization_is_idempotent() -> None:
    Draft202012Validator.check_schema(_VALID_SCHEMA)
    Draft202012Validator(_VALID_SCHEMA, format_checker=FormatChecker()).validate(_VALID_PACKAGE)
    package = ExtractionPackage.model_validate(_VALID_PACKAGE)
    normalized = normalize_chess_moves(package)
    assert normalized.model_dump(mode="json") == package.model_dump(mode="json")
    assert _VALID_PACKAGE["source"]["source_ref"] == "sample://opening-book/chapter-8"


# ---------------------------------------------------------------------------
# 2. python -I CLI: byte-identical stdout, empty stderr, return 0
# ---------------------------------------------------------------------------


def test_python_I_cli_stdout_is_byte_identical_to_golden() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(CONSUMER),
            "--schema",
            str(SCHEMA),
            "--package",
            str(SAMPLE),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout == GOLDEN.read_bytes()


# ---------------------------------------------------------------------------
# 3. Projection fidelity: items, anchors, tree, canonical fields, defaults
# ---------------------------------------------------------------------------


def test_projection_preserves_order_anchors_tree_and_defaults() -> None:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    snapshot = copy.deepcopy(sample)
    document = project_reader_document(sample)
    assert sample == snapshot
    assert document["consumer_format"] == "example-ccef-reader/1"
    assert document["schema_version"] == "chess-content-extraction/1.0"
    assert document["package_id"] == sample["package_id"]
    assert document["source"] == sample["source"]
    assert document["provenance"] == sample["provenance"]
    assert document["diagnostics"] == sample["diagnostics"]

    entries = document["entries"]
    assert [entry["source_id"] for entry in entries] == [
        "h1",
        "p1",
        "seq1",
        "p2",
        "p3",
        "f1",
        "u1",
    ]
    assert [entry["type"] for entry in entries] == [
        "heading",
        "prose",
        "move_sequence",
        "prose",
        "prose",
        "figure",
        "unresolved",
    ]

    narrative, node_anchor, position_anchor = entries[1], entries[3], entries[4]
    assert narrative["text_format"] == "plain"
    assert narrative["anchor"] is None
    assert narrative["warnings"] == []
    assert narrative["extensions"] == {}
    assert node_anchor["text_format"] == "markdown"
    assert node_anchor["anchor"] == {
        "kind": "move_node",
        "sequence_id": "seq1",
        "node_id": "n4",
    }
    assert position_anchor["text_format"] == "plain"
    assert position_anchor["confidence"] is None
    assert position_anchor["warnings"] == []
    assert position_anchor["extensions"] == {}
    assert position_anchor["anchor"] == {"kind": "position", "fen": START_FEN}

    sequence = entries[2]
    assert sequence["title"] == "Open Game with Two Replies"
    assert sequence["initial_position"] == {"kind": "startpos"}
    nodes = sequence["nodes"]
    assert [node["source_id"] for node in nodes] == [
        "n1",
        "n2",
        "n3",
        "n4",
        "n5",
        "n6",
        "n7",
    ]
    assert [node["parent_source_id"] for node in nodes] == [
        None,
        "n1",
        "n2",
        "n3",
        None,
        "n5",
        "n1",
    ]
    assert [node["order"] for node in nodes] == [0, 0, 0, 0, 1, 0, 1]

    n1, n2, n4, n5, n7 = nodes[0], nodes[1], nodes[3], nodes[4], nodes[6]
    assert (n1["san"], n1["uci"]) == ("e4", "e2e4")
    assert n1["status"] == "valid"
    assert len(n1["fen_before"].split()) == 6
    assert len(n1["fen_after"].split()) == 6
    assert n2["nags"] == [40]
    assert n4["evidence"][0] == {
        "page": 325,
        "bbox": [0.1, 0.2, 0.3, 0.4],
        "start_offset": 30,
        "end_offset": 45,
        "fragment_sha256": "9f7b12aebcf0a3b504fc2912261643af1e3238760b98c1c6018ac45b791284ab",
    }
    assert n5["confidence"] is None
    assert n5["nags"] == []
    assert n5["extensions"] == {}
    assert n7["status"] == "invalid"
    assert n7["san"] is None and n7["uci"] is None
    assert n7["fen_before"] is None and n7["fen_after"] is None
    assert n7["warnings"][0]["code"] == "ccef_chess_invalid_move"
    assert n7["warnings"][0]["evidence"] == n7["evidence"]

    figure = entries[5]
    assert figure["figure_type"] == "chessboard"
    assert len(figure["position_fen_candidate"].split()) == 6
    unresolved = entries[6]
    assert unresolved["reason_code"] == "ocr_unclear"
    assert unresolved["raw_text"] == "Diagram caption with a stray glyph."
    assert unresolved["details"] is None


def test_projection_returns_deep_copies_and_never_mutates_input() -> None:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    document = project_reader_document(sample)
    assert document is not sample
    document["source"]["source_ref"] = "mutated"
    document["entries"][0]["extensions"]["com.example.reader"]["kind"] = "mutated"
    assert sample["source"]["source_ref"] == "sample://opening-book/chapter-8"
    assert sample["items"][0]["extensions"]["com.example.reader"]["kind"] == "section"


def test_golden_contains_all_item_ids_and_required_review_entries() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert [entry["source_id"] for entry in golden["entries"]] == [
        "h1",
        "p1",
        "seq1",
        "p2",
        "p3",
        "f1",
        "u1",
    ]
    assert golden["review_queue"] == [
        {
            "item_id": "seq1",
            "node_id": "n7",
            "reasons": ["move_invalid", "ccef_chess_invalid_move"],
        },
        {
            "item_id": "f1",
            "node_id": None,
            "reasons": ["figure_fen_candidate_unchecked"],
        },
        {
            "item_id": "u1",
            "node_id": None,
            "reasons": ["ocr_unclear", "ocr_text_missing_context"],
        },
        {
            "item_id": "seq1",
            "node_id": "n7",
            "reasons": ["diagnostic_invalid_branch_retained"],
        },
    ]


# ---------------------------------------------------------------------------
# 4. Review-queue ordering, merge/dedup, diagnostic handling
# ---------------------------------------------------------------------------


def _queue_package(
    items: list[dict[str, Any]], diagnostics: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": "00000000-0000-0000-0000-000000000001",
        "source": {"source_ref": "synthetic", "media_type": "application/pdf"},
        "items": items,
        "diagnostics": diagnostics or [],
        "provenance": {
            "created_at": "2026-08-11T10:00:00Z",
            "adapter_name": "test",
            "adapter_version": "1",
        },
    }


def _node(
    node_id: str,
    parent_id: str | None,
    order: int,
    status: str = "valid",
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": order,
        "move_text": "e4",
        "validation_status": status,
        "evidence": [{"page": 1}],
    }
    if warnings is not None:
        data["warnings"] = warnings
    return data


def _sequence(nodes: list[dict[str, Any]], seq_id: str = "s1") -> dict[str, Any]:
    return {
        "kind": "move_sequence",
        "id": seq_id,
        "evidence": [{"page": 1}],
        "initial_position": {"kind": "startpos"},
        "nodes": nodes,
    }


def test_review_queue_ordering_merge_dedup_and_diagnostics() -> None:
    package = _queue_package(
        [
            _sequence(
                [
                    _node("a", None, 0),
                    _node(
                        "b",
                        "a",
                        0,
                        status="invalid",
                        warnings=[
                            {"code": "ccef_chess_invalid_move", "message": "first"},
                            {"code": "ccef_chess_invalid_move", "message": "second"},
                        ],
                    ),
                ]
            ),
            {
                "kind": "unresolved",
                "id": "u1",
                "unresolved_type": "text",
                "reason_code": "ocr_unclear",
                "raw_text": "x",
                "evidence": [{"page": 1}],
                "warnings": [{"code": "ocr_text_missing_context", "message": "context"}],
            },
            {
                "kind": "figure",
                "id": "f1",
                "figure_type": "chessboard",
                "evidence": [{"page": 1}],
                "warnings": [{"code": "figure_fen_candidate_unchecked", "message": "unverified"}],
            },
        ],
        diagnostics=[
            {"severity": "info", "code": "normalization_done", "message": "info"},
            {
                "severity": "warning",
                "code": "invalid_branch_retained",
                "message": "warning",
                "item_id": "s1",
                "node_id": "b",
            },
            {"severity": "error", "code": "fatal_parse", "message": "error"},
        ],
    )
    document = project_reader_document(package)
    assert document["review_queue"] == [
        {
            "item_id": "s1",
            "node_id": "b",
            "reasons": ["move_invalid", "ccef_chess_invalid_move"],
        },
        {
            "item_id": "u1",
            "node_id": None,
            "reasons": ["ocr_unclear", "ocr_text_missing_context"],
        },
        {
            "item_id": "f1",
            "node_id": None,
            "reasons": ["figure_fen_candidate_unchecked"],
        },
        {
            "item_id": "s1",
            "node_id": "b",
            "reasons": ["diagnostic_invalid_branch_retained"],
        },
        {"item_id": None, "node_id": None, "reasons": ["diagnostic_fatal_parse"]},
    ]


def test_review_queue_valid_warning_and_unvalidated_reasons() -> None:
    package = _queue_package(
        [
            _sequence(
                [
                    _node(
                        "a",
                        None,
                        0,
                        warnings=[{"code": "annotation_doubt", "message": "doubt"}],
                    ),
                    _node("b", "a", 0, status="unvalidated"),
                ]
            ),
            {
                "kind": "unresolved",
                "id": "u1",
                "unresolved_type": "text",
                "reason_code": "ocr_unclear",
                "raw_text": "x",
                "evidence": [{"page": 1}],
            },
        ]
    )
    document = project_reader_document(package)
    assert document["review_queue"] == [
        {"item_id": "s1", "node_id": "a", "reasons": ["annotation_doubt"]},
        {"item_id": "s1", "node_id": "b", "reasons": ["move_unvalidated"]},
        {"item_id": "u1", "node_id": None, "reasons": ["ocr_unclear"]},
    ]


# ---------------------------------------------------------------------------
# 5. Rejected inputs: return 2, empty stdout, fixed stderr only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema", "package"),
    [
        (_VALID_SCHEMA, "{not json"),
        ("{not json", _VALID_PACKAGE),
        (_VALID_SCHEMA, 42),
        (_VALID_SCHEMA, [1, 2]),
        (7, _VALID_PACKAGE),
        (["x"], _VALID_PACKAGE),
        (_WRONG_DIALECT, _VALID_PACKAGE),
        (_WRONG_ID, _VALID_PACKAGE),
        (_INVALID_SCHEMA, _VALID_PACKAGE),
        (_REMOTE_REF_SCHEMA, _VALID_PACKAGE),
        (_VALID_SCHEMA, _UNKNOWN_FIELD),
        (_VALID_SCHEMA, _UNKNOWN_EXTENSION_KEY),
        (_VALID_SCHEMA, _UNSUPPORTED_VERSION),
        (_VALID_SCHEMA, _BAD_UUID),
        (_VALID_SCHEMA, _BAD_DATETIME),
    ],
    ids=[
        "invalid_json_package",
        "invalid_json_schema",
        "scalar_package_top_level",
        "list_package_top_level",
        "scalar_schema_top_level",
        "list_schema_top_level",
        "wrong_schema_dialect",
        "wrong_schema_id",
        "invalid_schema",
        "remote_schema_reference",
        "unknown_package_field",
        "unknown_extension_key",
        "unsupported_version",
        "bad_uuid_format",
        "bad_datetime_format",
    ],
)
def test_rejected_inputs_return_2_with_fixed_stderr(
    schema: Any, package: Any, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    rc = consumer_main(["--schema", str(schema_path), "--package", str(package_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err == REJECTED_STDERR


def test_missing_files_are_contained(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = consumer_main(
        ["--schema", str(tmp_path / "no.json"), "--package", str(tmp_path / "no2.json")]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err == REJECTED_STDERR


def test_schema_valid_package_with_omitted_default_items_projects_empty_lists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = {
        key: copy.deepcopy(_VALID_PACKAGE[key])
        for key in ("schema_version", "package_id", "source", "provenance")
    }
    package_path = tmp_path / "minimal.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    rc = consumer_main(["--schema", str(SCHEMA), "--package", str(package_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    projected = json.loads(captured.out)
    assert projected["entries"] == []
    assert projected["diagnostics"] == []
    assert projected["review_queue"] == []


@pytest.mark.parametrize("constant", [float("nan"), float("inf"), float("-inf")])
def test_non_standard_json_numbers_are_rejected(
    constant: float, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = copy.deepcopy(_VALID_PACKAGE)
    package["extensions"] = {"org.example": constant}
    package_path = tmp_path / "non-standard.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    rc = consumer_main(["--schema", str(SCHEMA), "--package", str(package_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err == REJECTED_STDERR


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef", "$recursiveRef"])
def test_remote_schema_references_are_rejected_before_validator_construction(
    keyword: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    schema = copy.deepcopy(_VALID_SCHEMA)
    schema["$defs"]["Remote"] = {keyword: "https://example.invalid/schema.json"}
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(_VALID_PACKAGE), encoding="utf-8")

    def _must_not_construct(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("validator construction must not run for a remote reference")

    monkeypatch.setattr(consumer_module, "Draft202012Validator", _must_not_construct)
    with pytest.raises(ValueError, match="remote JSON Schema references"):
        consumer_module.load_validated_package(schema_path, package_path)


# ---------------------------------------------------------------------------
# 6. Unknown-kind ValueError; loader containment; non-loader exception propagation
# ---------------------------------------------------------------------------


def test_direct_unknown_kind_raises_value_error() -> None:
    package = {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": "00000000-0000-0000-0000-000000000001",
        "source": {"source_ref": "synthetic", "media_type": "application/pdf"},
        "items": [{"kind": "bogus", "id": "x", "evidence": [{"page": 1}]}],
        "provenance": {
            "created_at": "2026-08-11T10:00:00Z",
            "adapter_name": "test",
            "adapter_version": "1",
        },
    }
    with pytest.raises(ValueError, match="unknown CCEF item kind"):
        project_reader_document(package)


def test_non_loader_exceptions_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(exc: type[BaseException]) -> None:
        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise exc

        monkeypatch.setattr(consumer_module, "load_validated_package", _boom)
        with pytest.raises(exc):
            consumer_main(["--schema", str(SCHEMA), "--package", str(SAMPLE)])

    _raise(KeyboardInterrupt)
    _raise(MemoryError)


# ---------------------------------------------------------------------------
# 7. Import boundary: AST proof and isolated sys.modules proof
# ---------------------------------------------------------------------------


def test_consumer_import_boundary_ast() -> None:
    tree = ast.parse(CONSUMER.read_text(encoding="utf-8"))
    allowed_modules = {
        "__future__",
        "argparse",
        "collections",
        "copy",
        "json",
        "sys",
        "pathlib",
        "typing",
        "jsonschema",
    }
    allowed_jsonschema_names = {
        "Draft202012Validator",
        "FormatChecker",
        "SchemaError",
        "ValidationError",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            imported.add(node.module.split(".")[0])
            if node.module == "jsonschema":
                for alias in node.names:
                    assert alias.name in allowed_jsonschema_names
    assert imported <= allowed_modules
    for banned in ("chess_workbench", "pydantic", "chess", "httpx", "sanic", "sqlalchemy"):
        assert banned not in imported


def test_isolated_run_imports_no_forbidden_modules(tmp_path: Path) -> None:
    driver = tmp_path / "driver.py"
    report = tmp_path / "report.json"
    driver.write_text(_DRIVER, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(driver),
            str(CONSUMER),
            str(SCHEMA),
            str(SAMPLE),
            str(GOLDEN),
            str(report),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["rc"] == 0
    assert data["stdout_ok"] is True
    assert data["forbidden_modules"] == []


# ---------------------------------------------------------------------------
# 8. Mapping document contains the frozen decisions and boundary
# ---------------------------------------------------------------------------


def test_mapping_document_contains_required_decisions() -> None:
    # Normalize whitespace so prose line-wrapping cannot break phrase matching.
    text = re.sub(r"\s+", " ", MAPPING.read_text(encoding="utf-8"))
    required = [
        "design only",
        "No adapter, API route, table, migration or SQL write exists yet",
        "does not implement anything",
        "ConsumerAdapter",
        "never reused as SQL IDs",
        "not parsed as a path, URL or UUID",
        "PageSpan",
        "SourceSpan",
        "fragment_sha256",
        "persistence-design blocker",
        "section_header",
        "narrative",
        "200-character internal limit",
        "one `move_sequence` block and one root `CourseOccurrence`",
        "sibling_order",
        "sort_order",
        "uci_candidate",
        "python-chess",
        "fen_after",
        "aborts the whole publish transaction",
        "cannot publish while an included node is not `valid`",
        "explicit audited human edit",
        "one NAG",
        "Multiple NAGs block publication",
        "Never silently take the first",
        "KnowledgeNote",
        "exactly one occurrence",
        "human selection",
        "chessboard",
        "no current lossless Block target",
        "Every unresolved item and every error diagnostic blocks publication",
        "one transaction",
        "durable receipt",
        "zero formal partial writes",
        "8A",
        "8B",
        "8C",
        "8D",
        "evidence offset/hash fidelity",
        "multiple NAGs vs. single-NAG `CourseOccurrence`",
        "position-anchor occurrence selection",
        "non-chess figures, heading length and plain-text escaping",
    ]
    for needle in required:
        assert needle in text, needle
