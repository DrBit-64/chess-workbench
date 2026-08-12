"""DeepSeek V4 Flash transport adapter for the structured-generation provider port.

This module implements the first real ``StructuredGenerationProvider`` for the
official DeepSeek OpenAI-compatible Chat Completions endpoint (packet
DS-STAGE8-DEEPSEEK-ADAPTER-01).  It is transport only:

- fixed to model ``deepseek-v4-flash`` with non-thinking explicitly disabled;
- requests JSON Object output and injects the caller-owned JSON Schema as a
  deterministic system instruction;
- preserves the raw assistant content for the later decoder;
- maps transport/API failures into the provider-neutral error contract.

It performs no live request in tests and never decodes or validates CCEF:
the caller supplies the Schema and the adapter never imports the portable
extraction contract.
"""

from __future__ import annotations

import json
import math
from typing import Any, cast

import httpx
from pydantic import ValidationError

from .provider import (
    GenerationFinishReason,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    TokenUsage,
)

_MODEL = "deepseek-v4-flash"
_ENDPOINT = "https://api.deepseek.com/chat/completions"

_TIMEOUT_SECONDS_MIN = 1.0
_TIMEOUT_SECONDS_MAX = 1800.0
_MAX_OUTPUT_TOKENS_LIMIT_MIN = 1
_MAX_OUTPUT_TOKENS_LIMIT_MAX = 384_000

_INVALID_RESPONSE_MESSAGE = "DeepSeek returned an invalid response"
_OUTPUT_LIMIT_MESSAGE = "Requested output tokens exceed the configured DeepSeek output limit"
_TIMEOUT_MESSAGE = "DeepSeek request timed out"
_UNAVAILABLE_MESSAGE = "DeepSeek transport unavailable"
_INTERRUPTED_MESSAGE = "DeepSeek generation was interrupted"


def _canonical_schema_json(schema: dict[str, Any]) -> str:
    """Serialize the caller-owned Schema deterministically."""
    return json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _system_instruction(request: StructuredGenerationRequest) -> str:
    """Build the deterministic adapter system instruction for a request."""
    return (
        "Return exactly one JSON object that conforms to the JSON Schema below. "
        "Do not use Markdown fences or add commentary.\n"
        f"Schema name: {request.response_schema_name}\n"
        "JSON Schema:\n"
        f"{_canonical_schema_json(request.response_schema)}"
    )


def _invalid_response_error() -> StructuredGenerationProviderError:
    return StructuredGenerationProviderError("invalid_response", _INVALID_RESPONSE_MESSAGE, False)


def _status_error(status: int) -> StructuredGenerationProviderError:
    """Map a non-2xx HTTP status to the provider-neutral error contract."""
    if status in (408, 504):
        return StructuredGenerationProviderError(
            "timeout", f"DeepSeek request timed out (HTTP {status})", True
        )
    if status in (401, 402, 403):
        return StructuredGenerationProviderError(
            "authentication", f"DeepSeek authentication failed (HTTP {status})", False
        )
    if status == 429:
        return StructuredGenerationProviderError(
            "rate_limited", f"DeepSeek rate limit exceeded (HTTP {status})", True
        )
    if 400 <= status < 500:
        return StructuredGenerationProviderError(
            "invalid_request", f"DeepSeek rejected the request (HTTP {status})", False
        )
    if 500 <= status < 600:
        return StructuredGenerationProviderError(
            "unavailable", f"DeepSeek service unavailable (HTTP {status})", True
        )
    return StructuredGenerationProviderError(
        "unknown", f"DeepSeek returned an unknown error (HTTP {status})", False
    )


def _map_success(body: Any) -> StructuredGenerationResponse:
    """Validate a 2xx DeepSeek body and map it to the port response.

    Every malformed/missing/type-invalid required field maps to
    ``invalid_response``.  Provider-private fields are ignored and never
    surfaced.  The assistant content is preserved verbatim and is never parsed
    as JSON or validated against the Schema here (8P-4 owns both operations).
    """
    if not isinstance(body, dict):
        raise _invalid_response_error()
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _invalid_response_error()
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise _invalid_response_error()
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise _invalid_response_error()
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise _invalid_response_error()
    if "finish_reason" not in first_choice:
        raise _invalid_response_error()
    finish_reason = first_choice["finish_reason"]
    if not isinstance(finish_reason, str):
        raise _invalid_response_error()
    if finish_reason == "insufficient_system_resource":
        raise StructuredGenerationProviderError("unavailable", _INTERRUPTED_MESSAGE, True)
    if finish_reason not in ("stop", "length"):
        raise _invalid_response_error()
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        raise _invalid_response_error()
    usage = body.get("usage")
    if not isinstance(usage, dict):
        raise _invalid_response_error()
    token_counts = (
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        usage.get("total_tokens"),
    )
    for token_count in token_counts:
        if not isinstance(token_count, int) or isinstance(token_count, bool) or token_count < 0:
            raise _invalid_response_error()
    return StructuredGenerationResponse(
        content=content,
        provider="deepseek",
        model=model,
        finish_reason=cast(GenerationFinishReason, finish_reason),
        usage=TokenUsage(
            input_tokens=usage["prompt_tokens"],
            output_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"],
        ),
    )


class DeepSeekV4FlashProvider:
    """Structured-generation provider for the DeepSeek Chat Completions API.

    The API key is constructor-injected only: no environment lookup, no global
    secret access, and ``repr`` never exposes it.  The optional ``transport``
    argument is the httpx test seam; production uses the normal transport.
    Exactly one non-streaming POST is sent per accepted request with no
    automatic retry (retry/backoff orchestration belongs to a later job
    policy).
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 600.0,
        max_output_tokens_limit: int = 128_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(api_key, str):
            raise TypeError("api_key must be a string")
        if not api_key.strip():
            raise ValueError("api_key must not be empty or whitespace-only")
        self._api_key = api_key.strip()
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise TypeError("timeout_seconds must be an actual int or float")
        if not math.isfinite(float(timeout_seconds)):
            raise ValueError("timeout_seconds must be finite")
        if not (_TIMEOUT_SECONDS_MIN <= timeout_seconds <= _TIMEOUT_SECONDS_MAX):
            raise ValueError("timeout_seconds must be in [1, 1800]")
        self._timeout_seconds = float(timeout_seconds)
        if isinstance(max_output_tokens_limit, bool) or not isinstance(
            max_output_tokens_limit, int
        ):
            raise TypeError("max_output_tokens_limit must be an actual int")
        if not (
            _MAX_OUTPUT_TOKENS_LIMIT_MIN <= max_output_tokens_limit <= _MAX_OUTPUT_TOKENS_LIMIT_MAX
        ):
            raise ValueError("max_output_tokens_limit must be in [1, 384000]")
        self._max_output_tokens_limit = max_output_tokens_limit
        self._transport = transport

    def __repr__(self) -> str:
        # Deliberately static: never surface the injected API key.
        return "DeepSeekV4FlashProvider()"

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResponse:
        if request.max_output_tokens > self._max_output_tokens_limit:
            raise StructuredGenerationProviderError("invalid_request", _OUTPUT_LIMIT_MESSAGE, False)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": _system_instruction(request)}
        ]
        messages.extend(
            {"role": message.role, "content": message.content} for message in request.messages
        )
        payload: dict[str, Any] = {
            "model": _MODEL,
            "messages": messages,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        response: httpx.Response | None = None
        mapped_transport_error: StructuredGenerationProviderError | None = None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds), transport=self._transport
            ) as client:
                response = await client.post(_ENDPOINT, headers=headers, json=payload)
        except httpx.TimeoutException:
            mapped_transport_error = StructuredGenerationProviderError(
                "timeout", _TIMEOUT_MESSAGE, True
            )
        except httpx.TransportError:
            mapped_transport_error = StructuredGenerationProviderError(
                "unavailable", _UNAVAILABLE_MESSAGE, True
            )

        # Raise after leaving the provider exception handler. Otherwise Python attaches the raw
        # httpx exception as __context__/__cause__, which can retain the Authorization header.
        if mapped_transport_error is not None:
            raise mapped_transport_error
        assert response is not None

        if response.status_code // 100 != 2:
            raise _status_error(response.status_code)

        malformed_body = False
        body: Any = None
        try:
            body = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            malformed_body = True
        if malformed_body:
            # JSONDecodeError retains its source document, so it must not be chained to the public
            # error where a caller or traceback formatter could recover the provider response.
            raise _invalid_response_error()

        invalid_port_value = False
        mapped_response: StructuredGenerationResponse | None = None
        try:
            mapped_response = _map_success(body)
        except ValidationError:
            invalid_port_value = True
        if invalid_port_value:
            # Pydantic errors include the rejected provider values; detach them for the same reason.
            raise _invalid_response_error()
        assert mapped_response is not None
        return mapped_response


__all__ = ["DeepSeekV4FlashProvider"]
