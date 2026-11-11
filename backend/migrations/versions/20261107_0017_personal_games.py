"""Local personal games and their path-specific positions.

Revision ID: 20261107_0017
Revises: 20260925_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261107_0017"
down_revision: str | None = "20260925_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    long_text = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        "personal_games",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.Column("archived_at", timestamp),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("white", sa.Text(), nullable=False),
        sa.Column("black", sa.Text(), nullable=False),
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("result", sa.String(9), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("original_pgn", long_text, nullable=False),
        sa.Column("platform", sa.String(20)),
        sa.Column(
            "external_id",
            sa.String(64).with_variant(
                mysql.VARCHAR(64, charset="ascii", collation="ascii_bin"), "mysql"
            ),
        ),
        sa.Column("source_url", sa.Text()),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("import_key", sa.String(64), unique=True),
        sa.Column("summary", long_text, nullable=False),
        sa.UniqueConstraint("platform", "external_id", name="uq_personal_games_source"),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_personal_games_archive_created", "personal_games", ["archived_at", "created_at"]
    )
    op.create_index("ix_personal_games_fingerprint", "personal_games", ["fingerprint"])
    op.create_table(
        "personal_game_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "game_id",
            sa.Uuid(),
            sa.ForeignKey("personal_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id", sa.Uuid(), sa.ForeignKey("personal_game_nodes.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "position_id",
            sa.Uuid(),
            sa.ForeignKey("positions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("move_edge_id", sa.Uuid(), sa.ForeignKey("move_edges.id", ondelete="RESTRICT")),
        sa.Column("ply", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_mainline", sa.Boolean(), nullable=False),
        sa.Column("fen", sa.String(160), nullable=False),
        sa.Column("san", sa.String(24)),
        sa.Column("uci", sa.String(5)),
        sa.Column("nags", sa.JSON(), nullable=False),
        sa.Column("starting_comment", long_text, nullable=False),
        sa.Column("comment", long_text, nullable=False),
        sa.Column("note", long_text, nullable=False),
        sa.UniqueConstraint(
            "game_id", "parent_id", "sort_order", name="uq_personal_game_nodes_order"
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_personal_game_nodes_position", "personal_game_nodes", ["position_id", "is_mainline"]
    )


def downgrade() -> None:
    op.drop_table("personal_game_nodes")
    op.drop_table("personal_games")
