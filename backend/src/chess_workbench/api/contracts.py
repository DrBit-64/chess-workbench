"""Helpers shared by the runtime validator and generated OpenAPI document."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from pydantic import BaseModel, ValidationError
from sanic import Request

from chess_workbench.api.errors import ApiError


def openapi_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a Pydantic schema that is valid OpenAPI 3.0.

    Pydantic emits JSON Schema ``const`` and a dedicated ``null`` type while
    Sanic Extensions currently publishes an OpenAPI 3.0 document.  OpenAPI
    3.0 uses a single-value enum and ``nullable`` for the same contracts,
    including inside nested definitions.
    """

    schema = model.model_json_schema()
    definitions = cast(dict[str, Any], schema.pop("$defs", {}))
    _inline_local_references(schema, definitions, frozenset())
    _convert_to_openapi_30(schema)
    return schema


def _inline_local_references(
    value: Any,
    definitions: dict[str, Any],
    resolving: frozenset[str],
) -> None:
    """Inline Pydantic's private ``$defs`` so each route schema is standalone."""

    if isinstance(value, dict):
        discriminator = value.get("discriminator")
        if isinstance(discriminator, dict):
            # The schemas are inlined below, so Pydantic's mapping to private
            # ``$defs`` would otherwise be a dangling reference.
            discriminator.pop("mapping", None)
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.removeprefix("#/$defs/")
            if name in resolving:
                raise ValueError(f"recursive OpenAPI schema is unsupported: {name}")
            replacement = deepcopy(definitions[name])
            siblings = {key: nested for key, nested in value.items() if key != "$ref"}
            value.clear()
            value.update(replacement)
            value.update(siblings)
            _inline_local_references(value, definitions, resolving | {name})
            return
        for nested in value.values():
            _inline_local_references(nested, definitions, resolving)
    elif isinstance(value, list):
        for nested in value:
            _inline_local_references(nested, definitions, resolving)


def _convert_to_openapi_30(value: Any) -> None:
    """Translate the JSON Schema 2020-12 constructs emitted by Pydantic.

    Sanic Extensions publishes OpenAPI 3.0.3.  Besides not supporting
    ``const``, OpenAPI 3.0 has no ``null`` type: optional values are expressed
    with ``nullable`` on the non-null schema instead.
    """

    if isinstance(value, dict):
        if "const" in value:
            value["enum"] = [value.pop("const")]

        alternatives = value.get("anyOf")
        if isinstance(alternatives, list):
            non_null = [item for item in alternatives if item != {"type": "null"}]
            if len(non_null) != len(alternatives):
                siblings = {key: nested for key, nested in value.items() if key != "anyOf"}
                value.clear()
                if len(non_null) == 1 and isinstance(non_null[0], dict):
                    value.update(non_null[0])
                else:
                    value["anyOf"] = non_null
                value.update(siblings)
                value["nullable"] = True

        if value.get("type") == "null":
            value.pop("type")
            value["enum"] = [None]
            value["nullable"] = True

        for nested in value.values():
            _convert_to_openapi_30(nested)
    elif isinstance(value, list):
        for nested in value:
            _convert_to_openapi_30(nested)


def parse_body[Contract: BaseModel](request: Request, model: type[Contract]) -> Contract:
    """Validate a JSON body and convert validation errors to the stable API shape."""

    try:
        payload = request.json
    except Exception as exc:
        raise ApiError(
            status=422,
            code="validation_error",
            message="request body must contain valid JSON",
        ) from exc

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        errors = cast(list[dict[str, Any]], exc.errors(include_url=False))
        serializable_errors = [
            {
                "type": error["type"],
                "loc": [str(part) for part in error["loc"]],
                "msg": error["msg"],
            }
            for error in errors
        ]
        raise ApiError(
            status=422,
            code="validation_error",
            message="request body failed validation",
            details={"errors": serializable_errors},
        ) from exc
