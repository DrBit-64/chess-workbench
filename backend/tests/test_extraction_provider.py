"""Focused tests for the consumer-neutral structured-generation provider port.

Covers the required behaviors of DS-STAGE8-PROVIDER-PORT-01: strict value
objects, arbitrary caller-owned Schemas, Protocol conformance, the
deterministic scripted fake, provider errors and import purity.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from chess_workbench.extraction.provider import (
    ScriptedStructuredGenerationProvider,
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    StructuredMessage,
    TokenUsage,
)
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _response(**overrides: Any) -> StructuredGenerationResponse:
    values: dict[str, Any] = {
        "content": '{"ok": true}',
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "usage": TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    }
    values.update(overrides)
    return StructuredGenerationResponse.model_validate(values)


# ---------------------------------------------------------------------------
# Strict value objects
# ---------------------------------------------------------------------------


def test_valid_request_message_response_and_usage() -> None:
    request = _request(
        messages=[_message("system", "Be strict"), _message("user", "Do it")],
        response_schema={"type": "object", "required": ["x"]},
        max_output_tokens=1,
    )
    assert request.messages[0].role == "system"
    assert request.max_output_tokens == 1
    usage = TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0)
    response = _response(usage=usage)
    assert response.usage.input_tokens == 0
    empty = TokenUsage()
    assert empty.input_tokens is None and empty.total_tokens is None


def test_rejects_unknown_fields_at_every_boundary() -> None:
    with pytest.raises(ValidationError):
        StructuredMessage.model_validate({"role": "user", "content": "x", "extra": 1})
    with pytest.raises(ValidationError):
        StructuredGenerationRequest.model_validate({**_request().model_dump(), "surprise": True})
    with pytest.raises(ValidationError):
        TokenUsage.model_validate({"input_tokens": 1, "bogus": "x"})


def test_rejects_booleans_as_integers() -> None:
    with pytest.raises(ValidationError):
        TokenUsage.model_validate({"input_tokens": True})
    with pytest.raises(ValidationError):
        _request(max_output_tokens=True)


def test_rejects_empty_or_whitespace_only_text() -> None:
    with pytest.raises(ValidationError):
        _message(content="")
    with pytest.raises(ValidationError):
        _message(content="   \n\t")
    with pytest.raises(ValidationError):
        _response(content="   ")
    with pytest.raises(ValidationError):
        _response(provider="")
    with pytest.raises(ValidationError):
        _response(model="  ")


def test_message_content_is_preserved_verbatim() -> None:
    message = _message(content="  keep  me  ")
    assert message.content == "  keep  me  "


def test_rejects_missing_user_message() -> None:
    with pytest.raises(ValidationError, match="at least one user"):
        _request(messages=[_message("system", "only system")])
    with pytest.raises(ValidationError):
        _request(messages=[])


def test_rejects_invalid_schema_name() -> None:
    for bad in ("1starts-with-digit", "has space", "has/slash"):
        with pytest.raises(ValidationError):
            _request(response_schema_name=bad)


def test_response_schema_is_required_even_though_empty_schema_is_valid() -> None:
    values = _request().model_dump()
    del values["response_schema"]
    with pytest.raises(ValidationError, match="response_schema"):
        StructuredGenerationRequest.model_validate(values)


def test_rejects_non_finite_nested_schema_values() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError, match="finite JSON numbers"):
            _request(response_schema={"root": {"nested": [1, bad]}})


def test_rejects_negative_usage_and_zero_max_tokens() -> None:
    with pytest.raises(ValidationError):
        TokenUsage.model_validate({"input_tokens": -1})
    with pytest.raises(ValidationError):
        _request(max_output_tokens=0)


# ---------------------------------------------------------------------------
# Arbitrary caller-owned Schemas pass through unchanged
# ---------------------------------------------------------------------------


def test_empty_schema_and_unrelated_schema_pass_through() -> None:
    empty = _request(response_schema={})
    assert empty.response_schema == {}

    schema = {
        "title": "WeatherForecast",
        "type": "object",
        "properties": {
            "city": {"type": "string"},
            "temp_c": {"type": "number"},
        },
        "required": ["city"],
    }
    request = _request(
        response_schema_name="weather_forecast",
        response_schema=schema,
    )
    assert request.response_schema == schema
    round_tripped = StructuredGenerationRequest.model_validate(request.model_dump())
    assert round_tripped.response_schema == schema


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_scripted_fake_is_a_runtime_structured_generation_provider() -> None:
    provider = ScriptedStructuredGenerationProvider([_response()])
    assert isinstance(provider, StructuredGenerationProvider)


# ---------------------------------------------------------------------------
# Scripted fake behavior
# ---------------------------------------------------------------------------


def test_scripted_fifo_success_and_accounting() -> None:
    provider = ScriptedStructuredGenerationProvider(
        [_response(content="one"), _response(content="two")]
    )
    assert provider.remaining == 2
    assert provider.calls == ()

    async def run() -> None:
        await provider.generate(_request())
        await provider.generate(_request())

    asyncio.run(run())
    assert provider.remaining == 0
    assert len(provider.calls) == 2


def test_request_snapshot_is_isolated_from_later_mutation() -> None:
    provider = ScriptedStructuredGenerationProvider([_response()])
    request = _request()

    async def run() -> None:
        await provider.generate(request)
        request.messages[0].content = "MUTATED"

    asyncio.run(run())
    assert provider.calls[0].messages[0].content == "Extract the book"


def test_response_copy_is_isolated_from_stored_outcome() -> None:
    outcome = _response(content="original")
    provider = ScriptedStructuredGenerationProvider([outcome])

    async def run() -> None:
        returned = await provider.generate(_request())
        returned.content = "MUTATED"

    asyncio.run(run())
    assert provider.remaining == 0
    # The original outcome object and provider state are unaffected.
    assert outcome.content == "original"


def test_error_then_success() -> None:
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationProviderError("rate_limited", "slow down", True),
            _response(content="ok after retry"),
        ]
    )

    async def run() -> None:
        with pytest.raises(StructuredGenerationProviderError) as excinfo:
            await provider.generate(_request())
        assert excinfo.value.code == "rate_limited"
        second = await provider.generate(_request())
        assert second.content == "ok after retry"

    asyncio.run(run())
    assert provider.remaining == 0
    assert len(provider.calls) == 2


def test_deterministic_exhaustion_raises_assertion_error() -> None:
    provider = ScriptedStructuredGenerationProvider([_response()])
    assert provider.remaining == 1

    async def run() -> None:
        await provider.generate(_request())
        assert provider.remaining == 0
        with pytest.raises(AssertionError, match="exhausted"):
            await provider.generate(_request())

    asyncio.run(run())
    assert provider.remaining == 0
    # The exhausting call is still recorded as an awaited call.
    assert len(provider.calls) == 2


# ---------------------------------------------------------------------------
# Provider errors
# ---------------------------------------------------------------------------


def test_provider_error_fields_and_string_form() -> None:
    error = StructuredGenerationProviderError("timeout", "upstream timed out", True)
    assert error.code == "timeout"
    assert error.message == "upstream timed out"
    assert error.retryable is True
    assert str(error) == "upstream timed out"
    assert isinstance(error, RuntimeError)

    permanent = StructuredGenerationProviderError("invalid_response", "bad payload", False)
    assert permanent.retryable is False


def test_provider_error_rejects_empty_message() -> None:
    with pytest.raises(ValueError):
        StructuredGenerationProviderError("unknown", "   ", False)


def test_provider_error_has_no_raw_body_attribute() -> None:
    error = StructuredGenerationProviderError("invalid_response", "clean message", False)
    assert not hasattr(error, "body")
    assert not hasattr(error, "raw")


# ---------------------------------------------------------------------------
# Import purity
# ---------------------------------------------------------------------------


def test_provider_module_imports_without_forbidden_modules() -> None:
    # Load provider.py standalone (without executing the extraction package
    # __init__) so the test proves the module's own import graph is pure.
    code = (
        "import importlib.util, sys; "
        "from pathlib import Path; "
        "path = Path('backend/src/chess_workbench/extraction/provider.py'); "
        "spec = importlib.util.spec_from_file_location('_provider_pure', path); "
        "mod = importlib.util.module_from_spec(spec); "
        "sys.modules['_provider_pure'] = mod; "
        "spec.loader.exec_module(mod); "
        "forbidden = ('chess_workbench.store', 'chess_workbench.services', "
        "'chess_workbench.api', 'chess_workbench.schemas.domain', "
        "'chess_workbench.extraction.contracts', "
        "'sqlalchemy', 'sanic', 'httpx', 'aiohttp', 'requests'); "
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


def test_provider_source_does_not_mention_http_or_cccef_concepts() -> None:
    source = (
        REPO_ROOT / "backend" / "src" / "chess_workbench" / "extraction" / "provider.py"
    ).read_text(encoding="utf-8")
    for token in ("http", "aiohttp", "httpx", "requests", "api_key", "ExtractionPackage"):
        assert token not in source.lower(), f"provider.py mentions {token!r}"


# ---------------------------------------------------------------------------
# R1 corrections: error runtime validation, scripted outcome validation,
# calls tuple isolation
# ---------------------------------------------------------------------------


def test_error_rejects_invalid_code() -> None:
    with pytest.raises(ValueError, match="code must be one of"):
        StructuredGenerationProviderError(cast(Any, "not_a_code"), "x", True)
    with pytest.raises(ValueError, match="code must be one of"):
        StructuredGenerationProviderError(cast(Any, 123), "x", True)


def test_error_rejects_non_string_message() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        StructuredGenerationProviderError("timeout", cast(Any, 123), True)


def test_error_rejects_non_bool_retryable() -> None:
    for bad in ("yes", 0, 1, None):
        with pytest.raises(TypeError, match="actual bool"):
            StructuredGenerationProviderError("timeout", "x", cast(Any, bad))


def test_scripted_fake_rejects_invalid_outcomes_at_every_position() -> None:
    with pytest.raises(TypeError, match="index 0"):
        ScriptedStructuredGenerationProvider(cast(Any, [123]))
    with pytest.raises(TypeError, match="index 0"):
        ScriptedStructuredGenerationProvider(cast(Any, ["not an outcome"]))
    with pytest.raises(TypeError, match="index 1"):
        ScriptedStructuredGenerationProvider(cast(Any, [_response(), object(), _response()]))


def test_calls_tuple_mutation_cannot_change_observations() -> None:
    provider = ScriptedStructuredGenerationProvider([_response()])

    async def run() -> None:
        await provider.generate(_request())

    asyncio.run(run())
    first_view = provider.calls
    first_view[0].messages[0].content = "MUTATED via tuple"
    first_view[0].response_schema_name = "mutated_name"

    second_view = provider.calls
    assert second_view[0].messages[0].content == "Extract the book"
    assert second_view[0].response_schema_name == "chess_content"
    assert provider.calls[0].messages[0].content == "Extract the book"
