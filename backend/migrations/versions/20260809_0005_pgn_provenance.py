"""Add ordered PGN provenance and import receipt records.

Revision ID: 20260809_0005
Revises: 20260809_0004
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260809_0005"
down_revision: str | None = "20260809_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _ascii_string(length: int) -> sa.String:
    return sa.String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


def upgrade() -> None:
    # Create the replacement parent-leading index before removing the old
    # one: InnoDB may use either to enforce the self-referential parent FK.
    with op.batch_alter_table("course_occurrences") as batch_op:
        batch_op.create_unique_constraint(
            op.f("uq_occurrence_parent_sort"),
            ["parent_id", "sort_order"],
        )
    with op.batch_alter_table("course_occurrences") as batch_op:
        batch_op.drop_constraint(op.f("uq_occurrence_parent_edge"), type_="unique")

    op.create_table(
        "pgn_assets",
        sa.Column("content_sha256", _ascii_string(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_file_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint("byte_size > 0", name=op.f("ck_pgn_assets_byte_size_positive")),
        sa.CheckConstraint("length(content_sha256) = 64", name=op.f("ck_pgn_assets_sha256_length")),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["source_files.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_assets_source_file_id_source_files"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_assets_source_id_sources"),
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_assets_source_version_id_source_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pgn_assets")),
        sa.UniqueConstraint("content_sha256", name=op.f("uq_pgn_assets_content_sha256")),
        sa.UniqueConstraint("source_file_id", name=op.f("uq_pgn_assets_source_file_id")),
        sa.UniqueConstraint("source_id", name=op.f("uq_pgn_assets_source_id")),
        sa.UniqueConstraint("source_version_id", name=op.f("uq_pgn_assets_source_version_id")),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "pgn_imports",
        sa.Column("effective_key_hash", _ascii_string(64), nullable=False),
        sa.Column("logical_fingerprint", _ascii_string(64), nullable=False),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("course_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("mapping_version", sa.String(32), nullable=False),
        sa.Column("game_count", sa.Integer(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("course_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "course_version >= 1", name=op.f("ck_pgn_imports_course_version_positive")
        ),
        sa.CheckConstraint("game_count >= 1", name=op.f("ck_pgn_imports_game_count_positive")),
        sa.CheckConstraint(
            "length(logical_fingerprint) = 64",
            name=op.f("ck_pgn_imports_fingerprint_length"),
        ),
        sa.CheckConstraint(
            "length(effective_key_hash) = 64", name=op.f("ck_pgn_imports_key_hash_length")
        ),
        sa.CheckConstraint(
            "occurrence_count >= game_count",
            name=op.f("ck_pgn_imports_occurrence_count_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["pgn_assets.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_imports_asset_id_pgn_assets"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_imports_course_id_courses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pgn_imports")),
        sa.UniqueConstraint("effective_key_hash", name=op.f("uq_pgn_imports_effective_key_hash")),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "pgn_import_games",
        sa.Column("pgn_import_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("game_index", sa.Integer(), nullable=False),
        sa.Column("module_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("root_occurrence_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_span_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("movetext_result", sa.String(9), nullable=False),
        sa.Column("semantic_hash", _ascii_string(64), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.CheckConstraint(
            "game_index >= 0", name=op.f("ck_pgn_import_games_game_index_nonnegative")
        ),
        sa.CheckConstraint(
            "movetext_result IN ('1-0','0-1','1/2-1/2','*')",
            name=op.f("ck_pgn_import_games_result"),
        ),
        sa.CheckConstraint(
            "occurrence_count >= 1",
            name=op.f("ck_pgn_import_games_occurrence_count_positive"),
        ),
        sa.CheckConstraint(
            "length(semantic_hash) = 64",
            name=op.f("ck_pgn_import_games_semantic_hash_length"),
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["course_modules.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_import_games_module_id_course_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["pgn_import_id"],
            ["pgn_imports.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_import_games_pgn_import_id_pgn_imports"),
        ),
        sa.ForeignKeyConstraint(
            ["root_occurrence_id"],
            ["course_occurrences.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_import_games_root_occurrence_id_course_occurrences"),
        ),
        sa.ForeignKeyConstraint(
            ["source_span_id"],
            ["source_spans.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_import_games_source_span_id_source_spans"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pgn_import_games")),
        sa.UniqueConstraint("pgn_import_id", "game_index", name=op.f("uq_pgn_import_games_index")),
        sa.UniqueConstraint("module_id", name=op.f("uq_pgn_import_games_module_id")),
        sa.UniqueConstraint("root_occurrence_id", name=op.f("uq_pgn_import_games_root_id")),
        sa.UniqueConstraint("source_span_id", name=op.f("uq_pgn_import_games_span_id")),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "pgn_occurrence_annotations",
        sa.Column("occurrence_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("pgn_import_game_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("nags", sa.JSON(), nullable=False),
        sa.Column("starting_comment", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["course_occurrences.id"],
            ondelete="RESTRICT",
            name=op.f("fk_pgn_occurrence_annotations_occurrence_id_course_occurrences"),
        ),
        sa.ForeignKeyConstraint(
            ["pgn_import_game_id"],
            ["pgn_import_games.id"],
            ondelete="RESTRICT",
            name="fk_pgn_annotations_import_game",
        ),
        sa.PrimaryKeyConstraint("occurrence_id", name=op.f("pk_pgn_occurrence_annotations")),
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("pgn_occurrence_annotations")
    op.drop_table("pgn_import_games")
    op.drop_table("pgn_imports")
    op.drop_table("pgn_assets")

    with op.batch_alter_table("course_occurrences") as batch_op:
        batch_op.create_unique_constraint(
            op.f("uq_occurrence_parent_edge"),
            ["parent_id", "inbound_move_edge_id"],
        )
    with op.batch_alter_table("course_occurrences") as batch_op:
        batch_op.drop_constraint(op.f("uq_occurrence_parent_sort"), type_="unique")
