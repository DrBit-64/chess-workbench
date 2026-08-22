"""Focused tests for local-only failed CCEF response retention."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from chess_workbench.extraction.decoder import (
    CcefDecodeError,
    decode_extraction_response_v1_1,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationResponse,
    TokenUsage,
)
from chess_workbench.services.ccef_failure_debug import (
    CCEF_FAILURE_DEBUG_SCHEMA,
    store_ccef_failure_capture,
    store_deepseek_invalid_response_capture,
)


def _response(content: str) -> StructuredGenerationResponse:
    return StructuredGenerationResponse(
        content=content,
        provider="scripted-provider",
        model="scripted-model",
        finish_reason="stop",
        usage=TokenUsage(),
    )


def test_invalid_package_diagnostics_name_shape_not_rejected_values() -> None:
    private_marker = "rejected-private-value-0f9a"
    with pytest.raises(CcefDecodeError) as caught:
        decode_extraction_response_v1_1(
            _response(json.dumps({"schema_version": private_marker, private_marker: 1}))
        )

    assert caught.value.code == "invalid_package"
    assert "schema_version:literal_error" in caught.value.diagnostics
    assert "package_id:missing" in caught.value.diagnostics
    assert "<field>:extra_forbidden" in caught.value.diagnostics
    assert private_marker not in str(caught.value)
    assert all(private_marker not in item for item in caught.value.diagnostics)


def test_invalid_json_diagnostics_distinguish_safe_failure_classes() -> None:
    with pytest.raises(CcefDecodeError) as syntax_error:
        decode_extraction_response_v1_1(_response('{"items": [\n broken-private-value'))
    assert syntax_error.value.diagnostics == (
        "json_error_line=2",
        "json_error_column=2",
    )

    with pytest.raises(CcefDecodeError) as duplicate_error:
        decode_extraction_response_v1_1(_response('{"private": 1, "private": 2}'))
    assert duplicate_error.value.diagnostics == ("duplicate_object_member=1",)

    with pytest.raises(CcefDecodeError) as constant_error:
        decode_extraction_response_v1_1(_response('{"private": NaN}'))
    assert constant_error.value.diagnostics == ("non_standard_json_constant=1",)


def test_failed_response_is_exact_and_sidecar_is_sanitized(tmp_path: Path) -> None:
    run_id = uuid4()
    job_id = uuid4()
    private_marker = "synthetic-private-model-content-7f4c"
    content = f'{{"items":[{{"text":"{private_marker}"}}]}}\n'
    response = StructuredGenerationResponse(
        content=content,
        provider="scripted-provider",
        model="scripted-model",
        finish_reason="stop",
        usage=TokenUsage(input_tokens=12, output_tokens=7, total_tokens=19),
    )

    first = store_ccef_failure_capture(
        tmp_path,
        run_id=run_id,
        job_id=job_id,
        attempt_count=2,
        pipeline_version="pdf-extraction:v4",
        response=response,
        error_code="ccef_invalid_package",
        error_message="Structured generation content is not a valid CCEF package",
        diagnostics=("schema_version:missing", "items.0.kind:union_tag_not_found"),
    )
    second = store_ccef_failure_capture(
        tmp_path,
        run_id=run_id,
        job_id=job_id,
        attempt_count=2,
        pipeline_version="pdf-extraction:v4",
        response=response,
        error_code="ccef_invalid_package",
        error_message="Structured generation content is not a valid CCEF package",
        diagnostics=("schema_version:missing", "items.0.kind:union_tag_not_found"),
    )

    response_path = tmp_path / first.response.relative_path
    report_path = tmp_path / first.report.relative_path
    assert response_path.read_bytes() == content.encode("utf-8")
    assert first.response.sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert first.response.size_bytes == len(content.encode("utf-8"))
    assert stat.S_IMODE(response_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert second.response.reused is True
    assert second.report.reused is True

    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    assert report == {
        "artifact_schema": CCEF_FAILURE_DEBUG_SCHEMA,
        "attempt_count": 2,
        "failure": {
            "code": "ccef_invalid_package",
            "diagnostics": [
                "schema_version:missing",
                "items.0.kind:union_tag_not_found",
            ],
            "message": "Structured generation content is not a valid CCEF package",
        },
        "job_id": str(job_id),
        "pipeline_version": "pdf-extraction:v4",
        "response": {
            "byte_size": len(content.encode("utf-8")),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "finish_reason": "stop",
            "model": "scripted-model",
            "provider": "scripted-provider",
            "usage": {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
        },
        "run_id": str(run_id),
    }
    assert private_marker.encode() not in report_bytes
    for forbidden in (b"api_key", b"request", b"raw_http", b"absolute_path"):
        assert forbidden not in report_bytes


def test_invalid_provider_body_is_exact_and_sidecar_is_sanitized(tmp_path: Path) -> None:
    run_id = uuid4()
    job_id = uuid4()
    private_marker = b"private-reasoning-content-91af"
    body = b'{"choices":[{"message":{"content":null,"reasoning_content":"' + private_marker
    body += b'"},"finish_reason":"length"}]}'

    first = store_deepseek_invalid_response_capture(
        tmp_path,
        run_id=run_id,
        job_id=job_id,
        attempt_count=1,
        pipeline_version="pdf-extraction:v4",
        response_bytes=body,
        status_code=200,
        diagnostics=("content_null",),
    )
    second = store_deepseek_invalid_response_capture(
        tmp_path,
        run_id=run_id,
        job_id=job_id,
        attempt_count=1,
        pipeline_version="pdf-extraction:v4",
        response_bytes=body,
        status_code=200,
        diagnostics=("content_null",),
    )

    response_path = tmp_path / first.response.relative_path
    report_path = tmp_path / first.report.relative_path
    assert response_path.read_bytes() == body
    assert response_path.suffix == ".bin"
    assert stat.S_IMODE(response_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert second.response.reused is True
    assert second.report.reused is True

    report_bytes = report_path.read_bytes()
    assert json.loads(report_bytes) == {
        "artifact_schema": CCEF_FAILURE_DEBUG_SCHEMA,
        "attempt_count": 1,
        "failure": {
            "code": "invalid_response",
            "diagnostics": ["content_null"],
            "layer": "provider_transport",
            "message": "DeepSeek returned an invalid response",
        },
        "job_id": str(job_id),
        "pipeline_version": "pdf-extraction:v4",
        "response": {
            "byte_size": len(body),
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "http_status": 200,
            "provider": "deepseek",
        },
        "run_id": str(run_id),
    }
    assert private_marker not in report_bytes
    for forbidden in (b"api_key", b"authorization", b"request", b"absolute_path"):
        assert forbidden not in report_bytes


def test_empty_invalid_provider_body_is_still_retained(tmp_path: Path) -> None:
    capture = store_deepseek_invalid_response_capture(
        tmp_path,
        run_id=uuid4(),
        job_id=uuid4(),
        attempt_count=1,
        pipeline_version="pdf-extraction:v4",
        response_bytes=b"",
        status_code=204,
        diagnostics=("response_json_invalid",),
    )

    assert (tmp_path / capture.response.relative_path).read_bytes() == b""
    assert capture.response.size_bytes == 0
