import hashlib
import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]


def test_engine_tool_manifest_pins_release_and_fixture_hashes() -> None:
    manifest = cast(dict[str, Any], json.loads((ROOT / "tools-manifest.lock").read_text()))
    stockfish = manifest["stockfish"]
    assert stockfish["version"] == "18"
    assert stockfish["linux_x64_url"].startswith(
        "https://github.com/official-stockfish/Stockfish/releases/download/sf_18/"
    )
    assert len(stockfish["linux_x64_sha256"]) == 64

    fixtures = cast(dict[str, str], manifest["syzygy"]["fixtures"])
    for filename, expected in fixtures.items():
        payload = (ROOT / "backend" / "tests" / "fixtures" / "syzygy" / filename).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected
