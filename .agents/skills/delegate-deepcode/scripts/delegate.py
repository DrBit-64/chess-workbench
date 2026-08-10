#!/usr/bin/env python3
"""Run one bounded PLANS.md packet through DeepCode and await its notify hook."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

PACKET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _atomic_json_write(path: Path, value: object) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".write-", delete=False
    ) as handle:
        handle.write(encoded)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.rstrip("\n")


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _drain(master_fd: int, transcript: BinaryIO) -> None:
    while True:
        ready, _, _ = select.select([master_fd], [], [], 0)
        if not ready:
            return
        try:
            chunk = os.read(master_fd, 65_536)
        except (BlockingIOError, OSError):
            return
        if not chunk:
            return
        transcript.write(chunk)
        transcript.flush()


def _synthetic_result(run_id: str, status: str, reason: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "title": "DeepCode delegation did not complete",
        "body": "",
        "fail_reason": reason,
        "duration": "",
        "notified_at": datetime.now(UTC).isoformat(),
    }


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--packet", required=True, help="Exact packet ID present in PLANS.md"
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1800,
        help="Wall-clock timeout (30-7200 seconds)",
    )
    parser.add_argument(
        "--deepcode-bin",
        default=os.environ.get("DEEPCODE_BIN", "deepcode"),
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if not PACKET_PATTERN.fullmatch(arguments.packet):
        raise SystemExit("packet ID contains unsupported characters")
    if not 30 <= arguments.timeout_seconds <= 7200:
        raise SystemExit("timeout must be between 30 and 7200 seconds")

    root = _project_root()
    if Path.cwd().resolve() != root:
        raise SystemExit(f"run from repository root: {root}")
    plans_path = root / "PLANS.md"
    plans = plans_path.read_text(encoding="utf-8")
    if arguments.packet not in plans:
        raise SystemExit(f"packet {arguments.packet!r} is not present in PLANS.md")

    deepcode_bin = shutil.which(arguments.deepcode_bin)
    if deepcode_bin is None:
        raise SystemExit(f"DeepCode executable not found: {arguments.deepcode_bin}")

    sync_dir = root / ".agent-sync"
    runs_dir = sync_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    lock_path = sync_dir / "deepcode.lock"

    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(
                "another delegated DeepCode run already holds the project lock"
            )

        run_id = str(uuid.uuid4())
        run_dir = runs_dir / run_id
        run_dir.mkdir(mode=0o700)
        result_path = run_dir / "result.json"
        transcript_path = run_dir / "terminal.log"

        prompt = (
            "You are a bounded DeepCode implementation worker controlled by Codex. "
            "Read AGENTS.md, PLANS.md, and docs/agent/HANDOFF.md from the repository root. "
            f"Execute only packet `{arguments.packet}`. Obey its permitted edit boundary, "
            "preserved invariants, focused acceptance commands, escalation rules, and no-commit "
            "rule exactly. Preserve unrelated worktree changes. If anything is ambiguous or "
            "requires work outside the packet, stop and report evidence instead of guessing. "
            "Finish by updating HANDOFF as the packet requires and provide a concise completion "
            "or escalation report."
        )
        (run_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
        metadata = {
            "schema_version": 1,
            "run_id": run_id,
            "packet": arguments.packet,
            "started_at": datetime.now(UTC).isoformat(),
            "baseline_head": _git(root, "rev-parse", "HEAD"),
            "baseline_status": _git(root, "status", "--short"),
            "deepcode_bin": deepcode_bin,
        }
        _atomic_json_write(run_dir / "metadata.json", metadata)

        environment = os.environ.copy()
        environment["DEEP_AGENT_RUN_ID"] = run_id
        environment["DEEP_AGENT_RESULT_DIR"] = str(run_dir)
        master_fd, slave_fd = pty.openpty()
        process: subprocess.Popen[bytes] | None = None
        started = time.monotonic()
        try:
            with transcript_path.open("wb") as transcript:
                process = subprocess.Popen(
                    [deepcode_bin, "--prompt", prompt],
                    cwd=root,
                    env=environment,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    start_new_session=True,
                )
                os.close(slave_fd)
                slave_fd = -1
                os.set_blocking(master_fd, False)

                exit_seen_at: float | None = None
                while not result_path.is_file():
                    _drain(master_fd, transcript)
                    now = time.monotonic()
                    if now - started >= arguments.timeout_seconds:
                        result = _synthetic_result(
                            run_id,
                            "timeout",
                            f"no completion notification within {arguments.timeout_seconds} seconds",
                        )
                        _atomic_json_write(result_path, result)
                        break
                    if process.poll() is not None:
                        if exit_seen_at is None:
                            exit_seen_at = now
                        elif now - exit_seen_at >= 2:
                            result = _synthetic_result(
                                run_id,
                                "failed",
                                f"DeepCode exited with code {process.returncode} before notifying",
                            )
                            _atomic_json_write(result_path, result)
                            break
                    time.sleep(0.2)
                _drain(master_fd, transcript)
        except KeyboardInterrupt:
            if process is not None:
                _terminate(process)
            raise
        finally:
            if slave_fd >= 0:
                os.close(slave_fd)
            os.close(master_fd)
            if process is not None:
                _terminate(process)

        result = json.loads(result_path.read_text(encoding="utf-8"))
        summary = {
            "run_id": run_id,
            "packet": arguments.packet,
            "status": result.get("status", "failed"),
            "result_path": str(result_path),
            "transcript_path": str(transcript_path),
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"git preflight failed: {error}", file=sys.stderr)
        raise SystemExit(2) from error
