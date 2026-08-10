"""Run Alembic-based MySQL compat tests (DS-MYSQL-01).

Usage: python scripts/check_mysql.py [--container] [--port PORT]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
MYSQL_IMAGE = (
    "mysql:8.4@sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb"
)

_CONTAINER_DATABASE = "chesstest"
_CONTAINER_USER = "chesstest"
_CONTAINER_PASSWORD = "testpass"


def _start_mysql_container(name: str, port: int) -> str:
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-e",
            f"MYSQL_ROOT_PASSWORD={_CONTAINER_PASSWORD}",
            "-e",
            f"MYSQL_DATABASE={_CONTAINER_DATABASE}",
            "-e",
            f"MYSQL_USER={_CONTAINER_USER}",
            "-e",
            f"MYSQL_PASSWORD={_CONTAINER_PASSWORD}",
            "-p",
            f"{port}:3306",
            MYSQL_IMAGE,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return f"mysql+asyncmy://{_CONTAINER_USER}:{_CONTAINER_PASSWORD}@127.0.0.1:{port}/{_CONTAINER_DATABASE}"


def _wait_for_mysql(url: str, timeout: int = 90) -> None:
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:

            async def _ping() -> None:
                engine = create_async_engine(url, echo=False)
                try:
                    async with engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                finally:
                    await engine.dispose()

            asyncio.run(_ping())
            return
        except Exception:
            time.sleep(2)
    raise TimeoutError(f"MySQL not ready within {timeout}s")


def _has_data(url: str) -> bool:
    """Return True if the MySQL database already contains project tables or
    a non-empty alembic_version."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _check() -> bool:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                tables = await conn.execute(
                    text(
                        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_SCHEMA = DATABASE()"
                    )
                )
                names = {row[0] for row in tables.fetchall()}
                if names - {"alembic_version"}:
                    return True
                if "alembic_version" in names:
                    rev = await conn.execute(text("SELECT COUNT(*) FROM alembic_version"))
                    if rev.scalar():
                        return True
                return False
        finally:
            await engine.dispose()

    return asyncio.run(_check())


def _run_tests(mysql_url: str) -> int:
    env = os.environ.copy()
    env["CHESS_WORKBENCH_MYSQL_URL"] = mysql_url
    env["CHESS_WORKBENCH_DATABASE_URL"] = mysql_url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(BACKEND_DIR / "pyproject.toml"),
            "-o",
            "addopts=",
            str(BACKEND_DIR / "tests" / "test_mysql_compat.py"),
            "-v",
            "--no-cov",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=False,
        timeout=180,
    )
    return result.returncode


def _stop_container(name: str) -> int:
    """Stop and remove the container.  Returns the Docker exit code."""
    result = subprocess.run(
        ["docker", "stop", name],
        capture_output=True,
        timeout=30,
    )
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MySQL compat tests")
    parser.add_argument("--container", action="store_true")
    parser.add_argument("--port", type=int, default=13306)
    args = parser.parse_args()

    if args.container:
        name = f"chess-workbench-mysql-{os.getpid()}"
        url = _start_mysql_container(name, args.port)
        print(f"MySQL container started: {name}")
        test_rc = 1
        try:
            _wait_for_mysql(url)
            print("MySQL is ready")
            test_rc = _run_tests(url)
        finally:
            print("Stopping container …")
            stop_rc = _stop_container(name)
            if stop_rc == 0:
                print("Container stopped")
            else:
                print(
                    f"Container stop failed (exit {stop_rc}); "
                    f"manual cleanup may be needed: docker stop {name}",
                    file=sys.stderr,
                )
                if test_rc == 0:
                    test_rc = 4
        return test_rc
    else:
        url = os.environ.get("CHESS_WORKBENCH_MYSQL_URL", "")
        if not url:
            print("Set CHESS_WORKBENCH_MYSQL_URL or use --container", file=sys.stderr)
            return 2
        if _has_data(url):
            print(
                "Refusing to run against database that already contains tables "
                "or a non-empty alembic_version.  Use a fresh empty database.",
                file=sys.stderr,
            )
            return 3
        return _run_tests(url)


if __name__ == "__main__":
    raise SystemExit(main())
