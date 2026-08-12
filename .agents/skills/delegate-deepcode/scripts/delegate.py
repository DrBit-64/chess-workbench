#!/usr/bin/env python3
"""Run one bounded PLANS.md packet through DeepCode and await its notify hook."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

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


def _tmux_session_alive(tmux_bin: str, socket_path: Path, session_name: str) -> bool:
    completed = subprocess.run(
        [tmux_bin, "-S", str(socket_path), "has-session", "-t", session_name],
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def _capture_tmux(tmux_bin: str, socket_path: Path, target: str) -> str:
    completed = subprocess.run(
        [
            tmux_bin,
            "-S",
            str(socket_path),
            "capture-pane",
            "-p",
            "-S",
            "-2000",
            "-t",
            target,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout if completed.returncode == 0 else ""


def _send_tmux_literal(
    tmux_bin: str, socket_path: Path, target: str, value: str
) -> None:
    subprocess.run(
        [
            tmux_bin,
            "-S",
            str(socket_path),
            "send-keys",
            "-l",
            "-t",
            target,
            value,
        ],
        check=True,
        capture_output=True,
    )


def _send_tmux_enter(tmux_bin: str, socket_path: Path, target: str) -> None:
    subprocess.run(
        [
            tmux_bin,
            "-S",
            str(socket_path),
            "send-keys",
            "-t",
            target,
            "Enter",
        ],
        check=True,
        capture_output=True,
    )


def _kill_tmux_session(tmux_bin: str, socket_path: Path, session_name: str) -> None:
    if not _tmux_session_alive(tmux_bin, socket_path, session_name):
        return
    subprocess.run(
        [tmux_bin, "-S", str(socket_path), "kill-session", "-t", session_name],
        check=False,
        capture_output=True,
    )


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
    plans = (root / "PLANS.md").read_text(encoding="utf-8")
    if arguments.packet not in plans:
        raise SystemExit(f"packet {arguments.packet!r} is not present in PLANS.md")

    deepcode_bin = shutil.which(arguments.deepcode_bin)
    if deepcode_bin is None:
        raise SystemExit(f"DeepCode executable not found: {arguments.deepcode_bin}")
    tmux_bin = shutil.which("tmux")
    if tmux_bin is None:
        raise SystemExit(
            "tmux is required to provide DeepCode with a reliable private TTY"
        )

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
        tmux_socket = run_dir / "tmux.sock"
        session_name = f"cwb-deepcode-{uuid.UUID(run_id).hex[:12]}"
        target = f"{session_name}:0.0"

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
            "tmux_session": session_name,
        }
        _atomic_json_write(run_dir / "metadata.json", metadata)

        command = (
            f"exec env DEEP_AGENT_RUN_ID={shlex.quote(run_id)} "
            f"DEEP_AGENT_RESULT_DIR={shlex.quote(str(run_dir))} "
            f"{shlex.quote(deepcode_bin)}"
        )
        subprocess.run(
            [
                tmux_bin,
                "-S",
                str(tmux_socket),
                "new-session",
                "-d",
                "-s",
                session_name,
                "-c",
                str(root),
                "-x",
                "120",
                "-y",
                "40",
                command,
            ],
            check=True,
            capture_output=True,
        )

        started = time.monotonic()
        last_capture = ""
        try:
            with transcript_path.open("w", encoding="utf-8") as transcript:
                startup_deadline = min(
                    started + 15, started + arguments.timeout_seconds
                )
                current_capture = ""
                while not result_path.is_file():
                    current_capture = _capture_tmux(tmux_bin, tmux_socket, target)
                    if "Type your message" in current_capture:
                        break
                    if not _tmux_session_alive(tmux_bin, tmux_socket, session_name):
                        break
                    if time.monotonic() >= startup_deadline:
                        _atomic_json_write(
                            result_path,
                            _synthetic_result(
                                run_id,
                                "failed",
                                "DeepCode input prompt did not become ready within 15 seconds",
                            ),
                        )
                        break
                    time.sleep(0.1)

                if not result_path.is_file() and _tmux_session_alive(
                    tmux_bin, tmux_socket, session_name
                ):
                    _send_tmux_literal(tmux_bin, tmux_socket, target, prompt)
                    render_deadline = time.monotonic() + 5
                    while time.monotonic() < render_deadline:
                        current_capture = _capture_tmux(tmux_bin, tmux_socket, target)
                        if "escalation report." in current_capture:
                            break
                        time.sleep(0.1)
                    _send_tmux_enter(tmux_bin, tmux_socket, target)

                exit_seen_at: float | None = None
                while not result_path.is_file():
                    current_capture = _capture_tmux(tmux_bin, tmux_socket, target)
                    if current_capture and current_capture != last_capture:
                        transcript.write(
                            f"\n--- {datetime.now(UTC).isoformat()} ---\n{current_capture}"
                        )
                        transcript.flush()
                        last_capture = current_capture

                    now = time.monotonic()
                    if now - started >= arguments.timeout_seconds:
                        _atomic_json_write(
                            result_path,
                            _synthetic_result(
                                run_id,
                                "timeout",
                                "no completion notification within "
                                f"{arguments.timeout_seconds} seconds",
                            ),
                        )
                        break
                    if not _tmux_session_alive(tmux_bin, tmux_socket, session_name):
                        if exit_seen_at is None:
                            exit_seen_at = now
                        elif now - exit_seen_at >= 2:
                            _atomic_json_write(
                                result_path,
                                _synthetic_result(
                                    run_id,
                                    "failed",
                                    "DeepCode exited before notifying",
                                ),
                            )
                            break
                    time.sleep(0.2)
        except KeyboardInterrupt:
            _kill_tmux_session(tmux_bin, tmux_socket, session_name)
            raise
        finally:
            final_capture = _capture_tmux(tmux_bin, tmux_socket, target)
            if final_capture and final_capture != last_capture:
                with transcript_path.open("a", encoding="utf-8") as transcript:
                    transcript.write(
                        f"\n--- {datetime.now(UTC).isoformat()} ---\n{final_capture}"
                    )
            _kill_tmux_session(tmux_bin, tmux_socket, session_name)

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
        print(f"delegation subprocess failed: {error}", file=sys.stderr)
        raise SystemExit(2) from error
