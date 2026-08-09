"""Deterministic unit tests for scripts/check_mysql.py cleanup logic (DS-MYSQL-01).

These tests substitute the Docker, MySQL readiness, and pytest functions so
that every combination of test/readiness/cleanup success and failure is
exercised without invoking a real database or container.
"""

from __future__ import annotations

import io
import sys
from typing import Any, cast
from unittest import mock

import pytest

# –– helpers –––––––––––––––––––––––––––––––––––––––––––––––––––––––


def _import_main_function() -> Any:
    """Import the script's main() while keeping its __name__ guard inactive."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_mysql_script",
        "scripts/check_mysql.py",
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    mod.__name__ = "check_mysql_script"
    sys.modules["check_mysql_script"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.main


def _patch_everything(
    *,
    ready_ok: bool = True,
    test_rc: int = 0,
    stop_rc: int = 0,
    ready_side_effect: BaseException | None = None,
) -> dict[str, mock.MagicMock]:
    """Replace all external side-effects with controlled mocks."""
    mocks: dict[str, mock.MagicMock] = {}

    mocks["start"] = mock.MagicMock(
        return_value="mysql+asyncmy://user:pass@127.0.0.1:13306/chesstest"
    )

    def _ready(url: str, timeout: int = 90) -> None:
        if ready_side_effect is not None:
            raise ready_side_effect
        if not ready_ok:
            raise TimeoutError("MySQL not ready")

    mocks["ready"] = mock.MagicMock(side_effect=_ready)
    mocks["run_tests"] = mock.MagicMock(return_value=test_rc)
    mocks["stop"] = mock.MagicMock(return_value=stop_rc)

    return mocks


def _call_main(mocks: dict[str, Any]) -> int:
    """Invoke main() with patched globals and return its exit code."""
    main_fn = _import_main_function()
    mod = sys.modules["check_mysql_script"]
    with (
        mock.patch.object(mod, "_start_mysql_container", mocks["start"]),
        mock.patch.object(mod, "_wait_for_mysql", mocks["ready"]),
        mock.patch.object(mod, "_run_tests", mocks["run_tests"]),
        mock.patch.object(mod, "_stop_container", mocks["stop"]),
    ):
        argv = ["check_mysql.py", "--container", "--port", "19999"]
        with mock.patch.object(sys, "argv", argv):
            return cast(int, main_fn())


# –– tests ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


def test_success_and_cleanup_success() -> None:
    """Tests pass and Docker stop succeeds → exit 0."""
    mocks = _patch_everything(test_rc=0, stop_rc=0)
    rc = _call_main(mocks)
    assert rc == 0
    mocks["run_tests"].assert_called_once()
    mocks["stop"].assert_called_once()


def test_test_failure_and_cleanup_success() -> None:
    """Tests fail (exit 1) but Docker stop succeeds → return test_rc."""
    mocks = _patch_everything(test_rc=1, stop_rc=0)
    rc = _call_main(mocks)
    assert rc == 1
    mocks["stop"].assert_called_once()


def test_test_success_and_cleanup_failure() -> None:
    """Tests pass but Docker stop fails → exit 4 (cleanup signal)."""
    mocks = _patch_everything(test_rc=0, stop_rc=1)
    rc = _call_main(mocks)
    assert rc == 4
    mocks["stop"].assert_called_once()


def test_readiness_failure_and_cleanup_success() -> None:
    """MySQL not ready: TimeoutError propagates, Docker stop still called."""
    mocks = _patch_everything(ready_ok=False, stop_rc=0)
    with pytest.raises(TimeoutError, match="MySQL not ready"):
        _call_main(mocks)
    mocks["run_tests"].assert_not_called()
    mocks["stop"].assert_called_once()


def test_readiness_failure_and_cleanup_failure() -> None:
    """MySQL not ready and cleanup fails: TimeoutError propagates, cleanup warning emitted."""
    mocks = _patch_everything(ready_ok=False, stop_rc=1)
    stderr_capture = io.StringIO()
    with (
        mock.patch.object(sys, "stderr", stderr_capture),
        pytest.raises(TimeoutError, match="MySQL not ready"),
    ):
        _call_main(mocks)
    mocks["run_tests"].assert_not_called()
    mocks["stop"].assert_called_once()
    assert "Container stop failed" in stderr_capture.getvalue()


def test_keyboardinterrupt_and_cleanup_success() -> None:
    """KeyboardInterrupt propagates after Docker stop is called."""
    mocks = _patch_everything(ready_side_effect=KeyboardInterrupt(), stop_rc=0)
    with pytest.raises(KeyboardInterrupt):
        _call_main(mocks)
    mocks["run_tests"].assert_not_called()
    mocks["stop"].assert_called_once()


# –– ensure this module needs no special imports –––––––––––––––––––
