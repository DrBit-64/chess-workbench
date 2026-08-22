"""DeepSeek V4 Flash transport adapter for the structured-generation provider port.

This module implements the first real ``StructuredGenerationProvider`` for the
official DeepSeek OpenAI-compatible Chat Completions endpoint (packet
DS-STAGE8-DEEPSEEK-ADAPTER-01).  It is transport only:

- fixed to model ``deepseek-v4-flash`` with an explicit, constructor-owned thinking mode;
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
from collections.abc import Awaitable, Callable
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
_CAPTURE_FAILED_MESSAGE = "DeepSeek invalid response could not be retained for local diagnosis"

DeepSeekInvalidResponseRecorder = Callable[[bytes, int, tuple[str, ...]], Awaitable[None]]


class _InvalidResponseShapeError(ValueError):
    """Adapter-owned shape failure with no provider-owned values."""

    def __init__(self, diagnostic: str) -> None:
        super().__init__(diagnostic)
        self.diagnostic = diagnostic


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


def _invalid_shape(diagnostic: str) -> _InvalidResponseShapeError:
    return _InvalidResponseShapeError(diagnostic)


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
        raise _invalid_shape("response_root_not_object")
    choices = body.get("choices")
    if not isinstance(choices, list):
        raise _invalid_shape("choices_not_array")
    if not choices:
        raise _invalid_shape("choices_empty")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise _invalid_shape("first_choice_not_object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise _invalid_shape("message_not_object")
    if "content" not in message:
        raise _invalid_shape("content_missing")
    content = message["content"]
    if content is None:
        raise _invalid_shape("content_null")
    if not isinstance(content, str):
        raise _invalid_shape("content_wrong_type")
    if not content.strip():
        raise _invalid_shape("content_blank")
    if "finish_reason" not in first_choice:
        raise _invalid_shape("finish_reason_missing")
    finish_reason = first_choice["finish_reason"]
    if not isinstance(finish_reason, str):
        raise _invalid_shape("finish_reason_wrong_type")
    if finish_reason == "insufficient_system_resource":
        raise StructuredGenerationProviderError("unavailable", _INTERRUPTED_MESSAGE, True)
    if finish_reason not in ("stop", "length"):
        raise _invalid_shape("finish_reason_unsupported")
    if "model" not in body:
        raise _invalid_shape("model_missing")
    model = body.get("model")
    if not isinstance(model, str):
        raise _invalid_shape("model_wrong_type")
    if not model.strip():
        raise _invalid_shape("model_blank")
    if "usage" not in body:
        raise _invalid_shape("usage_missing")
    usage = body.get("usage")
    if not isinstance(usage, dict):
        raise _invalid_shape("usage_not_object")
    token_counts = (
        ("prompt_tokens", usage.get("prompt_tokens")),
        ("completion_tokens", usage.get("completion_tokens")),
        ("total_tokens", usage.get("total_tokens")),
    )
    for field_name, token_count in token_counts:
        if field_name not in usage:
            raise _invalid_shape(f"{field_name}_missing")
        if not isinstance(token_count, int) or isinstance(token_count, bool) or token_count < 0:
            raise _invalid_shape(f"{field_name}_invalid")
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
        thinking_enabled: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        invalid_response_recorder: DeepSeekInvalidResponseRecorder | None = None,
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
        if type(thinking_enabled) is not bool:
            raise TypeError("thinking_enabled must be an actual boolean")
        self._thinking_enabled = thinking_enabled
        self._transport = transport
        if invalid_response_recorder is not None and not callable(invalid_response_recorder):
            raise TypeError("invalid_response_recorder must be callable")
        self._invalid_response_recorder = invalid_response_recorder

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
            "thinking": {"type": "enabled" if self._thinking_enabled else "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if self._thinking_enabled:
            payload["reasoning_effort"] = "max"
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
            await self._record_invalid_response(response, ("response_json_invalid",))
            raise _invalid_response_error() from None

        invalid_diagnostics: tuple[str, ...] | None = None
        mapped_response: StructuredGenerationResponse | None = None
        try:
            mapped_response = _map_success(body)
        except _InvalidResponseShapeError as error:
            invalid_diagnostics = (error.diagnostic,)
        except ValidationError:
            invalid_diagnostics = ("mapped_response_validation_failed",)
        if invalid_diagnostics is not None:
            # Pydantic errors include the rejected provider values; detach them for the same reason.
            await self._record_invalid_response(response, invalid_diagnostics)
            raise _invalid_response_error() from None
        assert mapped_response is not None
        return mapped_response

    async def _record_invalid_response(
        self,
        response: httpx.Response,
        diagnostics: tuple[str, ...],
    ) -> None:
        if self._invalid_response_recorder is None:
            return
        capture_failed = False
        try:
            await self._invalid_response_recorder(
                response.content,
                response.status_code,
                diagnostics,
            )
        except Exception:
            capture_failed = True
        if capture_failed:
            raise StructuredGenerationProviderError(
                "invalid_response",
                _CAPTURE_FAILED_MESSAGE,
                False,
            ) from None


__all__ = ["DeepSeekInvalidResponseRecorder", "DeepSeekV4FlashProvider"]
