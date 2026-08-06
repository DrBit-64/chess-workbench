"""Create immutable position graph facts.

Revision ID: 20260806_0001
Revises:
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260806_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ascii_string(length: int) -> sa.String:
    return sa.String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("position_key", _ascii_string(160), nullable=False),
        sa.Column("canonical_fen", _ascii_string(128), nullable=False),
        sa.Column("piece_placement", _ascii_string(80), nullable=False),
        sa.Column("side_to_move", _ascii_string(1), nullable=False),
        sa.Column("castling_rights", _ascii_string(4), nullable=False),
        sa.Column("en_passant", _ascii_string(2), nullable=False),
        sa.Column("material_signature", _ascii_string(64), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "canonical_fen LIKE '% 0 1'",
            name=op.f("ck_positions_canonical_fen_counters"),
        ),
        sa.CheckConstraint(
            "castling_rights = '-' OR "
            "(length(castling_rights) BETWEEN 1 AND 4 AND "
            "castling_rights NOT LIKE '%-%')",
            name=op.f("ck_positions_castling_rights"),
        ),
        sa.CheckConstraint(
            "en_passant = '-' OR "
            "(length(en_passant) = 2 AND "
            "substr(en_passant, 1, 1) IN ('a','b','c','d','e','f','g','h') AND "
            "substr(en_passant, 2, 1) IN ('3','6'))",
            name=op.f("ck_positions_en_passant"),
        ),
        sa.CheckConstraint(
            "length(material_signature) > 0",
            name=op.f("ck_positions_material_signature_nonempty"),
        ),
        sa.CheckConstraint(
            "length(piece_placement) > 0",
            name=op.f("ck_positions_piece_placement_nonempty"),
        ),
        sa.CheckConstraint(
            "side_to_move IN ('w', 'b')",
            name=op.f("ck_positions_side_to_move"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_positions"),
        sa.UniqueConstraint("position_key", name="uq_positions_position_key"),
        mysql_engine="InnoDB",
    )

    op.create_table(
        "move_edges",
        sa.Column("from_position_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("to_position_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("uci", _ascii_string(5), nullable=False),
        sa.Column("san", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "from_position_id <> to_position_id",
            name=op.f("ck_move_edges_different_positions"),
        ),
        sa.CheckConstraint(
            "length(san) > 0",
            name=op.f("ck_move_edges_san_nonempty"),
        ),
        sa.CheckConstraint(
            "length(uci) IN (4, 5)",
            name=op.f("ck_move_edges_uci_length"),
        ),
        sa.CheckConstraint(
            "lower(uci) = uci",
            name=op.f("ck_move_edges_uci_lowercase"),
        ),
        sa.ForeignKeyConstraint(
            ["from_position_id"],
            ["positions.id"],
            name="fk_move_edges_from_position_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_position_id"],
            ["positions.id"],
            name="fk_move_edges_to_position_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_move_edges"),
        sa.UniqueConstraint(
            "from_position_id",
            "uci",
            name="uq_move_edges_from_uci",
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_move_edges_to_position_id",
        "move_edges",
        ["to_position_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_move_edges_to_position_id", table_name="move_edges")
    op.drop_table("move_edges")
    op.drop_table("positions")
