from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chess_workbench.store.base import Base
from chess_workbench.store.models.mixins import (
    ArchiveMixin,
    UTCCreatedAtMixin,
    UTCDateTime,
    UTCTimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)


class Job(UUIDPrimaryKeyMixin, UTCTimestampMixin, VersionMixin, ArchiveMixin, Base):
    """Durable SQL queue entry shared by engine and later import workers."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="status",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        UniqueConstraint("kind", "idempotency_key", name="uq_jobs_kind_idempotency"),
        Index("ix_jobs_claim", "status", "available_at", "lease_expires_at"),
        {"mysql_engine": "InnoDB"},
    )

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class InvalidationEvent(UTCCreatedAtMixin, Base):
    """SQL outbox row; sockets are only a lossy transport for this durable fact."""

    __tablename__ = "invalidation_events"
    __table_args__ = (
        Index("ix_invalidation_events_created", "created_at", "id"),
        {"mysql_engine": "InnoDB"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)


class EngineAnalysis(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    __tablename__ = "engine_analyses"
    __table_args__ = (
        CheckConstraint("source IN ('engine','tablebase')", name="source"),
        UniqueConstraint("cache_key", name="uq_engine_analyses_cache_key"),
        Index("ix_engine_analyses_fen", "fen"),
        {"mysql_engine": "InnoDB"},
    )

    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fen: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    engine_name: Mapped[str] = mapped_column(String(128), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seldepth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class EngineGame(UUIDPrimaryKeyMixin, UTCTimestampMixin, VersionMixin, Base):
    __tablename__ = "engine_games"
    __table_args__ = (
        CheckConstraint("user_color IN ('white','black')", name="user_color"),
        CheckConstraint("status IN ('active','finished','abandoned')", name="status"),
        CheckConstraint("strength >= 1 AND strength <= 8", name="strength_range"),
        {"mysql_engine": "InnoDB"},
    )

    initial_fen: Mapped[str] = mapped_column(String(128), nullable=False)
    current_fen: Mapped[str] = mapped_column(String(128), nullable=False)
    user_color: Mapped[str] = mapped_column(String(8), nullable=False)
    strength: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    engine_name: Mapped[str] = mapped_column(String(128), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)

    moves: Mapped[list[EngineGameMove]] = relationship(back_populates="game")
    review: Mapped[EngineGameReview | None] = relationship(back_populates="game")


class EngineGameMove(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    __tablename__ = "engine_game_moves"
    __table_args__ = (
        CheckConstraint("actor IN ('user','engine')", name="actor"),
        CheckConstraint("ply >= 1", name="ply_positive"),
        UniqueConstraint("game_id", "ply", name="uq_engine_game_moves_game_ply"),
        Index("ix_engine_game_moves_game", "game_id", "ply"),
        {"mysql_engine": "InnoDB"},
    )

    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("engine_games.id", ondelete="RESTRICT"), nullable=False
    )
    ply: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(String(8), nullable=False)
    before_fen: Mapped[str] = mapped_column(String(128), nullable=False)
    after_fen: Mapped[str] = mapped_column(String(128), nullable=False)
    uci: Mapped[str] = mapped_column(String(5), nullable=False)
    san: Mapped[str] = mapped_column(String(32), nullable=False)

    game: Mapped[EngineGame] = relationship(back_populates="moves")


class EngineGameReview(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    __tablename__ = "engine_game_reviews"
    __table_args__ = (
        UniqueConstraint("game_id", name="uq_engine_game_reviews_game"),
        {"mysql_engine": "InnoDB"},
    )

    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("engine_games.id", ondelete="RESTRICT"), nullable=False
    )
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    game: Mapped[EngineGame] = relationship(back_populates="review")
