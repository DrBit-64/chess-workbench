from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    """Enable SQLite FK enforcement for every pooled connection."""

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Database:
    """Small async SQLAlchemy lifecycle wrapper used by application services."""

    def __init__(self, database_url: str) -> None:
        self._prepare_sqlite_directory(database_url)
        self._engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
        if make_url(database_url).get_backend_name() == "sqlite":
            event.listen(self._engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        """Expose the engine for migrations and integration-test boundaries."""

        return self._engine

    def session(self) -> AsyncSession:
        """Create an independent unit-of-work session."""

        return self._sessions()

    @staticmethod
    def _prepare_sqlite_directory(database_url: str) -> None:
        url = make_url(database_url)
        database_name = url.database
        if url.get_backend_name() != "sqlite" or not database_name or database_name == ":memory:":
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
