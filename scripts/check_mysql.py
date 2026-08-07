"""Run backend tests against a real MySQL instance (Stage 3D).

Usage: python scripts/check_mysql.py [--container]

When ``--container`` is passed the script starts a temporary MySQL 8
Docker container, waits for it to become healthy, runs the minimal
domain-schema + migration tests against it, and tears down the
container on exit.  Without the flag the script expects the
``CHESS_WORKBENCH_MYSQL_URL`` environment variable to point at an
already-running MySQL instance.
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


def _start_mysql_container(
    container_name: str, database: str, user: str, password: str, port: int
) -> str:
    """Start a disposable MySQL container and return the connection URL."""
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "-e",
            f"MYSQL_ROOT_PASSWORD={password}",
            "-e",
            f"MYSQL_DATABASE={database}",
            "-e",
            f"MYSQL_USER={user}",
            "-e",
            f"MYSQL_PASSWORD={password}",
            "-p",
            f"{port}:3306",
            "mysql:8.4",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    url = f"mysql+asyncmy://{user}:{password}@127.0.0.1:{port}/{database}"
    return url


def _wait_for_mysql(url: str, timeout: int = 60) -> None:
    """Poll the MySQL instance until it is ready."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            import asyncio

            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

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
    raise TimeoutError(f"MySQL did not become ready within {timeout}s")


def _run_tests(url: str) -> int:
    """Run the compatibility test suite with the given MySQL URL."""
    env = os.environ.copy()
    env["CHESS_WORKBENCH_MYSQL_URL"] = url
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(BACKEND_DIR / "pyproject.toml"),
            str(BACKEND_DIR / "tests" / "test_mysql_compat.py"),
            "-v",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=False,
    )
    return result.returncode


def _stop_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "stop", container_name],
        capture_output=True,
        timeout=30,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MySQL compatibility tests")
    parser.add_argument(
        "--container",
        action="store_true",
        help="start a temporary Docker MySQL container",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=13306,
        help="MySQL port (default: 13306)",
    )
    args = parser.parse_args()

    if args.container:
        name = f"chess-workbench-mysql-{os.getpid()}"
        password = "testpass"
        try:
            url = _start_mysql_container(name, "chesstest", "chesstest", password, args.port)
            print(f"MySQL container started: {name}")
            _wait_for_mysql(url)
            print("MySQL is ready")
            return _run_tests(url)
        finally:
            _stop_container(name)
    else:
        url = os.environ.get("CHESS_WORKBENCH_MYSQL_URL", "")
        if not url:
            print(
                "Set CHESS_WORKBENCH_MYSQL_URL or use --container",
                file=sys.stderr,
            )
            return 2
        return _run_tests(url)


if __name__ == "__main__":
    raise SystemExit(main())
