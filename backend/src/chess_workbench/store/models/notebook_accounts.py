"""External account sync state, independent of the lifetime of saved games."""

from datetime import date
from uuid import UUID

from sqlalchemy import BigInteger, Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from chess_workbench.store.base import Base
from chess_workbench.store.models.mixins import UTCCreatedAtMixin, UUIDPrimaryKeyMixin


class NotebookAccount(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    __tablename__ = "notebook_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "username", name="uq_notebook_account_name"),
        {"mysql_engine": "InnoDB"},
    )

    platform: Mapped[str] = mapped_column(String(12))
    username: Mapped[str] = mapped_column(String(40))
    start_date: Mapped[date] = mapped_column(Date)
    # Half-open provider time window. All games below cursor_ms have been staged.
    cursor_ms: Mapped[int] = mapped_column(BigInteger)
    target_ms: Mapped[int | None] = mapped_column(BigInteger)
    last_synced_ms: Mapped[int | None] = mapped_column(BigInteger)


class NotebookAccountGame(Base):
    __tablename__ = "notebook_account_games"
    __table_args__ = (
        Index("ix_notebook_account_game_work", "account_id", "state", "checked_ms"),
        {"mysql_engine": "InnoDB"},
    )

    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("notebook_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    external_id: Mapped[str] = mapped_column(
        String(40).with_variant(mysql.VARCHAR(40, charset="ascii", collation="ascii_bin"), "mysql"),
        primary_key=True,
    )
    # queued -> new/existing, or failed; waiting tracks unfinished Lichess games by ID only.
    state: Mapped[str] = mapped_column(String(16))
    checked_ms: Mapped[int] = mapped_column(BigInteger)
    source_url: Mapped[str] = mapped_column(String(256))
    pending_pgn: Mapped[str | None] = mapped_column(
        Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    )
    error: Mapped[str | None] = mapped_column(Text)
