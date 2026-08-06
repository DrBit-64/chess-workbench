from pathlib import Path

from chess_workbench.store.database import Database
from sqlalchemy import text


async def test_ping_creates_parent_directory_and_database(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "database" / "test.db"
    database = Database(f"sqlite+aiosqlite:///{database_path}")

    try:
        assert database_path.parent.is_dir()
        await database.ping()
        assert database_path.is_file()
    finally:
        await database.close()


async def test_in_memory_database_ping() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")

    try:
        await database.ping()
    finally:
        await database.close()


async def test_sqlite_connections_enforce_foreign_keys() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")

    try:
        async with database.engine.connect() as connection:
            result = await connection.exec_driver_sql("PRAGMA foreign_keys")

        assert result.scalar_one() == 1
    finally:
        await database.close()


async def test_session_factory_creates_an_independent_unit_of_work() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")

    try:
        async with database.session() as session:
            result = await session.execute(text("SELECT 1"))

        assert result.scalar_one() == 1
    finally:
        await database.close()
