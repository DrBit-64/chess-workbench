import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_SQLITE_BUSY_TIMEOUT_MS = 5_000
_SQLITE_WRITE_ATTEMPTS = 3
_T = TypeVar("_T")


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    """Configure one local SQLite connection for bounded concurrent use."""

    # Leave transaction BEGIN under SQLAlchemy control.  This must happen
    # before the PRAGMAs so changing sqlite3's legacy isolation mode cannot
    # implicitly finish a caller-owned transaction.
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()
    # Python's sqlite3 legacy transaction mode does not BEGIN for SELECT or
    # DDL. A SAVEPOINT can therefore become the outer transaction and RELEASE
    # may commit writes that a caller-owned session.begin() later tries to
    # roll back. SQLAlchemy's explicit begin event below restores real outer
    # transaction semantics for both sqlite3 and aiosqlite.


def _begin_sqlite_transaction(connection: Any) -> None:
    connection.exec_driver_sql("BEGIN")


def _is_sqlite_busy(error: OperationalError) -> bool:
    message = str(error.orig).lower()
    return "database is locked" in message or "database table is locked" in message


class Database:
    """Small async SQLAlchemy lifecycle wrapper used by application services."""

    def __init__(self, database_url: str) -> None:
        url = make_url(database_url)
        engine_options: dict[str, Any] = {"pool_pre_ping": True}
        self._is_sqlite = url.get_backend_name() == "sqlite"
        if self._is_sqlite:
            engine_options["connect_args"] = {"timeout": _SQLITE_BUSY_TIMEOUT_MS / 1_000}
            # A local ChessWorkbench process has one authoritative SQLite
            # writer.  A single pooled connection serializes all of its
            # sessions without preventing other processes from reading the
            # WAL file.  In-memory SQLite already uses its own static pool.
            if url.database and url.database != ":memory:":
                engine_options.update(pool_size=1, max_overflow=0)
        self._engine = create_async_engine(url, **engine_options)
        self._sqlite_write_lock = asyncio.Lock()
        if self._engine.url.get_backend_name() == "sqlite":
            self._prepare_sqlite_directory(self._engine.url)
            event.listen(self._engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
            event.listen(self._engine.sync_engine, "begin", _begin_sqlite_transaction)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        """Expose the engine for migrations and integration-test boundaries."""

        return self._engine

    def session(self) -> AsyncSession:
        """Create an independent unit-of-work session."""

        return self._sessions()

    async def run_write(
        self,
        operation: Callable[[AsyncSession], Awaitable[_T]],
        *,
        attempts: int = _SQLITE_WRITE_ATTEMPTS,
    ) -> _T:
        """Run one short database-only write transaction.

        SQLite permits one writer.  Serialize writes issued through this
        boundary and retry only a rolled-back lock collision; callers must
        never include provider, engine, OCR or filesystem work in
        ``operation``.  Other databases retain their native concurrency and
        execute the transaction once.
        """

        if attempts < 1:
            raise ValueError("attempts must be positive")
        effective_attempts = attempts if self._is_sqlite else 1
        for attempt in range(effective_attempts):
            try:
                if self._is_sqlite:
                    async with (
                        self._sqlite_write_lock,
                        self.session() as session,
                        session.begin(),
                    ):
                        return await operation(session)
                async with self.session() as session, session.begin():
                    return await operation(session)
            except OperationalError as error:
                if (
                    not self._is_sqlite
                    or not _is_sqlite_busy(error)
                    or attempt + 1 >= effective_attempts
                ):
                    raise
                await asyncio.sleep(0.05 * (2**attempt))
        raise AssertionError("write retry loop exhausted without returning or raising")

    def is_transient_write_error(self, error: BaseException) -> bool:
        return self._is_sqlite and isinstance(error, OperationalError) and _is_sqlite_busy(error)

    @staticmethod
    def _prepare_sqlite_directory(engine_url: Any) -> None:
        database_name = engine_url.database
        if not database_name or database_name == ":memory:":
            return
        database_path = Path(database_name)
        if not database_path.is_absolute():
            database_path = Path.cwd() / database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)

    async def ping(self) -> None:
        async with self._engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            if result.scalar_one() != 1:
                raise RuntimeError("database health query returned an unexpected value")

    async def close(self) -> None:
        await self._engine.dispose()
