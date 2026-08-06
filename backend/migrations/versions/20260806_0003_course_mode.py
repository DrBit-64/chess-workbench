"""Add Course.mode and KnowledgeNote.source_note_id.

Revision ID: 20260806_0003
Revises: 20260806_0002
Create Date: 2026-08-06
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260806_0003"
down_revision: str | None = "20260806_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "mode",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'traditional'"),
        ),
    )

    with op.batch_alter_table("knowledge_notes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source_note_id",
                sa.Uuid(as_uuid=True),
                nullable=True,
            ),
        )
        batch_op.create_foreign_key(
            op.f("fk_knowledge_notes_source_note_id_knowledge_notes"),
            "knowledge_notes",
            ["source_note_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_notes") as batch_op:
        batch_op.drop_constraint(
            op.f("fk_knowledge_notes_source_note_id_knowledge_notes"),
            type_="foreignkey",
        )
        batch_op.drop_column("source_note_id")

    op.drop_column("courses", "mode")
