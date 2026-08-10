#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import stat
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any, cast
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools-manifest.lock"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifest = cast(dict[str, Any], json.loads(MANIFEST.read_text()))
    stockfish = cast(dict[str, Any], manifest["stockfish"])
    install_root = ROOT / str(stockfish["install_root"])
    target = install_root / "stockfish"
    if target.is_file() and "--force" not in sys.argv:
        print(f"Stockfish is already installed at {target}")
        return 0

    archive_name = str(stockfish["linux_x64_archive"])
    archive = ROOT / ".cache" / "downloads" / archive_name
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.is_file() or _sha256(archive) != stockfish["linux_x64_sha256"]:
        print(f"Downloading {stockfish['linux_x64_url']}")
        try:
            with (
                urllib.request.urlopen(str(stockfish["linux_x64_url"]), timeout=120) as response,
                archive.open("wb") as output,
            ):
                shutil.copyfileobj(response, output)
        except (OSError, URLError) as error:
            print(f"Could not download Stockfish: {error}", file=sys.stderr)
            return 4
    actual = _sha256(archive)
    expected = str(stockfish["linux_x64_sha256"])
    if actual != expected:
        print(f"SHA-256 mismatch: expected {expected}, got {actual}", file=sys.stderr)
        return 2

    with tarfile.open(archive) as bundle:
        candidates = [
            member
            for member in bundle.getmembers()
            if member.isfile() and Path(member.name).name == archive_name.removesuffix(".tar")
        ]
        if len(candidates) != 1:
            print("Official archive does not contain exactly one expected binary", file=sys.stderr)
            return 3
        source = bundle.extractfile(candidates[0])
        if source is None:
            print("Could not read Stockfish binary from archive", file=sys.stderr)
            return 3
        install_root.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            shutil.copyfileobj(source, output)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed Stockfish {stockfish['version']} at {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
