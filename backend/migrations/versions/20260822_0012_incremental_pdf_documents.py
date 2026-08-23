"""Add incremental PDF extraction documents and immutable append receipts.

Revision ID: 20260822_0012
Revises: 20260811_0011
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260822_0012"
down_revision: str | None = "20260811_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _ascii_string(length: int) -> sa.String:
    return sa.String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"), "mysql"
    )


def _case_sensitive_string(length: int) -> sa.String:
    return sa.String(length).with_variant(
        mysql.VARCHAR(length, charset="utf8mb4", collation="utf8mb4_bin"), "mysql"
    )


def upgrade() -> None:
    op.create_table(
        "pdf_extraction_documents",
        sa.Column("pdf_asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("first_page", sa.Integer(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("normalized_ccef_sha256", _ascii_string(64), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("updated_at", _utc_datetime(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "first_page >= 1", name=op.f("ck_pdf_extraction_documents_first_page_positive")
        ),
        sa.CheckConstraint(
            "last_page >= first_page",
            name=op.f("ck_pdf_extraction_documents_page_range_valid"),
        ),
        sa.CheckConstraint(
            "length(normalized_ccef_sha256) = 64",
            name=op.f("ck_pdf_extraction_documents_sha256_length"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_pdf_extraction_documents_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["pdf_asset_id"],
            ["pdf_assets.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_doc_asset"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_extraction_documents")),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_pdf_extraction_documents_asset_updated",
        "pdf_extraction_documents",
        ["pdf_asset_id", "updated_at"],
    )

    op.create_table(
        "pdf_extraction_document_segments",
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("first_page", sa.Integer(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("normalized_ccef_sha256", _ascii_string(64), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "first_page >= 1",
            name=op.f("ck_pdf_extraction_document_segments_first_page_positive"),
        ),
        sa.CheckConstraint(
            "last_page >= first_page",
            name=op.f("ck_pdf_extraction_document_segments_page_range_valid"),
        ),
        sa.CheckConstraint(
            "ordinal >= 1",
            name=op.f("ck_pdf_extraction_document_segments_ordinal_positive"),
        ),
        sa.CheckConstraint(
            "length(normalized_ccef_sha256) = 64",
            name=op.f("ck_pdf_extraction_document_segments_sha256_length"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["pdf_extraction_documents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_doc_seg_doc"),
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"],
            ["extraction_runs.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_doc_seg_run"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_extraction_document_segments")),
        sa.UniqueConstraint(
            "document_id",
            "ordinal",
            name=op.f("uq_pdf_extraction_document_segments_ordinal"),
        ),
        sa.UniqueConstraint(
            "extraction_run_id", name=op.f("uq_pdf_extraction_document_segments_run")
        ),
        mysql_engine="InnoDB",
    )

    op.create_table(
        "pdf_extraction_document_revisions",
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("predecessor_revision_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("terminal_segment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("first_page", sa.Integer(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("relative_path", _case_sensitive_string(512), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("normalized_ccef_sha256", _ascii_string(64), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name=op.f("ck_pdf_extraction_document_revisions_algorithm_version_nonempty"),
        ),
        sa.CheckConstraint(
            "byte_size > 0",
            name=op.f("ck_pdf_extraction_document_revisions_byte_size_positive"),
        ),
        sa.CheckConstraint(
            "first_page >= 1",
            name=op.f("ck_pdf_extraction_document_revisions_first_page_positive"),
        ),
        sa.CheckConstraint(
            "last_page >= first_page",
            name=op.f("ck_pdf_extraction_document_revisions_page_range_valid"),
        ),
        sa.CheckConstraint(
            "length(media_type) > 0",
            name=op.f("ck_pdf_extraction_document_revisions_media_type_nonempty"),
        ),
        sa.CheckConstraint(
            "length(relative_path) > 0",
            name=op.f("ck_pdf_extraction_document_revisions_relative_path_nonempty"),
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name=op.f("ck_pdf_extraction_document_revisions_revision_number_positive"),
        ),
        sa.CheckConstraint(
            "segment_count >= 1",
            name=op.f("ck_pdf_extraction_document_revisions_segment_count_positive"),
        ),
        sa.CheckConstraint(
            "length(normalized_ccef_sha256) = 64",
            name=op.f("ck_pdf_extraction_document_revisions_sha256_length"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["pdf_extraction_documents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_doc_rev_doc"),
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_revision_id"],
            ["pdf_extraction_document_revisions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_doc_rev_prev"),
        ),
        sa.ForeignKeyConstraint(
            ["terminal_segment_id"],
            ["pdf_extraction_document_segments.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_doc_rev_terminal_seg"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_extraction_document_revisions")),
        sa.UniqueConstraint(
            "document_id",
            "revision_number",
            name=op.f("uq_pdf_extraction_document_revisions_number"),
        ),
        sa.UniqueConstraint(
            "terminal_segment_id",
            name=op.f("uq_pdf_extraction_document_revisions_terminal_segment"),
        ),
        mysql_engine="InnoDB",
    )

    op.create_table(
        "pdf_extraction_document_appends",
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("predecessor_revision_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("predecessor_normalized_ccef_sha256", _ascii_string(64), nullable=False),
        sa.Column("first_page", sa.Integer(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("logical_fingerprint", _ascii_string(64), nullable=False),
        sa.Column("effective_key_hash", _ascii_string(64), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "expected_version >= 1",
            name=op.f("ck_pdf_extraction_document_appends_expected_version_positive"),
        ),
        sa.CheckConstraint(
            "first_page >= 1",
            name=op.f("ck_pdf_extraction_document_appends_first_page_positive"),
        ),
        sa.CheckConstraint(
            "length(logical_fingerprint) = 64",
            name=op.f("ck_pdf_extraction_document_appends_fingerprint_length"),
        ),
        sa.CheckConstraint(
            "length(effective_key_hash) = 64",
            name=op.f("ck_pdf_extraction_document_appends_key_hash_length"),
        ),
        sa.CheckConstraint(
            "last_page >= first_page",
            name=op.f("ck_pdf_extraction_document_appends_page_range_valid"),
        ),
        sa.CheckConstraint(
            "length(predecessor_normalized_ccef_sha256) = 64",
            name=op.f("ck_pdf_extraction_document_appends_sha256_length"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["pdf_extraction_documents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_doc_append_doc"),
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"],
            ["extraction_runs.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_doc_append_run"),
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_revision_id"],
            ["pdf_extraction_document_revisions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_doc_append_prev"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_extraction_document_appends")),
        sa.UniqueConstraint(
            "effective_key_hash",
            name=op.f("uq_pdf_extraction_document_appends_effective_key"),
        ),
        sa.UniqueConstraint(
            "extraction_run_id", name=op.f("uq_pdf_extraction_document_appends_run")
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_pdf_extraction_document_appends_document_created",
        "pdf_extraction_document_appends",
        ["document_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("pdf_extraction_document_appends")
    op.drop_table("pdf_extraction_document_revisions")
    op.drop_table("pdf_extraction_document_segments")
    op.drop_table("pdf_extraction_documents")
