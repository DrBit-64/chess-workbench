"""Personal game sources and the ordered occurrences of their recorded moves."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from chess_workbench.store.base import Base
from chess_workbench.store.models.mixins import (
    ArchiveMixin,
    UTCDateTime,
    UTCTimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)


class PersonalGame(UUIDPrimaryKeyMixin, UTCTimestampMixin, VersionMixin, ArchiveMixin, Base):
    __tablename__ = "personal_games"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_personal_games_source"),
        Index("ix_personal_games_archive_created", "archived_at", "created_at"),
        Index("ix_personal_games_chronology", "order_at", "created_at", "id"),
        {"mysql_engine": "InnoDB"},
    )

    white: Mapped[str] = mapped_column(Text)
    black: Mapped[str] = mapped_column(Text)
    date: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(9))
    order_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    time_control: Mapped[str | None] = mapped_column(Text)
    headers: Mapped[dict[str, str]] = mapped_column(JSON)
    original_pgn: Mapped[str] = mapped_column(Text().with_variant(mysql.MEDIUMTEXT(), "mysql"))
    platform: Mapped[str | None] = mapped_column(String(20))
    external_id: Mapped[str | None] = mapped_column(
        String(64).with_variant(mysql.VARCHAR(64, charset="ascii", collation="ascii_bin"), "mysql")
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    import_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    summary: Mapped[str] = mapped_column(
        Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), default=""
    )


class PersonalGameNode(UUIDPrimaryKeyMixin, VersionMixin, Base):
    __tablename__ = "personal_game_nodes"
    __table_args__ = (
        UniqueConstraint("game_id", "parent_id", "sort_order", name="uq_personal_game_nodes_order"),
        Index("ix_personal_game_nodes_position", "position_id", "is_mainline"),
        {"mysql_engine": "InnoDB"},
    )

    game_id: Mapped[UUID] = mapped_column(ForeignKey("personal_games.id", ondelete="CASCADE"))
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("personal_game_nodes.id", ondelete="RESTRICT")
    )
    position_id: Mapped[UUID] = mapped_column(ForeignKey("positions.id", ondelete="RESTRICT"))
    move_edge_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("move_edges.id", ondelete="RESTRICT")
    )
    ply: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer)
    is_mainline: Mapped[bool] = mapped_column(Boolean)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    fen: Mapped[str] = mapped_column(String(160))
    san: Mapped[str | None] = mapped_column(String(24))
    uci: Mapped[str | None] = mapped_column(String(5))
    nags: Mapped[list[int]] = mapped_column(JSON)
    starting_comment: Mapped[str] = mapped_column(Text().with_variant(mysql.MEDIUMTEXT(), "mysql"))
    comment: Mapped[str] = mapped_column(Text().with_variant(mysql.MEDIUMTEXT(), "mysql"))
    note: Mapped[str] = mapped_column(Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), default="")
