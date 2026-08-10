"""Add immutable authoring history and Explorer publication receipts.

Revision ID: 20260809_0007
Revises: 20260809_0006
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260809_0007"
down_revision: str | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "content_revisions",
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('course_module','course_content_block',"
            "'course_occurrence','knowledge_note')",
            name=op.f("ck_content_revisions_entity_type"),
        ),
        sa.CheckConstraint(
            "entity_version >= 1",
            name=op.f("ck_content_revisions_entity_version_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_revisions")),
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            "entity_version",
            name=op.f("uq_revision_entity_version"),
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_content_revisions_entity"),
        "content_revisions",
        ["entity_type", "entity_id"],
        unique=False,
    )

    op.create_table(
        "module_publications",
        sa.Column("target_course_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_module_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("target_module_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("note_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_module_id"],
            ["course_modules.id"],
            ondelete="RESTRICT",
            name=op.f("fk_module_publications_source_module_id_course_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["target_course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name=op.f("fk_module_publications_target_course_id_courses"),
        ),
        sa.ForeignKeyConstraint(
            ["target_module_id"],
            ["course_modules.id"],
            ondelete="RESTRICT",
            name=op.f("fk_module_publications_target_module_id_course_modules"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_publications")),
        sa.UniqueConstraint(
            "target_course_id",
            "source_module_id",
            name=op.f("uq_publication_target_source"),
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_module_publications_target_course_id"),
        "module_publications",
        ["target_course_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("module_publications")
    op.drop_table("content_revisions")
