"""Stage 4 immutable authoring history and publication receipts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from chess_workbench.store.base import Base
from chess_workbench.store.models.mixins import UTCCreatedAtMixin, UUIDPrimaryKeyMixin


class ContentRevision(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Immutable snapshot captured immediately before a mutable authoring edit."""

    __tablename__ = "content_revisions"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('course_module','course_content_block',"
            "'course_occurrence','knowledge_note')",
            name="entity_type",
        ),
        CheckConstraint("entity_version >= 1", name="entity_version_positive"),
        UniqueConstraint(
            "entity_type", "entity_id", "entity_version", name="uq_revision_entity_version"
        ),
        Index("ix_content_revisions_entity", "entity_type", "entity_id"),
        {"mysql_engine": "InnoDB"},
    )

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    entity_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ModulePublication(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Idempotency receipt for publishing one Traditional Module to an Explorer."""

    __tablename__ = "module_publications"
    __table_args__ = (
        UniqueConstraint(
            "target_course_id", "source_module_id", name="uq_publication_target_source"
        ),
        Index("ix_module_publications_target_course_id", "target_course_id"),
        {"mysql_engine": "InnoDB"},
    )

    target_course_id: Mapped[UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    source_module_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_modules.id", ondelete="RESTRICT"), nullable=False
    )
    target_module_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_modules.id", ondelete="RESTRICT"), nullable=False
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    note_count: Mapped[int] = mapped_column(Integer, nullable=False)
