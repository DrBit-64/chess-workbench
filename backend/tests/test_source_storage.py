"""Focused tests for the reusable atomic bytes CAS (packet DS-STAGE8A-CAS-01)."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from chess_workbench.services.content import ServiceError
from chess_workbench.services.source_storage import (
    StoredSourceBlob,
    read_verified_content_addressed_bytes,
    store_content_addressed_bytes,
)

PAYLOAD = b"deterministic source bytes\x00\xff\n"

INVALID_NAMESPACES = [
    "",
    "sources//pgn",
    "sources/pgn/",
    "/sources/pgn",
    "sources/./pgn",
    "sources/../pgn",
    "sources\\pgn",
    "sources/ pgn",
    " sources/pgn",
    "sources/pgn\n",
    "Sources/pgn",
    "sources/日本",
]

INVALID_SUFFIXES = [
    "",
    "pgn",
    ".",
    ".PGN",
    ".p gn",
    ".pgn!",
    ".pgn.txt",
    "." + "a" * 17,
]


def _files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def test_new_blob_has_exact_bytes_path_hash_size_and_mode(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    result = store_content_addressed_bytes(
        storage_root, namespace="sources/pgn", suffix=".pgn", raw_bytes=PAYLOAD
    )
    digest = sha256(PAYLOAD).hexdigest()
    assert isinstance(result, StoredSourceBlob)
    assert result.sha256 == digest
    assert result.sha256.islower()
    assert result.size_bytes == len(PAYLOAD)
    assert result.reused is False
    assert result.relative_path == f"sources/pgn/{digest[:2]}/{digest}.pgn"
    destination = storage_root / result.relative_path
    assert destination.read_bytes() == PAYLOAD
    assert destination.stat().st_size == len(PAYLOAD)
    assert destination.stat().st_mode & 0o777 == 0o600
    assert _files_under(storage_root) == [destination]


def test_replay_returns_reused_result_without_changing_contents(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    first = store_content_addressed_bytes(
        storage_root, namespace="sources/pgn", suffix=".pgn", raw_bytes=PAYLOAD
    )
    second = store_content_addressed_bytes(
        storage_root, namespace="sources/pgn", suffix=".pgn", raw_bytes=PAYLOAD
    )
    assert second.relative_path == first.relative_path
    assert second.sha256 == first.sha256
    assert second.size_bytes == first.size_bytes
    assert second.reused is True
    destination = storage_root / first.relative_path
    assert destination.read_bytes() == PAYLOAD
    assert destination.stat().st_mode & 0o777 == 0o600
    assert _files_under(storage_root) == [destination]


def test_result_is_frozen_and_digest_is_computed_from_bytes(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    result = store_content_addressed_bytes(
        storage_root, namespace="sources/pgn", suffix=".pgn", raw_bytes=PAYLOAD
    )
    with pytest.raises(FrozenInstanceError):
        result.reused = True  # type: ignore[misc]
    digest = sha256(PAYLOAD).hexdigest()
    assert result.relative_path == f"sources/pgn/{digest[:2]}/{digest}.pgn"


def test_multi_segment_namespace_and_alphanumeric_suffix_are_supported(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    result = store_content_addressed_bytes(
        storage_root,
        namespace="sources/pgn-extracted/v2",
        suffix=".pdf",
        raw_bytes=PAYLOAD,
    )
    digest = sha256(PAYLOAD).hexdigest()
    assert result.relative_path == (f"sources/pgn-extracted/v2/{digest[:2]}/{digest}.pdf")
    assert result.reused is False
    assert (storage_root / result.relative_path).read_bytes() == PAYLOAD


@pytest.mark.parametrize("namespace", INVALID_NAMESPACES)
def test_invalid_namespace_families_raise_before_filesystem_access(
    tmp_path: Path, namespace: str
) -> None:
    storage_root = tmp_path / "storage"
    with pytest.raises(ValueError):
        store_content_addressed_bytes(
            storage_root, namespace=namespace, suffix=".pgn", raw_bytes=PAYLOAD
        )
    assert not storage_root.exists()


@pytest.mark.parametrize("suffix", INVALID_SUFFIXES)
def test_invalid_suffix_families_raise_before_filesystem_access(
    tmp_path: Path, suffix: str
) -> None:
    storage_root = tmp_path / "storage"
    with pytest.raises(ValueError):
        store_content_addressed_bytes(
            storage_root, namespace="sources/pgn", suffix=suffix, raw_bytes=PAYLOAD
        )
    assert not storage_root.exists()


def test_pre_existing_corrupt_blob_raises_sanitized_error_and_is_not_overwritten(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    stored = store_content_addressed_bytes(
        storage_root, namespace="sources/pgn", suffix=".pgn", raw_bytes=PAYLOAD
    )
    destination = storage_root / stored.relative_path
    corrupt = b"corrupt-bytes"
    destination.write_bytes(corrupt)
    with pytest.raises(ServiceError) as excinfo:
        store_content_addressed_bytes(
            storage_root, namespace="sources/pgn", suffix=".pgn", raw_bytes=PAYLOAD
        )
    error = excinfo.value
    assert error.code == "source_storage_unavailable"
    assert error.status == 503
    assert error.message == "source storage is unavailable"
    assert str(error) == "source storage is unavailable"
    assert str(tmp_path) not in str(error)
    assert "OSError" not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert destination.read_bytes() == corrupt


def _raise_oserror(message: str) -> Callable[..., None]:
    def _fail(*_args: object) -> None:
        raise OSError(message)

    return _fail


@pytest.mark.parametrize("injection", ["fdopen", "replace"])
def test_injected_write_or_replace_failure_leaves_no_temp_file_and_sanitizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, injection: str
) -> None:
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(os, injection, _raise_oserror(f"injected {injection} failure"))
    with pytest.raises(ServiceError) as excinfo:
        store_content_addressed_bytes(
            storage_root, namespace="sources/pgn", suffix=".pgn", raw_bytes=PAYLOAD
        )
    error = excinfo.value
    assert error.code == "source_storage_unavailable"
    assert error.status == 503
    assert error.message == "source storage is unavailable"
    assert str(error) == "source storage is unavailable"
    assert str(tmp_path) not in str(error)
    assert "OSError" not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert _files_under(storage_root) == []
    assert not list(storage_root.rglob("*.tmp"))


def test_verified_reader_round_trips_exact_cas_bytes(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    stored = store_content_addressed_bytes(
        storage_root, namespace="sources/pdf", suffix=".pdf", raw_bytes=PAYLOAD
    )
    assert (
        read_verified_content_addressed_bytes(
            storage_root,
            relative_path=stored.relative_path,
            expected_sha256=stored.sha256,
            expected_size=stored.size_bytes,
            max_bytes=stored.size_bytes,
        )
        == PAYLOAD
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "",
        "/absolute.pdf",
        "sources//pdf/file.pdf",
        "sources/./pdf/file.pdf",
        "sources/../file.pdf",
        "sources\\pdf\\file.pdf",
        "sources/pdf/file.pdf/",
        "sources/pdf/secret\x00.pdf",
        "sources/pdf/secret\n.pdf",
    ],
)
def test_verified_reader_rejects_noncanonical_paths_before_access(
    tmp_path: Path, relative_path: str
) -> None:
    storage_root = tmp_path / "does-not-exist"
    with pytest.raises(ValueError, match="canonical POSIX"):
        read_verified_content_addressed_bytes(
            storage_root,
            relative_path=relative_path,
            expected_sha256="a" * 64,
            expected_size=1,
            max_bytes=1,
        )
    assert not storage_root.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expected_sha256": "A" * 64},
        {"expected_sha256": "a" * 63},
        {"expected_size": True},
        {"expected_size": 0},
        {"max_bytes": False},
        {"max_bytes": 0},
        {"expected_size": 2, "max_bytes": 1},
    ],
)
def test_verified_reader_rejects_identity_and_limit_misuse_before_access(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    arguments: dict[str, object] = {
        "relative_path": "sources/pdf/a.pdf",
        "expected_sha256": "a" * 64,
        "expected_size": 1,
        "max_bytes": 1,
    }
    arguments.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        read_verified_content_addressed_bytes(tmp_path / "missing", **arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("failure", ["missing", "directory", "size", "hash", "symlink"])
def test_verified_reader_maps_file_failures_to_one_sanitized_error(
    tmp_path: Path, failure: str
) -> None:
    storage_root = tmp_path / "storage"
    stored = store_content_addressed_bytes(
        storage_root, namespace="sources/pdf", suffix=".pdf", raw_bytes=PAYLOAD
    )
    relative_path = stored.relative_path
    expected_size = stored.size_bytes
    expected_hash = stored.sha256
    destination = storage_root / relative_path
    if failure == "missing":
        destination.unlink()
    elif failure == "directory":
        destination.unlink()
        destination.mkdir()
    elif failure == "size":
        destination.write_bytes(PAYLOAD + b"x")
    elif failure == "hash":
        destination.write_bytes(b"x" * len(PAYLOAD))
    else:
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(PAYLOAD)
        destination.unlink()
        destination.symlink_to(outside)

    with pytest.raises(ServiceError) as caught:
        read_verified_content_addressed_bytes(
            storage_root,
            relative_path=relative_path,
            expected_sha256=expected_hash,
            expected_size=expected_size,
            max_bytes=expected_size,
        )
    assert caught.value.code == "source_storage_unavailable"
    assert caught.value.status == 503
    assert str(caught.value) == "source storage is unavailable"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert str(tmp_path) not in str(caught.value)
