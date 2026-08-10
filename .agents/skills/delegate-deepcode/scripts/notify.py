#!/usr/bin/env python3
"""Persist a DeepCode completion notification for the active delegated run."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

RUN_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _atomic_json_write(path: Path, value: object) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".result-", delete=False
    ) as handle:
        handle.write(encoded)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def main() -> int:
    run_id = os.environ.get("DEEP_AGENT_RUN_ID", "")
    result_dir_text = os.environ.get("DEEP_AGENT_RESULT_DIR", "")

    # Manual DeepCode sessions use the same project settings. They intentionally produce no bus
    # message because only the Codex launcher supplies these two variables.
    if not run_id and not result_dir_text:
        return 0
    if not RUN_ID_PATTERN.fullmatch(run_id):
        return 2

    expected_dir = (_project_root() / ".agent-sync" / "runs" / run_id).resolve()
    try:
        result_dir = Path(result_dir_text).resolve(strict=True)
    except (FileNotFoundError, OSError):
        return 2
    if result_dir != expected_dir or not result_dir.is_dir():
        return 2

    status = os.environ.get("STATUS", "completed")
    if status not in {"completed", "failed"}:
        status = "failed"

    result = {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "title": os.environ.get("TITLE", ""),
        "body": os.environ.get("BODY", ""),
        "fail_reason": os.environ.get("FAIL_REASON", ""),
        "duration": os.environ.get("DURATION", ""),
        "notified_at": datetime.now(UTC).isoformat(),
    }
    _atomic_json_write(result_dir / "result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
