from __future__ import annotations

import os
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = PROJECT_ROOT / "backend" / "alembic.ini"


def main() -> int:
    """Prove that the complete migration chain upgrades, matches metadata, and downgrades."""

    with tempfile.TemporaryDirectory(prefix="chess-workbench-migrations-") as directory:
        database_path = Path(directory) / "migration-check.db"
        os.environ["CHESS_WORKBENCH_DATABASE_URL"] = (
            f"sqlite+aiosqlite:///{database_path.as_posix()}"
        )
        config = Config(str(ALEMBIC_CONFIG))

        command.upgrade(config, "head")
        command.check(config)
        command.downgrade(config, "base")

        if not database_path.is_file():
            raise RuntimeError("migration check did not create its temporary SQLite database")

    print("migration check passed: empty database -> head -> metadata check -> base")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
