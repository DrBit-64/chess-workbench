"""Focused 8D-3E2B persistence-model oracles for the incremental PDF extraction document tables.

Locks the frozen immutable/mutable ORM shape for the four new tables:

- ``pdf_extraction_documents`` is the only mutable head projection
  (``updated_at`` + ``version`` lifecycle fields);
- ``pdf_extraction_document_segments``, ``pdf_extraction_document_revisions``
  and ``pdf_extraction_document_appends`` are immutable receipts
  (creation timestamp only).

It also proves the MySQL guarantees rendered for these four tables:
InnoDB engine, binary ASCII hash/key identity, case-sensitive revision
paths, ``RESTRICT`` foreign keys, and constraint identifiers <= 64 chars.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from chess_workbench.store.base import Base
from chess_workbench.store.models import (
    ExtractionRun,
    Job,
    PdfAsset,
    PdfExtractionDocument,
    PdfExtractionDocumentAppend,
    PdfExtractionDocumentRevision,
    PdfExtractionDocumentSegment,
    Source,
    SourceFile,
    SourceVersion,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

NEW_TABLE_NAMES = (
    "pdf_extraction_documents",
    "pdf_extraction_document_segments",
    "pdf_extraction_document_revisions",
    "pdf_extraction_document_appends",
)

IMMUTABLE_LIFECYCLE_FIELDS = {"status", "version", "updated_at", "archived_at"}


def _alembic_config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


class _RevisionModule(Protocol):
    def upgrade(self) -> None: ...

    def downgrade(self) -> None: ...


def _revision_modules() -> list[_RevisionModule]:
    scripts = ScriptDirectory.from_config(_alembic_config())
    newest_first = scripts.walk_revisions(base="base", head="heads")
    return [cast(_RevisionModule, script.module) for script in reversed(list(newest_first))]


def _run_upgrades(context: MigrationContext) -> None:
    with Operations.context(context):
        for revision in _revision_modules():
            revision.upgrade()


def _run_downgrades(context: MigrationContext) -> None:
    with Operations.context(context):
        for revision in reversed(_revision_modules()):
            revision.downgrade()


def _inserted_uuid(result: Any) -> UUID:
    primary_key = result.inserted_primary_key
    assert primary_key is not None
    return cast(UUID, primary_key[0])


def _sqlite_engine() -> sa.Engine:
    """SQLite engine with runtime FK enforcement enabled.

    SQLite disables ``PRAGMA foreign_keys`` by default; the RESTRICT-delete
    oracles are only meaningful when the pragma is switched on.
    """

    engine = sa.create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _new_tables() -> list[sa.Table]:
    return [Base.metadata.tables[name] for name in NEW_TABLE_NAMES]


def _seed_parent_chain(connection: sa.Connection) -> dict[str, UUID]:
    now = datetime.now(UTC)
    source_id = _inserted_uuid(
        connection.execute(
            sa.insert(Source).values(kind="book", title="PDF source", updated_at=now)
        )
    )
    source_version_id = _inserted_uuid(
        connection.execute(
            sa.insert(SourceVersion).values(source_id=source_id, label="v1", updated_at=now)
        )
    )
    source_file_id = _inserted_uuid(
        connection.execute(
            sa.insert(SourceFile).values(
                source_version_id=source_version_id,
                filename="book.pdf",
                relative_path="sources/pdf/ab/abcdef.pdf",
                media_type="application/pdf",
                size_bytes=10,
                sha256="1" * 64,
                updated_at=now,
            )
        )
    )
    return {
        "source_id": source_id,
        "source_version_id": source_version_id,
        "source_file_id": source_file_id,
    }


def _seed_job(connection: sa.Connection, idempotency_key: str) -> UUID:
    now = datetime.now(UTC)
    return _inserted_uuid(
        connection.execute(
            sa.insert(Job).values(
                kind="pdf_extraction",
                payload={},
                idempotency_key=idempotency_key,
                request_hash="3" * 64,
                available_at=now,
                updated_at=now,
            )
        )
    )


def _seed_pdf_document_graph(connection: sa.Connection) -> dict[str, UUID]:
    """Seed one complete document graph using only invented synthetic rows.

    The graph contains:
    - one mutable ``PdfExtractionDocument`` head;
    - two segments (ordinal 1 and 2) so both revision uniqueness
      constraints can be exercised independently;
    - one revision terminating at the first segment;
    - one append attempt referencing the revision and the second run.
    """

    now = datetime.now(UTC)
    parents = _seed_parent_chain(connection)
    asset_id = _inserted_uuid(
        connection.execute(
            sa.insert(PdfAsset).values(
                content_sha256="2" * 64,
                byte_size=10,
                page_count=42,
                **parents,
            )
        )
    )

    def _seed_run(idempotency_key: str, effective_key_hash: str) -> UUID:
        job_id = _seed_job(connection, idempotency_key)
        return _inserted_uuid(
            connection.execute(
                sa.insert(ExtractionRun).values(
                    pdf_asset_id=asset_id,
                    job_id=job_id,
                    first_page=1,
                    last_page=2,
                    pipeline_version="8b-pdf/1",
                    logical_fingerprint="4" * 64,
                    effective_key_hash=effective_key_hash,
                )
            )
        )

    run1 = _seed_run("pdf-doc-seg-1", "5" * 64)
    run2 = _seed_run("pdf-doc-append-1", "6" * 64)
    run3 = _seed_run("pdf-doc-seg-2", "8" * 64)

    document_id = _inserted_uuid(
        connection.execute(
            sa.insert(PdfExtractionDocument).values(
                pdf_asset_id=asset_id,
                first_page=1,
                last_page=2,
                normalized_ccef_sha256="a" * 64,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
    )

    def _seed_segment(extraction_run_id: UUID, ordinal: int) -> UUID:
        return _inserted_uuid(
            connection.execute(
                sa.insert(PdfExtractionDocumentSegment).values(
                    document_id=document_id,
                    extraction_run_id=extraction_run_id,
                    ordinal=ordinal,
                    first_page=1,
                    last_page=2,
                    normalized_ccef_sha256="a" * 64,
                )
            )
        )

    segment1_id = _seed_segment(run1, 1)
    segment2_id = _seed_segment(run3, 2)

    revision_id = _inserted_uuid(
        connection.execute(
            sa.insert(PdfExtractionDocumentRevision).values(
                document_id=document_id,
                predecessor_revision_id=None,
                terminal_segment_id=segment1_id,
                revision_number=1,
                segment_count=1,
                first_page=1,
                last_page=2,
                algorithm_version="8b-pdf/1",
                relative_path="sources/pdf/revisions/1.json",
                media_type="application/json",
                byte_size=99,
                normalized_ccef_sha256="a" * 64,
            )
        )
    )

    append_id = _inserted_uuid(
        connection.execute(
            sa.insert(PdfExtractionDocumentAppend).values(
                document_id=document_id,
                predecessor_revision_id=revision_id,
                extraction_run_id=run2,
                expected_version=1,
                predecessor_normalized_ccef_sha256="a" * 64,
                first_page=3,
                last_page=4,
                profile={"render_profile": "pdfium@2"},
                logical_fingerprint="4" * 64,
                effective_key_hash="7" * 64,
            )
        )
    )

    return {
        "asset_id": asset_id,
        "run1": run1,
        "run2": run2,
        "run3": run3,
        "document_id": document_id,
        "segment1_id": segment1_id,
        "segment2_id": segment2_id,
        "revision_id": revision_id,
        "append_id": append_id,
    }


def test_pdf_document_tables_have_exact_columns_and_only_head_is_mutable() -> None:
    assert set(PdfExtractionDocument.__table__.columns.keys()) == {
        "id",
        "created_at",
        "updated_at",
        "version",
        "pdf_asset_id",
        "first_page",
        "last_page",
        "normalized_ccef_sha256",
    }
    assert set(PdfExtractionDocumentSegment.__table__.columns.keys()) == {
        "id",
        "created_at",
        "document_id",
        "extraction_run_id",
        "ordinal",
        "first_page",
        "last_page",
        "normalized_ccef_sha256",
    }
    assert set(PdfExtractionDocumentRevision.__table__.columns.keys()) == {
        "id",
        "created_at",
        "document_id",
        "predecessor_revision_id",
        "terminal_segment_id",
        "revision_number",
        "segment_count",
        "first_page",
        "last_page",
        "algorithm_version",
        "relative_path",
        "media_type",
        "byte_size",
        "normalized_ccef_sha256",
    }
    assert set(PdfExtractionDocumentAppend.__table__.columns.keys()) == {
        "id",
        "created_at",
        "document_id",
        "predecessor_revision_id",
        "extraction_run_id",
        "expected_version",
        "predecessor_normalized_ccef_sha256",
        "first_page",
        "last_page",
        "profile",
        "logical_fingerprint",
        "effective_key_hash",
    }
    # Only the head document is mutable.
    assert {"version", "updated_at"} <= set(PdfExtractionDocument.__table__.columns.keys())
    for table in (
        PdfExtractionDocumentSegment.__table__,
        PdfExtractionDocumentRevision.__table__,
        PdfExtractionDocumentAppend.__table__,
    ):
        assert IMMUTABLE_LIFECYCLE_FIELDS.isdisjoint(set(table.columns.keys()))


def test_pdf_document_uuid_and_aware_utc_round_trip() -> None:
    engine = _sqlite_engine()
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
        with engine.begin() as connection:
            ids = _seed_pdf_document_graph(connection)

        with engine.connect() as connection:
            document = (
                connection.execute(
                    sa.select(PdfExtractionDocument).where(
                        PdfExtractionDocument.id == ids["document_id"]
                    )
                )
                .mappings()
                .one()
            )
            segment = (
                connection.execute(
                    sa.select(PdfExtractionDocumentSegment).where(
                        PdfExtractionDocumentSegment.id == ids["segment1_id"]
                    )
                )
                .mappings()
                .one()
            )
            revision = (
                connection.execute(
                    sa.select(PdfExtractionDocumentRevision).where(
                        PdfExtractionDocumentRevision.id == ids["revision_id"]
                    )
                )
                .mappings()
                .one()
            )
            append = (
                connection.execute(
                    sa.select(PdfExtractionDocumentAppend).where(
                        PdfExtractionDocumentAppend.id == ids["append_id"]
                    )
                )
                .mappings()
                .one()
            )

        assert isinstance(document["id"], UUID)
        assert document["pdf_asset_id"] == ids["asset_id"]
        assert document["first_page"] == 1
        assert document["last_page"] == 2
        assert document["normalized_ccef_sha256"] == "a" * 64
        assert document["version"] == 1
        assert document["created_at"].tzinfo is UTC
        assert document["updated_at"].tzinfo is UTC

        assert isinstance(segment["id"], UUID)
        assert segment["document_id"] == ids["document_id"]
        assert segment["extraction_run_id"] == ids["run1"]
        assert segment["ordinal"] == 1
        assert segment["first_page"] == 1
        assert segment["last_page"] == 2
        assert segment["normalized_ccef_sha256"] == "a" * 64
        assert segment["created_at"].tzinfo is UTC

        assert isinstance(revision["id"], UUID)
        assert revision["document_id"] == ids["document_id"]
        assert revision["predecessor_revision_id"] is None
        assert revision["terminal_segment_id"] == ids["segment1_id"]
        assert revision["revision_number"] == 1
        assert revision["segment_count"] == 1
        assert revision["first_page"] == 1
        assert revision["last_page"] == 2
        assert revision["algorithm_version"] == "8b-pdf/1"
        assert revision["relative_path"] == "sources/pdf/revisions/1.json"
        assert revision["media_type"] == "application/json"
        assert revision["byte_size"] == 99
        assert revision["normalized_ccef_sha256"] == "a" * 64
        assert revision["created_at"].tzinfo is UTC

        assert isinstance(append["id"], UUID)
        assert append["document_id"] == ids["document_id"]
        assert append["predecessor_revision_id"] == ids["revision_id"]
        assert append["extraction_run_id"] == ids["run2"]
        assert append["expected_version"] == 1
        assert append["predecessor_normalized_ccef_sha256"] == "a" * 64
        assert append["first_page"] == 3
        assert append["last_page"] == 4
        assert append["profile"] == {"render_profile": "pdfium@2"}
        assert append["logical_fingerprint"] == "4" * 64
        assert append["effective_key_hash"] == "7" * 64
        assert append["created_at"].tzinfo is UTC
    finally:
        engine.dispose()


def test_pdf_document_check_and_unique_constraints_reject_invalid_rows() -> None:
    engine = _sqlite_engine()
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
        with engine.begin() as connection:
            ids = _seed_pdf_document_graph(connection)

        def _rejects(values: dict[str, Any], model: type[Any]) -> None:
            # Each check runs on a fresh connection with its own transaction, so a
            # rejected insert rolls back cleanly without touching the seeded data.
            with (
                engine.connect() as check_connection,
                check_connection.begin(),
                pytest.raises(IntegrityError),
            ):
                check_connection.execute(sa.insert(model).values(**values))

        # Head document check constraints.
        _rejects(
            {
                "pdf_asset_id": ids["asset_id"],
                "first_page": 0,
                "last_page": 2,
                "normalized_ccef_sha256": "a" * 64,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "version": 1,
            },
            PdfExtractionDocument,
        )
        _rejects(
            {
                "pdf_asset_id": ids["asset_id"],
                "first_page": 5,
                "last_page": 4,
                "normalized_ccef_sha256": "a" * 64,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "version": 1,
            },
            PdfExtractionDocument,
        )
        _rejects(
            {
                "pdf_asset_id": ids["asset_id"],
                "first_page": 1,
                "last_page": 2,
                "normalized_ccef_sha256": "a" * 63,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "version": 1,
            },
            PdfExtractionDocument,
        )
        _rejects(
            {
                "pdf_asset_id": ids["asset_id"],
                "first_page": 1,
                "last_page": 2,
                "normalized_ccef_sha256": "a" * 64,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "version": 0,
            },
            PdfExtractionDocument,
        )

        # Segment check and unique constraints.
        _rejects(
            {
                "document_id": ids["document_id"],
                "extraction_run_id": ids["run1"],
                "ordinal": 0,
                "first_page": 1,
                "last_page": 2,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentSegment,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "extraction_run_id": ids["run2"],
                "ordinal": 2,
                "first_page": 0,
                "last_page": 2,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentSegment,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "extraction_run_id": ids["run2"],
                "ordinal": 2,
                "first_page": 5,
                "last_page": 4,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentSegment,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "extraction_run_id": ids["run2"],
                "ordinal": 2,
                "first_page": 1,
                "last_page": 2,
                "normalized_ccef_sha256": "a" * 63,
            },
            PdfExtractionDocumentSegment,
        )
        # Duplicate (document_id, ordinal) with a different run.
        _rejects(
            {
                "document_id": ids["document_id"],
                "extraction_run_id": ids["run2"],
                "ordinal": 1,
                "first_page": 1,
                "last_page": 2,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentSegment,
        )
        # Reusing an already-segmented run at a different ordinal.
        _rejects(
            {
                "document_id": ids["document_id"],
                "extraction_run_id": ids["run1"],
                "ordinal": 2,
                "first_page": 1,
                "last_page": 2,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentSegment,
        )

        # Revision check and unique constraints.
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 0,
                "segment_count": 1,
                "first_page": 1,
                "last_page": 2,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "application/json",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 2,
                "segment_count": 0,
                "first_page": 1,
                "last_page": 2,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "application/json",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 2,
                "segment_count": 1,
                "first_page": 0,
                "last_page": 2,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "application/json",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 2,
                "segment_count": 1,
                "first_page": 5,
                "last_page": 4,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "application/json",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 2,
                "segment_count": 1,
                "first_page": 1,
                "last_page": 2,
                "algorithm_version": "",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "application/json",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 2,
                "segment_count": 1,
                "first_page": 1,
                "last_page": 2,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "",
                "media_type": "application/json",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 2,
                "segment_count": 1,
                "first_page": 1,
                "last_page": 2,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 2,
                "segment_count": 1,
                "first_page": 1,
                "last_page": 2,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "application/json",
                "byte_size": 0,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 2,
                "segment_count": 1,
                "first_page": 1,
                "last_page": 2,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "application/json",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 63,
            },
            PdfExtractionDocumentRevision,
        )
        # Duplicate (document_id, revision_number) with a different terminal segment.
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment2_id"],
                "revision_number": 1,
                "segment_count": 1,
                "first_page": 1,
                "last_page": 2,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "application/json",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )
        # Duplicate terminal segment at a different revision number.
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "terminal_segment_id": ids["segment1_id"],
                "revision_number": 2,
                "segment_count": 1,
                "first_page": 1,
                "last_page": 2,
                "algorithm_version": "8b-pdf/1",
                "relative_path": "sources/pdf/revisions/2.json",
                "media_type": "application/json",
                "byte_size": 99,
                "normalized_ccef_sha256": "a" * 64,
            },
            PdfExtractionDocumentRevision,
        )

        # Append check and unique constraints.
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "extraction_run_id": ids["run3"],
                "expected_version": 0,
                "predecessor_normalized_ccef_sha256": "a" * 64,
                "first_page": 3,
                "last_page": 4,
                "profile": {},
                "logical_fingerprint": "4" * 64,
                "effective_key_hash": "9" * 64,
            },
            PdfExtractionDocumentAppend,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "extraction_run_id": ids["run3"],
                "expected_version": 1,
                "predecessor_normalized_ccef_sha256": "a" * 64,
                "first_page": 0,
                "last_page": 4,
                "profile": {},
                "logical_fingerprint": "4" * 64,
                "effective_key_hash": "9" * 64,
            },
            PdfExtractionDocumentAppend,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "extraction_run_id": ids["run3"],
                "expected_version": 1,
                "predecessor_normalized_ccef_sha256": "a" * 64,
                "first_page": 5,
                "last_page": 4,
                "profile": {},
                "logical_fingerprint": "4" * 64,
                "effective_key_hash": "9" * 64,
            },
            PdfExtractionDocumentAppend,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "extraction_run_id": ids["run3"],
                "expected_version": 1,
                "predecessor_normalized_ccef_sha256": "a" * 63,
                "first_page": 3,
                "last_page": 4,
                "profile": {},
                "logical_fingerprint": "4" * 64,
                "effective_key_hash": "9" * 64,
            },
            PdfExtractionDocumentAppend,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "extraction_run_id": ids["run3"],
                "expected_version": 1,
                "predecessor_normalized_ccef_sha256": "a" * 64,
                "first_page": 3,
                "last_page": 4,
                "profile": {},
                "logical_fingerprint": "4" * 63,
                "effective_key_hash": "9" * 64,
            },
            PdfExtractionDocumentAppend,
        )
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "extraction_run_id": ids["run3"],
                "expected_version": 1,
                "predecessor_normalized_ccef_sha256": "a" * 64,
                "first_page": 3,
                "last_page": 4,
                "profile": {},
                "logical_fingerprint": "4" * 64,
                "effective_key_hash": "9" * 63,
            },
            PdfExtractionDocumentAppend,
        )
        # Duplicate append run (run2 already used by the seeded append).
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "extraction_run_id": ids["run2"],
                "expected_version": 1,
                "predecessor_normalized_ccef_sha256": "a" * 64,
                "first_page": 3,
                "last_page": 4,
                "profile": {},
                "logical_fingerprint": "4" * 64,
                "effective_key_hash": "9" * 64,
            },
            PdfExtractionDocumentAppend,
        )
        # Duplicate effective key hash ("7"*64 already used by the seeded append).
        _rejects(
            {
                "document_id": ids["document_id"],
                "predecessor_revision_id": ids["revision_id"],
                "extraction_run_id": ids["run3"],
                "expected_version": 1,
                "predecessor_normalized_ccef_sha256": "a" * 64,
                "first_page": 3,
                "last_page": 4,
                "profile": {},
                "logical_fingerprint": "4" * 64,
                "effective_key_hash": "7" * 64,
            },
            PdfExtractionDocumentAppend,
        )
    finally:
        engine.dispose()


def test_pdf_document_restrict_fks_reject_deletes() -> None:
    engine = _sqlite_engine()
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
        with engine.begin() as connection:
            ids = _seed_pdf_document_graph(connection)

        # Every new-table FK must be RESTRICT at the metadata level.
        for table in _new_tables():
            assert {fk.ondelete for fk in table.foreign_key_constraints} == {"RESTRICT"}

        # Deleting any referenced parent row must be rejected by RESTRICT.
        def _delete_rejected(statement: Any) -> None:
            with (
                engine.connect() as check_connection,
                check_connection.begin(),
                pytest.raises(IntegrityError),
            ):
                check_connection.execute(statement)

        _delete_rejected(sa.delete(PdfAsset).where(PdfAsset.id == ids["asset_id"]))
        _delete_rejected(
            sa.delete(PdfExtractionDocument).where(PdfExtractionDocument.id == ids["document_id"])
        )
        _delete_rejected(
            sa.delete(PdfExtractionDocumentSegment).where(
                PdfExtractionDocumentSegment.id == ids["segment1_id"]
            )
        )
        _delete_rejected(
            sa.delete(PdfExtractionDocumentRevision).where(
                PdfExtractionDocumentRevision.id == ids["revision_id"]
            )
        )
    finally:
        engine.dispose()


def test_pdf_document_mysql_ddl_and_short_constraint_names() -> None:
    new_tables = _new_tables()
    mysql_ddl = "\n".join(
        str(CreateTable(table).compile(dialect=mysql.dialect())) for table in new_tables
    )
    assert mysql_ddl.count("ENGINE=InnoDB") == 4
    assert mysql_ddl.count("ON DELETE RESTRICT") == 9
    # Binary ASCII identity for hashes/keys; case-sensitive Unicode for revision paths.
    assert "CHARACTER SET ascii COLLATE ascii_bin" in mysql_ddl
    assert "CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" in mysql_ddl
    assert mysql_ddl.count("DATETIME(6) NOT NULL") == 5
    constraint_names = {
        str(constraint.name)
        for table in new_tables
        for constraint in table.constraints
        if constraint.name is not None
    }
    assert max(map(len, constraint_names)) <= 64


def test_pdf_document_migrations_match_metadata_and_downgrade_cleanly() -> None:
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "target_metadata": Base.metadata,
                    "compare_type": True,
                    "compare_server_default": True,
                },
            )
            _run_upgrades(context)
            assert compare_metadata(context, Base.metadata) == []
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) == set(Base.metadata.tables)
            for table in _new_tables():
                assert {fk.ondelete for fk in table.foreign_key_constraints} == {"RESTRICT"}
        with engine.begin() as connection:
            _run_downgrades(MigrationContext.configure(connection))
            assert sa.inspect(connection).get_table_names() == []
    finally:
        engine.dispose()


def test_pdf_document_offline_mysql_downgrade_has_no_index_drops() -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output, "target_metadata": Base.metadata},
    )
    _run_downgrades(context)
    downgrade_ddl = output.getvalue()
    assert downgrade_ddl.count("DROP TABLE") == len(Base.metadata.tables)
    # Migration 0012 is the newest revision, so its downgrade (four DROP TABLE
    # statements, no index drops) runs first in the offline chain. Older
    # migrations may legitimately emit DROP INDEX for their own tables, so the
    # no-index-drop guarantee is scoped to migration 0012's own section.
    new_tables_ddl = downgrade_ddl[
        : downgrade_ddl.index("DROP TABLE pdf_extraction_documents;")
        + len("DROP TABLE pdf_extraction_documents;")
    ]
    assert new_tables_ddl.count("DROP TABLE") == 4
    assert "DROP INDEX" not in new_tables_ddl
