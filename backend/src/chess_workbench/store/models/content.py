from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chess_workbench.store.base import Base
from chess_workbench.store.models.graph import MoveEdge, Position
from chess_workbench.store.models.mixins import (
    ArchiveMixin,
    UTCCreatedAtMixin,
    UTCTimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)


def _case_sensitive_string(length: int) -> String:
    """Keep unique Unicode identifiers case-sensitive on SQLite and MySQL."""

    return String(length).with_variant(
        mysql.VARCHAR(length, charset="utf8mb4", collation="utf8mb4_bin"),
        "mysql",
    )


def _ascii_string(length: int) -> String:
    """Store ASCII identity values with portable binary comparison semantics."""

    return String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


class MutableEntityMixin(
    UUIDPrimaryKeyMixin,
    UTCTimestampMixin,
    VersionMixin,
    ArchiveMixin,
):
    """Common lifecycle for recoverable user-owned content."""


class Course(MutableEntityMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published')", name="status"),
        CheckConstraint("length(title) > 0", name="title_nonempty"),
        {"mysql_engine": "InnoDB"},
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    mode: Mapped[str] = mapped_column(
        String(32), default="traditional", server_default=text("'traditional'"), nullable=False
    )

    modules: Mapped[list[CourseModule]] = relationship(back_populates="course")
    occurrences: Mapped[list[CourseOccurrence]] = relationship(back_populates="course")


class CourseModule(MutableEntityMixin, Base):
    __tablename__ = "course_modules"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        CheckConstraint("length(title) > 0", name="title_nonempty"),
        Index("ix_course_modules_course_parent", "course_id", "parent_id"),
        {"mysql_engine": "InnoDB"},
    )

    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("course_modules.id", ondelete="RESTRICT"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    course: Mapped[Course] = relationship(back_populates="modules")
    parent: Mapped[CourseModule | None] = relationship(
        back_populates="children", remote_side="CourseModule.id"
    )
    children: Mapped[list[CourseModule]] = relationship(back_populates="parent")
    occurrences: Mapped[list[CourseOccurrence]] = relationship(back_populates="module")


class CourseOccurrence(MutableEntityMixin, Base):
    __tablename__ = "course_occurrences"
    __table_args__ = (
        CheckConstraint(
            "(parent_id IS NULL AND inbound_move_edge_id IS NULL) OR "
            "(parent_id IS NOT NULL AND inbound_move_edge_id IS NOT NULL)",
            name="parent_inbound_pair",
        ),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        CheckConstraint("nag IS NULL OR (nag >= 0 AND nag <= 255)", name="nag_range"),
        UniqueConstraint("parent_id", "inbound_move_edge_id", name="uq_occurrence_parent_edge"),
        Index("ix_occurrences_course_module", "course_id", "module_id"),
        Index("ix_occurrences_position_id", "position_id"),
        {"mysql_engine": "InnoDB"},
    )

    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    module_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("course_modules.id", ondelete="RESTRICT"), nullable=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("course_occurrences.id", ondelete="RESTRICT"), nullable=True
    )
    position_id: Mapped[UUID] = mapped_column(
        ForeignKey("positions.id", ondelete="RESTRICT"), nullable=False
    )
    inbound_move_edge_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("move_edges.id", ondelete="RESTRICT"), nullable=True
    )
    full_fen: Mapped[str] = mapped_column(String(128), nullable=False)
    nag: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    course: Mapped[Course] = relationship(back_populates="occurrences")
    module: Mapped[CourseModule | None] = relationship(back_populates="occurrences")
    parent: Mapped[CourseOccurrence | None] = relationship(
        back_populates="children", remote_side="CourseOccurrence.id"
    )
    children: Mapped[list[CourseOccurrence]] = relationship(back_populates="parent")
    position: Mapped[Position] = relationship()
    inbound_move_edge: Mapped[MoveEdge | None] = relationship()


class Source(MutableEntityMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('book','video','article','web','pgn','game','manual','other')",
            name="kind",
        ),
        CheckConstraint("length(title) > 0", name="title_nonempty"),
        {"mysql_engine": "InnoDB"},
    )

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    external_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    versions: Mapped[list[SourceVersion]] = relationship(back_populates="source")


class SourceVersion(MutableEntityMixin, Base):
    __tablename__ = "source_versions"
    __table_args__ = (
        CheckConstraint("length(label) > 0", name="label_nonempty"),
        UniqueConstraint("source_id", "label", name="uq_source_versions_source_label"),
        {"mysql_engine": "InnoDB"},
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    label: Mapped[str] = mapped_column(_case_sensitive_string(200), nullable=False)
    edition: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column("metadata_json", JSON, default=dict)

    source: Mapped[Source] = relationship(back_populates="versions")
    files: Mapped[list[SourceFile]] = relationship(back_populates="source_version")
    spans: Mapped[list[SourceSpan]] = relationship(back_populates="source_version")


class SourceFile(MutableEntityMixin, Base):
    __tablename__ = "source_files"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        UniqueConstraint("source_version_id", "sha256", name="uq_source_files_version_hash"),
        UniqueConstraint("relative_path", name="uq_source_files_relative_path"),
        {"mysql_engine": "InnoDB"},
    )

    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    relative_path: Mapped[str] = mapped_column(_case_sensitive_string(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)

    source_version: Mapped[SourceVersion] = relationship(back_populates="files")
    spans: Mapped[list[SourceSpan]] = relationship(back_populates="source_file")


class SourceSpan(MutableEntityMixin, Base):
    __tablename__ = "source_spans"
    __table_args__ = (
        CheckConstraint("locator_kind IN ('whole','page','video','text')", name="locator_kind"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
        CheckConstraint(
            "(locator_kind = 'whole' AND page_number IS NULL AND bbox IS NULL "
            "AND start_value IS NULL AND end_value IS NULL) OR "
            "(locator_kind = 'page' AND page_number IS NOT NULL AND page_number >= 1 "
            "AND start_value IS NULL AND end_value IS NULL) OR "
            "(locator_kind IN ('video','text') AND page_number IS NULL AND bbox IS NULL "
            "AND start_value IS NOT NULL AND end_value IS NOT NULL "
            "AND start_value >= 0 AND end_value > start_value)",
            name="locator_fields",
        ),
        Index("ix_source_spans_source_version_id", "source_version_id"),
        {"mysql_engine": "InnoDB"},
    )

    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    source_file_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=True
    )
    locator_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[dict[str, float] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    start_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_version: Mapped[SourceVersion] = relationship(back_populates="spans")
    source_file: Mapped[SourceFile | None] = relationship(back_populates="spans")
    citations: Mapped[list[KnowledgeNoteCitation]] = relationship(back_populates="source_span")


class KnowledgeNote(MutableEntityMixin, Base):
    __tablename__ = "knowledge_notes"
    __table_args__ = (
        CheckConstraint("scope IN ('course','global')", name="scope"),
        CheckConstraint(
            "target_kind IN ('occurrence','global_position','global_move')", name="target_kind"
        ),
        CheckConstraint(
            "(scope = 'course' AND target_kind = 'occurrence' "
            "AND occurrence_id IS NOT NULL AND position_id IS NULL AND move_edge_id IS NULL) OR "
            "(scope = 'global' AND target_kind = 'global_position' "
            "AND occurrence_id IS NULL AND position_id IS NOT NULL AND move_edge_id IS NULL) OR "
            "(scope = 'global' AND target_kind = 'global_move' "
            "AND occurrence_id IS NULL AND position_id IS NULL AND move_edge_id IS NOT NULL)",
            name="target_scope",
        ),
        CheckConstraint("review_status IN ('draft','approved','rejected')", name="review_status"),
        CheckConstraint(
            "note_type IN ('general','explanation','plan','candidate_comparison',"
            "'common_error','memory_hint','source_quote')",
            name="note_type",
        ),
        CheckConstraint("length(markdown) > 0", name="markdown_nonempty"),
        Index("ix_knowledge_notes_occurrence_id", "occurrence_id"),
        Index("ix_knowledge_notes_position_id", "position_id"),
        Index("ix_knowledge_notes_move_edge_id", "move_edge_id"),
        {"mysql_engine": "InnoDB"},
    )

    scope: Mapped[str] = mapped_column(String(12), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    occurrence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("course_occurrences.id", ondelete="RESTRICT"), nullable=True
    )
    position_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("positions.id", ondelete="RESTRICT"), nullable=True
    )
    move_edge_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("move_edges.id", ondelete="RESTRICT"), nullable=True
    )
    source_note_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_notes.id", ondelete="RESTRICT"), nullable=True
    )
    note_type: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), default="approved", nullable=False)

    citations: Mapped[list[KnowledgeNoteCitation]] = relationship(
        back_populates="knowledge_note", cascade="all, delete-orphan"
    )


class KnowledgeNoteCitation(UTCCreatedAtMixin, Base):
    __tablename__ = "knowledge_note_citations"
    __table_args__ = ({"mysql_engine": "InnoDB"},)

    knowledge_note_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_notes.id", ondelete="RESTRICT"), primary_key=True
    )
    source_span_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_spans.id", ondelete="RESTRICT"), primary_key=True
    )

    knowledge_note: Mapped[KnowledgeNote] = relationship(back_populates="citations")
    source_span: Mapped[SourceSpan] = relationship(back_populates="citations")
