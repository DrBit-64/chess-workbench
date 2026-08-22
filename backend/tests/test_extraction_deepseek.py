"""Focused tests for the DeepSeek V4 Flash transport adapter.

Covers the required behaviors of DS-STAGE8-DEEPSEEK-ADAPTER-01: exact request
mapping (endpoint, headers, deterministic Schema instruction, non-thinking
JSON mode, output bound, no request mutation), successful response mapping,
invalid-response handling, transport/HTTP error and cancellation mapping,
constructor validation, Protocol conformance and import purity.  All HTTP
interactions use ``httpx.MockTransport``; no live DeepSeek call is ever made.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest

from chess_workbench.extraction import DeepSeekV4FlashProvider
from chess_workbench.extraction.provider import (
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredMessage,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "https://api.deepseek.com/chat/completions"
INVALID_RESPONSE_MESSAGE = "DeepSeek returned an invalid response"
OUTPUT_LIMIT_MESSAGE = "Requested output tokens exceed the configured DeepSeek output limit"

_SYSTEM_INSTRUCTION_PREFIX = (
    "Return exactly one JSON object that conforms to the JSON Schema below. "
    "Do not use Markdown fences or add commentary."
)


def _message(
    role: Literal["system", "user", "assistant"] = "user",
    content: str = "Extract the book",
) -> StructuredMessage:
    return StructuredMessage(role=role, content=content)


def _request(**overrides: Any) -> StructuredGenerationRequest:
    values: dict[str, Any] = {
        "messages": [_message()],
        "response_schema_name": "chess_content",
        "response_schema": {},
        "max_output_tokens": 2048,
    }
    values.update(overrides)
    return StructuredGenerationRequest.model_validate(values)


def _ok_payload(
    content: str = '{"ok": true}',
    model: str = "deepseek-v4-flash",
    finish_reason: str | None = "stop",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if usage is None:
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    return {
        "id": "chatcmpl-test-123",
        "object": "chat.completion",
        "created": 1_752_000_000,
        "model": model,
        "system_fingerprint": "fp_provider_private",
        "choices": [
            {
                "index": 0,
                "logprobs": None,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }


def _assert_request_shape(request: httpx.Request) -> None:
    assert request.method == "POST"
    assert str(request.url) == ENDPOINT
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["accept"] == "application/json"
    assert request.headers["content-type"].startswith("application/json")


def _assert_invalid_response_error(error: StructuredGenerationProviderError) -> None:
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert error.message == INVALID_RESPONSE_MESSAGE


# ---------------------------------------------------------------------------
# 1. Successful request mapping
# ---------------------------------------------------------------------------


async def test_successful_request_mapping_with_non_ascii_schema() -> None:
    schema = {
        "type": "object",
        "title": "棋谱抽取",
        "properties": {"标题": {"type": "string"}, "变例": {"type": "array"}},
        "required": ["标题"],
    }
    canonical = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    request = _request(
        messages=[
            _message("system", "你是助手"),
            _message("user", "提取棋谱"),
            _message("assistant", "好的"),
        ],
        response_schema_name="chess_content",
        response_schema=schema,
        max_output_tokens=777,
    )
    expected_system_content = (
        f"{_SYSTEM_INSTRUCTION_PREFIX}\nSchema name: chess_content\nJSON Schema:\n{canonical}"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        _assert_request_shape(req)
        body = json.loads(req.content)
        assert set(body) == {
            "model",
            "messages",
            "thinking",
            "response_format",
            "max_tokens",
            "stream",
        }
        assert body["model"] == "deepseek-v4-flash"
        assert body["thinking"] == {"type": "disabled"}
        assert body["response_format"] == {"type": "json_object"}
        assert body["stream"] is False
        assert body["max_tokens"] == 777
        messages = body["messages"]
        assert messages[0] == {"role": "system", "content": expected_system_content}
        assert messages[1:] == [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "提取棋谱"},
            {"role": "assistant", "content": "好的"},
        ]
        return httpx.Response(200, json=_ok_payload())

    provider = DeepSeekV4FlashProvider(api_key="test-key", transport=httpx.MockTransport(handler))
    snapshot = request.model_dump()
    response = await provider.generate(request)

    assert response.content == '{"ok": true}'
    assert response.provider == "deepseek"
    assert response.model == "deepseek-v4-flash"
    assert response.finish_reason == "stop"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == 15
    # The caller-owned request is never mutated.
    assert request.model_dump() == snapshot


async def test_thinking_profile_is_explicit_and_uses_max_effort() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["thinking"] == {"type": "enabled"}
        assert body["reasoning_effort"] == "max"
        return httpx.Response(200, json=_ok_payload())

    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        thinking_enabled=True,
        transport=httpx.MockTransport(handler),
    )
    response = await provider.generate(_request())
    assert response.content == '{"ok": true}'


async def test_successful_request_mapping_with_empty_schema() -> None:
    request = _request(response_schema={}, max_output_tokens=1)
    expected_system_content = (
        f"{_SYSTEM_INSTRUCTION_PREFIX}\nSchema name: chess_content\nJSON Schema:\n{{}}"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        _assert_request_shape(req)
        body = json.loads(req.content)
        assert body["messages"][0]["content"] == expected_system_content
        assert body["max_tokens"] == 1
        return httpx.Response(200, json=_ok_payload())

    provider = DeepSeekV4FlashProvider(api_key="test-key", transport=httpx.MockTransport(handler))
    response = await provider.generate(request)
    assert response.content == '{"ok": true}'


# ---------------------------------------------------------------------------
# 2. Successful response mapping
# ---------------------------------------------------------------------------


async def test_successful_response_mapping_ignores_private_fields() -> None:
    payload = _ok_payload(
        content='{"moves": "e2e4"}',
        finish_reason="length",
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )
    payload["id"] = "chatcmpl-private"
    payload["created"] = 123
    payload["system_fingerprint"] = "fp-private"
    payload["choices"][0]["logprobs"] = {"tokens": ["a"]}
    payload["choices"][0]["index"] = 7

    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)),
    )
    response = await provider.generate(_request())

    assert response.content == '{"moves": "e2e4"}'
    assert response.provider == "deepseek"
    assert response.model == "deepseek-v4-flash"
    assert response.finish_reason == "length"
    assert response.usage.input_tokens == 0
    assert response.usage.output_tokens == 0
    assert response.usage.total_tokens == 0
    # Provider-private fields never leak into the response.
    assert response.model_dump() == {
        "content": '{"moves": "e2e4"}',
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "finish_reason": "length",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    }


async def test_null_finish_reason_is_invalid_for_non_streaming_response() -> None:
    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=_ok_payload(finish_reason=None))
        ),
    )
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())
    _assert_invalid_response_error(excinfo.value)


@pytest.mark.parametrize("finish_reason", ["content_filter", "tool_calls", "unknown"])
async def test_non_output_finish_reasons_are_invalid_response(finish_reason: str) -> None:
    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=_ok_payload(finish_reason=finish_reason))
        ),
    )
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())
    _assert_invalid_response_error(excinfo.value)


async def test_insufficient_system_resource_is_retryable_unavailable() -> None:
    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, json=_ok_payload(finish_reason="insufficient_system_resource")
            )
        ),
    )
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())
    assert excinfo.value.code == "unavailable"
    assert excinfo.value.retryable is True
    assert str(excinfo.value) == "DeepSeek generation was interrupted"


# ---------------------------------------------------------------------------
# 3. Raw content handling: literal {} valid, empty/whitespace invalid
# ---------------------------------------------------------------------------


async def test_literal_empty_json_object_content_is_valid() -> None:
    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=_ok_payload(content="{}"))
        ),
    )
    response = await provider.generate(_request())
    assert response.content == "{}"
    assert response.model == "deepseek-v4-flash"


@pytest.mark.parametrize("content", ["", "   ", "\n\t  "])
async def test_empty_or_whitespace_content_is_invalid_response(content: str) -> None:
    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=_ok_payload(content=content))
        ),
    )
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())
    _assert_invalid_response_error(excinfo.value)


# ---------------------------------------------------------------------------
# 4. Invalid top-level JSON and malformed required fields
# ---------------------------------------------------------------------------


async def test_invalid_top_level_json_is_invalid_response() -> None:
    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"{broken json")),
    )
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())
    _assert_invalid_response_error(excinfo.value)


async def test_invalid_null_content_records_exact_raw_response() -> None:
    private_marker = "PRIVATE_REASONING_MARKER_16f2"
    raw_body = json.dumps(
        {
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning_content": private_marker,
                    },
                    "finish_reason": "length",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 48_000,
                "total_tokens": 48_010,
            },
        },
        separators=(",", ":"),
    ).encode()
    captures: list[tuple[bytes, int, tuple[str, ...]]] = []

    async def recorder(
        response_bytes: bytes,
        status_code: int,
        diagnostics: tuple[str, ...],
    ) -> None:
        captures.append((response_bytes, status_code, diagnostics))

    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                content=raw_body,
                headers={"content-type": "application/json"},
            )
        ),
        invalid_response_recorder=recorder,
    )

    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())

    _assert_invalid_response_error(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert private_marker not in str(excinfo.value)
    assert captures == [(raw_body, 200, ("content_null",))]


async def test_malformed_json_records_exact_raw_response() -> None:
    raw_body = b'{"private":"PRIVATE_INVALID_JSON_901d"'
    captures: list[tuple[bytes, int, tuple[str, ...]]] = []

    async def recorder(
        response_bytes: bytes,
        status_code: int,
        diagnostics: tuple[str, ...],
    ) -> None:
        captures.append((response_bytes, status_code, diagnostics))

    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                content=raw_body,
                headers={"content-type": "application/json"},
            )
        ),
        invalid_response_recorder=recorder,
    )

    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())

    _assert_invalid_response_error(excinfo.value)
    assert captures == [(raw_body, 200, ("response_json_invalid",))]


async def test_invalid_response_recorder_failure_is_sanitized() -> None:
    private_marker = "PRIVATE_CAPTURE_FAILURE_d179"

    async def recorder(
        response_bytes: bytes,
        status_code: int,
        diagnostics: tuple[str, ...],
    ) -> None:
        raise OSError(private_marker)

    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"not-json")),
        invalid_response_recorder=recorder,
    )

    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())

    assert excinfo.value.code == "invalid_response"
    assert excinfo.value.retryable is False
    assert str(excinfo.value) == (
        "DeepSeek invalid response could not be retained for local diagnosis"
    )
    assert private_marker not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


@pytest.mark.parametrize(
    "payload",
    [
        [1, 2, 3],  # top-level JSON array, not an object
        {},  # missing choices
        {"choices": []},  # empty choices
        {"choices": "not-a-list"},  # choices not a list
        {"choices": [123]},  # first choice not an object
        {"choices": [{}]},  # message missing
        {"choices": [{"message": "not-an-object"}]},  # message not an object
        {"choices": [{"message": {}}]},  # content missing
        {"choices": [{"message": {"content": 123}}]},  # content not a string
        {"choices": [{"message": {"content": "x"}, "finish_reason": 123}]},  # wrong type
        {"choices": [{"message": {"content": "x"}, "finish_reason": "  "}]},  # whitespace
        {  # finish_reason missing
            "choices": [{"message": {"content": "x"}}],
            "model": "m",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 1},
        },
        {  # model missing
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
        },
        {  # model empty
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "",
        },
        {  # model whitespace
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "   ",
        },
        {  # model not a string
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": 123,
        },
        {  # usage missing
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "m",
        },
        {  # usage not an object
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "m",
            "usage": "not-an-object",
        },
        {  # total_tokens missing
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "m",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
        {  # prompt_tokens boolean
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "m",
            "usage": {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 1},
        },
        {  # prompt_tokens negative
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "m",
            "usage": {"prompt_tokens": -1, "completion_tokens": 1, "total_tokens": 1},
        },
        {  # prompt_tokens float
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "m",
            "usage": {"prompt_tokens": 1.5, "completion_tokens": 1, "total_tokens": 1},
        },
        {  # completion_tokens string
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "m",
            "usage": {"prompt_tokens": 1, "completion_tokens": "5", "total_tokens": 1},
        },
        {  # total_tokens boolean
            "choices": [{"message": {"content": "x"}, "finish_reason": None}],
            "model": "m",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": False},
        },
    ],
)
async def test_malformed_response_fields_are_invalid_response(payload: Any) -> None:
    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)),
    )
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())
    _assert_invalid_response_error(excinfo.value)


# ---------------------------------------------------------------------------
# 5. Timeout, transport failure and cancellation propagation
# ---------------------------------------------------------------------------


async def test_timeout_exception_maps_to_timeout() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated connect timeout")

    provider = DeepSeekV4FlashProvider(api_key="test-key", transport=httpx.MockTransport(handler))
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())
    assert excinfo.value.code == "timeout"
    assert excinfo.value.retryable is True
    assert "simulated" not in excinfo.value.message


async def test_generic_transport_error_maps_to_unavailable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection refused")

    provider = DeepSeekV4FlashProvider(api_key="test-key", transport=httpx.MockTransport(handler))
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())
    assert excinfo.value.code == "unavailable"
    assert excinfo.value.retryable is True
    assert "simulated" not in excinfo.value.message


async def test_cancellation_propagates() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    provider = DeepSeekV4FlashProvider(api_key="test-key", transport=httpx.MockTransport(handler))
    with pytest.raises(asyncio.CancelledError):
        await provider.generate(_request())


# ---------------------------------------------------------------------------
# 6. HTTP status mapping with no body/credential leakage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_code", "expected_retryable"),
    [
        (408, "timeout", True),
        (504, "timeout", True),
        (401, "authentication", False),
        (402, "authentication", False),
        (403, "authentication", False),
        (429, "rate_limited", True),
        (400, "invalid_request", False),
        (404, "invalid_request", False),
        (409, "invalid_request", False),
        (422, "invalid_request", False),
        (418, "invalid_request", False),
        (500, "unavailable", True),
        (501, "unavailable", True),
        (502, "unavailable", True),
        (503, "unavailable", True),
        (599, "unavailable", True),
        (301, "unknown", False),
    ],
)
async def test_http_status_error_mapping(
    status: int, expected_code: str, expected_retryable: bool
) -> None:
    secret = "PROVIDER_BODY_SECRET_MARKER"
    body = {"error": {"message": secret, "type": "server_error", "param": None}}
    provider = DeepSeekV4FlashProvider(
        api_key="SUPER_SECRET_KEY",
        transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)),
    )
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())

    error = excinfo.value
    assert error.code == expected_code
    assert error.retryable is expected_retryable
    assert secret not in error.message
    assert secret not in str(error)
    assert "SUPER_SECRET_KEY" not in error.message
    assert "SUPER_SECRET_KEY" not in str(error)
    assert str(error) == error.message


# ---------------------------------------------------------------------------
# 7. Constructor validation, trimmed key, safe repr, output limit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   \n\t", 123, None, b"key"])
def test_constructor_rejects_invalid_api_key(bad: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        DeepSeekV4FlashProvider(api_key=bad)


@pytest.mark.parametrize("bad", [True, "30", 0, -1, 1800.5, float("nan"), float("inf")])
def test_constructor_rejects_invalid_timeout_seconds(bad: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        DeepSeekV4FlashProvider(api_key="k", timeout_seconds=bad)


@pytest.mark.parametrize("bad", [True, "128000", 0, -5, 384_001, 1.5])
def test_constructor_rejects_invalid_max_output_tokens_limit(bad: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        DeepSeekV4FlashProvider(api_key="k", max_output_tokens_limit=bad)


@pytest.mark.parametrize("bad", [0, 1, "true", None])
def test_constructor_rejects_non_boolean_thinking_mode(bad: Any) -> None:
    with pytest.raises(TypeError):
        DeepSeekV4FlashProvider(api_key="k", thinking_enabled=bad)


async def test_api_key_is_trimmed_before_use() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer trimmed-key"
        return httpx.Response(200, json=_ok_payload())

    provider = DeepSeekV4FlashProvider(
        api_key="   trimmed-key   ", transport=httpx.MockTransport(handler)
    )
    response = await provider.generate(_request())
    assert response.content == '{"ok": true}'


def test_repr_does_not_expose_api_key() -> None:
    provider = DeepSeekV4FlashProvider(api_key="super-secret-key")
    assert "super-secret-key" not in repr(provider)


async def test_output_limit_rejected_before_network_io() -> None:
    called: list[bool] = []

    def handler(req: httpx.Request) -> httpx.Response:
        called.append(True)
        return httpx.Response(200, json=_ok_payload())

    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        max_output_tokens_limit=100,
    )
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request(max_output_tokens=101))

    assert excinfo.value.code == "invalid_request"
    assert excinfo.value.retryable is False
    assert excinfo.value.message == OUTPUT_LIMIT_MESSAGE
    assert called == []


async def test_output_limit_equal_to_limit_is_allowed() -> None:
    provider = DeepSeekV4FlashProvider(
        api_key="test-key",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=_ok_payload())),
        max_output_tokens_limit=2048,
    )
    response = await provider.generate(_request(max_output_tokens=2048))
    assert response.content == '{"ok": true}'


@pytest.mark.parametrize("case", ["transport", "json", "pydantic"])
async def test_public_errors_detach_sensitive_provider_exceptions(case: str) -> None:
    secret = "DETACHED_PROVIDER_SECRET"

    def handler(request: httpx.Request) -> httpx.Response:
        if case == "transport":
            raise httpx.ReadTimeout(secret, request=request)
        if case == "json":
            return httpx.Response(200, text=f"{secret} not-json")
        return httpx.Response(200, json=_ok_payload(model=secret * 20))

    provider = DeepSeekV4FlashProvider(
        api_key=secret,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(StructuredGenerationProviderError) as excinfo:
        await provider.generate(_request())

    error = excinfo.value
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in str(error)


# ---------------------------------------------------------------------------
# 8. Runtime Protocol conformance and import purity
# ---------------------------------------------------------------------------


def test_runtime_protocol_conformance() -> None:
    provider = DeepSeekV4FlashProvider(api_key="k")
    assert isinstance(provider, StructuredGenerationProvider)


def test_deepseek_module_imports_without_forbidden_modules() -> None:
    # Load deepseek.py (and its provider.py dependency) standalone with a
    # synthetic package namespace so the real extraction __init__ (which
    # re-exports the CCEF contracts) cannot pollute sys.modules.
    code = (
        "import importlib.util, sys, types; "
        "from pathlib import Path; "
        "root = types.ModuleType('chess_workbench'); sys.modules['chess_workbench'] = root; "
        "pkg = types.ModuleType('chess_workbench.extraction'); "
        "pkg.__path__ = [str(Path('backend/src/chess_workbench/extraction'))]; "
        "sys.modules['chess_workbench.extraction'] = pkg; "
        "spec = importlib.util.spec_from_file_location("
        "'chess_workbench.extraction.provider', "
        "'backend/src/chess_workbench/extraction/provider.py'); "
        "mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; "
        "spec.loader.exec_module(mod); "
        "spec = importlib.util.spec_from_file_location("
        "'chess_workbench.extraction.deepseek', "
        "'backend/src/chess_workbench/extraction/deepseek.py'); "
        "mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; "
        "spec.loader.exec_module(mod); "
        "forbidden = ('chess_workbench.store', 'chess_workbench.services', "
        "'chess_workbench.api', 'chess_workbench.schemas', "
        "'chess_workbench.config', 'chess_workbench.domain', "
        "'chess_workbench.extraction.contracts', "
        "'sqlalchemy', 'sanic', 'pydantic_settings'); "
        "bad = [m for m in forbidden if m in sys.modules]; "
        "print('bad=', bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"forbidden modules imported: {result.stdout}{result.stderr}"


def test_deepseek_source_does_not_mention_cccef_or_http_framework_concepts() -> None:
    source = (
        REPO_ROOT / "backend" / "src" / "chess_workbench" / "extraction" / "deepseek.py"
    ).read_text(encoding="utf-8")
    for token in (
        "ExtractionPackage",
        "contracts",
        "sqlalchemy",
        "sanic",
        "store",
        "services",
        "Settings",
        "pydantic_settings",
    ):
        assert re.search(rf"\b{re.escape(token)}\b", source) is None, (
            f"deepseek.py mentions {token!r}"
        )
