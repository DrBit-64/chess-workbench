"""Standalone example reader for the published CCEF v1 JSON contract.

This file is an *example*, not a stable ChessWorkbench API. It proves the
output boundary is genuinely consumer-neutral: it imports only Python's
standard library and four names from the external ``jsonschema`` package, and
consumes nothing but the checked-in Draft 2020-12 Schema and a JSON package.
It never imports ChessWorkbench, Pydantic, python-chess, provider code, HTTP,
SQL, environment/config code or the repository source tree (``python -I`` from
the repository root must work, proving those are not import paths).

The reader owns a separate, deterministic projection document; it does not
expose ChessWorkbench domain concepts and never mutates the package it reads.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

# jsonschema ships no type stubs; the four imported names are validated by the
# focused tests and the isolated ``python -I`` run.
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
    SchemaError,
    ValidationError,
)

# Identity of the published contract, mirrored from ccef-v1.md. The consumer
# intentionally does not import chess_workbench to obtain these constants.
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "urn:chess-content-extraction:schema:1.0"
CCEF_VERSION = "chess-content-extraction/1.0"

_CONSUMER_FORMAT = "example-ccef-reader/1"
_REJECTED_STDERR = "CCEF consumer rejected the input\n"

# Expected loader failures: JSON syntax, I/O and decoding, schema/validation
# errors and the value errors raised by the manual identity/type/version
# checks. Process-control exceptions and unexpected runtime failures deliberately
# propagate.
_LOADER_ERRORS = (OSError, ValueError, TypeError, SchemaError, ValidationError)

_REFERENCE_KEYWORDS = frozenset({"$ref", "$dynamicRef", "$recursiveRef"})


def _reject_remote_references(value: Any) -> None:
    """Reject references that could make validation leave the input document."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _REFERENCE_KEYWORDS and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                raise ValueError("remote JSON Schema references are not supported")
            _reject_remote_references(child)
    elif isinstance(value, list):
        for child in value:
            _reject_remote_references(child)


def _reject_non_standard_constant(constant: str) -> Any:
    """Reject Python's non-standard NaN/Infinity JSON extensions."""
    raise ValueError(f"non-standard JSON constant {constant!r}")


def load_validated_package(schema_path: Path, package_path: Path) -> dict[str, Any]:
    """Load and validate a CCEF package against the published Schema.

    Raises one of ``_LOADER_ERRORS`` (or a plain ``ValueError`` for the manual
    identity/type/version checks) when the input is rejected. No remote
    reference is ever fetched.
    """
    with open(schema_path, encoding="utf-8") as handle:
        schema = json.load(handle, parse_constant=_reject_non_standard_constant)
    with open(package_path, encoding="utf-8") as handle:
        package = json.load(handle, parse_constant=_reject_non_standard_constant)

    if not isinstance(schema, dict):
        raise ValueError("schema top level must be a JSON object")
    if not isinstance(package, dict):
        raise ValueError("package top level must be a JSON object")
    if schema.get("$schema") != SCHEMA_DIALECT:
        raise ValueError("unsupported JSON Schema dialect")
    if schema.get("$id") != SCHEMA_ID:
        raise ValueError("unexpected JSON Schema id")

    _reject_remote_references(schema)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(package)

    # Defensive version check after Schema validation.
    if package.get("schema_version") != CCEF_VERSION:
        raise ValueError("unsupported CCEF schema version")
    return package


def project_reader_document(package: dict[str, Any]) -> dict[str, Any]:
    """Project a validated package into the deterministic example-reader shape.

    The package is never mutated; mutable sub-objects are deep-copied. Item
    order and move-node order are preserved exactly. An unknown CCEF item kind
    raises ``ValueError`` (unreachable through Schema validation, but checked
    here for direct callers).
    """
    entries = [_project_item(item) for item in package.get("items", [])]
    return {
        "consumer_format": _CONSUMER_FORMAT,
        "schema_version": CCEF_VERSION,
        "package_id": package["package_id"],
        "source": copy.deepcopy(package["source"]),
        "provenance": copy.deepcopy(package["provenance"]),
        "entries": entries,
        "diagnostics": copy.deepcopy(package.get("diagnostics", [])),
        "review_queue": _review_queue(package),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: ``python consumer.py --schema PATH --package PATH``."""
    parser = argparse.ArgumentParser(
        prog="ccef_consumer",
        description="Validate a CCEF v1 package against the published Schema and "
        "emit the example reader projection as JSON on stdout.",
    )
    parser.add_argument("--schema", required=True, type=Path, metavar="PATH")
    parser.add_argument("--package", required=True, type=Path, metavar="PATH")
    args = parser.parse_args(argv)

    try:
        package = load_validated_package(args.schema, args.package)
    except _LOADER_ERRORS:
        sys.stderr.write(_REJECTED_STDERR)
        return 2

    document = project_reader_document(package)
    sys.stdout.write(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return 0


# ---------------------------------------------------------------------------
# Reader projection helpers
# ---------------------------------------------------------------------------


def _common(item: dict[str, Any]) -> dict[str, Any]:
    """Common entry fields with CCEF defaults for externally omitted values."""
    return {
        "type": item["kind"],
        "source_id": item["id"],
        "evidence": copy.deepcopy(item["evidence"]),
        "confidence": item.get("confidence"),
        "warnings": copy.deepcopy(item.get("warnings", [])),
        "extensions": copy.deepcopy(item.get("extensions", {})),
    }


def _project_heading(item: dict[str, Any]) -> dict[str, Any]:
    return {**_common(item), "level": item["level"], "text": item["text"]}


def _project_prose(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common(item),
        "text": item["text"],
        "text_format": item.get("text_format", "plain"),
        "anchor": copy.deepcopy(item.get("anchor")),
    }


def _project_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": node["id"],
        "parent_source_id": node.get("parent_id"),
        "order": node["sibling_order"],
        "move_text": node["move_text"],
        "move_number": node.get("move_number"),
        "side_to_move": node.get("side_to_move"),
        "san": node.get("san_candidate"),
        "uci": node.get("uci_candidate"),
        "status": node.get("validation_status", "unvalidated"),
        "fen_before": node.get("fen_before"),
        "fen_after": node.get("fen_after"),
        "nags": copy.deepcopy(node.get("nags", [])),
        "evidence": copy.deepcopy(node["evidence"]),
        "confidence": node.get("confidence"),
        "warnings": copy.deepcopy(node.get("warnings", [])),
        "extensions": copy.deepcopy(node.get("extensions", {})),
    }


def _project_move_sequence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common(item),
        "title": item.get("title"),
        "initial_position": copy.deepcopy(item["initial_position"]),
        "nodes": [_project_node(node) for node in item["nodes"]],
    }


def _project_figure(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common(item),
        "figure_type": item["figure_type"],
        "caption": item.get("caption"),
        "alt_text": item.get("alt_text"),
        "position_fen_candidate": item.get("position_fen_candidate"),
    }


def _project_unresolved(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common(item),
        "unresolved_type": item["unresolved_type"],
        "reason_code": item["reason_code"],
        "raw_text": item.get("raw_text"),
        "details": item.get("details"),
    }


_ITEM_PROJECTORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "heading": _project_heading,
    "prose": _project_prose,
    "move_sequence": _project_move_sequence,
    "figure": _project_figure,
    "unresolved": _project_unresolved,
}


def _project_item(item: dict[str, Any]) -> dict[str, Any]:
    projector = _ITEM_PROJECTORS.get(item["kind"])
    if projector is None:
        raise ValueError(f"unknown CCEF item kind: {item['kind']!r}")
    return projector(item)


def _dedup(reasons: list[str]) -> list[str]:
    """Remove duplicates while preserving first occurrence."""
    seen: set[str] = set()
    result: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            result.append(reason)
    return result


def _review_queue(package: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic review queue in encounter order.

    Item entries (one per item with warnings, plus the unresolved reason_code
    merged into that item's entry), then one entry per flagged move node, then
    one entry per warning/error diagnostic. Info diagnostics never enter.
    """
    queue: list[dict[str, Any]] = []
    for item in package.get("items", []):
        item_id = item["id"]
        warning_codes = [warning["code"] for warning in item.get("warnings", [])]
        if item["kind"] == "unresolved":
            queue.append(
                {
                    "item_id": item_id,
                    "node_id": None,
                    "reasons": _dedup([item["reason_code"], *warning_codes]),
                }
            )
        elif warning_codes:
            queue.append({"item_id": item_id, "node_id": None, "reasons": warning_codes})

        if item["kind"] == "move_sequence":
            for node in item["nodes"]:
                status = node.get("validation_status", "unvalidated")
                node_warning_codes = [warning["code"] for warning in node.get("warnings", [])]
                if status != "valid" or node_warning_codes:
                    reasons: list[str] = []
                    if status != "valid":
                        reasons.append(f"move_{status}")
                    reasons.extend(node_warning_codes)
                    queue.append(
                        {
                            "item_id": item_id,
                            "node_id": node["id"],
                            "reasons": _dedup(reasons),
                        }
                    )

    for diagnostic in package.get("diagnostics", []):
        if diagnostic["severity"] in ("warning", "error"):
            queue.append(
                {
                    "item_id": diagnostic.get("item_id"),
                    "node_id": diagnostic.get("node_id"),
                    "reasons": [f"diagnostic_{diagnostic['code']}"],
                }
            )
    return queue


if __name__ == "__main__":
    raise SystemExit(main())
