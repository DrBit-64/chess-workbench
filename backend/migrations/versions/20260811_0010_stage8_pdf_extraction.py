"""Add immutable Stage 8A PDF assets, extraction runs and artifact indexes.

Revision ID: 20260811_0010
Revises: 20260810_0009
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260811_0010"
down_revision: str | None = "20260810_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _ascii_string(length: int) -> sa.String:
    return sa.String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


def _case_sensitive_string(length: int) -> sa.String:
    return sa.String(length).with_variant(
        mysql.VARCHAR(length, charset="utf8mb4", collation="utf8mb4_bin"),
        "mysql",
    )


def upgrade() -> None:
    op.create_table(
        "pdf_assets",
        sa.Column("content_sha256", _ascii_string(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_file_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint("byte_size > 0", name=op.f("ck_pdf_assets_byte_size_positive")),
        sa.CheckConstraint(
            "page_count >= 1 AND page_count <= 20000",
            name=op.f("ck_pdf_assets_page_count_range"),
        ),
        sa.CheckConstraint("length(content_sha256) = 64", name=op.f("ck_pdf_assets_sha256_length")),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["source_files.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_assets_source_file_id_source_files"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_assets_source_id_sources"),
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_assets_source_version_id_source_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_assets")),
        sa.UniqueConstraint("content_sha256", name=op.f("uq_pdf_assets_content_sha256")),
        sa.UniqueConstraint("source_file_id", name=op.f("uq_pdf_assets_source_file_id")),
        sa.UniqueConstraint("source_id", name=op.f("uq_pdf_assets_source_id")),
        sa.UniqueConstraint("source_version_id", name=op.f("uq_pdf_assets_source_version_id")),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "extraction_runs",
        sa.Column("pdf_asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("first_page", sa.Integer(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column("logical_fingerprint", _ascii_string(64), nullable=False),
        sa.Column("effective_key_hash", _ascii_string(64), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "length(effective_key_hash) = 64", name=op.f("ck_extraction_runs_key_hash_length")
        ),
        sa.CheckConstraint(
            "length(logical_fingerprint) = 64",
            name=op.f("ck_extraction_runs_fingerprint_length"),
        ),
        sa.CheckConstraint("first_page >= 1", name=op.f("ck_extraction_runs_first_page_positive")),
        sa.CheckConstraint(
            "last_page >= first_page", name=op.f("ck_extraction_runs_page_range_valid")
        ),
        sa.CheckConstraint(
            "length(pipeline_version) > 0",
            name=op.f("ck_extraction_runs_pipeline_version_nonempty"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="RESTRICT",
            name=op.f("fk_extraction_runs_job_id_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["pdf_asset_id"],
            ["pdf_assets.id"],
            ondelete="RESTRICT",
            name=op.f("fk_extraction_runs_pdf_asset_id_pdf_assets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_runs")),
        sa.UniqueConstraint(
            "effective_key_hash", name=op.f("uq_extraction_runs_effective_key_hash")
        ),
        sa.UniqueConstraint("job_id", name=op.f("uq_extraction_runs_job_id")),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_extraction_runs_fingerprint", "extraction_runs", ["logical_fingerprint"])
    op.create_index(
        "ix_extraction_runs_asset_created", "extraction_runs", ["pdf_asset_id", "created_at"]
    )
    op.create_table(
        "extraction_artifacts",
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("relative_path", _case_sensitive_string(512), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", _ascii_string(64), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "byte_size > 0", name=op.f("ck_extraction_artifacts_byte_size_positive")
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name=op.f("ck_extraction_artifacts_sha256_length"),
        ),
        sa.CheckConstraint(
            "kind IN ('rendered_page','render_manifest','ocr_fragment','ocr_manifest',"
            "'provider_response','raw_ccef','normalized_ccef')",
            name=op.f("ck_extraction_artifacts_kind"),
        ),
        sa.CheckConstraint(
            "length(media_type) > 0", name=op.f("ck_extraction_artifacts_media_type_nonempty")
        ),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name=op.f("ck_extraction_artifacts_page_number_positive"),
        ),
        sa.CheckConstraint(
            "length(relative_path) > 0",
            name=op.f("ck_extraction_artifacts_relative_path_nonempty"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["extraction_runs.id"],
            ondelete="RESTRICT",
            name=op.f("fk_extraction_artifacts_run_id_extraction_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_artifacts")),
        sa.UniqueConstraint(
            "run_id", "kind", "content_sha256", name=op.f("uq_extraction_artifacts_run_kind_hash")
        ),
        sa.UniqueConstraint("relative_path", name=op.f("uq_extraction_artifacts_relative_path")),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_extraction_artifacts_run_kind_page",
        "extraction_artifacts",
        ["run_id", "kind", "page_number"],
    )


def downgrade() -> None:
    op.drop_table("extraction_artifacts")
    op.drop_table("extraction_runs")
    op.drop_table("pdf_assets")
