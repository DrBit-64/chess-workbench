"""Add source citations for narrative course content blocks.

Revision ID: 20260810_0008
Revises: 20260809_0007
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260810_0008"
down_revision: str | None = "20260809_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "course_content_block_citations",
        sa.Column("course_content_block_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_span_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["course_content_block_id"],
            ["course_content_blocks.id"],
            ondelete="RESTRICT",
            name=op.f("fk_block_citations_block_id_content_blocks"),
        ),
        sa.ForeignKeyConstraint(
            ["source_span_id"],
            ["source_spans.id"],
            ondelete="RESTRICT",
            name=op.f("fk_block_citations_source_span_id_source_spans"),
        ),
        sa.PrimaryKeyConstraint(
            "course_content_block_id",
            "source_span_id",
            name=op.f("pk_course_content_block_citations"),
        ),
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("course_content_block_citations")
