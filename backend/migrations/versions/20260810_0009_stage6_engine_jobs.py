"""Add Stage 6 engine jobs, analysis cache and engine games.

Revision ID: 20260810_0009
Revises: 20260810_0008
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260810_0009"
down_revision: str | None = "20260810_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def _timestamps(*, updated: bool = False) -> list[sa.Column]:
    columns = [sa.Column("created_at", _utc_datetime(), nullable=False)]
    if updated:
        columns.append(sa.Column("updated_at", _utc_datetime(), nullable=False))
    return columns


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", _utc_datetime(), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", _utc_datetime(), nullable=True),
        sa.Column("heartbeat_at", _utc_datetime(), nullable=True),
        sa.Column("started_at", _utc_datetime(), nullable=True),
        sa.Column("finished_at", _utc_datetime(), nullable=True),
        sa.Column("cancel_requested_at", _utc_datetime(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("id", _uuid(), nullable=False),
        *_timestamps(updated=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name=op.f("ck_jobs_attempt_count_nonnegative")),
        sa.CheckConstraint("max_attempts >= 1", name=op.f("ck_jobs_max_attempts_positive")),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name=op.f("ck_jobs_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("kind", "idempotency_key", name="uq_jobs_kind_idempotency"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "available_at", "lease_expires_at"])
    op.create_table(
        "invalidation_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invalidation_events")),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_invalidation_events_created", "invalidation_events", ["created_at", "id"])
    op.create_table(
        "engine_analyses",
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("fen", sa.String(128), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("engine_name", sa.String(128), nullable=False),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("seldepth", sa.Integer(), nullable=True),
        sa.Column("nodes", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("from_cache", sa.Boolean(), nullable=False),
        sa.Column("id", _uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "source IN ('engine','tablebase')", name=op.f("ck_engine_analyses_source")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engine_analyses")),
        sa.UniqueConstraint("cache_key", name="uq_engine_analyses_cache_key"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_engine_analyses_fen", "engine_analyses", ["fen"])
    op.create_table(
        "engine_games",
        sa.Column("initial_fen", sa.String(128), nullable=False),
        sa.Column("current_fen", sa.String(128), nullable=False),
        sa.Column("user_color", sa.String(8), nullable=False),
        sa.Column("strength", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.String(16), nullable=True),
        sa.Column("engine_name", sa.String(128), nullable=False),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("id", _uuid(), nullable=False),
        *_timestamps(updated=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','finished','abandoned')", name=op.f("ck_engine_games_status")
        ),
        sa.CheckConstraint(
            "strength >= 1 AND strength <= 8", name=op.f("ck_engine_games_strength_range")
        ),
        sa.CheckConstraint(
            "user_color IN ('white','black')", name=op.f("ck_engine_games_user_color")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engine_games")),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "engine_game_moves",
        sa.Column("game_id", _uuid(), nullable=False),
        sa.Column("ply", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(8), nullable=False),
        sa.Column("before_fen", sa.String(128), nullable=False),
        sa.Column("after_fen", sa.String(128), nullable=False),
        sa.Column("uci", sa.String(5), nullable=False),
        sa.Column("san", sa.String(32), nullable=False),
        sa.Column("id", _uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("actor IN ('user','engine')", name=op.f("ck_engine_game_moves_actor")),
        sa.CheckConstraint("ply >= 1", name=op.f("ck_engine_game_moves_ply_positive")),
        sa.ForeignKeyConstraint(["game_id"], ["engine_games.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engine_game_moves")),
        sa.UniqueConstraint("game_id", "ply", name="uq_engine_game_moves_game_ply"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_engine_game_moves_game", "engine_game_moves", ["game_id", "ply"])
    op.create_table(
        "engine_game_reviews",
        sa.Column("game_id", _uuid(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("id", _uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["game_id"], ["engine_games.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engine_game_reviews")),
        sa.UniqueConstraint("game_id", name="uq_engine_game_reviews_game"),
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("engine_game_reviews")
    op.drop_table("engine_game_moves")
    op.drop_table("engine_games")
    op.drop_table("engine_analyses")
    op.drop_table("invalidation_events")
    op.drop_table("jobs")
