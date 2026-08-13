"""Focused oracle for the Stage 8A PDF HTTP data contracts (DS-STAGE8A-PDF-API-SCHEMAS-01).

The generic JobRead contract moved out of the engine schema module into
schemas.jobs; these tests prove the frozen field sets, validators, JSON
round trips, OpenAPI 3.0 conversion and the identity-preserving engine
re-export.  All IDs and timestamps are fixed so the suite stays deterministic.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest
from pydantic import ValidationError

from chess_workbench.api.contracts import openapi_schema
from chess_workbench.schemas.jobs import JobRead as JobsJobRead
from chess_workbench.schemas.jobs import JobStatusValue as JobsJobStatus
from chess_workbench.schemas.pdf import (
    PdfAssetEnvelope,
    PdfAssetList,
    PdfAssetRead,
    PdfAssetUploadMetadata,
    PdfCandidateSummary,
    PdfEvidenceSummary,
    PdfExtractionCreate,
    PdfExtractionEnvelope,
    PdfExtractionList,
    PdfExtractionRead,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

ASSET_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_ID = "22222222-2222-4222-8222-222222222222"
SOURCE_VERSION_ID = "33333333-3333-4333-8333-333333333333"
SOURCE_FILE_ID = "44444444-4444-4444-8444-444444444444"
JOB_ID = "55555555-5555-4555-8555-555555555555"
EXTRACTION_ID = "66666666-6666-4666-8666-666666666666"
PDF_ASSET_ID = "77777777-7777-4777-8777-777777777777"

_JOB_READ_CANONICAL_SCHEMA = {
    "additionalProperties": False,
    "properties": {
        "attempt_count": {"title": "Attempt Count", "type": "integer"},
        "cancel_requested_at": {
            "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
            "title": "Cancel Requested At",
        },
        "created_at": {"format": "date-time", "title": "Created At", "type": "string"},
        "id": {"format": "uuid", "title": "Id", "type": "string"},
        "kind": {"minLength": 1, "title": "Kind", "type": "string"},
        "last_error_code": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "title": "Last Error Code",
        },
        "last_error_message": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "title": "Last Error Message",
        },
        "max_attempts": {"title": "Max Attempts", "type": "integer"},
        "payload": {"additionalProperties": True, "title": "Payload", "type": "object"},
        "result": {
            "anyOf": [
                {"additionalProperties": True, "type": "object"},
                {"type": "null"},
            ],
            "title": "Result",
        },
        "status": {
            "enum": ["queued", "running", "succeeded", "failed", "cancelled"],
            "title": "Status",
            "type": "string",
        },
        "updated_at": {"format": "date-time", "title": "Updated At", "type": "string"},
    },
    "required": [
        "id",
        "kind",
        "status",
        "payload",
        "result",
        "attempt_count",
        "max_attempts",
        "cancel_requested_at",
        "last_error_code",
        "last_error_message",
        "created_at",
        "updated_at",
    ],
    "title": "JobRead",
    "type": "object",
}


def _job_payload(status: str = "queued") -> dict[str, object]:
    return {
        "id": JOB_ID,
        "kind": "pdf_extraction",
        "status": status,
        "payload": {},
        "result": None,
        "attempt_count": 0,
        "max_attempts": 3,
        "cancel_requested_at": None,
        "last_error_code": None,
        "last_error_message": None,
        "created_at": "2026-08-11T07:00:00Z",
        "updated_at": "2026-08-11T07:00:00Z",
    }


def _asset_payload() -> dict[str, object]:
    return {
        "id": ASSET_ID,
        "content_sha256": "a" * 64,
        "byte_size": 12_345,
        "page_count": 320,
        "source_id": SOURCE_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "source_file_id": SOURCE_FILE_ID,
        "filename": "zurich-1953.pdf",
        "title": "Zurich 1953",
        "author": "David Bronstein",
        "edition": "Dover",
        "created_at": "2026-08-11T07:00:00Z",
    }


def _extraction_payload() -> dict[str, object]:
    return {
        "id": EXTRACTION_ID,
        "pdf_asset_id": PDF_ASSET_ID,
        "first_page": 3,
        "last_page": 12,
        "pipeline_version": "pdf-extraction:v1",
        "profile": {"mode": "fast"},
        "job": _job_payload(),
        "evidence": None,
        "created_at": "2026-08-11T07:00:00Z",
    }


def test_job_contract_is_owned_by_jobs_and_identity_equal_in_engine() -> None:
    from chess_workbench.schemas.engine import JobRead as EngineJobRead
    from chess_workbench.schemas.engine import JobStatusValue as EngineJobStatus

    assert EngineJobRead is JobsJobRead
    assert EngineJobStatus is JobsJobStatus
    assert JobsJobRead.__module__ == "chess_workbench.schemas.jobs"
    assert EngineJobRead.__module__ == "chess_workbench.schemas.jobs"
    # The status literal still covers exactly the five operational states.
    assert set(get_args(EngineJobStatus)) == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }


def test_job_read_json_schema_is_unchanged_from_engine_shape() -> None:
    assert JobsJobRead.model_json_schema() == _JOB_READ_CANONICAL_SCHEMA


def test_upload_metadata_exact_fields_and_defaults() -> None:
    metadata = PdfAssetUploadMetadata()
    assert set(PdfAssetUploadMetadata.model_fields) == {"title", "author", "edition"}
    assert metadata.title is None
    assert metadata.author is None
    assert metadata.edition is None

    filled = PdfAssetUploadMetadata(title="Book", author="Writer", edition="2nd")
    assert filled.model_dump() == {"title": "Book", "author": "Writer", "edition": "2nd"}


@pytest.mark.parametrize("field", ["title", "author", "edition"])
def test_upload_metadata_applies_title_constraints(field: str) -> None:
    with pytest.raises(ValidationError):
        PdfAssetUploadMetadata(**{field: ""})
    with pytest.raises(ValidationError):
        PdfAssetUploadMetadata(**{field: "   "})
    with pytest.raises(ValidationError):
        PdfAssetUploadMetadata(**{field: "x" * 201})
    accepted = PdfAssetUploadMetadata(**{field: "x" * 200})
    assert getattr(accepted, field) == "x" * 200
    stripped = PdfAssetUploadMetadata(**{field: "  padded  "})
    assert getattr(stripped, field) == "padded"


def test_extraction_create_exact_fields_and_default_profile() -> None:
    create = PdfExtractionCreate.model_validate(
        {"pdf_asset_id": PDF_ASSET_ID, "first_page": 1, "last_page": 1}
    )
    assert set(PdfExtractionCreate.model_fields) == {
        "pdf_asset_id",
        "first_page",
        "last_page",
        "profile",
    }
    assert create.profile == {}
    assert create.pdf_asset_id == UUID(PDF_ASSET_ID)


def test_extraction_create_page_and_profile_validators() -> None:
    with pytest.raises(ValidationError):
        PdfExtractionCreate.model_validate(
            {"pdf_asset_id": PDF_ASSET_ID, "first_page": 0, "last_page": 1}
        )
    with pytest.raises(ValidationError):
        PdfExtractionCreate.model_validate(
            {"pdf_asset_id": PDF_ASSET_ID, "first_page": 1, "last_page": 0}
        )
    # Reverse range is rejected even though every page is >= 1.
    with pytest.raises(ValidationError, match="last_page cannot be less than first_page"):
        PdfExtractionCreate.model_validate(
            {"pdf_asset_id": PDF_ASSET_ID, "first_page": 4, "last_page": 3}
        )
    equal = PdfExtractionCreate.model_validate(
        {"pdf_asset_id": PDF_ASSET_ID, "first_page": 7, "last_page": 7}
    )
    assert (equal.first_page, equal.last_page) == (7, 7)


def test_extraction_read_exact_fields_and_defaults() -> None:
    read = PdfExtractionRead.model_validate(_extraction_payload())
    assert set(PdfExtractionRead.model_fields) == {
        "id",
        "pdf_asset_id",
        "first_page",
        "last_page",
        "pipeline_version",
        "profile",
        "job",
        "evidence",
        "candidate",
        "has_conflicts",
        "created_at",
    }
    assert read.has_conflicts is False
    assert read.evidence is None
    assert read.candidate is None
    assert read.job.id == UUID(JOB_ID)
    assert read.pipeline_version == "pdf-extraction:v1"
    conflicting = PdfExtractionRead.model_validate({**_extraction_payload(), "has_conflicts": True})
    assert conflicting.has_conflicts is True
    # Lax-mode bool coercion follows existing contract conventions; a value
    # pydantic cannot interpret as boolean is still rejected.
    assert PdfExtractionRead.model_fields["has_conflicts"].annotation is bool
    with pytest.raises(ValidationError):
        PdfExtractionRead.model_validate({**_extraction_payload(), "has_conflicts": "maybe"})


def test_read_applies_same_page_order_validation_as_create() -> None:
    with pytest.raises(ValidationError, match="last_page cannot be less than first_page"):
        PdfExtractionRead.model_validate(
            {**_extraction_payload(), "first_page": 12, "last_page": 3}
        )
    with pytest.raises(ValidationError):
        PdfExtractionRead.model_validate({**_extraction_payload(), "first_page": 0})


def test_nested_job_status_validation() -> None:
    for status in ("queued", "running", "succeeded", "failed", "cancelled"):
        read = PdfExtractionRead.model_validate(
            {**_extraction_payload(), "job": _job_payload(status=status)}
        )
        assert read.job.status == status
    with pytest.raises(ValidationError):
        PdfExtractionRead.model_validate(
            {**_extraction_payload(), "job": _job_payload(status="exploded")}
        )
    with pytest.raises(ValidationError):
        PdfExtractionRead.model_validate(
            {**_extraction_payload(), "job": {**_job_payload(), "bogus": 1}}
        )


def test_asset_read_exact_fields_and_no_storage_path() -> None:
    assert set(PdfAssetRead.model_fields) == {
        "id",
        "content_sha256",
        "byte_size",
        "page_count",
        "source_id",
        "source_version_id",
        "source_file_id",
        "filename",
        "title",
        "author",
        "edition",
        "created_at",
    }
    for hidden in ("relative_path", "absolute_path", "storage_path", "path"):
        assert hidden not in PdfAssetRead.model_fields
        with pytest.raises(ValidationError):
            PdfAssetRead.model_validate({**_asset_payload(), hidden: "sources/pdf/ab/x.pdf"})


def test_asset_read_size_and_page_constraints() -> None:
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "byte_size": 0})
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "byte_size": -1})
    PdfAssetRead.model_validate({**_asset_payload(), "byte_size": 1})
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "page_count": 0})
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "page_count": 20_001})
    PdfAssetRead.model_validate({**_asset_payload(), "page_count": 20_000})
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "content_sha256": "abc"})
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "content_sha256": "z" * 64})


def test_asset_read_utc_uuid_json_round_trip() -> None:
    asset = PdfAssetRead.model_validate_json(json.dumps(_asset_payload()))
    assert asset.created_at == datetime(2026, 8, 11, 7, 0, tzinfo=UTC)
    assert asset.id == UUID(ASSET_ID)
    dumped = asset.model_dump(mode="json")
    assert dumped["created_at"] == "2026-08-11T07:00:00Z"
    assert dumped["id"] == ASSET_ID
    assert dumped["content_sha256"] == "a" * 64
    # Python-mode instances accept UUID and aware-UTC datetime objects.
    PdfAssetRead.model_validate(
        {
            **_asset_payload(),
            "id": UUID(ASSET_ID),
            "created_at": datetime(2026, 8, 11, 7, 0, tzinfo=UTC),
        }
    )


def test_timestamps_must_be_aware_utc() -> None:
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "created_at": "2026-08-11T07:00:00"})
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "created_at": "2026-08-11T09:00:00+02:00"})
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "created_at": datetime(2026, 8, 11, 7, 0)})


def test_entity_ids_must_be_uuids() -> None:
    with pytest.raises(ValidationError):
        PdfExtractionCreate.model_validate(
            {"pdf_asset_id": "not-a-uuid", "first_page": 1, "last_page": 1}
        )
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "id": 12345})
    with pytest.raises(ValidationError):
        PdfExtractionRead.model_validate({**_extraction_payload(), "pdf_asset_id": "nope"})


def test_extraction_json_round_trip_with_nested_job() -> None:
    extraction = PdfExtractionRead.model_validate_json(json.dumps(_extraction_payload()))
    assert extraction.job.status == "queued"
    assert extraction.profile == {"mode": "fast"}
    dumped = extraction.model_dump(mode="json")
    assert dumped["created_at"] == "2026-08-11T07:00:00Z"
    assert dumped["job"]["created_at"] == "2026-08-11T07:00:00Z"
    assert dumped["job"]["status"] == "queued"


def test_profile_accepts_ordinary_nested_json_values() -> None:
    profile: dict[str, Any] = {
        "null": None,
        "bool": True,
        "int": 7,
        "float": 0.5,
        "string": "fast",
        "list": [1, "x", False, None],
        "object": {"nested": [1.5, {"deep": 2}]},
    }
    create = PdfExtractionCreate.model_validate(
        {"pdf_asset_id": PDF_ASSET_ID, "first_page": 1, "last_page": 1, "profile": profile}
    )
    assert create.profile == profile
    read = PdfExtractionRead.model_validate({**_extraction_payload(), "profile": profile})
    assert read.profile == profile


@pytest.mark.parametrize(
    "bad_profile",
    [
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": float("-inf")},
        {"x": [1, {"y": float("nan")}]},
        {"x": {"y": {"z": [float("inf")]}}},
    ],
)
def test_profile_rejects_non_finite_numbers_recursively(bad_profile: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="profile values must be finite numbers"):
        PdfExtractionCreate.model_validate(
            {"pdf_asset_id": PDF_ASSET_ID, "first_page": 1, "last_page": 1, "profile": bad_profile}
        )
    with pytest.raises(ValidationError, match="profile values must be finite numbers"):
        PdfExtractionRead.model_validate({**_extraction_payload(), "profile": bad_profile})
    with pytest.raises(ValidationError, match="profile values must be finite numbers"):
        PdfExtractionRead.model_validate_json(
            json.dumps({**_extraction_payload(), "profile": {"x": [float("nan")]}})
        )


def test_profile_is_a_deep_caller_independent_snapshot() -> None:
    source: dict[str, Any] = {"a": [1, 2], "b": {"c": 3}}
    create = PdfExtractionCreate.model_validate(
        {"pdf_asset_id": PDF_ASSET_ID, "first_page": 1, "last_page": 1, "profile": source}
    )
    source["a"].append(99)
    source["b"]["c"] = 100
    source["d"] = True
    assert create.profile == {"a": [1, 2], "b": {"c": 3}}
    assert create.profile is not source

    read_source: dict[str, Any] = {"mode": "fast"}
    read = PdfExtractionRead.model_validate({**_extraction_payload(), "profile": read_source})
    read_source["mode"] = "slow"
    assert read.profile == {"mode": "fast"}


def test_envelopes_and_list_exact_fields() -> None:
    asset = PdfAssetRead.model_validate(_asset_payload())
    envelope = PdfAssetEnvelope(replayed=True, asset=asset)
    assert set(PdfAssetEnvelope.model_fields) == {"replayed", "asset"}
    assert envelope.replayed is True
    assert envelope.asset.id == UUID(ASSET_ID)

    asset_listing = PdfAssetList(items=[asset])
    assert set(PdfAssetList.model_fields) == {"items"}
    assert [item.id for item in asset_listing.items] == [UUID(ASSET_ID)]

    extraction = PdfExtractionRead.model_validate(_extraction_payload())
    extraction_envelope = PdfExtractionEnvelope(replayed=False, extraction=extraction)
    assert set(PdfExtractionEnvelope.model_fields) == {"replayed", "extraction"}
    assert extraction_envelope.extraction.job.status == "queued"

    listing = PdfExtractionList(items=[extraction])
    assert set(PdfExtractionList.model_fields) == {"items"}
    assert [item.id for item in listing.items] == [UUID(EXTRACTION_ID)]

    with pytest.raises(ValidationError):
        PdfAssetEnvelope.model_validate({"replayed": "maybe", "asset": _asset_payload()})


def test_unknown_fields_rejected_at_every_nested_boundary() -> None:
    asset = PdfAssetRead.model_validate(_asset_payload())

    with pytest.raises(ValidationError):
        PdfAssetUploadMetadata.model_validate({"title": "x", "bogus": 1})
    with pytest.raises(ValidationError):
        PdfExtractionCreate.model_validate(
            {"pdf_asset_id": PDF_ASSET_ID, "first_page": 1, "last_page": 1, "bogus": 1}
        )
    with pytest.raises(ValidationError):
        PdfAssetRead.model_validate({**_asset_payload(), "bogus": 1})
    with pytest.raises(ValidationError):
        PdfExtractionRead.model_validate({**_extraction_payload(), "bogus": 1})
    with pytest.raises(ValidationError):
        PdfAssetEnvelope.model_validate(
            {"replayed": False, "asset": asset.model_dump(), "bogus": 1}
        )
    with pytest.raises(ValidationError):
        PdfAssetList.model_validate({"items": [{**_asset_payload(), "bogus": 1}]})
    with pytest.raises(ValidationError):
        PdfAssetEnvelope.model_validate(
            {
                "replayed": False,
                "asset": {**_asset_payload(), "relative_path": "sources/pdf/ab/x.pdf"},
            }
        )
    with pytest.raises(ValidationError):
        PdfExtractionEnvelope.model_validate(
            {"replayed": False, "extraction": {**_extraction_payload(), "bogus": 1}}
        )
    with pytest.raises(ValidationError):
        PdfExtractionList.model_validate({"items": [{**_extraction_payload(), "bogus": 1}]})
    # The create contract must not carry client-supplied hash/path/job/status keys.
    with pytest.raises(ValidationError):
        PdfExtractionCreate.model_validate(
            {
                "pdf_asset_id": PDF_ASSET_ID,
                "first_page": 1,
                "last_page": 1,
                "idempotency_key": "client-key",
            }
        )


def test_models_are_immutable() -> None:
    create = PdfExtractionCreate.model_validate(
        {"pdf_asset_id": PDF_ASSET_ID, "first_page": 1, "last_page": 1}
    )
    asset = PdfAssetRead.model_validate(_asset_payload())
    extraction = PdfExtractionRead.model_validate(_extraction_payload())
    envelope = PdfAssetEnvelope(replayed=False, asset=asset)
    for model in (create, asset, extraction, envelope):
        assert model.model_config.get("frozen") is True
    with pytest.raises(ValidationError):
        create.profile = {"mode": "fast"}
    with pytest.raises(ValidationError):
        asset.title = "renamed"
    with pytest.raises(ValidationError):
        extraction.has_conflicts = True
    with pytest.raises(ValidationError):
        envelope.replayed = True


def test_openapi_30_conversion_has_no_dangling_refs() -> None:
    for model in (
        PdfAssetRead,
        PdfAssetEnvelope,
        PdfAssetList,
        PdfExtractionCreate,
        PdfEvidenceSummary,
        PdfExtractionRead,
        PdfExtractionEnvelope,
        PdfExtractionList,
    ):
        schema = openapi_schema(model)
        rendered = str(schema)
        assert "$defs" not in rendered
        assert "#/$defs" not in rendered
        assert "'const'" not in rendered
    extraction_schema = openapi_schema(PdfExtractionRead)
    assert extraction_schema["type"] == "object"
    # The nested generic job contract is inlined without dangling references.
    job_schema = extraction_schema["properties"]["job"]
    assert job_schema["type"] == "object"
    assert "properties" in job_schema
    assert job_schema["properties"]["status"]["enum"] == [
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    ]


def test_committed_evidence_summary_is_strict_bounded_and_path_free() -> None:
    payload = {
        "status": "committed",
        "page_count": 81,
        "fragment_count": 12_345,
        "warning_count": 2,
        "render_manifest_sha256": "a" * 64,
        "ocr_manifest_sha256": "b" * 64,
    }
    summary = PdfEvidenceSummary.model_validate(payload)
    assert summary.model_dump(mode="json") == payload
    assert summary.model_config.get("frozen") is True
    assert not any("path" in field for field in PdfEvidenceSummary.model_fields)

    for field, value in (
        ("status", "ready"),
        ("page_count", 0),
        ("fragment_count", -1),
        ("fragment_count", 200_001),
        ("warning_count", -1),
        ("warning_count", 20_001),
        ("render_manifest_sha256", "not-a-digest"),
    ):
        with pytest.raises(ValidationError):
            PdfEvidenceSummary.model_validate({**payload, field: value})
    with pytest.raises(ValidationError):
        PdfEvidenceSummary.model_validate({**payload, "relative_path": "derived/secret.json"})


def test_committed_candidate_summary_is_strict_and_path_free() -> None:
    payload = {
        "status": "committed",
        "provider_response_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "response_sha256": "c" * 64,
        "raw_ccef_sha256": "d" * 64,
        "normalized_ccef_sha256": "e" * 64,
        "item_count": 3,
        "move_node_count": 8,
        "figure_count": 0,
        "unresolved_item_count": 1,
        "warning_count": 2,
        "error_count": 0,
        "invalid_move_count": 1,
        "ambiguous_move_count": 0,
        "has_conflicts": True,
    }
    summary = PdfCandidateSummary.model_validate(payload)
    assert summary.model_dump(mode="json") == payload
    assert summary.model_config.get("frozen") is True
    assert not any("path" in field for field in PdfCandidateSummary.model_fields)
    for field, value in (
        ("status", "ready"),
        ("raw_ccef_sha256", "not-a-digest"),
        ("item_count", -1),
        ("has_conflicts", "maybe"),
    ):
        with pytest.raises(ValidationError):
            PdfCandidateSummary.model_validate({**payload, field: value})
    with pytest.raises(ValidationError):
        PdfCandidateSummary.model_validate({**payload, "relative_path": "derived/secret.json"})


def test_schema_modules_import_only_domain_and_jobs() -> None:
    schemas_root = REPO_ROOT / "backend" / "src" / "chess_workbench" / "schemas"
    for filename in ("pdf.py", "jobs.py"):
        tree = ast.parse((schemas_root / filename).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        joined = "\n".join(imported)
        for forbidden in ("sqlalchemy", "sanic", "services", "api", "store", "engine"):
            assert forbidden not in joined, f"{filename} imports {forbidden!r}"
        first_party = {name for name in imported if name.startswith("chess_workbench")}
        assert first_party <= {
            "chess_workbench.schemas.domain",
            "chess_workbench.schemas.jobs",
        }
