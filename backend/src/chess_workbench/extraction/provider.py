"""Consumer-neutral structured-generation provider port.

This module defines how later DeepSeek/Qwen/OpenAI/local adapters receive
prompts and a caller-owned JSON Schema.  It performs no network call and
knows nothing about CCEF fields: the caller supplies the Schema, and the
provider code never imports or hardcodes the portable extraction format.

It deliberately imports only the standard library and Pydantic so the
port stays dependency-free and testable with a deterministic fake.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Protocol, get_args, runtime_checkable

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

_SCHEMA_NAME = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"

ProviderErrorCode = Literal[
    "authentication",
    "rate_limited",
    "timeout",
    "unavailable",
    "invalid_request",
    "invalid_response",
    "unknown",
]

# Single maintained source: derived from the literal union so the runtime
# constructor check can never drift from the declared public codes.
_PROVIDER_ERROR_CODES: frozenset[str] = frozenset(get_args(ProviderErrorCode))


def _reject_whitespace_only(value: str) -> str:
    """Reject empty/whitespace-only text while preserving the value verbatim."""
    if not value.strip():
        raise ValueError("value must not be empty or whitespace-only")
    return value


def _reject_non_finite(value: JsonValue) -> JsonValue:
    """Reject NaN/Infinity anywhere inside a JSON value (finite JSON numbers)."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("schema values must be finite JSON numbers")
        return value
    if isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
        return value
    if isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)
        return value
    return value


FiniteJsonValue = Annotated[JsonValue, AfterValidator(_reject_non_finite)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StructuredMessage(_StrictModel):
    role: Literal["system", "user", "assistant"]
    # Preserved verbatim: whitespace-only rejected, no trimming of accepted text.
    content: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2_000_000),
        AfterValidator(_reject_whitespace_only),
    ]


class StructuredGenerationRequest(_StrictModel):
    messages: list[StructuredMessage] = Field(min_length=1)
    response_schema_name: Annotated[str, StringConstraints(pattern=_SCHEMA_NAME)]
    response_schema: dict[str, FiniteJsonValue]
    max_output_tokens: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _at_least_one_user_message(self) -> StructuredGenerationRequest:
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("request must contain at least one user message")
        return self


class TokenUsage(_StrictModel):
    input_tokens: Annotated[int | None, Field(ge=0)] = None
    output_tokens: Annotated[int | None, Field(ge=0)] = None
    total_tokens: Annotated[int | None, Field(ge=0)] = None


class StructuredGenerationResponse(_StrictModel):
    content: Annotated[str, AfterValidator(_reject_whitespace_only)]
    provider: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    finish_reason: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    ] = None
    usage: TokenUsage = Field(default_factory=TokenUsage)


class StructuredGenerationProviderError(RuntimeError):
    """Provider-neutral error carrying only code, message and retryability.

    ``message`` is intentionally the only textual payload: raw provider
    response bodies and credentials must never be stored on the error.
    """

    def __init__(self, code: ProviderErrorCode, message: str, retryable: bool) -> None:
        if not isinstance(code, str) or code not in _PROVIDER_ERROR_CODES:
            raise ValueError(f"code must be one of {sorted(_PROVIDER_ERROR_CODES)}, got {code!r}")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be an actual bool")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def __str__(self) -> str:
        return self.message

    def __deepcopy__(self, memo: dict[int, Any]) -> StructuredGenerationProviderError:
        return type(self)(self.code, self.message, self.retryable)


@runtime_checkable
class StructuredGenerationProvider(Protocol):
    async def generate(
        self, request: StructuredGenerationRequest
    ) -> StructuredGenerationResponse: ...


class ScriptedStructuredGenerationProvider:
    """Deterministic sequential fake implementing the provider port.

    Outcomes are consumed strictly in order; every awaited call records a
    deep snapshot of the request and returns a deep copy of the response,
    or raises the scripted error.  Exhaustion raises ``AssertionError``.
    """

    def __init__(
        self,
        outcomes: Sequence[StructuredGenerationResponse | StructuredGenerationProviderError],
    ) -> None:
        validated: list[StructuredGenerationResponse | StructuredGenerationProviderError] = []
        for index, outcome in enumerate(outcomes):
            if isinstance(
                outcome, (StructuredGenerationResponse, StructuredGenerationProviderError)
            ):
                validated.append(copy.deepcopy(outcome))
            else:
                raise TypeError(
                    f"outcome at index {index} must be a "
                    "StructuredGenerationResponse or StructuredGenerationProviderError, "
                    f"got {type(outcome).__name__}"
                )
        self._outcomes = validated
        self._calls: list[StructuredGenerationRequest] = []

    @property
    def calls(self) -> tuple[StructuredGenerationRequest, ...]:
        # Return fresh deep copies so callers can never mutate the internal
        # snapshots through a previously observed calls tuple.
        return tuple(copy.deepcopy(call) for call in self._calls)

    @property
    def remaining(self) -> int:
        return len(self._outcomes)

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResponse:
        self._calls.append(copy.deepcopy(request))
        if not self._outcomes:
            raise AssertionError(
                "ScriptedStructuredGenerationProvider exhausted: no outcomes remaining"
            )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, StructuredGenerationProviderError):
            raise outcome
        return copy.deepcopy(outcome)


__all__ = [
    "FiniteJsonValue",
    "ProviderErrorCode",
    "ScriptedStructuredGenerationProvider",
    "StructuredGenerationProvider",
    "StructuredGenerationProviderError",
    "StructuredGenerationRequest",
    "StructuredGenerationResponse",
    "StructuredMessage",
    "TokenUsage",
]
