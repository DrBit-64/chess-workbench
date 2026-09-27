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
from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.services.content import ServiceError
from chess_workbench.services.jobs import JobService
from chess_workbench.services.pdf_documents import (
    PDF_INCREMENTAL_EXTRACTION_JOB_KIND,
    PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    PdfDocumentService,
)
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    ExtractionArtifact,
    ExtractionRun,
    Job,
    PdfAsset,
    PdfExtractionDocument,
    PdfExtractionDocumentAppend,
    PdfExtractionDocumentRevision,
    PdfExtractionDocumentSegment,
    PdfReviewEvent,
    PdfReviewRevision,
    PdfReviewSession,
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


@pytest.mark.asyncio
async def test_rollback_latest_append_restores_previous_document_head(tmp_path: Path) -> None:
    database, settings, initial_run_id = await _setup(
        tmp_path,
        "document-rollback",
        pipeline_version="pdf-extraction:v4",
    )
    await _complete_review(
        database,
        settings,
        initial_run_id,
        normalized_payload=_package_payload_v1_1(initial_run_id, FIRST_PAGE, LAST_PAGE),
    )
    try:
        async with database.session() as session, session.begin():
            asset = await session.scalar(select(PdfAsset))
            assert asset is not None
            asset.page_count = 10
            service = PdfDocumentService(session, settings)
            document = (await service.adopt_run(initial_run_id)).document
            append = await service.register_append(
                document_id=document.id,
                expected_version=1,
                first_page=7,
                last_page=8,
                profile=None,
                idempotency_key="rollback-append",
            )
            append.job.status = "running"
            segment_sha = "a" * 64
            session.add(
                ExtractionArtifact(
                    run_id=append.run.id,
                    kind="normalized_ccef",
                    page_number=None,
                    relative_path="derived/extraction/aa/segment.json",
                    media_type="application/json",
                    byte_size=1,
                    content_sha256=segment_sha,
                )
            )
            aggregate = normalize_chess_moves_v1_1(
                ExtractionPackageV1_1.model_validate(
                    _package_payload_v1_1(document.id, FIRST_PAGE, 8)
                )
            )
            committed = await service.commit_verified_append(
                run_id=append.run.id,
                segment_normalized_ccef_sha256=segment_sha,
                aggregate=aggregate,
            )
            assert committed.document.version == 2
            review_session = PdfReviewSession(
                document_id=document.id,
                baseline_document_revision_id=committed.revision.id,
                baseline_ccef_sha256=committed.revision.normalized_ccef_sha256,
                status="open",
            )
            session.add(review_session)
            await session.flush()
            review_revision = PdfReviewRevision(
                session_id=review_session.id,
                parent_revision_id=None,
                revision_number=1,
                relative_path=committed.revision.relative_path,
                media_type=committed.revision.media_type,
                byte_size=committed.revision.byte_size,
                package_sha256=committed.revision.normalized_ccef_sha256,
            )
            session.add(review_revision)
            await session.flush()
            session.add(
                PdfReviewEvent(
                    session_id=review_session.id,
                    revision_id=review_revision.id,
                    parent_version=0,
                    resulting_version=1,
                    kind="created",
                    decisions={"target_kind": "document"},
                )
            )
            await session.flush()
            document_id = document.id
            appended_run_id = append.run.id

        async with database.session() as session, session.begin():
            service = PdfDocumentService(session, settings)
            rolled_back = await service.rollback_latest_append(
                document_id=document_id,
                expected_version=2,
            )
            assert rolled_back.document.version == 1
            assert rolled_back.document.last_page == LAST_PAGE
            assert len(rolled_back.segments) == len(rolled_back.revisions) == 1
            assert rolled_back.append_attempts == ()
            assert (
                await session.scalar(select(func.count()).select_from(PdfExtractionDocumentAppend))
            ) == 0
            assert (await session.scalar(select(func.count()).select_from(PdfReviewSession))) == 0
            assert (await session.scalar(select(func.count()).select_from(PdfReviewRevision))) == 0
            assert (await session.scalar(select(func.count()).select_from(PdfReviewEvent))) == 0
            replacement = await service.register_append(
                document_id=document_id,
                expected_version=1,
                first_page=7,
                last_page=8,
                profile=None,
                idempotency_key="replacement-after-rollback",
            )
            assert replacement.job.status == "queued"

        async with database.session() as session:
            assert await session.get(ExtractionRun, appended_run_id) is not None
            appended_run = await session.get(ExtractionRun, appended_run_id)
            assert appended_run is not None
            appended_job = await session.get(Job, appended_run.job_id)
            assert appended_job is not None and appended_job.archived_at is not None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ExtractionArtifact)
                    .where(ExtractionArtifact.run_id == appended_run_id)
                )
            ) == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_source_first_document_append_queues_v7_without_changing_legacy(
    tmp_path: Path,
) -> None:
    from chess_workbench.services.pdf_documents import (
        PDF_SOURCE_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
    )
    from chess_workbench.services.pdf_persistence import PDF_SOURCE_EXTRACTION_PIPELINE_VERSION

    database, settings, run_id = await _setup(
        tmp_path, "source-first-document", pipeline_version=PDF_SOURCE_EXTRACTION_PIPELINE_VERSION
    )
    await _complete_review(
        database,
        settings,
        run_id,
        normalized_payload=_package_payload_v1_1(run_id, FIRST_PAGE, LAST_PAGE),
    )
    try:
        async with database.session() as session, session.begin():
            asset = await session.scalar(select(PdfAsset))
            assert asset is not None
            asset.page_count = 10
            document = (await PdfDocumentService(session, settings).adopt_run(run_id)).document
        async with database.session() as session, session.begin():
            append = await PdfDocumentService(session, settings).register_append(
                document_id=document.id,
                expected_version=1,
                first_page=7,
                last_page=8,
                profile={},
                idempotency_key="source-first-append",
            )
        assert append.run.pipeline_version == PDF_SOURCE_INCREMENTAL_EXTRACTION_PIPELINE_VERSION
        assert (
            append.job.payload["pipeline_version"]
            == PDF_SOURCE_INCREMENTAL_EXTRACTION_PIPELINE_VERSION
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_v7_append_uses_source_events_and_commits_verified_continuation(
    tmp_path: Path,
) -> None:
    import json

    from chess_workbench.extraction.evidence import (
        PixelBox,
        RenderedPage,
        RenderProfile,
        TextFragment,
    )
    from chess_workbench.extraction.provider import (
        ScriptedStructuredGenerationProvider,
        StructuredGenerationResponse,
    )
    from chess_workbench.services.pdf_extraction import process_pdf_extraction_job
    from chess_workbench.services.pdf_incremental_extraction import (
        process_pdf_incremental_extraction_job,
    )
    from chess_workbench.services.pdf_persistence import PDF_SOURCE_EXTRACTION_PIPELINE_VERSION

    database, settings, run_id = await _setup(
        tmp_path, "source-first-append-job", pipeline_version=PDF_SOURCE_EXTRACTION_PIPELINE_VERSION
    )
    async with database.session() as session:
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        asset = await session.get(PdfAsset, run.pdf_asset_id)
        assert asset is not None
        source_ref = f"source-file:{asset.source_file_id}"
    initial = _package_payload_v1_1(run_id, FIRST_PAGE, LAST_PAGE)
    initial["source"]["source_ref"] = source_ref
    await _complete_review(database, settings, run_id, normalized_payload=initial)

    class TwoPageRenderer:
        def render_page(
            self, pdf_bytes: bytes, physical_page: int, profile: RenderProfile
        ) -> RenderedPage:
            source = "2.Nf3 Nc6" if physical_page == 7 else "New game 1.d4 d5"
            return RenderedPage(
                physical_page=physical_page,
                width=120,
                height=80,
                dpi=profile.dpi,
                png_bytes=b"\x89PNG\r\n\x1a\nfixture",
                embedded_fragments=[
                    TextFragment(
                        order=0,
                        text=source,
                        box=PixelBox(x0=10, y0=10, x1=110, y1=30),
                        confidence=None,
                    )
                ],
                renderer_name="fixture",
                renderer_version="1",
            )

    try:
        async with database.session() as session, session.begin():
            asset = await session.get(PdfAsset, run.pdf_asset_id)
            assert asset is not None
            asset.page_count = 10
            document = (await PdfDocumentService(session, settings).adopt_run(run_id)).document
        async with database.session() as session, session.begin():
            append = await PdfDocumentService(session, settings).register_append(
                document_id=document.id,
                expected_version=1,
                first_page=7,
                last_page=8,
                profile={"render": {"dpi": 72, "embedded_text_min_chars": 1}},
                idempotency_key="v7-fixture",
            )
            append.job.status = "running"
        await process_pdf_extraction_job(
            database,
            settings,
            append.job.payload,
            renderer=TwoPageRenderer(),
        )
        responses = [
            {
                "events": [
                    {
                        "id": "m1",
                        "kind": "move",
                        "sequence": "continued",
                        "parent": None,
                        "continuation_anchor": "anchor-3",
                        "source": {"page": 7, "order": 0, "quote": "Nf3"},
                    },
                    {
                        "id": "m2",
                        "kind": "move",
                        "sequence": "continued",
                        "parent": "m1",
                        "source": {"page": 7, "order": 0, "quote": "Nc6"},
                    },
                ]
            },
            {
                "events": [
                    {
                        "id": "m1",
                        "kind": "move",
                        "sequence": "new",
                        "parent": None,
                        "source": {"page": 8, "order": 0, "quote": "d4"},
                    },
                    {
                        "id": "m2",
                        "kind": "move",
                        "sequence": "new",
                        "parent": "m1",
                        "source": {"page": 8, "order": 0, "quote": "d5"},
                    },
                ]
            },
        ]
        provider = ScriptedStructuredGenerationProvider(
            [
                StructuredGenerationResponse(
                    content=json.dumps(value),
                    provider="scripted",
                    model="fixture",
                    finish_reason="stop",
                )
                for value in responses
            ]
        )
        result = await process_pdf_incremental_extraction_job(
            database, settings, append.job.payload, provider=provider
        )
        assert result["run_id"] == str(append.run.id)
        assert len(provider.calls) == 2
        async with database.session() as session:
            updated = await session.get(PdfExtractionDocument, document.id)
            assert updated is not None and updated.version == 2
            rows = list(
                await session.scalars(
                    select(ExtractionArtifact).where(ExtractionArtifact.run_id == append.run.id)
                )
            )
        assert any(row.kind == "semantic_manifest" for row in rows)
    finally:
        await database.close()
