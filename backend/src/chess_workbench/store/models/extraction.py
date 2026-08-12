"""Immutable Stage 8A PDF asset, extraction receipt and artifact index records.

These records are durable receipts/indexes only: the running job status lives on
``jobs`` and nothing here carries progress, result JSON, lifecycle, version or
archive fields.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chess_workbench.store.base import Base
from chess_workbench.store.models.mixins import UTCCreatedAtMixin, UUIDPrimaryKeyMixin


def _ascii_string(length: int) -> String:
    """Store ASCII identity values with portable binary comparison semantics."""

    return String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


def _case_sensitive_string(length: int) -> String:
    """Keep unique Unicode relative paths case-sensitive on SQLite and MySQL."""

    return String(length).with_variant(
        mysql.VARCHAR(length, charset="utf8mb4", collation="utf8mb4_bin"),
        "mysql",
    )


class PdfAsset(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Immutable content-addressed PDF upload record owned by one source."""

    __tablename__ = "pdf_assets"
    __table_args__ = (
        CheckConstraint("length(content_sha256) = 64", name="sha256_length"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("page_count >= 1 AND page_count <= 20000", name="page_count_range"),
        UniqueConstraint("content_sha256", name="uq_pdf_assets_content_sha256"),
        UniqueConstraint("source_id", name="uq_pdf_assets_source_id"),
        UniqueConstraint("source_version_id", name="uq_pdf_assets_source_version_id"),
        UniqueConstraint("source_file_id", name="uq_pdf_assets_source_file_id"),
        {"mysql_engine": "InnoDB"},
    )

    content_sha256: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    source_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=False
    )

    runs: Mapped[list[ExtractionRun]] = relationship(back_populates="pdf_asset")


class ExtractionRun(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Immutable physical-page extraction request receipt keyed by effective key."""

    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint("first_page >= 1", name="first_page_positive"),
        CheckConstraint("last_page >= first_page", name="page_range_valid"),
        CheckConstraint("length(pipeline_version) > 0", name="pipeline_version_nonempty"),
        CheckConstraint("length(logical_fingerprint) = 64", name="fingerprint_length"),
        CheckConstraint("length(effective_key_hash) = 64", name="key_hash_length"),
        UniqueConstraint("effective_key_hash", name="uq_extraction_runs_effective_key_hash"),
        UniqueConstraint("job_id", name="uq_extraction_runs_job_id"),
        Index("ix_extraction_runs_fingerprint", "logical_fingerprint"),
        Index("ix_extraction_runs_asset_created", "pdf_asset_id", "created_at"),
        {"mysql_engine": "InnoDB"},
    )

    pdf_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("pdf_assets.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False)
    first_page: Mapped[int] = mapped_column(Integer, nullable=False)
    last_page: Mapped[int] = mapped_column(Integer, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    logical_fingerprint: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)
    effective_key_hash: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)

    pdf_asset: Mapped[PdfAsset] = relationship(back_populates="runs")
    artifacts: Mapped[list[ExtractionArtifact]] = relationship(back_populates="run")


class ExtractionArtifact(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Immutable derived-artifact index row pointing into the raw CAS."""

    __tablename__ = "extraction_artifacts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('rendered_page','render_manifest','ocr_fragment','ocr_manifest',"
            "'provider_response','raw_ccef','normalized_ccef')",
            name="kind",
        ),
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="page_number_positive"),
        CheckConstraint("length(relative_path) > 0", name="relative_path_nonempty"),
        CheckConstraint("length(media_type) > 0", name="media_type_nonempty"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("length(content_sha256) = 64", name="sha256_length"),
        Index("ix_extraction_artifacts_run_kind_page", "run_id", "kind", "page_number"),
        {"mysql_engine": "InnoDB"},
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relative_path: Mapped[str] = mapped_column(_case_sensitive_string(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)

    run: Mapped[ExtractionRun] = relationship(back_populates="artifacts")
