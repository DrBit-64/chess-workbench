"""Keep removed review moves addressable by their notes and bookmarks.

Revision ID: 20261112_0021
Revises: 20261107_0020
"""

import sqlalchemy as sa
from alembic import op

revision = "20261112_0021"
down_revision = "20261107_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "personal_game_nodes",
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("personal_game_nodes", "hidden")
