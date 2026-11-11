"""A hand-authored exercise retains the exact position that inspired it."""

from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from chess_workbench.store.base import Base
from chess_workbench.store.models.mixins import VersionMixin


class NotebookPractice(VersionMixin, Base):
    __tablename__ = "notebook_practice"
    __table_args__ = {"mysql_engine": "InnoDB"}

    bookmark_id: Mapped[UUID] = mapped_column(
        ForeignKey("personal_bookmarks.id", ondelete="CASCADE"), primary_key=True
    )
    prompt: Mapped[str] = mapped_column(Text)
    lines: Mapped[list[list[str]]] = mapped_column(JSON)
