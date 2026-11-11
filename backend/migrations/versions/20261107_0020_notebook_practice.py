"""Store authored answers separately from personal bookmarks.

Revision ID: 20261107_0020
Revises: 20261107_0019
"""

import sqlalchemy as sa
from alembic import op

revision = "20261107_0020"
down_revision = "20261107_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebook_practice",
        sa.Column("bookmark_id", sa.Uuid(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["bookmark_id"], ["personal_bookmarks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("bookmark_id"),
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("notebook_practice")
