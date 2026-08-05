from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class Database:
    """Small async SQLAlchemy lifecycle wrapper used by application services."""

    def __init__(self, database_url: str) -> None:
        self._prepare_sqlite_directory(database_url)
        self._engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)

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
