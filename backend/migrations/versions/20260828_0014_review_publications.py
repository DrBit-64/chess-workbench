"""Add immutable Stage 8D review publication receipts.

Revision ID: 20260828_0014
Revises: 20260824_0013
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260828_0014"
down_revision: str | None = "20260824_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _ascii_string(length: int) -> sa.String:
    return sa.String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"), "mysql"
    )


def upgrade() -> None:
    op.create_table(
        "pdf_review_publications",
        sa.Column("session_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("target_course_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("mapping_version", sa.String(length=64), nullable=False),
        sa.Column("plan_sha256", _ascii_string(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "length(mapping_version) > 0",
            name=op.f("ck_pdf_review_publications_mapping_version_nonempty"),
        ),
        sa.CheckConstraint(
            "length(plan_sha256) = 64",
            name=op.f("ck_pdf_review_publications_plan_hash"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["pdf_review_sessions.id"],
            name=op.f("fk_pdf_review_publication_session"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["pdf_review_revisions.id"],
            name=op.f("fk_pdf_review_publication_revision"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_course_id"],
            ["courses.id"],
            name=op.f("fk_pdf_review_publication_course"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pdf_review_publications")),
        sa.UniqueConstraint(
            "session_id",
            "revision_id",
            "target_course_id",
            "mapping_version",
            "plan_sha256",
            name=op.f("uq_pdf_review_publication_plan"),
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_pdf_review_publication_session"),
        "pdf_review_publications",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("pdf_review_publications")
