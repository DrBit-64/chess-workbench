"""Focused functional checks for the 8D-3E2 document persistence boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from test_stage8d_review_read_service import (
    FIRST_PAGE,
    LAST_PAGE,
    _complete_review,
    _package_payload_v1_1,
    _setup,
)

from chess_workbench.api.app import create_app
from chess_workbench.services.content import ServiceError
from chess_workbench.services.jobs import JobService
from chess_workbench.services.pdf_documents import (
    PDF_INCREMENTAL_EXTRACTION_JOB_KIND,
    PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    PdfDocumentService,
)
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    PdfAsset,
    PdfExtractionDocument,
    PdfExtractionDocumentAppend,
    PdfExtractionDocumentRevision,
    PdfExtractionDocumentSegment,
)


async def _count(database: Database, model: type[object]) -> int:
    async with database.session() as session:
        return (await session.scalar(select(func.count()).select_from(model))) or 0


@pytest.mark.asyncio
async def test_adopt_and_register_adjacent_append_without_advancing_head(
    tmp_path: Path,
) -> None:
    database, settings, run_id = await _setup(
        tmp_path,
        "document-main",
        pipeline_version="pdf-extraction:v4",
    )
    await _complete_review(
        database,
        settings,
        run_id,
        normalized_payload=_package_payload_v1_1(run_id, FIRST_PAGE, LAST_PAGE),
    )
    async with database.session() as session, session.begin():
        asset = await session.scalar(select(PdfAsset))
        assert asset is not None
        asset.page_count = 10

    try:
        async with database.session() as session, session.begin():
            service = PdfDocumentService(session, settings)
            adopted = await service.adopt_run(run_id)
            document_id = adopted.document.id
            assert adopted.replayed is False
            replayed = await service.adopt_run(run_id)
            assert replayed.replayed is True
            assert replayed.document.id == document_id

        async with database.session() as session, session.begin():
            service = PdfDocumentService(session, settings)
            outcome = await service.register_append(
                document_id=document_id,
                expected_version=1,
                first_page=7,
                last_page=8,
                profile={"language": "en"},
                idempotency_key="append-1",
            )
            assert outcome.replayed is False
            assert outcome.job.kind == PDF_INCREMENTAL_EXTRACTION_JOB_KIND
            assert outcome.job.status == "queued"
            assert outcome.run.pipeline_version == PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION
            assert outcome.append.predecessor_normalized_ccef_sha256 == (
                adopted.document.normalized_ccef_sha256
            )
            repeated = await service.register_append(
                document_id=document_id,
                expected_version=1,
                first_page=7,
                last_page=8,
                profile={"language": "en"},
                idempotency_key="append-1",
            )
            assert repeated.replayed is True
            assert repeated.append.id == outcome.append.id

        async with database.session() as session:
            view = await PdfDocumentService(session, settings).get_document(document_id)
            assert view is not None
            assert view.document.version == 1
            assert (view.document.first_page, view.document.last_page) == (5, 6)
            assert len(view.segments) == len(view.revisions) == len(view.append_attempts) == 1
            assert view.append_attempts[0].job.status == "queued"

        async with database.session() as session, session.begin():
            assert (
                await JobService(session).claim(
                    worker_id="ordinary-pdf-worker",
                    allowed_kinds={"pdf_extraction"},
                )
                is None
            )

        assert await _count(database, PdfExtractionDocument) == 1
        assert await _count(database, PdfExtractionDocumentSegment) == 1
        assert await _count(database, PdfExtractionDocumentRevision) == 1
        assert await _count(database, PdfExtractionDocumentAppend) == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_append_rejects_stale_nonadjacent_and_parallel_attempts(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(
        tmp_path,
        "document-errors",
        pipeline_version="pdf-extraction:v4",
    )
    await _complete_review(
        database,
        settings,
        run_id,
        normalized_payload=_package_payload_v1_1(run_id, FIRST_PAGE, LAST_PAGE),
    )
    async with database.session() as session, session.begin():
        asset = await session.scalar(select(PdfAsset))
        assert asset is not None
        asset.page_count = 10
        document_id = (await PdfDocumentService(session, settings).adopt_run(run_id)).document.id

    try:
        async with database.session() as session, session.begin():
            service = PdfDocumentService(session, settings)
            with pytest.raises(ServiceError) as nonadjacent:
                await service.register_append(
                    document_id=document_id,
                    expected_version=1,
                    first_page=8,
                    last_page=9,
                    profile=None,
                    idempotency_key=None,
                )
            assert nonadjacent.value.code == "validation_error"

            with pytest.raises(ServiceError) as stale:
                await service.register_append(
                    document_id=document_id,
                    expected_version=2,
                    first_page=7,
                    last_page=8,
                    profile=None,
                    idempotency_key=None,
                )
            assert stale.value.code == "stale_version"

            first = await service.register_append(
                document_id=document_id,
                expected_version=1,
                first_page=7,
                last_page=8,
                profile=None,
                idempotency_key="first-active",
            )
            with pytest.raises(ServiceError) as parallel:
                await service.register_append(
                    document_id=document_id,
                    expected_version=1,
                    first_page=7,
                    last_page=8,
                    profile=None,
                    idempotency_key="parallel",
                )
            assert parallel.value.code == "ambiguous_context"

            first.job.status = "failed"
            retry = await service.register_append(
                document_id=document_id,
                expected_version=1,
                first_page=7,
                last_page=8,
                profile=None,
                idempotency_key="retry-after-failure",
            )
            assert retry.append.id != first.append.id
            assert retry.job.status == "queued"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_document_http_adopt_append_and_grouped_read(tmp_path: Path) -> None:
    database, settings, run_id = await _setup(
        tmp_path,
        "document-http",
        pipeline_version="pdf-extraction:v4",
    )
    await _complete_review(
        database,
        settings,
        run_id,
        normalized_payload=_package_payload_v1_1(run_id, FIRST_PAGE, LAST_PAGE),
    )
    async with database.session() as session, session.begin():
        asset = await session.scalar(select(PdfAsset))
        assert asset is not None
        asset.page_count = 10

    app = create_app(settings)
    await app.ctx.database.close()
    app.ctx.database = database
    client = app.asgi_client
    try:
        _, adopted = await client.post(
            "/api/pdf-extraction-documents",
            json={"initial_run_id": str(run_id)},
        )
        assert adopted.status == 201
        document = adopted.json["document"]
        document_id = document["id"]
        assert document["version"] == 1
        assert (document["first_page"], document["last_page"]) == (5, 6)
        assert len(document["segments"]) == len(document["revisions"]) == 1

        _, appended = await client.post(
            f"/api/pdf-extraction-documents/{document_id}/appends",
            headers={"Idempotency-Key": "http-append"},
            json={
                "expected_version": 1,
                "first_page": 7,
                "last_page": 8,
                "profile": {"language": "en"},
            },
        )
        assert appended.status == 202
        assert appended.json["append"]["job"]["status"] == "queued"
        assert appended.json["document"]["version"] == 1
        assert appended.json["document"]["last_page"] == 6

        _, listed = await client.get("/api/pdf-extraction-documents")
        assert listed.status == 200
        assert [item["id"] for item in listed.json["items"]] == [document_id]
        assert len(listed.json["items"][0]["append_attempts"]) == 1
    finally:
        await database.close()
