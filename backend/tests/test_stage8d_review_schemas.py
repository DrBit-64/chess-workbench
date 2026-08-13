"""Focused tests for the Stage 8D read-only review document contracts (8D-2A).

Covers: valid construction with exact field order, JSON round trip and
frozen/unknown-field rejection; package/run ID and null page-range validation;
missing/duplicate/unordered/extra page descriptors; content_url run/page,
noncanonical UUID path, media type, byte size and hash validation; stale or
tampered inspection rejection and unvalidated-package error propagation; the
no-secret model dump; and the standalone OpenAPI 3.0 output (no $defs/$ref/
const/type-null, nested CCEF discriminator preserved).  Only synthetic,
non-copyrighted packages are used.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from chess_workbench.api.contracts import openapi_schema
from chess_workbench.extraction.contracts import ExtractionPackage
from chess_workbench.extraction.validation import normalize_chess_moves
from chess_workbench.review.inspection import (
    ReviewInspection,
    inspect_review_candidate,
)
from chess_workbench.schemas.review import (
    PdfReviewDocumentRead,
    PdfReviewPageRead,
    ReviewPageContentPath,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
RUN_ID_PATH = str(RUN_ID)
CCEF_SHA = "a" * 64
PAGE_SHA_5 = "b" * 64
PAGE_SHA_6 = "c" * 64


def _node(
    node_id: str,
    parent_id: str | None,
    order: int,
    move_text: str,
    page: int,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": order,
        "move_text": move_text,
        "evidence": [{"page": page}],
    }


def _package_payload(
    page_range: dict[str, int] | None,
    package_id: str = str(RUN_ID),
) -> dict[str, Any]:
    return {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": package_id,
        "source": {
            "source_ref": "opaque-ref-1",
            "media_type": "application/pdf",
            "language": "en",
            "page_range": page_range,
        },
        "items": [
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": "Chapter",
                "evidence": [{"page": 5}],
            },
            {
                "kind": "move_sequence",
                "id": "seq1",
                "evidence": [{"page": 5}],
                "initial_position": {"kind": "startpos"},
                "nodes": [
                    _node("n1", None, 0, "e4", 5),
                    _node("n2", "n1", 0, "e5", 6),
                ],
            },
        ],
        "provenance": {
            "created_at": "2026-08-11T10:00:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "0.1.0",
        },
    }


_UNSET = object()


def normalized_package(
    page_range: dict[str, int] | object = _UNSET,
    package_id: str = str(RUN_ID),
) -> ExtractionPackage:
    resolved = cast(
        "dict[str, int] | None",
        {"start_page": 5, "end_page": 6} if page_range is _UNSET else page_range,
    )
    payload = _package_payload(resolved, package_id=package_id)
    return normalize_chess_moves(ExtractionPackage.model_validate(payload))


def page_read(physical_page: int, sha: str, content_url: str) -> PdfReviewPageRead:
    return PdfReviewPageRead(
        physical_page=physical_page,
        byte_size=1024,
        content_sha256=sha,
        content_url=content_url,
    )


def document_pages() -> list[PdfReviewPageRead]:
    return [
        page_read(
            5,
            PAGE_SHA_5,
            f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/5",
        ),
        page_read(
            6,
            PAGE_SHA_6,
            f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/6",
        ),
    ]


def build_document(**overrides: Any) -> PdfReviewDocumentRead:
    values: dict[str, Any] = {
        "run_id": RUN_ID,
        "normalized_ccef_sha256": CCEF_SHA,
        "package": normalized_package(),
        "inspection": None,
        "pages": document_pages(),
    }
    values.update(overrides)
    if values.get("inspection") is None:
        values["inspection"] = inspect_review_candidate(values["package"])
    return PdfReviewDocumentRead.model_validate(values)


# ---------------------------------------------------------------------------
# 1. Valid construction, field order, round trip, frozen/unknown rejection
# ---------------------------------------------------------------------------


def test_valid_document_construction_and_exact_field_order() -> None:
    document = build_document()

    assert list(PdfReviewPageRead.model_fields) == [
        "physical_page",
        "media_type",
        "byte_size",
        "content_sha256",
        "content_url",
    ]
    assert list(PdfReviewDocumentRead.model_fields) == [
        "run_id",
        "normalized_ccef_sha256",
        "package",
        "inspection",
        "pages",
    ]
    assert document.run_id == RUN_ID
    assert document.normalized_ccef_sha256 == CCEF_SHA
    assert document.package.package_id == RUN_ID
    assert document.pages[0].media_type == "image/png"


def test_json_round_trip_preserves_the_document() -> None:
    document = build_document()
    restored = PdfReviewDocumentRead.model_validate_json(document.model_dump_json())
    assert restored == document
    assert restored.package.items == document.package.items
    assert restored.inspection == document.inspection


def test_models_are_frozen_and_reject_unknown_fields() -> None:
    document = build_document()
    with pytest.raises(ValidationError):
        document.run_id = UUID("22222222-2222-4222-8222-222222222222")
    with pytest.raises(ValidationError):
        PdfReviewDocumentRead.model_validate(
            {
                **document.model_dump(mode="python"),
                "extra": 1,
            }
        )
    with pytest.raises(ValidationError):
        PdfReviewPageRead.model_validate(
            {
                "physical_page": 5,
                "byte_size": 1,
                "content_sha256": PAGE_SHA_5,
                "content_url": "/x",
                "extra": True,
            }
        )


# ---------------------------------------------------------------------------
# 2. Package/run ID mismatch and null page range
# ---------------------------------------------------------------------------


def test_package_id_mismatch_is_rejected() -> None:
    other = normalized_package(package_id="22222222-2222-4222-8222-222222222222")
    with pytest.raises(ValueError, match="package_id does not match run_id"):
        build_document(package=other.model_copy(deep=True))


def test_null_source_page_range_is_rejected() -> None:
    package = normalized_package(page_range=None)
    inspection = inspect_review_candidate(package)
    with pytest.raises(ValueError, match="source page range is missing"):
        PdfReviewDocumentRead.model_validate(
            {
                "run_id": RUN_ID,
                "normalized_ccef_sha256": CCEF_SHA,
                "package": package,
                "inspection": inspection,
                "pages": document_pages(),
            }
        )


# ---------------------------------------------------------------------------
# 3. Missing, duplicate, unordered and extra page descriptors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pages",
    [
        "missing",
        "duplicate",
        "unordered",
        "extra",
    ],
)
def test_invalid_page_descriptor_sets_are_rejected(pages: str) -> None:
    def make_pages() -> list[PdfReviewPageRead]:
        if pages == "missing":
            return document_pages()[:1]
        if pages == "duplicate":
            return [document_pages()[0], document_pages()[0]]
        if pages == "unordered":
            return [document_pages()[1], document_pages()[0]]
        return document_pages() + [
            page_read(7, "d" * 64, f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/7")
        ]

    with pytest.raises(ValueError, match="page descriptors"):
        build_document(pages=make_pages())


# ---------------------------------------------------------------------------
# 4. content_url, media type, byte size and hash validation
# ---------------------------------------------------------------------------


def test_wrong_run_or_page_in_content_url_is_rejected() -> None:
    other = UUID("22222222-2222-4222-8222-222222222222")
    with pytest.raises(ValueError, match="content_url"):
        build_document(
            pages=[
                page_read(
                    5,
                    PAGE_SHA_5,
                    f"/api/pdf-extractions/{other}/review/pages/5",
                ),
                document_pages()[1],
            ]
        )
    with pytest.raises(ValueError, match="content_url"):
        build_document(
            pages=[
                page_read(5, PAGE_SHA_5, f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/7"),
                document_pages()[1],
            ]
        )


def test_uppercase_noncanonical_uuid_path_is_rejected() -> None:
    lettered = UUID("abcdef01-1234-4678-9abc-def012345678")
    uppercase_path = f"/api/pdf-extractions/{str(lettered).upper()}/review/pages/5"
    assert any(char in uppercase_path for char in "ABCDEF")
    with pytest.raises(ValidationError):
        page_read(5, PAGE_SHA_5, uppercase_path)


def test_non_png_zero_size_and_bad_hash_are_rejected() -> None:
    url5 = f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/5"
    with pytest.raises(ValidationError):
        PdfReviewPageRead(
            physical_page=5,
            media_type=cast(Any, "image/jpeg"),
            byte_size=1,
            content_sha256=PAGE_SHA_5,
            content_url=url5,
        )
    with pytest.raises(ValidationError):
        PdfReviewPageRead(
            physical_page=5,
            byte_size=0,
            content_sha256=PAGE_SHA_5,
            content_url=url5,
        )
    with pytest.raises(ValidationError):
        PdfReviewPageRead(
            physical_page=5,
            byte_size=1,
            content_sha256="zz" * 32,
            content_url=url5,
        )


def test_page_number_boundaries() -> None:
    url = f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/1"
    PdfReviewPageRead(physical_page=1, byte_size=1, content_sha256=PAGE_SHA_5, content_url=url)
    with pytest.raises(ValidationError):
        PdfReviewPageRead(
            physical_page=0,
            byte_size=1,
            content_sha256=PAGE_SHA_5,
            content_url=f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/0",
        )
    with pytest.raises(ValidationError):
        PdfReviewPageRead(
            physical_page=20_001,
            byte_size=1,
            content_sha256=PAGE_SHA_5,
            content_url=f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/20001",
        )


# ---------------------------------------------------------------------------
# 5. Stale inspection and unvalidated-package propagation
# ---------------------------------------------------------------------------


def test_stale_or_tampered_inspection_is_rejected() -> None:
    package = normalized_package()
    correct = inspect_review_candidate(package)
    tampered = correct.model_copy(update={"issue_count": correct.issue_count + 1})
    with pytest.raises(ValueError, match="inspection does not match"):
        PdfReviewDocumentRead.model_validate(
            {
                "run_id": RUN_ID,
                "normalized_ccef_sha256": CCEF_SHA,
                "package": package,
                "inspection": tampered,
                "pages": document_pages(),
            }
        )


def test_unvalidated_package_error_propagates() -> None:
    payload = _package_payload({"start_page": 5, "end_page": 6})
    unvalidated = ExtractionPackage.model_validate(payload)
    inspection = ReviewInspection(
        item_count=len(unvalidated.items),
        move_node_count=1,
        issue_count=0,
        blocking_issue_count=0,
    )
    with pytest.raises(ValueError, match="review candidate must be locally normalized"):
        PdfReviewDocumentRead.model_validate(
            {
                "run_id": RUN_ID,
                "normalized_ccef_sha256": CCEF_SHA,
                "package": unvalidated,
                "inspection": inspection,
                "pages": document_pages(),
            }
        )


# ---------------------------------------------------------------------------
# 6. No provider/raw/path/secret content in the JSON dump
# ---------------------------------------------------------------------------


def test_model_dump_contains_no_secret_or_path_content() -> None:
    document = build_document()
    dumped = json.dumps(document.model_dump(mode="json"))
    assert "package_id" in dumped
    assert "inspection" in json.dumps(document.model_dump(mode="json"))
    assert "physical_page" in dumped
    for forbidden in (
        "provider_response",
        "raw_ccef",
        "relative_path",
        "absolute_path",
        "api_key",
        "ocr_text",
    ):
        assert forbidden not in dumped, f"leaked {forbidden!r}"


# ---------------------------------------------------------------------------
# 7. Standalone OpenAPI 3.0 output
# ---------------------------------------------------------------------------


def _walk(value: Any) -> Any:
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def test_openapi_schema_is_standalone_openapi_30() -> None:
    schema = openapi_schema(PdfReviewDocumentRead)
    nodes = list(_walk(schema))
    for node in nodes:
        if isinstance(node, dict):
            assert "$defs" not in node, "standalone schema contains $defs"
            assert "$ref" not in node, "standalone schema contains $ref"
            assert "const" not in node, "standalone schema contains const"
            assert node.get("type") != "null", "standalone schema contains type null"


def test_openapi_schema_keeps_the_nested_ccef_discriminator() -> None:
    schema = openapi_schema(PdfReviewDocumentRead)
    item_union = schema["properties"]["package"]["properties"]["items"]["items"]
    assert item_union["discriminator"]["propertyName"] == "kind"


def test_openapi_schema_rejects_huge_page_range_with_constant_memory() -> None:
    # A valid normalized package whose declared source range is enormous: the
    # descriptor-count check must reject promptly without materializing it.
    package = normalized_package(
        page_range={"start_page": 1, "end_page": 1_000_000_000},
        package_id=str(RUN_ID),
    )
    inspection = inspect_review_candidate(package)
    with pytest.raises(ValueError, match="page descriptors"):
        PdfReviewDocumentRead.model_validate(
            {
                "run_id": RUN_ID,
                "normalized_ccef_sha256": CCEF_SHA,
                "package": package,
                "inspection": inspection,
                "pages": [],
            }
        )


def test_content_path_alias_constraints() -> None:
    url = f"/api/pdf-extractions/{RUN_ID_PATH}/review/pages/5"
    assert isinstance(url, str)
    assert ReviewPageContentPath is not None
