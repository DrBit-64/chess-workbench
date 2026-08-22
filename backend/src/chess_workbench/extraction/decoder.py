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
import logging
from collections.abc import Mapping
from typing import Any, Literal, get_args

from pydantic import BaseModel, ValidationError

from .contracts import ExtractionPackage, ExtractionPackageV1_1
from .provider import StructuredGenerationResponse

_LOGGER = logging.getLogger(__name__)

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


class _DuplicateMemberError(ValueError):
    """Internal marker for a duplicate JSON object member."""


class _NonStandardConstantError(ValueError):
    """Internal marker for NaN or infinity in JSON."""


def _schema_property_names(model: type[BaseModel]) -> frozenset[str]:
    """Return only contract-owned field names, never provider-owned keys."""
    names: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                names.update(key for key in properties if type(key) is str)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(model.model_json_schema())
    return frozenset(names)


def _sanitized_validation_diagnostic(
    detail: Mapping[str, Any], allowed_fields: frozenset[str]
) -> str:
    location_parts = []
    for part in detail.get("loc", ()):
        if type(part) is int:
            location_parts.append(str(part))
        elif type(part) is str and part in allowed_fields:
            location_parts.append(part)
        else:
            location_parts.append("<field>")
    location = ".".join(location_parts) or "<root>"
    error_type = detail.get("type")
    if type(error_type) is not str or not error_type.replace("_", "").isalnum():
        error_type = "validation_error"
    return f"{location}:{error_type}"[:512]


class CcefDecodeError(ValueError):
    """Public decode failure with a fixed message and sanitized diagnostics.

    Raw provider content, rejected input values and parser/Pydantic exceptions
    are never stored on the error, in ``args``, or in ``__cause__``/
    ``__context__``. Diagnostics contain only bounded field locations and
    validation error types.
    """

    def __init__(
        self,
        code: CcefDecodeErrorCode,
        message: str,
        *,
        diagnostics: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(code, str) or code not in _CCEF_DECODE_ERROR_CODES:
            raise ValueError(
                f"code must be one of {sorted(_CCEF_DECODE_ERROR_CODES)}, got {code!r}"
            )
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if type(diagnostics) is not tuple or any(
            type(item) is not str or not item or "\n" in item or len(item) > 512
            for item in diagnostics
        ):
            raise ValueError("diagnostics must contain bounded single-line strings")
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics

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
            raise _DuplicateMemberError
        result[key] = value
    return result


def _reject_non_standard_constant(constant: str) -> Any:
    """json.loads ``parse_constant`` that rejects NaN/Infinity/-Infinity."""
    del constant
    raise _NonStandardConstantError


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
    payload = _parse_payload(response)
    package = _validate_payload(payload, ExtractionPackage)
    assert isinstance(package, ExtractionPackage)
    return package


def decode_extraction_response_v1_1(
    response: StructuredGenerationResponse,
) -> ExtractionPackageV1_1:
    """Decode one structured-generation response into a strict CCEF 1.1 package.

    Version-explicit: the payload must declare ``schema_version`` 1.1; a 1.0
    package is rejected as ``invalid_package`` and never auto-upgraded. The
    strict parse and the unvalidated-only trust boundary are shared with the
    v1 decoder.
    """
    payload = _parse_payload(response)
    package = _validate_payload(payload, ExtractionPackageV1_1)
    assert isinstance(package, ExtractionPackageV1_1)
    return package


def _parse_payload(response: StructuredGenerationResponse) -> dict[str, Any]:
    """Shared strict parse: truncation wins, then JSON syntax, then root shape."""
    if response.finish_reason == "length":
        raise CcefDecodeError("truncated", _TRUNCATED_MESSAGE)

    parse_diagnostics: tuple[str, ...] = ()
    payload: Any = None
    try:
        payload = json.loads(
            response.content,
            parse_constant=_reject_non_standard_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as error:
        parse_diagnostics = (
            f"json_error_line={error.lineno}",
            f"json_error_column={error.colno}",
        )
    except _DuplicateMemberError:
        parse_diagnostics = ("duplicate_object_member=1",)
    except _NonStandardConstantError:
        parse_diagnostics = ("non_standard_json_constant=1",)
    except RecursionError:
        parse_diagnostics = ("json_nesting_too_deep=1",)
    except ValueError:
        # JSONDecodeError (a ValueError) retains the raw source document in
        # .doc, so the handler must be left before the public error is raised.
        parse_diagnostics = ("json_parser_value_error=1",)
    if parse_diagnostics:
        raise CcefDecodeError(
            "invalid_json",
            _INVALID_JSON_MESSAGE,
            diagnostics=parse_diagnostics,
        )

    if not isinstance(payload, dict):
        raise CcefDecodeError(
            "invalid_json",
            _INVALID_JSON_MESSAGE,
            diagnostics=("json_root_not_object=1",),
        )
    return payload


def _validate_payload[PackageModel: (ExtractionPackage, ExtractionPackageV1_1)](
    payload: dict[str, Any], model: type[PackageModel]
) -> PackageModel:
    """Shared trust boundary: unvalidated-only nodes, then strict model validation."""
    _check_untrusted_move_nodes(payload)
    validation_failed = False
    validation_diagnostics: tuple[str, ...] = ()
    package: PackageModel | None = None
    try:
        package = model.model_validate(payload)
    except ValidationError as error:
        # Pydantic errors embed the rejected input values; detach them for
        # the same reason as above.
        allowed_fields = _schema_property_names(model)
        diagnostics = []
        for detail in error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )[:20]:
            diagnostics.append(_sanitized_validation_diagnostic(detail, allowed_fields))
        _LOGGER.warning(
            "Structured CCEF validation failed for %s: %s",
            model.__name__,
            ", ".join(diagnostics),
        )
        validation_diagnostics = tuple(diagnostics)
        validation_failed = True
    if validation_failed:
        raise CcefDecodeError(
            "invalid_package",
            _INVALID_PACKAGE_MESSAGE,
            diagnostics=validation_diagnostics,
        )
    assert package is not None
    return package


__all__ = [
    "CcefDecodeError",
    "CcefDecodeErrorCode",
    "decode_extraction_response",
    "decode_extraction_response_v1_1",
]
