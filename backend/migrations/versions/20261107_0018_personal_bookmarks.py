"""Position bookmarks and their occurrence-scoped tags and related moves."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261107_0018"
down_revision: str | None = "20261107_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personal_bookmarks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "node_id",
            sa.Uuid(),
            sa.ForeignKey("personal_game_nodes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("note", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_personal_bookmarks_list", "personal_bookmarks", ["active", "created_at"])
    op.create_table(
        "personal_bookmark_tags",
        sa.Column(
            "bookmark_id",
            sa.Uuid(),
            sa.ForeignKey("personal_bookmarks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "name",
            sa.String(80).with_variant(
                mysql.VARCHAR(80, charset="utf8mb4", collation="utf8mb4_bin"), "mysql"
            ),
            primary_key=True,
        ),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_personal_bookmark_tags_name", "personal_bookmark_tags", ["name"])
    op.create_table(
        "personal_bookmark_moves",
        sa.Column(
            "bookmark_id",
            sa.Uuid(),
            sa.ForeignKey("personal_bookmarks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "node_id",
            sa.Uuid(),
            sa.ForeignKey("personal_game_nodes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("personal_bookmark_moves")
    op.drop_table("personal_bookmark_tags")
    op.drop_table("personal_bookmarks")
