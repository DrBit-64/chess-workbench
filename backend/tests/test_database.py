from pathlib import Path

from chess_workbench.store.database import Database


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
