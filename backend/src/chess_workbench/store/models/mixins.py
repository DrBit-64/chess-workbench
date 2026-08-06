from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, Uuid, text
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, declared_attr, mapped_column
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-owned audit fields."""

    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Persist aware datetimes as naive UTC and restore an explicit UTC timezone.

    SQLite and MySQL do not preserve timezone offsets in their native datetime
    values. Normalising at the type boundary gives both dialects identical
    semantics while rejecting ambiguous naive application values.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime(timezone=False))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTC datetime columns require an aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class UUIDPrimaryKeyMixin:
    """Portable application-generated UUID primary key."""

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


class UTCCreatedAtMixin:
    """UTC creation timestamp shared by immutable and mutable rows."""

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class UTCTimestampMixin(UTCCreatedAtMixin):
    """UTC creation and last-update timestamps for mutable rows.

    Both use the same ``utc_now()`` sample on first insert so that
    ``updated_at`` can never precede ``created_at`` because of
    separate call-site evaluation.
    """

    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        onupdate=utc_now,
        nullable=False,
    )

    def __init__(self, **kw: object) -> None:
        now = utc_now()
        kw.setdefault("created_at", now)
        kw.setdefault("updated_at", now)
        super().__init__(**kw)


class VersionMixin:
    """Integer optimistic-lock version for mutable domain rows."""

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}


class ArchiveMixin:
    """Recoverable archival marker for mutable user-owned rows."""

    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
