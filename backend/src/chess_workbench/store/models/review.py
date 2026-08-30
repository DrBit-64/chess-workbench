"""Persistent Stage 8D human-review ledger.

Only ``PdfReviewSession`` is mutable.  Revisions and events are immutable facts
that retain the exact package hash and state transition without storing model
reasoning or exposing content-addressed paths through the public API.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from chess_workbench.store.base import Base
from chess_workbench.store.models.extraction import _ascii_string, _case_sensitive_string
from chess_workbench.store.models.mixins import (
    UTCCreatedAtMixin,
    UTCTimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)


class PdfReviewSession(UUIDPrimaryKeyMixin, UTCTimestampMixin, VersionMixin, Base):
    """Mutable head for one exact extraction candidate review."""

    __tablename__ = "pdf_review_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('open','approved','rejected')", name="status"),
        CheckConstraint("length(baseline_ccef_sha256) = 64", name="baseline_hash"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(extraction_run_id IS NOT NULL AND document_id IS NULL "
            "AND baseline_artifact_id IS NOT NULL AND baseline_document_revision_id IS NULL) OR "
            "(extraction_run_id IS NULL AND document_id IS NOT NULL "
            "AND baseline_artifact_id IS NULL AND baseline_document_revision_id IS NOT NULL)",
            name="target_binding",
        ),
        UniqueConstraint(
            "extraction_run_id",
            "baseline_ccef_sha256",
            name="uq_pdf_review_sessions_run_hash",
        ),
        UniqueConstraint(
            "document_id",
            "baseline_ccef_sha256",
            name="uq_pdf_review_sessions_doc_hash",
        ),
        {"mysql_engine": "InnoDB"},
    )

    extraction_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extraction_runs.id", name="fk_pdf_review_session_run", ondelete="RESTRICT"),
        nullable=True,
    )
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "pdf_extraction_documents.id",
            name="fk_pdf_review_session_doc",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    baseline_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "extraction_artifacts.id",
            name="fk_pdf_review_session_artifact",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    baseline_document_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "pdf_extraction_document_revisions.id",
            name="fk_pdf_review_session_doc_rev",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    baseline_ccef_sha256: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)


class PdfReviewRevision(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Immutable canonical review package revision."""

    __tablename__ = "pdf_review_revisions"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="number_positive"),
        CheckConstraint("length(relative_path) > 0", name="path_nonempty"),
        CheckConstraint("length(media_type) > 0", name="media_type_nonempty"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("length(package_sha256) = 64", name="package_hash"),
        CheckConstraint(
            "(revision_number = 1 AND parent_revision_id IS NULL) OR "
            "(revision_number > 1 AND parent_revision_id IS NOT NULL)",
            name="parent_binding",
        ),
        UniqueConstraint(
            "session_id", "revision_number", name="uq_pdf_review_revisions_session_number"
        ),
        UniqueConstraint("parent_revision_id", name="uq_pdf_review_revisions_parent"),
        {"mysql_engine": "InnoDB"},
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "pdf_review_sessions.id",
            name="fk_pdf_review_revision_session",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "pdf_review_revisions.id",
            name="fk_pdf_review_revision_parent",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    relative_path: Mapped[str] = mapped_column(_case_sensitive_string(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    package_sha256: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)


class PdfReviewEvent(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Immutable audit event for one review-session version transition."""

    __tablename__ = "pdf_review_events"
    __table_args__ = (
        CheckConstraint("parent_version >= 0", name="parent_version_nonnegative"),
        CheckConstraint("resulting_version = parent_version + 1", name="version_transition"),
        CheckConstraint(
            "kind IN ('created','edited','acknowledged','approved','rejected','reopened')",
            name="kind",
        ),
        UniqueConstraint(
            "session_id", "resulting_version", name="uq_pdf_review_events_session_version"
        ),
        UniqueConstraint("revision_id", name="uq_pdf_review_events_revision"),
        {"mysql_engine": "InnoDB"},
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "pdf_review_sessions.id",
            name="fk_pdf_review_event_session",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "pdf_review_revisions.id",
            name="fk_pdf_review_event_revision",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    parent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    decisions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PdfReviewPublication(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Immutable idempotency receipt for one approved review publication plan."""

    __tablename__ = "pdf_review_publications"
    __table_args__ = (
        CheckConstraint("length(mapping_version) > 0", name="mapping_version_nonempty"),
        CheckConstraint("length(plan_sha256) = 64", name="plan_hash"),
        UniqueConstraint(
            "session_id",
            "revision_id",
            "target_course_id",
            "mapping_version",
            "plan_sha256",
            name="uq_pdf_review_publication_plan",
        ),
        Index("ix_pdf_review_publication_session", "session_id"),
        {"mysql_engine": "InnoDB"},
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "pdf_review_sessions.id",
            name="fk_pdf_review_publication_session",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "pdf_review_revisions.id",
            name="fk_pdf_review_publication_revision",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    target_course_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "courses.id",
            name="fk_pdf_review_publication_course",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    mapping_version: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_sha256: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


__all__ = [
    "PdfReviewEvent",
    "PdfReviewPublication",
    "PdfReviewRevision",
    "PdfReviewSession",
]
