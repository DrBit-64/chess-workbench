"""Focused tests for the read-only Stage 8D review loader (8D-2B1).

Uses a temporary SQLite database and a temporary CAS with a synthetic
two-page normalized package, render manifest and PNG-signature payloads.
Covers valid document/page reads, every stable service outcome, verified
binding failures, sanitized errors, exact-type misuse, no session writes and
deterministic repeated reads.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackage
from chess_workbench.extraction.validation import normalize_chess_moves
from chess_workbench.review.inspection import inspect_review_candidate
from chess_workbench.schemas.review import PdfReviewDocumentRead
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf import prepare_pdf_asset
from chess_workbench.services.pdf_extraction import (
    PDF_EVIDENCE_ARTIFACT_SCHEMA,
    PDF_EXTRACTION_RESULT_SCHEMA,
)
from chess_workbench.services.pdf_persistence import (
    PDF_EXTRACTION_PIPELINE_VERSION,
    PdfPersistenceService,
)
from chess_workbench.services.pdf_review import PdfReviewPageContent, PdfReviewReadService
from chess_workbench.services.source_storage import store_content_addressed_bytes
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import ExtractionArtifact, ExtractionRun, Job, PdfAsset

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
REVIEW_NOT_FOUND = "PDF extraction review was not found"
REVIEW_UNAVAILABLE = "PDF extraction review is not available"
PAGE_NOT_FOUND = "PDF review page was not found"
STORAGE_UNAVAILABLE = "source storage is unavailable"
FIRST_PAGE = 5
LAST_PAGE = 6


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    for _ in range(6):
        writer.add_blank_page(width=120, height=80)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _json_bytes(document: dict[str, object]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _png_body(page: int) -> bytes:
    return PNG_SIGNATURE + f"fixture-page-{page}".encode("ascii")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _normalized_package(run_id: UUID, first: int, last: int) -> ExtractionPackage:
    return normalize_chess_moves(
        ExtractionPackage.model_validate(_package_payload(run_id, first, last))
    )


async def _store(settings: Settings, *, suffix: str, raw_bytes: bytes) -> str:
    def _sync() -> str:
        return store_content_addressed_bytes(
            settings.source_storage_root,
            namespace="derived/extraction",
            suffix=suffix,
            raw_bytes=raw_bytes,
        ).relative_path

    return await asyncio.to_thread(_sync)


async def _setup(
    tmp_path: Path, name: str, *, first: int = FIRST_PAGE, last: int = LAST_PAGE
) -> tuple[Database, Settings, UUID]:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}",
        source_storage_root=tmp_path / f"{name}-storage",
        engine_worker_enabled=False,
        pdf_max_bytes=1024 * 1024,
    )
    database = Database(settings.database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    prepared = prepare_pdf_asset(
        _pdf_bytes(),
        filename="chapter.pdf",
        declared_media_type="application/pdf",
        title="Chapter",
        author=None,
        edition=None,
        storage_root=settings.source_storage_root,
        max_bytes=settings.pdf_max_bytes,
    )
    async with database.session() as session, session.begin():
        service = PdfPersistenceService(session)
        asset = await service.register_asset(prepared)
        extraction = await service.enqueue_extraction(
            pdf_asset_id=asset.asset.id,
            first_page=first,
            last_page=last,
            idempotency_key=name,
            pipeline_version=PDF_EXTRACTION_PIPELINE_VERSION,
        )
    return database, settings, extraction.run.id


async def _complete_review(
    database: Database,
    settings: Settings,
    run_id: UUID,
    *,
    job_status: str = "succeeded",
    manifest_overrides: dict[str, object] | None = None,
    normalized_payload: dict[str, Any] | None = None,
    png_body: bytes | None = None,
) -> None:
    """Persist a fully valid two-page v2 review; callers mutate afterwards."""
    payload = (
        _package_payload(run_id, FIRST_PAGE, LAST_PAGE)
        if normalized_payload is None
        else normalized_payload
    )
    package = normalize_chess_moves(ExtractionPackage.model_validate(payload))
    normalized_bytes = _json_bytes(package.model_dump(mode="json"))
    normalized_path = await _store(settings, suffix=".json", raw_bytes=normalized_bytes)
    normalized_sha = _sha256(normalized_bytes)

    page5_bytes = png_body if png_body is not None else _png_body(5)
    page6_bytes = _png_body(6)
    page5_path = await _store(settings, suffix=".png", raw_bytes=page5_bytes)
    page6_path = await _store(settings, suffix=".png", raw_bytes=page6_bytes)
    page5_sha = _sha256(page5_bytes)
    page6_sha = _sha256(page6_bytes)

    async with database.session() as session, session.begin():
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        asset = await session.get(PdfAsset, run.pdf_asset_id)
        assert asset is not None
        manifest: dict[str, object] = {
            "artifact_schema": PDF_EVIDENCE_ARTIFACT_SCHEMA,
            "run_id": str(run_id),
            "pdf_asset_id": str(run.pdf_asset_id),
            "pdf_content_sha256": asset.content_sha256,
            "first_page": run.first_page,
            "last_page": run.last_page,
            "render_profile": {"dpi": 72},
            "pages": [
                {
                    "physical_page": run.first_page,
                    "width": 100,
                    "height": 80,
                    "dpi": 72,
                    "renderer_name": "fixture",
                    "renderer_version": "1",
                    "content_sha256": page5_sha,
                    "byte_size": len(page5_bytes),
                    "media_type": "image/png",
                },
                {
                    "physical_page": run.last_page,
                    "width": 100,
                    "height": 80,
                    "dpi": 72,
                    "renderer_name": "fixture",
                    "renderer_version": "1",
                    "content_sha256": page6_sha,
                    "byte_size": len(page6_bytes),
                    "media_type": "image/png",
                },
            ],
        }
        if manifest_overrides is not None:
            manifest.update(manifest_overrides)
        manifest_bytes = _json_bytes(manifest)
        manifest_path = await _store(settings, suffix=".json", raw_bytes=manifest_bytes)
        manifest_sha = _sha256(manifest_bytes)

        job = await session.get(Job, run.job_id)
        assert job is not None
        job.status = job_status
        job.result = {
            "result_schema": PDF_EXTRACTION_RESULT_SCHEMA,
            "run_id": str(run_id),
            "evidence": {
                "render_manifest_sha256": manifest_sha,
                "ocr_manifest_sha256": "f" * 64,
                "page_count": run.last_page - run.first_page + 1,
                "fragment_count": 0,
                "warning_count": 0,
            },
            "candidate": {
                "provider_response_sha256": "a" * 64,
                "request_sha256": "b" * 64,
                "response_sha256": "c" * 64,
                "raw_ccef_sha256": "d" * 64,
                "normalized_ccef_sha256": normalized_sha,
                "summary": {
                    "item_count": len(package.items),
                    "move_node_count": 2,
                    "figure_count": 0,
                    "unresolved_item_count": 0,
                    "warning_count": 0,
                    "error_count": 0,
                    "invalid_move_count": 0,
                    "ambiguous_move_count": 0,
                    "has_conflicts": False,
                },
            },
        }
        session.add_all(
            [
                ExtractionArtifact(
                    run_id=run_id,
                    kind="normalized_ccef",
                    page_number=None,
                    relative_path=normalized_path,
                    media_type="application/json",
                    byte_size=len(normalized_bytes),
                    content_sha256=normalized_sha,
                ),
                ExtractionArtifact(
                    run_id=run_id,
                    kind="render_manifest",
                    page_number=None,
                    relative_path=manifest_path,
                    media_type="application/json",
                    byte_size=len(manifest_bytes),
                    content_sha256=manifest_sha,
                ),
                ExtractionArtifact(
                    run_id=run_id,
                    kind="rendered_page",
                    page_number=run.first_page,
                    relative_path=page5_path,
                    media_type="image/png",
                    byte_size=len(page5_bytes),
                    content_sha256=page5_sha,
                ),
                ExtractionArtifact(
                    run_id=run_id,
                    kind="rendered_page",
                    page_number=run.last_page,
                    relative_path=page6_path,
                    media_type="image/png",
                    byte_size=len(page6_bytes),
                    content_sha256=page6_sha,
                ),
            ]
        )


async def _read_document_error(
    database: Database, settings: Settings, run_id: UUID
) -> ServiceError:
    async with database.session() as session:
        service = PdfReviewReadService(session, settings)
        with pytest.raises(ServiceError) as caught:
            await service.read_document(run_id)
    return caught.value


async def _mutate_job_result(database: Database, run_id: UUID, mutation: Any) -> None:
    async with database.session() as session, session.begin():
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        job = await session.get(Job, run.job_id)
        assert job is not None
        # JSON columns do not track in-place dict mutation; assign a fresh dict.
        fresh = dict(job.result or {})
        mutation(fresh)
        job.result = fresh


async def _mutate_artifact(
    database: Database,
    run_id: UUID,
    kind: str,
    page_number: int | None,
    mutation: Any,
) -> None:
    async with database.session() as session, session.begin():
        artifact = (
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run_id,
                    ExtractionArtifact.kind == kind,
                    ExtractionArtifact.page_number.is_(page_number),
                )
            )
        ).one()
        mutation(artifact)


def _set_artifact_fields(artifact: Any, **updates: Any) -> None:
    for key, value in updates.items():
        setattr(artifact, key, value)


# ---------------------------------------------------------------------------
# 1. Valid document and page reads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_document_and_page_reads(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "valid")
    await _complete_review(database, settings, run_id)
    async with database.session() as session:
        service = PdfReviewReadService(session, settings)
        document = await service.read_document(run_id)
        page = await service.read_page(run_id, FIRST_PAGE)

    assert isinstance(document, PdfReviewDocumentRead)
    assert document.run_id == run_id
    assert document.package.package_id == run_id
    page_range = document.package.source.page_range
    assert page_range is not None
    assert page_range.start_page == FIRST_PAGE
    assert page_range.end_page == LAST_PAGE
    assert document.inspection == inspect_review_candidate(document.package)
    assert [entry.physical_page for entry in document.pages] == [FIRST_PAGE, LAST_PAGE]
    for entry in document.pages:
        assert entry.media_type == "image/png"
        assert entry.content_url == (
            f"/api/pdf-extractions/{run_id}/review/pages/{entry.physical_page}"
        )
        assert entry.byte_size > 0

    assert isinstance(page, PdfReviewPageContent)
    assert page.body == _png_body(FIRST_PAGE)
    assert page.body[:8] == PNG_SIGNATURE
    assert page.media_type == "image/png"
    assert page.byte_size == len(page.body)
    assert page.content_sha256 == _sha256(page.body)

    await database.close()


@pytest.mark.asyncio
async def test_reads_are_deterministic_and_session_is_not_mutated(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "deterministic")
    await _complete_review(database, settings, run_id)
    async with database.session() as session:
        service = PdfReviewReadService(session, settings)
        first = await service.read_document(run_id)
        second = await service.read_document(run_id)
        assert first == second
        assert not session.dirty
        assert not session.new
        assert not session.deleted

    # ---------------------------------------------------------------------------
    # 2. Missing run, non-succeeded job, historical v1
    # ---------------------------------------------------------------------------

    await database.close()


@pytest.mark.asyncio
async def test_missing_run_is_404(tmp_path: Path) -> None:
    database, settings, _ = await _setup(tmp_path, "missing")
    error = await _read_document_error(
        database, settings, UUID("22222222-2222-4222-8222-222222222222")
    )
    assert error.code == "not_found"
    assert error.status == 404
    assert str(error) == REVIEW_NOT_FOUND
    assert error.details is None

    await database.close()


@pytest.mark.asyncio
async def test_non_succeeded_job_is_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "queued")
    await _complete_review(database, settings, run_id, job_status="queued")
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"
    assert error.status == 409
    assert str(error) == REVIEW_UNAVAILABLE
    assert error.details is None
    assert error.__cause__ is None

    await database.close()


@pytest.mark.asyncio
async def test_historical_v1_pipeline_is_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "v1")
    await _complete_review(database, settings, run_id)
    async with database.session() as session, session.begin():
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        run.pipeline_version = "pdf-extraction:v1"
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"
    assert error.status == 409
    assert str(error) == REVIEW_UNAVAILABLE

    # ---------------------------------------------------------------------------
    # 3. Malformed result, hash mismatch, slot problems, media/size metadata
    # ---------------------------------------------------------------------------

    await database.close()


@pytest.mark.asyncio
async def test_malformed_or_wrong_run_result_is_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "badresult")
    await _complete_review(database, settings, run_id)
    await _mutate_job_result(
        database,
        run_id,
        lambda result: result.update(
            {
                "result_schema": PDF_EXTRACTION_RESULT_SCHEMA,
                "run_id": str(run_id),
                "candidate": {},
            }
        ),
    )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"

    await database.close()


@pytest.mark.asyncio
async def test_wrong_run_id_in_result_is_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "wrongrun")
    await _complete_review(database, settings, run_id)
    await _mutate_job_result(
        database,
        run_id,
        lambda result: result.update({"run_id": "00000000-0000-4000-8000-000000000000"}),
    )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"

    await database.close()


@pytest.mark.asyncio
async def test_candidate_normalized_hash_mismatch_is_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "hashmismatch")
    await _complete_review(database, settings, run_id)
    await _mutate_artifact(
        database,
        run_id,
        "normalized_ccef",
        None,
        lambda artifact: setattr(artifact, "content_sha256", "e" * 64),
    )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"

    await database.close()


@pytest.mark.asyncio
async def test_missing_duplicate_or_extra_slots_are_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "missing-slot")
    await _complete_review(database, settings, run_id)
    async with database.session() as session, session.begin():
        artifact = (
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run_id,
                    ExtractionArtifact.kind == "rendered_page",
                    ExtractionArtifact.page_number == LAST_PAGE,
                )
            )
        ).one()
        await session.delete(artifact)
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"

    database2, settings2, run_id2 = await _setup(tmp_path, "duplicate-slot")
    await _complete_review(database2, settings2, run_id2)
    async with database2.session() as session, session.begin():
        existing = (
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run_id2,
                    ExtractionArtifact.kind == "rendered_page",
                    ExtractionArtifact.page_number == FIRST_PAGE,
                )
            )
        ).one()
        session.add(
            ExtractionArtifact(
                run_id=run_id2,
                kind="rendered_page",
                page_number=FIRST_PAGE,
                relative_path=existing.relative_path,
                media_type="image/png",
                byte_size=existing.byte_size,
                content_sha256=existing.content_sha256,
            )
        )
    error = await _read_document_error(database2, settings2, run_id2)
    assert error.code == "ambiguous_context"

    database3, settings3, run_id3 = await _setup(tmp_path, "extra-slot")
    await _complete_review(database3, settings3, run_id3)
    async with database3.session() as session, session.begin():
        session.add(
            ExtractionArtifact(
                run_id=run_id3,
                kind="rendered_page",
                page_number=LAST_PAGE + 1,
                relative_path="derived/extraction/aa/extra",
                media_type="image/png",
                byte_size=1,
                content_sha256="a" * 64,
            )
        )
    error = await _read_document_error(database3, settings3, run_id3)
    assert error.code == "ambiguous_context"

    await database.close()
    await database2.close()
    await database3.close()


@pytest.mark.asyncio
async def test_wrong_media_metadata_is_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "media")
    await _complete_review(database, settings, run_id)
    await _mutate_artifact(
        database,
        run_id,
        "normalized_ccef",
        None,
        lambda artifact: setattr(artifact, "media_type", "application/octet-stream"),
    )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"

    # ---------------------------------------------------------------------------
    # 4. Malformed/misbound manifest and malformed/unvalidated CCEF
    # ---------------------------------------------------------------------------

    await database.close()


@pytest.mark.asyncio
async def test_misbound_manifest_is_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "manifest")
    await _complete_review(
        database,
        settings,
        run_id,
        manifest_overrides={"run_id": "00000000-0000-4000-8000-000000000000"},
    )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"

    await database.close()


@pytest.mark.asyncio
async def test_empty_manifest_pages_are_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "emptypages")
    await _complete_review(database, settings, run_id)
    # Rewrite the manifest blob with an empty page list and rebind the artifact.
    async with database.session() as session:
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        asset = await session.get(PdfAsset, run.pdf_asset_id)
        assert asset is not None
        manifest: dict[str, object] = {
            "artifact_schema": PDF_EVIDENCE_ARTIFACT_SCHEMA,
            "run_id": str(run_id),
            "pdf_asset_id": str(run.pdf_asset_id),
            "pdf_content_sha256": asset.content_sha256,
            "first_page": run.first_page,
            "last_page": run.last_page,
            "render_profile": {"dpi": 72},
            "pages": [],
        }
    manifest_bytes = _json_bytes(manifest)
    manifest_path = await _store(settings, suffix=".json", raw_bytes=manifest_bytes)
    async with database.session() as session, session.begin():
        artifact = (
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run_id,
                    ExtractionArtifact.kind == "render_manifest",
                )
            )
        ).one()
        artifact.relative_path = manifest_path
        artifact.byte_size = len(manifest_bytes)
        artifact.content_sha256 = _sha256(manifest_bytes)
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        job = await session.get(Job, run.job_id)
        assert job is not None
        fresh = dict(job.result or {})
        evidence = dict(fresh.get("evidence") or {})
        evidence["render_manifest_sha256"] = _sha256(manifest_bytes)
        fresh["evidence"] = evidence
        job.result = fresh
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"

    await database.close()


@pytest.mark.asyncio
async def test_unvalidated_ccef_is_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "unvalidated")
    # Raw (unvalidated) package bytes replace the normalized artifact.
    raw_payload = _package_payload(run_id, FIRST_PAGE, LAST_PAGE)
    raw_bytes = _json_bytes(raw_payload)
    raw_path = await _store(settings, suffix=".json", raw_bytes=raw_bytes)
    raw_sha = _sha256(raw_bytes)
    await _complete_review(database, settings, run_id)
    await _mutate_artifact(
        database,
        run_id,
        "normalized_ccef",
        None,
        lambda artifact: _set_artifact_fields(
            artifact,
            relative_path=raw_path,
            byte_size=len(raw_bytes),
            content_sha256=raw_sha,
        ),
    )
    await _mutate_job_result(
        database,
        run_id,
        lambda result: result["candidate"].update({"normalized_ccef_sha256": raw_sha}),
    )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"

    await database.close()


@pytest.mark.asyncio
async def test_package_run_or_page_range_mismatch_is_unavailable(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "packagebind")
    await _complete_review(database, settings, run_id)
    wrong_payload = _package_payload(
        UUID("33333333-3333-4333-8333-333333333333"), FIRST_PAGE, LAST_PAGE
    )
    wrong = _normalized_package(UUID("33333333-3333-4333-8333-333333333333"), FIRST_PAGE, LAST_PAGE)
    wrong_bytes = _json_bytes(wrong.model_dump(mode="json"))
    wrong_path = await _store(settings, suffix=".json", raw_bytes=wrong_bytes)
    await _mutate_artifact(
        database,
        run_id,
        "normalized_ccef",
        None,
        lambda artifact: _set_artifact_fields(
            artifact,
            relative_path=wrong_path,
            byte_size=len(wrong_bytes),
            content_sha256=_sha256(wrong_bytes),
        ),
    )
    await _mutate_job_result(
        database,
        run_id,
        lambda result: result["candidate"].update({"normalized_ccef_sha256": _sha256(wrong_bytes)}),
    )
    del wrong_payload
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"

    # ---------------------------------------------------------------------------
    # 5. Missing/corrupt CAS bytes propagate the stable storage error
    # ---------------------------------------------------------------------------

    await database.close()


@pytest.mark.asyncio
async def test_missing_cas_bytes_propagate_storage_error(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "missingcas")
    await _complete_review(database, settings, run_id)
    await _mutate_artifact(
        database,
        run_id,
        "render_manifest",
        None,
        lambda artifact: setattr(artifact, "relative_path", "derived/extraction/zz/missing.json"),
    )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "source_storage_unavailable"
    assert error.status == 503
    assert str(error) == STORAGE_UNAVAILABLE

    await database.close()


@pytest.mark.asyncio
async def test_missing_page_cas_bytes_propagate_storage_error(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "missingpagecas")
    await _complete_review(database, settings, run_id)
    await _mutate_artifact(
        database,
        run_id,
        "rendered_page",
        FIRST_PAGE,
        lambda artifact: setattr(artifact, "relative_path", "derived/extraction/zz/missing.png"),
    )
    async with database.session() as session:
        service = PdfReviewReadService(session, settings)
        with pytest.raises(ServiceError) as caught:
            await service.read_page(run_id, FIRST_PAGE)
    assert caught.value.code == "source_storage_unavailable"
    assert caught.value.status == 503
    assert str(caught.value) == STORAGE_UNAVAILABLE

    # ---------------------------------------------------------------------------
    # 6. Out-of-range page and wrong PNG signature
    # ---------------------------------------------------------------------------

    await database.close()


@pytest.mark.asyncio
async def test_out_of_range_page_is_404(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "outofrange")
    await _complete_review(database, settings, run_id)
    async with database.session() as session:
        service = PdfReviewReadService(session, settings)
        with pytest.raises(ServiceError) as caught:
            await service.read_page(run_id, LAST_PAGE + 1)
    assert caught.value.code == "not_found"
    assert caught.value.status == 404
    assert str(caught.value) == PAGE_NOT_FOUND

    await database.close()


@pytest.mark.asyncio
async def test_wrong_png_signature_is_sanitized_409(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "badpng")
    await _complete_review(database, settings, run_id, png_body=b"not-a-png-body")
    async with database.session() as session:
        service = PdfReviewReadService(session, settings)
        with pytest.raises(ServiceError) as caught:
            await service.read_page(run_id, FIRST_PAGE)
    assert caught.value.code == "ambiguous_context"
    assert caught.value.status == 409
    assert str(caught.value) == REVIEW_UNAVAILABLE
    assert caught.value.details is None
    assert caught.value.__cause__ is None

    # ---------------------------------------------------------------------------
    # 7. Exact-type misuse and sanitized public errors
    # ---------------------------------------------------------------------------

    await database.close()


@pytest.mark.asyncio
async def test_exact_type_misuse_raises_type_error(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "types")
    await _complete_review(database, settings, run_id)
    async with database.session() as session:
        service = PdfReviewReadService(session, settings)
        with pytest.raises(TypeError, match="run_id must be UUID"):
            await service.read_document("not-a-uuid")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="run_id must be UUID"):
            await service.read_page("not-a-uuid", FIRST_PAGE)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="physical_page must be int"):
            await service.read_page(run_id, True)
        with pytest.raises(TypeError, match="physical_page must be int"):
            await service.read_page(run_id, "5")  # type: ignore[arg-type]

    await database.close()


@pytest.mark.asyncio
async def test_public_errors_never_leak_paths_hashes_or_content(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "noleak")
    await _complete_review(database, settings, run_id)
    await _mutate_artifact(
        database,
        run_id,
        "normalized_ccef",
        None,
        lambda artifact: setattr(artifact, "media_type", "application/octet-stream"),
    )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"
    assert error.details is None
    assert error.__cause__ is None
    message = str(error)
    assert message == REVIEW_UNAVAILABLE
    assert "/" not in message
    assert "sha256" not in message.lower()
    assert "ccef" not in message.lower()
    assert "provider" not in message.lower()
    assert "api_key" not in message.lower()
    assert "fixture" not in message

    await database.close()


# ---------------------------------------------------------------------------
# 8. R1 corrections: exact slot map, bounded pages, strict hashes/sizes, types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_non_null_normalized_slot_is_409(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "extra-normalized")
    await _complete_review(database, settings, run_id)
    async with database.session() as session, session.begin():
        session.add(
            ExtractionArtifact(
                run_id=run_id,
                kind="normalized_ccef",
                page_number=FIRST_PAGE,
                relative_path="derived/extraction/aa/extra",
                media_type="application/json",
                byte_size=1,
                content_sha256="a" * 64,
            )
        )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"
    assert error.status == 409

    await database.close()


@pytest.mark.asyncio
async def test_extra_non_null_render_manifest_slot_is_409(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "extra-manifest")
    await _complete_review(database, settings, run_id)
    async with database.session() as session, session.begin():
        session.add(
            ExtractionArtifact(
                run_id=run_id,
                kind="render_manifest",
                page_number=FIRST_PAGE,
                relative_path="derived/extraction/aa/extra",
                media_type="application/json",
                byte_size=1,
                content_sha256="a" * 64,
            )
        )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"
    assert error.status == 409

    await database.close()


@pytest.mark.asyncio
async def test_corrupt_last_page_is_prompt_409_before_range_allocation(
    tmp_path: Path,
) -> None:
    database, settings, run_id = await _setup(tmp_path, "hugerange")
    await _complete_review(database, settings, run_id)
    async with database.session() as session, session.begin():
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        run.last_page = 1_000_000_000
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"
    assert error.status == 409

    await database.close()


@pytest.mark.asyncio
async def test_uppercase_rendered_hash_is_409(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(tmp_path, "upperhash")
    await _complete_review(database, settings, run_id)
    await _mutate_artifact(
        database,
        run_id,
        "rendered_page",
        FIRST_PAGE,
        lambda artifact: setattr(artifact, "content_sha256", "A" * 64),
    )
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"
    assert error.status == 409

    await database.close()


@pytest.mark.asyncio
async def test_manifest_byte_size_bool_does_not_bind(tmp_path: Path) -> None:
    # A one-byte rendered blob with database size 1; the manifest entry claims
    # byte_size=true (JSON true). The strict int check must reject it instead
    # of binding true == 1.
    database, settings, run_id = await _setup(tmp_path, "boolsize")
    await _complete_review(database, settings, run_id, png_body=PNG_SIGNATURE[:1])
    async with database.session() as session, session.begin():
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        asset = await session.get(PdfAsset, run.pdf_asset_id)
        assert asset is not None
        manifest: dict[str, object] = {
            "artifact_schema": PDF_EVIDENCE_ARTIFACT_SCHEMA,
            "run_id": str(run_id),
            "pdf_asset_id": str(run.pdf_asset_id),
            "pdf_content_sha256": asset.content_sha256,
            "first_page": run.first_page,
            "last_page": run.last_page,
            "render_profile": {"dpi": 72},
            "pages": [
                {
                    "physical_page": run.first_page,
                    "width": 100,
                    "height": 80,
                    "dpi": 72,
                    "renderer_name": "fixture",
                    "renderer_version": "1",
                    "content_sha256": _sha256(PNG_SIGNATURE[:1]),
                    "byte_size": True,
                    "media_type": "image/png",
                },
                {
                    "physical_page": run.last_page,
                    "width": 100,
                    "height": 80,
                    "dpi": 72,
                    "renderer_name": "fixture",
                    "renderer_version": "1",
                    "content_sha256": _sha256(_png_body(6)),
                    "byte_size": len(_png_body(6)),
                    "media_type": "image/png",
                },
            ],
        }
    manifest_bytes = _json_bytes(manifest)
    manifest_path = await _store(settings, suffix=".json", raw_bytes=manifest_bytes)
    async with database.session() as session, session.begin():
        artifact = (
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run_id,
                    ExtractionArtifact.kind == "render_manifest",
                )
            )
        ).one()
        artifact.relative_path = manifest_path
        artifact.byte_size = len(manifest_bytes)
        artifact.content_sha256 = _sha256(manifest_bytes)
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        job = await session.get(Job, run.job_id)
        assert job is not None
        fresh = dict(job.result or {})
        evidence = dict(fresh.get("evidence") or {})
        evidence["render_manifest_sha256"] = _sha256(manifest_bytes)
        fresh["evidence"] = evidence
        job.result = fresh
    error = await _read_document_error(database, settings, run_id)
    assert error.code == "ambiguous_context"
    assert error.status == 409

    await database.close()


@pytest.mark.asyncio
async def test_uuid_subclass_is_rejected(tmp_path: Path) -> None:
    class _SubclassUUID(UUID):
        pass

    database, settings, run_id = await _setup(tmp_path, "uuidsubclass")
    await _complete_review(database, settings, run_id)
    subclass = _SubclassUUID(str(run_id))
    async with database.session() as session:
        service = PdfReviewReadService(session, settings)
        with pytest.raises(TypeError, match="run_id must be UUID"):
            await service.read_document(subclass)
        with pytest.raises(TypeError, match="run_id must be UUID"):
            await service.read_page(subclass, FIRST_PAGE)

    await database.close()
