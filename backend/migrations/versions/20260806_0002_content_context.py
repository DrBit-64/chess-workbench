"""Create course context, sources, spans and notes.

Revision ID: 20260806_0002
Revises: 20260806_0001
Create Date: 2026-08-06
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260806_0002"
down_revision: str | None = "20260806_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _case_sensitive_string(length: int) -> sa.String:
    return sa.String(length).with_variant(
        mysql.VARCHAR(length, charset="utf8mb4", collation="utf8mb4_bin"),
        "mysql",
    )


def _ascii_string(length: int) -> sa.String:
    return sa.String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


def _lifecycle_columns() -> tuple[sa.Column[Any], ...]:
    return (
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("updated_at", _utc_datetime(), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("archived_at", _utc_datetime(), nullable=True),
    )


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(200), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        *_lifecycle_columns(),
        sa.CheckConstraint("status IN ('draft', 'published')", name=op.f("ck_courses_status")),
        sa.CheckConstraint("length(title) > 0", name=op.f("ck_courses_title_nonempty")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courses")),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "sources",
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("external_url", sa.String(2048), nullable=True),
        *_lifecycle_columns(),
        sa.CheckConstraint(
            "kind IN ('book','video','article','web','pgn','game','manual','other')",
            name=op.f("ck_sources_kind"),
        ),
        sa.CheckConstraint("length(title) > 0", name=op.f("ck_sources_title_nonempty")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "course_modules",
        sa.Column("course_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("parent_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *_lifecycle_columns(),
        sa.CheckConstraint("length(title) > 0", name=op.f("ck_course_modules_title_nonempty")),
        sa.CheckConstraint(
            "sort_order >= 0",
            name=op.f("ck_course_modules_sort_order_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_modules_course_id_courses"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["course_modules.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_modules_parent_id_course_modules"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_modules")),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_course_modules_course_parent",
        "course_modules",
        ["course_id", "parent_id"],
    )
    op.create_table(
        "source_versions",
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("label", _case_sensitive_string(200), nullable=False),
        sa.Column("edition", sa.String(200), nullable=True),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("external_url", sa.String(2048), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        *_lifecycle_columns(),
        sa.CheckConstraint("length(label) > 0", name=op.f("ck_source_versions_label_nonempty")),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="RESTRICT",
            name=op.f("fk_source_versions_source_id_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_versions")),
        sa.UniqueConstraint(
            "source_id",
            "label",
            name=op.f("uq_source_versions_source_label"),
        ),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "course_occurrences",
        sa.Column("course_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("module_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("parent_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("position_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("inbound_move_edge_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("full_fen", sa.String(128), nullable=False),
        sa.Column("nag", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        *_lifecycle_columns(),
        sa.CheckConstraint(
            "(parent_id IS NULL AND inbound_move_edge_id IS NULL) OR "
            "(parent_id IS NOT NULL AND inbound_move_edge_id IS NOT NULL)",
            name=op.f("ck_course_occurrences_parent_inbound_pair"),
        ),
        sa.CheckConstraint(
            "nag IS NULL OR (nag >= 0 AND nag <= 255)",
            name=op.f("ck_course_occurrences_nag_range"),
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name=op.f("ck_course_occurrences_sort_order_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_occurrences_course_id_courses"),
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["course_modules.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_occurrences_module_id_course_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["course_occurrences.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_occurrences_parent_id_course_occurrences"),
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["positions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_occurrences_position_id_positions"),
        ),
        sa.ForeignKeyConstraint(
            ["inbound_move_edge_id"],
            ["move_edges.id"],
            ondelete="RESTRICT",
            name=op.f("fk_course_occurrences_inbound_move_edge_id_move_edges"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_occurrences")),
        sa.UniqueConstraint(
            "parent_id",
            "inbound_move_edge_id",
            name=op.f("uq_occurrence_parent_edge"),
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_occurrences_course_module",
        "course_occurrences",
        ["course_id", "module_id"],
    )
    op.create_index("ix_occurrences_position_id", "course_occurrences", ["position_id"])
    op.create_table(
        "source_files",
        sa.Column("source_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("relative_path", _case_sensitive_string(512), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", _ascii_string(64), nullable=False),
        *_lifecycle_columns(),
        sa.CheckConstraint("length(sha256) = 64", name=op.f("ck_source_files_sha256_length")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_source_files_size_nonnegative")),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_source_files_source_version_id_source_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_files")),
        sa.UniqueConstraint("relative_path", name=op.f("uq_source_files_relative_path")),
        sa.UniqueConstraint(
            "source_version_id",
            "sha256",
            name=op.f("uq_source_files_version_hash"),
        ),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "knowledge_notes",
        sa.Column("scope", sa.String(12), nullable=False),
        sa.Column("target_kind", sa.String(24), nullable=False),
        sa.Column("occurrence_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("position_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("move_edge_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("note_type", sa.String(32), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False),
        *_lifecycle_columns(),
        sa.CheckConstraint("scope IN ('course','global')", name=op.f("ck_knowledge_notes_scope")),
        sa.CheckConstraint(
            "target_kind IN ('occurrence','global_position','global_move')",
            name=op.f("ck_knowledge_notes_target_kind"),
        ),
        sa.CheckConstraint(
            "(scope = 'course' AND target_kind = 'occurrence' "
            "AND occurrence_id IS NOT NULL AND position_id IS NULL AND move_edge_id IS NULL) OR "
            "(scope = 'global' AND target_kind = 'global_position' "
            "AND occurrence_id IS NULL AND position_id IS NOT NULL AND move_edge_id IS NULL) OR "
            "(scope = 'global' AND target_kind = 'global_move' "
            "AND occurrence_id IS NULL AND position_id IS NULL AND move_edge_id IS NOT NULL)",
            name=op.f("ck_knowledge_notes_target_scope"),
        ),
        sa.CheckConstraint(
            "review_status IN ('draft','approved','rejected')",
            name=op.f("ck_knowledge_notes_review_status"),
        ),
        sa.CheckConstraint(
            "note_type IN ('general','explanation','plan','candidate_comparison',"
            "'common_error','memory_hint','source_quote')",
            name=op.f("ck_knowledge_notes_note_type"),
        ),
        sa.CheckConstraint(
            "length(markdown) > 0",
            name=op.f("ck_knowledge_notes_markdown_nonempty"),
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["course_occurrences.id"],
            ondelete="RESTRICT",
            name=op.f("fk_knowledge_notes_occurrence_id_course_occurrences"),
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["positions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_knowledge_notes_position_id_positions"),
        ),
        sa.ForeignKeyConstraint(
            ["move_edge_id"],
            ["move_edges.id"],
            ondelete="RESTRICT",
            name=op.f("fk_knowledge_notes_move_edge_id_move_edges"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_notes")),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_knowledge_notes_occurrence_id", "knowledge_notes", ["occurrence_id"])
    op.create_index("ix_knowledge_notes_position_id", "knowledge_notes", ["position_id"])
    op.create_index("ix_knowledge_notes_move_edge_id", "knowledge_notes", ["move_edge_id"])
    op.create_table(
        "source_spans",
        sa.Column("source_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_file_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("locator_kind", sa.String(12), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("start_value", sa.Integer(), nullable=True),
        sa.Column("end_value", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        *_lifecycle_columns(),
        sa.CheckConstraint(
            "locator_kind IN ('whole','page','video','text')",
            name=op.f("ck_source_spans_locator_kind"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_source_spans_confidence"),
        ),
        sa.CheckConstraint(
            "(locator_kind = 'whole' AND page_number IS NULL AND bbox IS NULL "
            "AND start_value IS NULL AND end_value IS NULL) OR "
            "(locator_kind = 'page' AND page_number IS NOT NULL AND page_number >= 1 "
            "AND start_value IS NULL AND end_value IS NULL) OR "
            "(locator_kind IN ('video','text') AND page_number IS NULL AND bbox IS NULL "
            "AND start_value IS NOT NULL AND end_value IS NOT NULL "
            "AND start_value >= 0 AND end_value > start_value)",
            name=op.f("ck_source_spans_locator_fields"),
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_source_spans_source_version_id_source_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["source_files.id"],
            ondelete="RESTRICT",
            name=op.f("fk_source_spans_source_file_id_source_files"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_spans")),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_source_spans_source_version_id", "source_spans", ["source_version_id"])
    op.create_table(
        "knowledge_note_citations",
        sa.Column("knowledge_note_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_span_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_note_id"],
            ["knowledge_notes.id"],
            ondelete="RESTRICT",
            name=op.f("fk_knowledge_note_citations_knowledge_note_id_knowledge_notes"),
        ),
        sa.ForeignKeyConstraint(
            ["source_span_id"],
            ["source_spans.id"],
            ondelete="RESTRICT",
            name=op.f("fk_knowledge_note_citations_source_span_id_source_spans"),
        ),
        sa.PrimaryKeyConstraint(
            "knowledge_note_id",
            "source_span_id",
            name=op.f("pk_knowledge_note_citations"),
        ),
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("knowledge_note_citations")
    op.drop_table("source_spans")
    op.drop_table("knowledge_notes")
    op.drop_table("source_files")
    op.drop_table("course_occurrences")
    op.drop_table("source_versions")
    op.drop_table("course_modules")
    op.drop_table("sources")
    op.drop_table("courses")
