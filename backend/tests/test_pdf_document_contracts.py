"""Focused 8D-3E2B OpenAPI contract oracles for incremental PDF extraction documents.

Asserts the frozen public contract of the four document operations against the
generated ``backend/openapi.json`` and the generated TypeScript client. The
contract is machine-generated only: any drift here means the routes or schemas
changed without regenerating ``make contracts``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"

FROZEN_OPERATIONS: dict[str, tuple[str, str]] = {
    "createPdfExtractionDocument": ("/api/pdf-extraction-documents", "post"),
    "listPdfExtractionDocuments": ("/api/pdf-extraction-documents", "get"),
    "getPdfExtractionDocument": ("/api/pdf-extraction-documents/{document_id}", "get"),
    "createPdfExtractionDocumentAppend": (
        "/api/pdf-extraction-documents/{document_id}/appends",
        "post",
    ),
}

# CAS relative_path, provider/raw response fields, API keys and OCR text must
# never leak into the public document operations.
FORBIDDEN_FIELD_MARKERS = (
    "relative_path",
    "provider_response",
    "raw_ccef",
    "api_key",
    "ocr_text",
    "provider",
    "secret",
    "deepseek",
)


def _openapi_document() -> Any:
    with (BACKEND_ROOT / "openapi.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def _operation(doc: Any, operation_id: str) -> Any:
    path, method = FROZEN_OPERATIONS[operation_id]
    paths = doc["paths"]
    assert path in paths, f"missing frozen path {path}"
    assert method in paths[path], f"missing {method.upper()} {path}"
    op = paths[path][method]
    assert op.get("operationId") == operation_id, f"operationId mismatch for {path} {method}"
    return op


def _response_schema(doc: Any, operation_id: str, status: str) -> Any:
    op = _operation(doc, operation_id)
    responses = op["responses"]
    assert status in responses, f"missing response {status} on {operation_id}"
    return responses[status]["content"]["application/json"]["schema"]


def _collect_property_names(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            for name in props:
                out.add(str(name))
        for value in node.values():
            _collect_property_names(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_property_names(value, out)


def test_openapi_contains_exactly_the_frozen_operations() -> None:
    doc = _openapi_document()
    paths = doc["paths"]
    for operation_id, (path, method) in FROZEN_OPERATIONS.items():
        assert path in paths, f"missing frozen path {path}"
        assert method in paths[path], f"missing {method.upper()} {path}"
        assert paths[path][method].get("operationId") == operation_id
    # No other pdf-extraction-document operation may exist.
    for path, methods in paths.items():
        if "/api/pdf-extraction-documents" not in path:
            continue
        for method, op in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            assert op.get("operationId") in FROZEN_OPERATIONS, (
                f"unexpected document operation {op.get('operationId')} at {path}"
            )


def test_create_document_contract() -> None:
    doc = _openapi_document()
    op = _operation(doc, "createPdfExtractionDocument")
    assert sorted(op["responses"].keys()) == ["200", "201", "404", "409", "503"]
    body = op["requestBody"]
    assert body.get("required") is True
    create_schema = body["content"]["application/json"]["schema"]
    assert create_schema.get("title") == "PdfExtractionDocumentCreate"
    assert sorted(create_schema.get("properties", {}).keys()) == ["initial_run_id"]
    assert create_schema.get("required") == ["initial_run_id"]
    envelope = _response_schema(doc, "createPdfExtractionDocument", "201")
    assert envelope.get("title") == "PdfExtractionDocumentEnvelope"
    assert sorted(envelope.get("properties", {}).keys()) == ["document", "replayed"]


def test_list_documents_contract() -> None:
    doc = _openapi_document()
    op = _operation(doc, "listPdfExtractionDocuments")
    assert sorted(op["responses"].keys()) == ["200"]
    schema = _response_schema(doc, "listPdfExtractionDocuments", "200")
    assert schema.get("title") == "PdfExtractionDocumentList"
    assert sorted(schema.get("properties", {}).keys()) == ["items"]


def test_get_document_contract() -> None:
    doc = _openapi_document()
    op = _operation(doc, "getPdfExtractionDocument")
    assert sorted(op["responses"].keys()) == ["200", "404"]
    params = op.get("parameters", [])
    assert any(
        p.get("name") == "document_id" and p.get("in") == "path" and p.get("required") is True
        for p in params
    ), "getPdfExtractionDocument must declare the required document_id path parameter"
    schema = _response_schema(doc, "getPdfExtractionDocument", "200")
    assert schema.get("title") == "PdfExtractionDocumentRead"


def test_append_document_contract() -> None:
    doc = _openapi_document()
    op = _operation(doc, "createPdfExtractionDocumentAppend")
    assert sorted(op["responses"].keys()) == ["200", "202", "404", "409", "422"]
    params = op.get("parameters", [])
    assert any(
        p.get("name") == "Idempotency-Key"
        and p.get("in") == "header"
        and p.get("required") is False
        and p.get("schema", {}).get("type") == "string"
        for p in params
    ), "append must declare the optional Idempotency-Key header parameter"
    assert any(
        p.get("name") == "document_id" and p.get("in") == "path" and p.get("required") is True
        for p in params
    ), "append must declare the required document_id path parameter"
    body = op["requestBody"]
    assert body.get("required") is True
    append_schema = body["content"]["application/json"]["schema"]
    assert append_schema.get("title") == "PdfExtractionDocumentAppendCreate"
    assert sorted(append_schema.get("properties", {}).keys()) == [
        "expected_version",
        "first_page",
        "last_page",
        "profile",
    ]
    assert append_schema.get("required") == ["expected_version", "first_page", "last_page"]
    expected_version = append_schema["properties"]["expected_version"]
    assert expected_version.get("type") == "integer"
    assert expected_version.get("minimum") == 1
    for page in ("first_page", "last_page"):
        prop = append_schema["properties"][page]
        assert prop.get("type") == "integer"
        assert prop.get("minimum") == 1
        assert prop.get("maximum") == 20000
    assert append_schema["properties"]["profile"].get("type") == "object"
    envelope = _response_schema(doc, "createPdfExtractionDocumentAppend", "202")
    assert envelope.get("title") == "PdfExtractionDocumentAppendEnvelope"
    assert sorted(envelope.get("properties", {}).keys()) == ["append", "document", "replayed"]


def test_document_read_shape_is_grouped_and_leak_free() -> None:
    doc = _openapi_document()
    schema = _response_schema(doc, "getPdfExtractionDocument", "200")
    assert schema.get("title") == "PdfExtractionDocumentRead"
    assert sorted(schema.get("properties", {}).keys()) == [
        "append_attempts",
        "created_at",
        "first_page",
        "id",
        "last_page",
        "normalized_ccef_sha256",
        "pdf_asset_id",
        "revisions",
        "segments",
        "updated_at",
        "version",
    ]
    segments = schema["properties"]["segments"]["items"]
    assert segments.get("title") == "PdfExtractionDocumentSegmentRead"
    assert "run_id" in segments.get("properties", {})
    assert "ordinal" in segments.get("properties", {})
    revisions = schema["properties"]["revisions"]["items"]
    assert revisions.get("title") == "PdfExtractionDocumentRevisionRead"
    assert "revision_number" in revisions.get("properties", {})
    assert "terminal_segment_id" in revisions.get("properties", {})
    appends = schema["properties"]["append_attempts"]["items"]
    assert appends.get("title") == "PdfExtractionDocumentAppendRead"
    job = appends["properties"]["job"]
    assert "status" in job.get("properties", {})
    assert "run_id" in appends.get("properties", {})

    # Recursively scan every schema of the four frozen operations for leaks.
    collected: set[str] = set()
    for operation_id in FROZEN_OPERATIONS:
        op = _operation(doc, operation_id)
        _collect_property_names(op, collected)
    leaks = sorted(
        name for name in collected if any(marker in name for marker in FORBIDDEN_FIELD_MARKERS)
    )
    assert leaks == [], f"forbidden fields leaked into the public contract: {leaks}"


def test_error_responses_use_shared_strict_schema() -> None:
    doc = _openapi_document()
    for operation_id, statuses in (
        ("createPdfExtractionDocument", ("404", "409", "503")),
        ("createPdfExtractionDocumentAppend", ("404", "409", "422")),
        ("getPdfExtractionDocument", ("404",)),
    ):
        for status in statuses:
            schema = _response_schema(doc, operation_id, status)
            assert schema.get("title") == "ErrorResponse", (
                f"{operation_id} {status} must use the shared ErrorResponse schema"
            )
            assert sorted(schema.get("properties", {}).keys()) == ["code", "details", "message"]
            assert schema.get("required") == ["code", "message"]


def test_generated_typescript_contains_document_paths() -> None:
    generated = FRONTEND_ROOT / "src/types/api.generated.ts"
    source = generated.read_text(encoding="utf-8")
    for path in (
        "/api/pdf-extraction-documents",
        "/api/pdf-extraction-documents/{document_id}",
        "/api/pdf-extraction-documents/{document_id}/appends",
    ):
        assert path in source, f"generated TypeScript missing path {path}"
