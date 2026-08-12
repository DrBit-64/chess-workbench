"""Allow immutable extraction artifacts to share one content-addressed blob.

Revision ID: 20260811_0011
Revises: 20260811_0010
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260811_0011"
down_revision: str | None = "20260811_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("extraction_artifacts") as batch_op:
        batch_op.drop_constraint(
            "uq_extraction_artifacts_relative_path",
            type_="unique",
        )
        batch_op.drop_constraint(
            "uq_extraction_artifacts_run_kind_hash",
            type_="unique",
        )


def downgrade() -> None:
    with op.batch_alter_table("extraction_artifacts") as batch_op:
        batch_op.create_unique_constraint(
            "uq_extraction_artifacts_run_kind_hash",
            ["run_id", "kind", "content_sha256"],
        )
        batch_op.create_unique_constraint(
            "uq_extraction_artifacts_relative_path",
            ["relative_path"],
        )
