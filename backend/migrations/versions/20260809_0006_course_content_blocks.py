"""Add ADR 0006 ordered CourseModule content blocks.

Revision ID: 20260809_0006
Revises: 20260809_0005
Create Date: 2026-08-09
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260809_0006"
down_revision: str | None = "20260809_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    blocks = op.create_table(
        "course_content_blocks",
        sa.Column("module_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(200), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("root_occurrence_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("knowledge_note_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("updated_at", _utc_datetime(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("archived_at", _utc_datetime(), nullable=True),
        sa.CheckConstraint(
            "(kind = 'section_header' AND heading IS NOT NULL AND length(heading) > 0 "
            "AND markdown IS NULL AND root_occurrence_id IS NULL AND knowledge_note_id IS NULL) "
            "OR (kind = 'narrative' AND heading IS NULL AND markdown IS NOT NULL "
            "AND length(markdown) > 0 AND root_occurrence_id IS NULL "
            "AND knowledge_note_id IS NULL) "
            "OR (kind = 'move_sequence' AND heading IS NULL AND markdown IS NULL "
            "AND root_occurrence_id IS NOT NULL AND knowledge_note_id IS NULL) "
            "OR (kind = 'knowledge_note' AND heading IS NULL AND markdown IS NULL "
            "AND root_occurrence_id IS NULL AND knowledge_note_id IS NOT NULL)",
            name=op.f("ck_course_content_blocks_kind_payload"),
        ),
        sa.CheckConstraint(
            "sort_order >= 0", name=op.f("ck_course_content_blocks_sort_order_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_note_id"],
            ["knowledge_notes.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_content_blocks_knowledge_note_id_knowledge_notes"),
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["course_modules.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_content_blocks_module_id_course_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["root_occurrence_id"],
            ["course_occurrences.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_content_blocks_root_occurrence_id_occurrences"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_content_blocks")),
        sa.UniqueConstraint("knowledge_note_id", name=op.f("uq_content_blocks_knowledge_note")),
        sa.UniqueConstraint("module_id", "sort_order", name=op.f("uq_content_blocks_module_sort")),
        sa.UniqueConstraint("root_occurrence_id", name=op.f("uq_content_blocks_root_occurrence")),
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_content_blocks_module_id"),
        "course_content_blocks",
        ["module_id"],
        unique=False,
    )

    if op.get_context().as_sql:
        return
    connection = op.get_bind()
    modules = sa.table("course_modules", sa.column("id", sa.Uuid(as_uuid=True)))
    occurrences = sa.table(
        "course_occurrences",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("module_id", sa.Uuid(as_uuid=True)),
        sa.column("parent_id", sa.Uuid(as_uuid=True)),
        sa.column("created_at", _utc_datetime()),
        sa.column("archived_at", _utc_datetime()),
    )
    roots = connection.execute(
        sa.select(
            modules.c.id.label("module_id"),
            occurrences.c.id.label("root_occurrence_id"),
        )
        .join(occurrences, occurrences.c.module_id == modules.c.id)
        .where(occurrences.c.parent_id.is_(None), occurrences.c.archived_at.is_(None))
        .order_by(modules.c.id, occurrences.c.created_at, occurrences.c.id)
    ).mappings()
    now = datetime.now(UTC).replace(tzinfo=None)
    seen_modules: set[object] = set()
    backfill: list[dict[str, object]] = []
    for root in roots:
        if root["module_id"] in seen_modules:
            continue
        seen_modules.add(root["module_id"])
        backfill.append(
            {
                "id": uuid4(),
                "module_id": root["module_id"],
                "kind": "move_sequence",
                "sort_order": 0,
                "heading": None,
                "markdown": None,
                "root_occurrence_id": root["root_occurrence_id"],
                "knowledge_note_id": None,
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "archived_at": None,
            }
        )
    if backfill:
        connection.execute(sa.insert(blocks), backfill)


def downgrade() -> None:
    op.drop_table("course_content_blocks")
