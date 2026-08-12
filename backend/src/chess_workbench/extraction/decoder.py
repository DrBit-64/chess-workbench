"""Provider-neutral CCEF decoder (packet DS-STAGE8-CCEF-DECODER-01).

This module is the security boundary that turns one
``StructuredGenerationResponse.content`` string into a strict
``ExtractionPackage``.  It owns JSON syntax, duplicate-key rejection,
structural/reference validation through the accepted CCEF models,
truncated-output rejection and the rule that untrusted model output can
never claim a deterministic chess-validation result:

- provider output may create only ``unvalidated`` move nodes;
- ``valid``/``invalid``/``ambiguous`` statuses and authoritative
  SAN/UCI/FEN fields are produced only by the later local python-chess
  validator (8P-4B).

It deliberately imports only the standard library, Pydantic, the CCEF
contracts and the provider port.  No chess parsing, HTTP, retry, SQL or
filesystem work happens here, and no raw provider content or nested
parser/Pydantic exception is ever retained by the public error.
"""

from __future__ import annotations

import json
from typing import Any, Literal, get_args

from pydantic import ValidationError

from .contracts import ExtractionPackage
from .provider import StructuredGenerationResponse

CcefDecodeErrorCode = Literal[
    "truncated",
    "invalid_json",
    "invalid_package",
    "untrusted_validation",
]

# Single maintained source: derived from the literal union so the runtime
# constructor check can never drift from the declared public codes.
_CCEF_DECODE_ERROR_CODES: frozenset[str] = frozenset(get_args(CcefDecodeErrorCode))

_TRUNCATED_MESSAGE = "Structured generation was truncated"
_INVALID_JSON_MESSAGE = "Structured generation content is not valid JSON"
_UNTRUSTED_MESSAGE = "Provider output may contain only unvalidated move nodes"
_INVALID_PACKAGE_MESSAGE = "Structured generation content is not a valid CCEF package"

# Move-node fields whose presence would claim a deterministic
# chess-validation result; provider output may only omit them or set null.
_AUTHORITATIVE_FIELDS = ("san_candidate", "uci_candidate", "fen_before", "fen_after")


class CcefDecodeError(ValueError):
    """Public decode failure carrying only a fixed code and fixed message.

    ``message`` is intentionally the only textual payload: raw provider
    content, rejected input values and parser/Pydantic exceptions are
    never stored on the error, in ``args``, or in ``__cause__``/
    ``__context__`` (the decoder raises it only after leaving the
    sensitive exception handler).
    """

    def __init__(self, code: CcefDecodeErrorCode, message: str) -> None:
        if not isinstance(code, str) or code not in _CCEF_DECODE_ERROR_CODES:
            raise ValueError(
                f"code must be one of {sorted(_CCEF_DECODE_ERROR_CODES)}, got {code!r}"
            )
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """json.loads ``object_pairs_hook`` that rejects duplicate member names.

    Invoked for every object at any nesting depth; raises before the last
    value could silently win.
    """
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object member name {key!r}")
        result[key] = value
    return result


def _reject_non_standard_constant(constant: str) -> Any:
    """json.loads ``parse_constant`` that rejects NaN/Infinity/-Infinity."""
    raise ValueError(f"non-standard JSON constant {constant!r}")


def _check_untrusted_move_nodes(payload: dict[str, Any]) -> None:
    """Reject any provider-claimed validation result before CCEF validation.

    Only objects whose discriminator is ``kind == "move_sequence"`` are
    inspected.  Every node may omit ``validation_status`` or set it to
    exactly ``"unvalidated"`` and may only omit or null the authoritative
    fields.  Malformed ``items``/``nodes`` shapes are left to ordinary CCEF
    validation, never guessed or repaired.
    """
    items = payload.get("items")
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict) or item.get("kind") != "move_sequence":
            continue
        nodes = item.get("nodes")
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            if not isinstance(node, dict):
                continue
            status = node.get("validation_status")
            if status is not None and status != "unvalidated":
                raise CcefDecodeError("untrusted_validation", _UNTRUSTED_MESSAGE)
            if any(node.get(field) is not None for field in _AUTHORITATIVE_FIELDS):
                raise CcefDecodeError("untrusted_validation", _UNTRUSTED_MESSAGE)


def decode_extraction_response(
    response: StructuredGenerationResponse,
) -> ExtractionPackage:
    """Decode one structured-generation response into a strict package.

    Policy (packet DS-STAGE8-CCEF-DECODER-01):

    1. ``finish_reason == "length"`` is rejected before content is read.
    2. Exactly one JSON value is parsed with the standard library; malformed
       JSON, non-standard constants, duplicate member names and a non-object
       top level are ``invalid_json``.
    3. Provider-claimed validation results are rejected as
       ``untrusted_validation`` before CCEF validation.
    4. Every remaining CCEF failure is ``invalid_package``.
    5. The validated package is returned without mutating ``response``.

    The public error is raised only after leaving the sensitive exception
    handler so Python exception chaining can never retain raw provider
    content or rejected validation input values.
    """
    if response.finish_reason == "length":
        raise CcefDecodeError("truncated", _TRUNCATED_MESSAGE)

    parse_failed = False
    payload: Any = None
    try:
        payload = json.loads(
            response.content,
            parse_constant=_reject_non_standard_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (ValueError, RecursionError):
        # JSONDecodeError (a ValueError) retains the raw source document in
        # .doc and duplicate/constant errors carry value reprs, so the
        # handler must be left before the public error is raised.
        parse_failed = True
    if parse_failed:
        raise CcefDecodeError("invalid_json", _INVALID_JSON_MESSAGE)

    if not isinstance(payload, dict):
        raise CcefDecodeError("invalid_json", _INVALID_JSON_MESSAGE)

    _check_untrusted_move_nodes(payload)

    validation_failed = False
    package: ExtractionPackage | None = None
    try:
        package = ExtractionPackage.model_validate(payload)
    except ValidationError:
        # Pydantic errors embed the rejected input values; detach them for
        # the same reason as above.
        validation_failed = True
    if validation_failed:
        raise CcefDecodeError("invalid_package", _INVALID_PACKAGE_MESSAGE)
    assert package is not None
    return package


__all__ = ["CcefDecodeError", "CcefDecodeErrorCode", "decode_extraction_response"]
