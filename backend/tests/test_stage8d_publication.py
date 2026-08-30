from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.schemas.domain import (
    CourseCreate,
    SourceCreate,
    SourceFileCreate,
    SourceVersionCreate,
)
from chess_workbench.schemas.review import PdfReviewPublishRequest
from chess_workbench.services.content import ContentService
from chess_workbench.services.pdf_review_ledger import PdfReviewLedgerService
from chess_workbench.services.pdf_review_publication import PdfReviewPublicationService
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    CourseModule,
    CourseOccurrence,
    ExtractionArtifact,
    ExtractionRun,
    Job,
    KnowledgeNote,
    PdfAsset,
    PdfReviewPublication,
    PdfReviewRevision,
    PdfReviewSession,
    utc_now,
)


def _package() -> ExtractionPackageV1_1:
    raw = ExtractionPackageV1_1.model_validate(
        {
            "schema_version": "chess-content-extraction/1.1",
            "package_id": str(uuid4()),
            "source": {
                "source_ref": "synthetic-publication",
                "media_type": "application/pdf",
                "page_range": {"start_page": 10, "end_page": 11},
            },
            "items": [
                {
                    "kind": "move_sequence",
                    "id": "game1",
                    "title": "Game 1",
                    "evidence": [{"page": 10}],
                    "initial_position": {"kind": "startpos"},
                    "nodes": [
                        {
                            "id": "n1",
                            "parent_id": None,
                            "sibling_order": 0,
                            "move_text": "e4",
                            "evidence": [{"page": 10}],
                        },
                        {
                            "id": "n2",
                            "parent_id": "n1",
                            "sibling_order": 0,
                            "move_text": "e5",
                            "evidence": [{"page": 10}],
                        },
                        {
                            "id": "n3",
                            "parent_id": "n1",
                            "sibling_order": 1,
                            "move_text": "c5",
                            "evidence": [{"page": 11}],
                        },
                    ],
                    "annotations": [
                        {
                            "id": "a1",
                            "text": "Sicilian branch.",
                            "anchor": None,
                            "evidence": [{"page": 11}],
                        }
                    ],
                    "reading_flow": [
                        {"kind": "move", "node_id": "n1"},
                        {"kind": "move", "node_id": "n2"},
                        {"kind": "move", "node_id": "n3"},
                        {"kind": "annotation", "annotation_id": "a1"},
                    ],
                }
            ],
            "provenance": {
                "created_at": "2026-08-28T00:00:00Z",
                "adapter_name": "test",
                "adapter_version": "1.1",
            },
        }
    )
    return normalize_chess_moves_v1_1(raw)


async def test_approved_review_publishes_multiple_fragments_into_nested_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'publication.db'}"
    database = Database(database_url)
    settings = Settings(
        database_url=database_url,
        source_storage_root=tmp_path / "storage",
        engine_worker_enabled=False,
    )
    package = _package()
    now = utc_now()
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.session() as session, session.begin():
            content = ContentService(session)
            source = await content.create_source(SourceCreate(kind="book", title="Book"))
            version = await content.create_source_version(
                SourceVersionCreate(source_id=source.id, label="Edition")
            )
            source_file = await content.create_source_file(
                SourceFileCreate(
                    source_version_id=version.id,
                    filename="book.pdf",
                    relative_path="sources/book.pdf",
                    media_type="application/pdf",
                    size_bytes=100,
                    sha256="a" * 64,
                )
            )
            asset = PdfAsset(
                id=uuid4(),
                content_sha256="b" * 64,
                byte_size=100,
                page_count=20,
                source_id=source.id,
                source_version_id=version.id,
                source_file_id=source_file.id,
            )
            session.add(asset)
            await session.flush()
            job = Job(
                id=uuid4(),
                kind="pdf_extraction",
                status="succeeded",
                payload={},
                result={},
                idempotency_key="publication-test",
                request_hash="c" * 64,
                attempt_count=1,
                max_attempts=1,
                available_at=now,
            )
            session.add(job)
            await session.flush()
            run = ExtractionRun(
                id=uuid4(),
                pdf_asset_id=asset.id,
                job_id=job.id,
                first_page=10,
                last_page=11,
                pipeline_version="pdf-extraction:v4",
                logical_fingerprint="d" * 64,
                effective_key_hash="e" * 64,
            )
            session.add(run)
            await session.flush()
            artifact = ExtractionArtifact(
                id=uuid4(),
                run_id=run.id,
                kind="normalized_ccef",
                page_number=None,
                relative_path="extractions/test.json",
                media_type="application/json",
                byte_size=10,
                content_sha256="f" * 64,
            )
            session.add(artifact)
            await session.flush()
            review = PdfReviewSession(
                id=uuid4(),
                extraction_run_id=run.id,
                document_id=None,
                baseline_artifact_id=artifact.id,
                baseline_document_revision_id=None,
                baseline_ccef_sha256="f" * 64,
                status="approved",
                version=1,
            )
            session.add(review)
            await session.flush()
            revision = PdfReviewRevision(
                id=uuid4(),
                session_id=review.id,
                parent_revision_id=None,
                revision_number=1,
                relative_path="reviews/test.json",
                media_type="application/json",
                byte_size=10,
                package_sha256="f" * 64,
            )
            session.add(revision)
            await session.flush()
            course = await content.create_course(CourseCreate(title="Published Book"))

            async def current_package(
                _self: PdfReviewLedgerService, _session_id: object
            ) -> ExtractionPackageV1_1:
                return package

            monkeypatch.setattr(PdfReviewLedgerService, "get_current_package", current_package)
            request = PdfReviewPublishRequest.model_validate(
                {
                    "expected_version": 1,
                    "target_course_id": str(course.id),
                    "segments": [
                        {
                            "sequence_id": "game1",
                            "node_ids": ["n1", "n2"],
                            "target": {"chapter": {"kind": "new", "title": "Chapter 1"}},
                        },
                        {
                            "sequence_id": "game1",
                            "node_ids": ["n3"],
                            "target": {
                                "chapter": {"kind": "new", "title": "Chapter 2"},
                                "subsection": {"kind": "new", "title": "Game 1"},
                            },
                        },
                    ],
                }
            )
            outcome = await PdfReviewPublicationService(session, settings).publish(
                review.id, request
            )
            assert outcome.replayed is False
            assert len(outcome.publication.segments) == 2
            assert outcome.publication.segments[1].note_count == 1

        async with database.session() as session, session.begin():
            replay = await PdfReviewPublicationService(session, settings).publish(
                review.id, request
            )
            assert replay.replayed is True
            assert replay.publication.publication_id == outcome.publication.publication_id

        async with database.session() as session:
            modules = list(
                await session.scalars(
                    select(CourseModule).order_by(CourseModule.sort_order, CourseModule.title)
                )
            )
            by_title = {item.title: item for item in modules}
            assert by_title["Chapter 1"].parent_id is None
            assert by_title["Chapter 2"].parent_id is None
            assert by_title["Game 1"].parent_id == by_title["Chapter 2"].id
            assert await session.scalar(select(func.count()).select_from(PdfReviewPublication)) == 1
            published_note = await session.scalar(
                select(KnowledgeNote).where(KnowledgeNote.markdown == r"Sicilian branch\.")
            )
            assert published_note is not None
            occurrences = list(
                await session.scalars(
                    select(CourseOccurrence).where(CourseOccurrence.course_id == course.id)
                )
            )
            assert any(
                isinstance(row.context.get("source_span_ids"), list)
                and row.context["source_span_ids"]
                for row in occurrences
            )
    finally:
        await database.close()
