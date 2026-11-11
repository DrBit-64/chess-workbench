"""Personal game bookmarks always point at an occurrence in the original score."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from chess_workbench.store.base import Base
from chess_workbench.store.models.mixins import UTCCreatedAtMixin, UUIDPrimaryKeyMixin, VersionMixin


class PersonalBookmark(UUIDPrimaryKeyMixin, VersionMixin, UTCCreatedAtMixin, Base):
    __tablename__ = "personal_bookmarks"
    __table_args__ = (
        Index("ix_personal_bookmarks_list", "active", "created_at"),
        {"mysql_engine": "InnoDB"},
    )

    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("personal_game_nodes.id", ondelete="CASCADE"), unique=True
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PersonalBookmarkTag(Base):
    __tablename__ = "personal_bookmark_tags"
    __table_args__ = (Index("ix_personal_bookmark_tags_name", "name"), {"mysql_engine": "InnoDB"})

    bookmark_id: Mapped[UUID] = mapped_column(
        ForeignKey("personal_bookmarks.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(
        String(80).with_variant(
            mysql.VARCHAR(80, charset="utf8mb4", collation="utf8mb4_bin"), "mysql"
        ),
        primary_key=True,
    )


class PersonalBookmarkMove(Base):
    """A bookmarked decision can be revisited from its incoming or a chosen outgoing move."""

    __tablename__ = "personal_bookmark_moves"
    __table_args__ = {"mysql_engine": "InnoDB"}

    bookmark_id: Mapped[UUID] = mapped_column(
        ForeignKey("personal_bookmarks.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("personal_game_nodes.id", ondelete="CASCADE"), primary_key=True
    )
