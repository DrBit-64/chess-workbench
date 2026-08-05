from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from chess_workbench import __version__
from chess_workbench.api.app import create_app
from chess_workbench.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = PROJECT_ROOT / "backend" / "openapi.json"
TYPESCRIPT_PATH = PROJECT_ROOT / "frontend" / "src" / "types" / "api.generated.ts"


async def render_openapi(instance_name: str) -> str:
    app = create_app(
        Settings(
            service_name=instance_name,
            version=__version__,
            debug=False,
            database_url="sqlite+aiosqlite:///:memory:",
        )
    )
    client = cast(Any, app.asgi_client)
    _, response = await client.get("/docs/openapi.json")
    if response.status != 200:
        raise RuntimeError(f"OpenAPI endpoint returned HTTP {response.status}")

    document = cast(dict[str, Any], response.json)
    return f"{json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)}\n"


def generate_types(openapi_path: Path, output_path: Path) -> None:
    subprocess.run(
        [
            "pnpm",
            "--dir",
            str(PROJECT_ROOT / "frontend"),
            "exec",
            "openapi-typescript",
            str(openapi_path),
            "--output",
            str(output_path),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def write_contracts() -> None:
    OPENAPI_PATH.write_text(
        asyncio.run(render_openapi("chess-workbench-contract-write")), encoding="utf-8"
    )
    generate_types(OPENAPI_PATH, TYPESCRIPT_PATH)
    print(f"wrote {OPENAPI_PATH.relative_to(PROJECT_ROOT)}")
    print(f"wrote {TYPESCRIPT_PATH.relative_to(PROJECT_ROOT)}")


def show_diff(expected: Path, actual: Path) -> None:
    expected_lines = expected.read_text(encoding="utf-8").splitlines(keepends=True)
    actual_lines = actual.read_text(encoding="utf-8").splitlines(keepends=True)
    sys.stdout.writelines(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile=str(expected.relative_to(PROJECT_ROOT)),
            tofile="freshly generated contract",
        )
    )


def check_contracts() -> int:
    if not OPENAPI_PATH.is_file() or not TYPESCRIPT_PATH.is_file():
        print("generated contracts are missing; run `make contracts`", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="chess-workbench-contracts-") as directory:
        temporary_directory = Path(directory)
        first_directory = temporary_directory / "first"
        second_directory = temporary_directory / "second"
        first_directory.mkdir()
        second_directory.mkdir()
        temporary_openapi = first_directory / "openapi.json"
        temporary_typescript = first_directory / "api.generated.ts"
        second_openapi = second_directory / "openapi.json"
        second_typescript = second_directory / "api.generated.ts"

        for instance_name, openapi_path, typescript_path in (
            ("chess-workbench-contract-check-first", temporary_openapi, temporary_typescript),
            ("chess-workbench-contract-check-second", second_openapi, second_typescript),
        ):
            openapi_path.write_text(asyncio.run(render_openapi(instance_name)), encoding="utf-8")
            generate_types(openapi_path, typescript_path)

        matches = True
        if (
            temporary_openapi.read_bytes() != second_openapi.read_bytes()
            or temporary_typescript.read_bytes() != second_typescript.read_bytes()
        ):
            matches = False
            print("two consecutive contract generations produced different bytes", file=sys.stderr)

        for expected, actual in (
            (OPENAPI_PATH, temporary_openapi),
            (TYPESCRIPT_PATH, temporary_typescript),
        ):
            if expected.read_bytes() != actual.read_bytes():
                matches = False
                show_diff(expected, actual)

    if not matches:
        print("generated contracts have drifted; run `make contracts`", file=sys.stderr)
        return 1

    print("generated contracts are up to date")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or verify API contract artifacts")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write generated files")
    mode.add_argument("--check", action="store_true", help="fail if generated files drift")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.write:
        write_contracts()
        return 0
    return check_contracts()


if __name__ == "__main__":
    raise SystemExit(main())
