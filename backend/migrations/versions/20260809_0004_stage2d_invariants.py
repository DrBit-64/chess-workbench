"""Enforce dual-course and reference-card invariants.

Revision ID: 20260809_0004
Revises: 20260806_0003
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0004"
down_revision: str | None = "20260806_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("courses") as batch_op:
        batch_op.create_check_constraint(
            op.f("ck_courses_mode"),
            "mode IN ('traditional', 'opening_explorer')",
        )

    with op.batch_alter_table("source_spans") as batch_op:
        batch_op.create_check_constraint(
            op.f("ck_source_spans_coordinate_file"),
            "locator_kind = 'whole' OR source_file_id IS NOT NULL",
        )

    with op.batch_alter_table("knowledge_notes") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_knowledge_notes_markdown_nonempty"),
            type_="check",
        )
        batch_op.alter_column(
            "markdown",
            existing_type=sa.Text(),
            nullable=True,
        )

    # Revision 0003 allowed reference cards to carry a copied markdown cache.
    # The accepted model renders the source note live, so discard only that
    # redundant cache after the column becomes nullable.
    op.execute(
        sa.text("UPDATE knowledge_notes SET markdown = NULL WHERE source_note_id IS NOT NULL")
    )

    with op.batch_alter_table("knowledge_notes") as batch_op:
        batch_op.create_check_constraint(
            op.f("ck_knowledge_notes_markdown_source"),
            "(source_note_id IS NULL AND markdown IS NOT NULL AND length(markdown) > 0) OR "
            "(source_note_id IS NOT NULL AND markdown IS NULL)",
        )
        batch_op.create_unique_constraint(
            op.f("uq_knowledge_notes_occurrence_source"),
            ["occurrence_id", "source_note_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_notes") as batch_op:
        batch_op.drop_constraint(
            op.f("uq_knowledge_notes_occurrence_source"),
            type_="unique",
        )
        batch_op.drop_constraint(
            op.f("ck_knowledge_notes_markdown_source"),
            type_="check",
        )

    # Older schemas require non-null markdown and cannot represent reference
    # cards. Preserve a visible marker before removing that capability.
    op.execute(
        sa.text("UPDATE knowledge_notes SET markdown = '[reference card]' WHERE markdown IS NULL")
    )

    with op.batch_alter_table("knowledge_notes") as batch_op:
        batch_op.alter_column(
            "markdown",
            existing_type=sa.Text(),
            nullable=False,
        )
        batch_op.create_check_constraint(
            op.f("ck_knowledge_notes_markdown_nonempty"),
            "length(markdown) > 0",
        )

    with op.batch_alter_table("source_spans") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_source_spans_coordinate_file"),
            type_="check",
        )

    with op.batch_alter_table("courses") as batch_op:
        batch_op.drop_constraint(op.f("ck_courses_mode"), type_="check")
