"""Add Stage 8D review ledger and lossless page evidence coordinates.

Revision ID: 20260824_0013
Revises: 20260822_0012
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260824_0013"
down_revision: str | None = "20260822_0012"
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


_SOURCE_SPAN_LOCATOR_FIELDS = (
    "(locator_kind = 'whole' AND page_number IS NULL AND bbox IS NULL "
    "AND start_value IS NULL AND end_value IS NULL AND fragment_sha256 IS NULL) OR "
    "(locator_kind = 'page' AND page_number IS NOT NULL AND page_number >= 1 "
    "AND ((start_value IS NULL AND end_value IS NULL) OR "
    "(start_value IS NOT NULL AND end_value IS NOT NULL "
    "AND start_value >= 0 AND end_value > start_value))) OR "
    "(locator_kind IN ('video','text') AND page_number IS NULL AND bbox IS NULL "
    "AND start_value IS NOT NULL AND end_value IS NOT NULL "
    "AND start_value >= 0 AND end_value > start_value AND fragment_sha256 IS NULL)"
)

_OLD_SOURCE_SPAN_LOCATOR_FIELDS = (
    "(locator_kind = 'whole' AND page_number IS NULL AND bbox IS NULL "
    "AND start_value IS NULL AND end_value IS NULL) OR "
    "(locator_kind = 'page' AND page_number IS NOT NULL AND page_number >= 1 "
    "AND start_value IS NULL AND end_value IS NULL) OR "
    "(locator_kind IN ('video','text') AND page_number IS NULL AND bbox IS NULL "
    "AND start_value IS NOT NULL AND end_value IS NOT NULL "
    "AND start_value >= 0 AND end_value > start_value)"
)


def upgrade() -> None:
    with op.batch_alter_table("source_spans") as batch_op:
        batch_op.add_column(sa.Column("fragment_sha256", _ascii_string(64), nullable=True))
        batch_op.drop_constraint(op.f("ck_source_spans_locator_fields"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_source_spans_locator_fields"), _SOURCE_SPAN_LOCATOR_FIELDS
        )
        batch_op.create_check_constraint(
            op.f("ck_source_spans_fragment_sha256_length"),
            "fragment_sha256 IS NULL OR length(fragment_sha256) = 64",
        )

    op.create_table(
        "pdf_review_sessions",
        sa.Column("extraction_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("baseline_artifact_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("baseline_document_revision_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("baseline_ccef_sha256", _ascii_string(64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("updated_at", _utc_datetime(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "length(baseline_ccef_sha256) = 64",
            name=op.f("ck_pdf_review_sessions_baseline_hash"),
        ),
        sa.CheckConstraint(
            "status IN ('open','approved','rejected')",
            name=op.f("ck_pdf_review_sessions_status"),
        ),
        sa.CheckConstraint(
            "(extraction_run_id IS NOT NULL AND document_id IS NULL "
            "AND baseline_artifact_id IS NOT NULL "
            "AND baseline_document_revision_id IS NULL) OR "
            "(extraction_run_id IS NULL AND document_id IS NOT NULL "
            "AND baseline_artifact_id IS NULL "
            "AND baseline_document_revision_id IS NOT NULL)",
            name=op.f("ck_pdf_review_sessions_target_binding"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_pdf_review_sessions_version_positive")),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"],
            ["extraction_runs.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_review_session_run"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["pdf_extraction_documents.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_review_session_doc"),
        ),
        sa.ForeignKeyConstraint(
            ["baseline_artifact_id"],
            ["extraction_artifacts.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_review_session_artifact"),
        ),
        sa.ForeignKeyConstraint(
            ["baseline_document_revision_id"],
            ["pdf_extraction_document_revisions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_review_session_doc_rev"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_review_sessions")),
        sa.UniqueConstraint(
            "extraction_run_id",
            "baseline_ccef_sha256",
            name=op.f("uq_pdf_review_sessions_run_hash"),
        ),
        sa.UniqueConstraint(
            "document_id",
            "baseline_ccef_sha256",
            name=op.f("uq_pdf_review_sessions_doc_hash"),
        ),
        mysql_engine="InnoDB",
    )

    op.create_table(
        "pdf_review_revisions",
        sa.Column("session_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("parent_revision_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("relative_path", _case_sensitive_string(512), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("package_sha256", _ascii_string(64), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "byte_size > 0", name=op.f("ck_pdf_review_revisions_byte_size_positive")
        ),
        sa.CheckConstraint(
            "length(media_type) > 0",
            name=op.f("ck_pdf_review_revisions_media_type_nonempty"),
        ),
        sa.CheckConstraint(
            "length(package_sha256) = 64",
            name=op.f("ck_pdf_review_revisions_package_hash"),
        ),
        sa.CheckConstraint(
            "(revision_number = 1 AND parent_revision_id IS NULL) OR "
            "(revision_number > 1 AND parent_revision_id IS NOT NULL)",
            name=op.f("ck_pdf_review_revisions_parent_binding"),
        ),
        sa.CheckConstraint(
            "length(relative_path) > 0",
            name=op.f("ck_pdf_review_revisions_path_nonempty"),
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name=op.f("ck_pdf_review_revisions_number_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["pdf_review_sessions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_review_revision_session"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"],
            ["pdf_review_revisions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_review_revision_parent"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_review_revisions")),
        sa.UniqueConstraint("parent_revision_id", name=op.f("uq_pdf_review_revisions_parent")),
        sa.UniqueConstraint(
            "session_id",
            "revision_number",
            name=op.f("uq_pdf_review_revisions_session_number"),
        ),
        mysql_engine="InnoDB",
    )

    op.create_table(
        "pdf_review_events",
        sa.Column("session_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("parent_version", sa.Integer(), nullable=False),
        sa.Column("resulting_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('created','edited','acknowledged','approved','rejected','reopened')",
            name=op.f("ck_pdf_review_events_kind"),
        ),
        sa.CheckConstraint(
            "parent_version >= 0",
            name=op.f("ck_pdf_review_events_parent_version_nonnegative"),
        ),
        sa.CheckConstraint(
            "resulting_version = parent_version + 1",
            name=op.f("ck_pdf_review_events_version_transition"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["pdf_review_sessions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_review_event_session"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["pdf_review_revisions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pdf_review_event_revision"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_review_events")),
        sa.UniqueConstraint("revision_id", name=op.f("uq_pdf_review_events_revision")),
        sa.UniqueConstraint(
            "session_id",
            "resulting_version",
            name=op.f("uq_pdf_review_events_session_version"),
        ),
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("pdf_review_events")
    op.drop_table("pdf_review_revisions")
    op.drop_table("pdf_review_sessions")

    with op.batch_alter_table("source_spans") as batch_op:
        batch_op.drop_constraint(op.f("ck_source_spans_fragment_sha256_length"), type_="check")
        batch_op.drop_constraint(op.f("ck_source_spans_locator_fields"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_source_spans_locator_fields"), _OLD_SOURCE_SPAN_LOCATOR_FIELDS
        )
        batch_op.drop_column("fragment_sha256")
