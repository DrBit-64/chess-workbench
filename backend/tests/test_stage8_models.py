"""Focused Stage 8A persistence-model tests (packet DS-STAGE8A-PDF-MODELS-01).

Proves the frozen immutable ORM shape: exact column sets without lifecycle
fields, UUID + aware-UTC round trips, every check/unique rejection on SQLite,
shared ``logical_fingerprint`` receipts and the RESTRICT/InnoDB/collation/
constraint-name guarantees rendered for MySQL.
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
    ExtractionArtifact,
    ExtractionRun,
    Job,
    PdfAsset,
    Source,
    SourceFile,
    SourceVersion,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

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


def test_stage8_tables_have_exact_columns_and_no_mutable_lifecycle() -> None:
    assert set(PdfAsset.__table__.columns.keys()) == {
        "id",
        "created_at",
        "content_sha256",
        "byte_size",
        "page_count",
        "source_id",
        "source_version_id",
        "source_file_id",
    }
    assert set(ExtractionRun.__table__.columns.keys()) == {
        "id",
        "created_at",
        "pdf_asset_id",
        "job_id",
        "first_page",
        "last_page",
        "pipeline_version",
        "logical_fingerprint",
        "effective_key_hash",
    }
    assert set(ExtractionArtifact.__table__.columns.keys()) == {
        "id",
        "created_at",
        "run_id",
        "kind",
        "page_number",
        "relative_path",
        "media_type",
        "byte_size",
        "content_sha256",
    }
    for table in (
        PdfAsset.__table__,
        ExtractionRun.__table__,
        ExtractionArtifact.__table__,
    ):
        assert IMMUTABLE_LIFECYCLE_FIELDS.isdisjoint(set(table.columns.keys()))


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


def test_stage8_uuid_and_aware_utc_round_trip() -> None:
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
        with engine.begin() as connection:
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
            job_id = _seed_job(connection, "round-trip-job")
            run_id = _inserted_uuid(
                connection.execute(
                    sa.insert(ExtractionRun).values(
                        pdf_asset_id=asset_id,
                        job_id=job_id,
                        first_page=3,
                        last_page=9,
                        pipeline_version="8a-pdf/1",
                        logical_fingerprint="4" * 64,
                        effective_key_hash="5" * 64,
                    )
                )
            )
            artifact_id = _inserted_uuid(
                connection.execute(
                    sa.insert(ExtractionArtifact).values(
                        run_id=run_id,
                        kind="raw_ccef",
                        page_number=3,
                        relative_path="sources/pdf/artifacts/raw_ccef.json",
                        media_type="application/json",
                        byte_size=99,
                        content_sha256="6" * 64,
                    )
                )
            )

        with engine.connect() as connection:
            asset = (
                connection.execute(sa.select(PdfAsset).where(PdfAsset.id == asset_id))
                .mappings()
                .one()
            )
            run = (
                connection.execute(sa.select(ExtractionRun).where(ExtractionRun.id == run_id))
                .mappings()
                .one()
            )
            artifact = (
                connection.execute(
                    sa.select(ExtractionArtifact).where(ExtractionArtifact.id == artifact_id)
                )
                .mappings()
                .one()
            )

        assert isinstance(asset["id"], UUID)
        assert asset["content_sha256"] == "2" * 64
        assert asset["byte_size"] == 10
        assert asset["page_count"] == 42
        assert asset["source_id"] == parents["source_id"]
        assert asset["source_version_id"] == parents["source_version_id"]
        assert asset["source_file_id"] == parents["source_file_id"]
        assert asset["created_at"].tzinfo is UTC

        assert isinstance(run["id"], UUID)
        assert run["pdf_asset_id"] == asset_id
        assert run["job_id"] == job_id
        assert run["first_page"] == 3
        assert run["last_page"] == 9
        assert run["pipeline_version"] == "8a-pdf/1"
        assert run["logical_fingerprint"] == "4" * 64
        assert run["effective_key_hash"] == "5" * 64
        assert run["created_at"].tzinfo is UTC

        assert isinstance(artifact["id"], UUID)
        assert artifact["run_id"] == run_id
        assert artifact["kind"] == "raw_ccef"
        assert artifact["page_number"] == 3
        assert artifact["relative_path"] == "sources/pdf/artifacts/raw_ccef.json"
        assert artifact["media_type"] == "application/json"
        assert artifact["byte_size"] == 99
        assert artifact["content_sha256"] == "6" * 64
        assert artifact["created_at"].tzinfo is UTC
    finally:
        engine.dispose()


def test_stage8_check_and_unique_constraints_reject_invalid_rows() -> None:
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
        with engine.begin() as connection:
            parents = _seed_parent_chain(connection)
            asset_id = _inserted_uuid(
                connection.execute(
                    sa.insert(PdfAsset).values(
                        content_sha256="2" * 64,
                        byte_size=10,
                        page_count=10,
                        **parents,
                    )
                )
            )
            job_id = _seed_job(connection, "constraint-job")
            run_id = _inserted_uuid(
                connection.execute(
                    sa.insert(ExtractionRun).values(
                        pdf_asset_id=asset_id,
                        job_id=job_id,
                        first_page=1,
                        last_page=2,
                        pipeline_version="8a/1",
                        logical_fingerprint="4" * 64,
                        effective_key_hash="5" * 64,
                    )
                )
            )
            _inserted_uuid(
                connection.execute(
                    sa.insert(ExtractionArtifact).values(
                        run_id=run_id,
                        kind="raw_ccef",
                        page_number=1,
                        relative_path="sources/pdf/artifacts/base.json",
                        media_type="application/json",
                        byte_size=1,
                        content_sha256="6" * 64,
                    )
                )
            )

            invalid_asset_rows = (
                {"content_sha256": "a" * 63, "byte_size": 10, "page_count": 1},
                {"content_sha256": "a" * 64, "byte_size": 0, "page_count": 1},
                {"content_sha256": "a" * 64, "byte_size": 10, "page_count": 0},
                {"content_sha256": "a" * 64, "byte_size": 10, "page_count": 20_001},
            )
            for asset_values in invalid_asset_rows:
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        sa.insert(PdfAsset).values(
                            source_id=parents["source_id"],
                            source_version_id=parents["source_version_id"],
                            source_file_id=parents["source_file_id"],
                            **asset_values,
                        )
                    )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    sa.insert(PdfAsset).values(
                        content_sha256="2" * 64,
                        byte_size=10,
                        page_count=1,
                        **parents,
                    )
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    sa.insert(PdfAsset).values(
                        content_sha256="b" * 64,
                        byte_size=10,
                        page_count=1,
                        source_id=parents["source_id"],
                        source_version_id=UUID(int=1),
                        source_file_id=UUID(int=2),
                    )
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    sa.insert(PdfAsset).values(
                        content_sha256="c" * 64,
                        byte_size=10,
                        page_count=1,
                        source_id=UUID(int=3),
                        source_version_id=parents["source_version_id"],
                        source_file_id=UUID(int=4),
                    )
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    sa.insert(PdfAsset).values(
                        content_sha256="d" * 64,
                        byte_size=10,
                        page_count=1,
                        source_id=UUID(int=5),
                        source_version_id=UUID(int=6),
                        source_file_id=parents["source_file_id"],
                    )
                )

            invalid_run_rows = (
                {"first_page": 0, "last_page": 2},
                {"first_page": 5, "last_page": 4},
                {"pipeline_version": ""},
                {"logical_fingerprint": "a" * 63},
                {"effective_key_hash": "a" * 63},
            )
            run_base_values: dict[str, object] = {
                "pdf_asset_id": asset_id,
                "job_id": job_id,
                "first_page": 1,
                "last_page": 2,
                "pipeline_version": "8a/1",
                "logical_fingerprint": "4" * 64,
                "effective_key_hash": "7" * 64,
            }
            for run_values in invalid_run_rows:
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        sa.insert(ExtractionRun).values(**{**run_base_values, **run_values})
                    )

            second_job_id = _seed_job(connection, "constraint-job-2")
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    sa.insert(ExtractionRun).values(
                        pdf_asset_id=asset_id,
                        job_id=second_job_id,
                        first_page=1,
                        last_page=2,
                        pipeline_version="8a/1",
                        logical_fingerprint="8" * 64,
                        effective_key_hash="5" * 64,
                    )
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    sa.insert(ExtractionRun).values(
                        pdf_asset_id=asset_id,
                        job_id=job_id,
                        first_page=1,
                        last_page=2,
                        pipeline_version="8a/1",
                        logical_fingerprint="8" * 64,
                        effective_key_hash="9" * 64,
                    )
                )

            invalid_artifact_rows = (
                {"kind": "bogus"},
                {"page_number": 0},
                {"relative_path": ""},
                {"media_type": ""},
                {"byte_size": 0},
                {"content_sha256": "a" * 63},
            )
            artifact_base_values: dict[str, object] = {
                "run_id": run_id,
                "kind": "raw_ccef",
                "page_number": 1,
                "relative_path": "sources/pdf/artifacts/one.json",
                "media_type": "application/json",
                "byte_size": 1,
                "content_sha256": "6" * 64,
            }
            for artifact_values in invalid_artifact_rows:
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        sa.insert(ExtractionArtifact).values(
                            **{**artifact_base_values, **artifact_values}
                        )
                    )

            # Stage 8B permits multiple immutable artifact indexes to reuse one
            # content-addressed blob. Logical-slot conflicts and metadata/hash
            # agreement are serialized and enforced by the registration service,
            # not by global path or run/kind/hash uniqueness constraints.
    finally:
        engine.dispose()


def test_stage8_runs_may_share_logical_fingerprint() -> None:
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
        with engine.begin() as connection:
            parents = _seed_parent_chain(connection)
            asset_id = _inserted_uuid(
                connection.execute(
                    sa.insert(PdfAsset).values(
                        content_sha256="2" * 64,
                        byte_size=10,
                        page_count=10,
                        **parents,
                    )
                )
            )
            first_job_id = _seed_job(connection, "fingerprint-job-1")
            second_job_id = _seed_job(connection, "fingerprint-job-2")
            shared_fingerprint = "4" * 64
            first_run_id = _inserted_uuid(
                connection.execute(
                    sa.insert(ExtractionRun).values(
                        pdf_asset_id=asset_id,
                        job_id=first_job_id,
                        first_page=1,
                        last_page=2,
                        pipeline_version="8a/1",
                        logical_fingerprint=shared_fingerprint,
                        effective_key_hash="5" * 64,
                    )
                )
            )
            second_run_id = _inserted_uuid(
                connection.execute(
                    sa.insert(ExtractionRun).values(
                        pdf_asset_id=asset_id,
                        job_id=second_job_id,
                        first_page=1,
                        last_page=2,
                        pipeline_version="8a/1",
                        logical_fingerprint=shared_fingerprint,
                        effective_key_hash="6" * 64,
                    )
                )
            )

        with engine.connect() as connection:
            fingerprints = set(
                connection.execute(
                    sa.select(ExtractionRun.logical_fingerprint).where(
                        ExtractionRun.id.in_([first_run_id, second_run_id])
                    )
                ).scalars()
            )
            assert fingerprints == {shared_fingerprint}
    finally:
        engine.dispose()


def test_stage8_restrict_fks_and_mysql_ddl_and_short_constraint_names() -> None:
    new_tables = [
        Base.metadata.tables[name]
        for name in ("pdf_assets", "extraction_runs", "extraction_artifacts")
    ]

    for table in new_tables:
        assert {fk.ondelete for fk in table.foreign_key_constraints} == {"RESTRICT"}

    mysql_ddl = "\n".join(
        str(CreateTable(table).compile(dialect=mysql.dialect())) for table in new_tables
    )
    assert mysql_ddl.count("ENGINE=InnoDB") == 3
    assert mysql_ddl.count("ON DELETE RESTRICT") == 6
    assert "CHARACTER SET ascii COLLATE ascii_bin" in mysql_ddl
    assert "CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" in mysql_ddl
    assert "DATETIME(6) NOT NULL" in mysql_ddl

    constraint_names = {
        str(constraint.name)
        for table in new_tables
        for constraint in table.constraints
        if constraint.name is not None
    }
    assert constraint_names
    assert max(map(len, constraint_names)) <= 64


def test_stage8_migrations_match_metadata_and_downgrade_cleanly() -> None:
    """Offline SQLite upgrades to head match the models; downgrade reaches zero tables."""

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
            for table_name in ("pdf_assets", "extraction_runs", "extraction_artifacts"):
                for foreign_key in inspector.get_foreign_keys(table_name):
                    assert foreign_key["options"].get("ondelete") == "RESTRICT"

            _run_downgrades(context)
            assert sa.inspect(connection).get_table_names() == []
    finally:
        engine.dispose()


def test_stage8_offline_mysql_downgrade_has_no_index_drops() -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={
            "as_sql": True,
            "output_buffer": output,
            "target_metadata": Base.metadata,
        },
    )
    _run_downgrades(context)
    downgrade_ddl = output.getvalue()

    assert downgrade_ddl.count("DROP TABLE") == len(Base.metadata.tables)
    assert "DROP INDEX ix_" not in downgrade_ddl
