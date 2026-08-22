"""Local-only capture of failed structured CCEF generations.

Failure captures are deliberately outside the authoritative extraction artifact
index. They retain the model-generated content for diagnosis without exposing it
through the HTTP API or allowing it to masquerade as a reviewable candidate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from chess_workbench.extraction.provider import StructuredGenerationResponse
from chess_workbench.services.source_storage import (
    StoredSourceBlob,
    store_content_addressed_bytes,
)

CCEF_FAILURE_DEBUG_SCHEMA = "chess-workbench/ccef-failure-debug/1.0"


@dataclass(frozen=True, slots=True)
class CcefFailureCapture:
    response: StoredSourceBlob
    report: StoredSourceBlob


def store_ccef_failure_capture(
    storage_root: Path,
    *,
    run_id: UUID,
    job_id: UUID,
    attempt_count: int,
    pipeline_version: str,
    response: StructuredGenerationResponse,
    error_code: str,
    error_message: str,
    diagnostics: tuple[str, ...],
) -> CcefFailureCapture:
    """Persist exact generated content plus a sanitized diagnostic sidecar.

    The response is stored verbatim, but only below the gitignored local debug
    namespace. The sidecar contains no request, API key, raw HTTP body or model
    content. Content addressing makes repeated capture of the same attempt safe.
    """
    if type(attempt_count) is not int or attempt_count < 0:
        raise ValueError("attempt_count must be a non-negative exact integer")
    namespace = f"debug/extraction-failures/{run_id}/attempt-{attempt_count}"
    response_bytes = response.content.encode("utf-8")
    response_blob = store_content_addressed_bytes(
        storage_root,
        namespace=namespace,
        suffix=".txt",
        raw_bytes=response_bytes,
    )
    report_document = {
        "artifact_schema": CCEF_FAILURE_DEBUG_SCHEMA,
        "run_id": str(run_id),
        "job_id": str(job_id),
        "attempt_count": attempt_count,
        "pipeline_version": pipeline_version,
        "failure": {
            "code": error_code,
            "message": error_message,
            "diagnostics": list(diagnostics),
        },
        "response": {
            "content_sha256": response_blob.sha256,
            "byte_size": response_blob.size_bytes,
            "provider": response.provider,
            "model": response.model,
            "finish_reason": response.finish_reason,
            "usage": response.usage.model_dump(mode="json"),
        },
    }
    report_bytes = (
        json.dumps(
            report_document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    report_blob = store_content_addressed_bytes(
        storage_root,
        namespace=namespace,
        suffix=".json",
        raw_bytes=report_bytes,
    )
    return CcefFailureCapture(response=response_blob, report=report_blob)


def store_deepseek_invalid_response_capture(
    storage_root: Path,
    *,
    run_id: UUID,
    job_id: UUID,
    attempt_count: int,
    pipeline_version: str,
    response_bytes: bytes,
    status_code: int,
    diagnostics: tuple[str, ...],
) -> CcefFailureCapture:
    """Persist an invalid 2xx provider body before port-level mapping.

    The HTTP body is a separate local-only binary blob. The sidecar contains
    only bounded adapter-owned diagnostics and never headers, request data,
    credentials or decoded provider values.
    """
    if type(attempt_count) is not int or attempt_count < 0:
        raise ValueError("attempt_count must be a non-negative exact integer")
    if type(response_bytes) is not bytes:
        raise ValueError("response_bytes must be exact bytes")
    if type(status_code) is not int or not 200 <= status_code < 300:
        raise ValueError("status_code must be an exact 2xx integer")
    if (
        type(diagnostics) is not tuple
        or not 1 <= len(diagnostics) <= 20
        or any(
            type(item) is not str or not item or "\n" in item or len(item) > 512
            for item in diagnostics
        )
    ):
        raise ValueError("diagnostics must contain 1 to 20 bounded single-line strings")

    namespace = f"debug/extraction-failures/{run_id}/attempt-{attempt_count}"
    response_blob = store_content_addressed_bytes(
        storage_root,
        namespace=namespace,
        suffix=".bin",
        raw_bytes=response_bytes,
    )
    report_document = {
        "artifact_schema": CCEF_FAILURE_DEBUG_SCHEMA,
        "run_id": str(run_id),
        "job_id": str(job_id),
        "attempt_count": attempt_count,
        "pipeline_version": pipeline_version,
        "failure": {
            "layer": "provider_transport",
            "code": "invalid_response",
            "message": "DeepSeek returned an invalid response",
            "diagnostics": list(diagnostics),
        },
        "response": {
            "content_sha256": response_blob.sha256,
            "byte_size": response_blob.size_bytes,
            "http_status": status_code,
            "provider": "deepseek",
        },
    }
    report_bytes = (
        json.dumps(
            report_document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    report_blob = store_content_addressed_bytes(
        storage_root,
        namespace=namespace,
        suffix=".json",
        raw_bytes=report_bytes,
    )
    return CcefFailureCapture(response=response_blob, report=report_blob)


__all__ = [
    "CCEF_FAILURE_DEBUG_SCHEMA",
    "CcefFailureCapture",
    "store_ccef_failure_capture",
    "store_deepseek_invalid_response_capture",
]
