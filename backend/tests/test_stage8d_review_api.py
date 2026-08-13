"""Focused HTTP tests for the Stage 8D review routes (packet DS-STAGE8D-REVIEW-HTTP-01).

Transport-only wiring: the accepted loader owns real DB/CAS integration, so
here the imported `PdfReviewReadService` symbol in `chess_workbench.api.pdf` is
monkeypatched with a small scripted async fake. A synthetic normalized
package/document is used; no user book, provider, network or sleep is used.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackage
from chess_workbench.extraction.validation import normalize_chess_moves
from chess_workbench.review.inspection import inspect_review_candidate
from chess_workbench.schemas.review import PdfReviewDocumentRead, PdfReviewPageRead
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf_review import PdfReviewPageContent

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
RUN_ID_PATH = str(RUN_ID)
CCEF_SHA = "a" * 64
PAGE5_SHA = "b" * 64
PAGE6_SHA = "c" * 64
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MISSING_ERROR = ServiceError("not_found", 404, "PDF extraction review was not found")
UNAVAILABLE_ERROR = ServiceError("ambiguous_context", 409, "PDF extraction review is not available")
STORAGE_ERROR = ServiceError("source_storage_unavailable", 503, "source storage is unavailable")


def build_app(tmp_path: Path, name: str) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-review-api-{name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}",
            source_storage_root=tmp_path / "storage",
            engine_worker_enabled=False,
            pdf_max_bytes=1024 * 1024,
        )
    )


def _node(
    node_id: str, parent_id: str | None, order: int, move_text: str, page: int
) -> dict[str, Any]:
    return {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": order,
        "move_text": move_text,
        "evidence": [{"page": page}],
    }


def _package_payload(run_id: UUID, first: int, last: int) -> dict[str, Any]:
    return {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": str(run_id),
        "source": {
            "source_ref": "opaque-ref-1",
            "media_type": "application/pdf",
            "language": "en",
            "page_range": {"start_page": first, "end_page": last},
        },
        "items": [
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": "Chapter",
                "evidence": [{"page": first}],
            },
            {
                "kind": "move_sequence",
                "id": "seq1",
                "evidence": [{"page": first}],
                "initial_position": {"kind": "startpos"},
                "nodes": [
                    _node("n1", None, 0, "e4", first),
                    _node("n2", "n1", 0, "e5", last),
                ],
            },
        ],
        "provenance": {
            "created_at": "2026-08-11T10:00:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "0.1.0",
        },
    }


def _synthetic_document() -> PdfReviewDocumentRead:
    package = normalize_chess_moves(
        ExtractionPackage.model_validate(_package_payload(RUN_ID, 5, 6))
    )
    pages = [
        PdfReviewPageRead(
            physical_page=5,
            media_type="image/png",
            byte_size=1024,
            content_sha256=PAGE5_SHA,
            content_url=f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/5",
        ),
        PdfReviewPageRead(
            physical_page=6,
            media_type="image/png",
            byte_size=2048,
            content_sha256=PAGE6_SHA,
            content_url=f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/6",
        ),
    ]
    return PdfReviewDocumentRead(
        run_id=RUN_ID,
        normalized_ccef_sha256=CCEF_SHA,
        package=package,
        inspection=inspect_review_candidate(package),
        pages=pages,
    )


def _synthetic_page() -> PdfReviewPageContent:
    body = PNG_SIGNATURE + b"fixture-page-5"
    return PdfReviewPageContent(
        body=body,
        media_type="image/png",
        byte_size=len(body),
        content_sha256=hashlib.sha256(body).hexdigest(),
    )


def _install_fake(monkeypatch: pytest.MonkeyPatch, state: dict[str, Any]) -> None:
    import chess_workbench.api.pdf as pdf_module

    class _FakeReviewService:
        def __init__(self, session: object, settings: object) -> None:
            self.session = session
            self.settings = settings

        async def read_document(self, run_id: object) -> PdfReviewDocumentRead:
            state["document_calls"].append(run_id)
            if state["document_error"] is not None:
                raise state["document_error"]
            return cast(PdfReviewDocumentRead, state["document"])

        async def read_page(self, run_id: object, physical_page: object) -> PdfReviewPageContent:
            state["page_calls"].append((run_id, physical_page))
            if state["page_error"] is not None:
                raise state["page_error"]
            return cast(PdfReviewPageContent, state["page"])

    monkeypatch.setattr(pdf_module, "PdfReviewReadService", _FakeReviewService)


def _fresh_state() -> dict[str, Any]:
    return {
        "document": _synthetic_document(),
        "page": _synthetic_page(),
        "document_calls": [],
        "page_calls": [],
        "document_error": None,
        "page_error": None,
    }


def _error_payload(response: Any) -> dict[str, Any]:
    return cast(dict[str, Any], response.json)


async def _openapi(client: Any) -> dict[str, Any]:
    _, response = await client.get("/docs/openapi.json")
    assert response.status == 200
    return cast(dict[str, Any], response.json)


def _operation(document: dict[str, Any], operation_id: str) -> dict[str, Any]:
    for methods in document["paths"].values():
        for operation in methods.values():
            if isinstance(operation, dict) and operation.get("operationId") == operation_id:
                return cast(dict[str, Any], operation)
    raise AssertionError(f"operation {operation_id!r} not found")


# ---------------------------------------------------------------------------
# 1. Document GET
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_get_returns_exact_json_and_uuid(tmp_path: Path) -> None:
    app = build_app(tmp_path, "doc")
    client = cast(Any, app.asgi_client)
    state = _fresh_state()
    monkeypatch = pytest.MonkeyPatch()
    _install_fake(monkeypatch, state)
    try:
        _, response = await client.get(f"/api/pdf-extractions/{RUN_ID_PATH}/review")
        assert response.status == 200
        assert response.headers["content-type"].startswith("application/json")
        expected = state["document"].model_dump(mode="json")
        assert response.json == expected
        assert state["document_calls"] == [RUN_ID]
        assert state["page_calls"] == []
    finally:
        monkeypatch.undo()


# ---------------------------------------------------------------------------
# 2. Page GET: routing, bytes, headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_get_returns_exact_bytes_and_headers(tmp_path: Path) -> None:
    app = build_app(tmp_path, "page")
    client = cast(Any, app.asgi_client)
    state = _fresh_state()
    monkeypatch = pytest.MonkeyPatch()
    _install_fake(monkeypatch, state)
    try:
        for physical_page in (5, 6):
            _, response = await client.get(
                f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/{physical_page}"
            )
            assert response.status == 200
            assert response.body == state["page"].body
            headers = response.headers
            assert headers.get("content-type") == "image/png"
            assert headers.get("content-length") == str(state["page"].byte_size)
            assert headers.get("etag") == f'"{state["page"].content_sha256}"'
            assert headers.get("cache-control") == "private, max-age=31536000, immutable"
            assert headers.get("x-content-type-options") == "nosniff"
            assert "content-disposition" not in headers
        assert state["page_calls"] == [(RUN_ID, 5), (RUN_ID, 6)]
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_document_content_urls_are_routable(tmp_path: Path) -> None:
    app = build_app(tmp_path, "routable")
    client = cast(Any, app.asgi_client)
    state = _fresh_state()
    monkeypatch = pytest.MonkeyPatch()
    _install_fake(monkeypatch, state)
    try:
        document = state["document"]
        for page in document.pages:
            _, response = await client.get(page.content_url)
            assert response.status == 200
            assert response.body == state["page"].body
    finally:
        monkeypatch.undo()


# ---------------------------------------------------------------------------
# 3. Stable error propagation on both route families
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_errors_propagate_on_both_route_families(tmp_path: Path) -> None:
    cases = [
        (MISSING_ERROR, 404, "not_found", "PDF extraction review was not found"),
        (UNAVAILABLE_ERROR, 409, "ambiguous_context", "PDF extraction review is not available"),
        (STORAGE_ERROR, 503, "source_storage_unavailable", "source storage is unavailable"),
    ]
    for error, status, code, message in cases:
        app = build_app(tmp_path, f"err-{status}")
        client = cast(Any, app.asgi_client)
        state = _fresh_state()
        state["document_error"] = error
        state["page_error"] = error
        monkeypatch = pytest.MonkeyPatch()
        _install_fake(monkeypatch, state)
        try:
            _, response = await client.get(f"/api/pdf-extractions/{RUN_ID_PATH}/review")
            assert response.status == status
            payload = _error_payload(response)
            assert payload["code"] == code
            assert payload["message"] == message
            assert "fixture" not in json.dumps(payload)
            assert "raw" not in json.dumps(payload)

            _, response = await client.get(f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/5")
            assert response.status == status
            payload = _error_payload(response)
            assert payload["code"] == code
            assert payload["message"] == message
        finally:
            monkeypatch.undo()


# ---------------------------------------------------------------------------
# 4. Malformed paths do not call the service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_paths_do_not_call_service(tmp_path: Path) -> None:
    app = build_app(tmp_path, "malformed")
    client = cast(Any, app.asgi_client)
    state = _fresh_state()
    monkeypatch = pytest.MonkeyPatch()
    _install_fake(monkeypatch, state)
    try:
        urls = [
            "/api/pdf-extractions/not-a-uuid/review",
            "/api/pdf-extractions/not-a-uuid/review/pages/5",
            f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/abc",
            f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/",
        ]
        for url in urls:
            _, response = await client.get(url)
            assert response.status != 200, url
        assert state["document_calls"] == []
        assert state["page_calls"] == []
    finally:
        monkeypatch.undo()


# ---------------------------------------------------------------------------
# 5. OpenAPI operations and schemas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openapi_contains_both_review_operations(tmp_path: Path) -> None:
    app = build_app(tmp_path, "openapi")
    client = cast(Any, app.asgi_client)
    document = await _openapi(client)

    document_operation = _operation(document, "getPdfExtractionReview")
    assert document_operation["tags"] == ["pdf"]
    assert document_operation["summary"] == "Read one verified PDF extraction review document"
    schema = document_operation["responses"]["200"]["content"]["application/json"]["schema"]
    item_union = schema["properties"]["package"]["properties"]["items"]["items"]
    assert item_union["discriminator"]["propertyName"] == "kind"
    for status in ("404", "409", "503"):
        assert "application/json" in document_operation["responses"][status]["content"]

    page_operation = _operation(document, "getPdfExtractionReviewPage")
    assert page_operation["tags"] == ["pdf"]
    assert page_operation["summary"] == "Read one verified rendered PDF review page"
    page_content = page_operation["responses"]["200"]["content"]
    assert set(page_content) == {"image/png"}
    assert page_content["image/png"]["schema"] == {"type": "string", "format": "binary"}
    for status in ("404", "409", "503"):
        assert "application/json" in page_operation["responses"][status]["content"]


# ---------------------------------------------------------------------------
# 6. No secret/path/raw content in responses or OpenAPI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_responses_and_openapi_never_leak_forbidden_values(tmp_path: Path) -> None:
    app = build_app(tmp_path, "noleak")
    client = cast(Any, app.asgi_client)
    state = _fresh_state()
    monkeypatch = pytest.MonkeyPatch()
    _install_fake(monkeypatch, state)
    try:
        _, response = await client.get(f"/api/pdf-extractions/{RUN_ID_PATH}/review")
        assert response.status == 200
        dumped = json.dumps(response.json)
        for forbidden in (
            "provider_response",
            "raw_ccef",
            "relative_path",
            "absolute_path",
            "api_key",
            "ocr_text",
        ):
            assert forbidden not in dumped, f"document leaked {forbidden!r}"
    finally:
        monkeypatch.undo()

    document = await _openapi(client)
    review_operations = [
        _operation(document, "getPdfExtractionReview"),
        _operation(document, "getPdfExtractionReviewPage"),
    ]
    dumped = json.dumps(review_operations)
    for forbidden in (
        "provider_response",
        "raw_ccef",
        "relative_path",
        "absolute_path",
        "api_key",
        "ocr_text",
    ):
        assert forbidden not in dumped, f"review openapi leaked {forbidden!r}"
