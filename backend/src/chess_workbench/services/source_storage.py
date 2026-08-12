"""Reusable atomic content-addressed source blob storage (Stage 8A-1).

This module owns the server-side byte CAS: deterministic digest naming, strictly
validated namespace/suffix inputs, same-directory temporary writes with atomic
replace, and sanitized storage errors. It is synchronous and has no knowledge of
PGN, PDFs, schemas or the database.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from chess_workbench.services.content import ServiceError

_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*$")
_SUFFIX_PATTERN = re.compile(r"^\.[a-z0-9]{1,16}$")
_HASH_CHUNK_BYTES = 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class StoredSourceBlob:
    """Immutable result of one content-addressed store operation."""

    relative_path: str
    sha256: str
    size_bytes: int
    reused: bool


def store_content_addressed_bytes(
    storage_root: Path,
    *,
    namespace: str,
    suffix: str,
    raw_bytes: bytes,
) -> StoredSourceBlob:
    """Store ``raw_bytes`` under ``<namespace>/<sha256[:2]>/<sha256><suffix>``.

    ``namespace`` and ``suffix`` are controlled caller inputs and are strictly
    validated before any filesystem access. The digest is always computed from
    the bytes here; callers cannot supply a path or an expected digest. An
    existing blob with matching size and hash is reused; otherwise the bytes are
    written through a temporary file in the destination directory, flushed,
    fsynced, chmod 0600, verified, and atomically replaced. Any filesystem
    ``OSError`` (including an existing corrupt blob) becomes a sanitized
    ``ServiceError`` that exposes no absolute path or OS message.
    """
    if not _NAMESPACE_PATTERN.fullmatch(namespace):
        raise ValueError(
            "namespace must be one or more lowercase ASCII segments matching "
            "[a-z0-9][a-z0-9_-]* separated only by '/'"
        )
    if not _SUFFIX_PATTERN.fullmatch(suffix):
        raise ValueError(
            "suffix must be '.' followed by 1..16 lowercase ASCII alphanumeric characters"
        )
    digest = sha256(raw_bytes).hexdigest()
    relative_path = f"{namespace}/{digest[:2]}/{digest}{suffix}"
    destination = storage_root / relative_path
    storage_failed = False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.stat().st_size != len(raw_bytes) or _file_sha256(destination) != digest:
                raise OSError("existing source blob failed size/hash verification")
            return StoredSourceBlob(
                relative_path=relative_path,
                sha256=digest,
                size_bytes=len(raw_bytes),
                reused=True,
            )
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            try:
                handle = os.fdopen(file_descriptor, "wb")
            except BaseException:
                with suppress(OSError):
                    os.close(file_descriptor)
                raise
            with handle:
                handle.write(raw_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600)
            if temporary_path.stat().st_size != len(raw_bytes):
                raise OSError("temporary source blob size mismatch")
            if _file_sha256(temporary_path) != digest:
                raise OSError("temporary source blob hash mismatch")
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
        return StoredSourceBlob(
            relative_path=relative_path,
            sha256=digest,
            size_bytes=len(raw_bytes),
            reused=False,
        )
    except OSError:
        # Leave the except block before creating the public error. ``raise ... from
        # None`` only suppresses display of ``__context__``; it does not remove the
        # original OSError object, which may contain an absolute path.
        storage_failed = True
    if storage_failed:
        raise ServiceError("source_storage_unavailable", 503, "source storage is unavailable")
    raise AssertionError("unreachable content-addressed storage state")


def read_verified_content_addressed_bytes(
    storage_root: Path,
    *,
    relative_path: str,
    expected_sha256: str,
    expected_size: int,
    max_bytes: int,
) -> bytes:
    """Read one server-owned CAS blob after containment, size and hash checks."""
    if not isinstance(storage_root, Path):
        raise TypeError("storage_root must be Path")
    if type(relative_path) is not str:
        raise TypeError("relative_path must be an exact string")
    if type(expected_sha256) is not str:
        raise TypeError("expected_sha256 must be an exact string")
    if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise ValueError("expected_sha256 must be lowercase 64-hex")
    if type(expected_size) is not int:
        raise TypeError("expected_size must be an exact integer")
    if type(max_bytes) is not int:
        raise TypeError("max_bytes must be an exact integer")
    if expected_size <= 0 or max_bytes <= 0:
        raise ValueError("expected_size and max_bytes must be positive")
    if expected_size > max_bytes:
        raise ValueError("expected_size may not exceed max_bytes")
    if (
        not relative_path
        or relative_path.startswith("/")
        or relative_path.endswith("/")
        or "\\" in relative_path
        or any(ord(character) < 32 or ord(character) == 127 for character in relative_path)
    ):
        raise ValueError("relative_path must be a canonical POSIX relative path")
    parsed_path = PurePosixPath(relative_path)
    if (
        parsed_path.is_absolute()
        or str(parsed_path) != relative_path
        or any(part in ("", ".", "..") for part in parsed_path.parts)
    ):
        raise ValueError("relative_path must be a canonical POSIX relative path")

    read_failed = False
    payload: bytes | None = None
    try:
        resolved_root = storage_root.resolve(strict=True)
        candidate = storage_root.joinpath(*parsed_path.parts)
        if candidate.is_symlink():
            raise OSError("final CAS path is a symlink")
        resolved_candidate = candidate.resolve(strict=True)
        if not resolved_candidate.is_relative_to(resolved_root):
            raise OSError("CAS path escaped the storage root")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor = os.open(candidate, flags)
        try:
            handle = os.fdopen(file_descriptor, "rb")
        except BaseException:
            with suppress(OSError):
                os.close(file_descriptor)
            raise
        digest = sha256()
        chunks: list[bytes] = []
        total = 0
        with handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size != expected_size
                or before.st_size > max_bytes
            ):
                raise OSError("CAS size mismatch")
            while chunk := handle.read(min(_HASH_CHUNK_BYTES, max_bytes - total + 1)):
                total += len(chunk)
                if total > max_bytes:
                    raise OSError("CAS blob exceeded read limit")
                digest.update(chunk)
                chunks.append(chunk)
            after = os.fstat(handle.fileno())
        if (
            total != expected_size
            or after.st_size != expected_size
            or (before.st_dev, before.st_ino, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_mtime_ns)
            or digest.hexdigest() != expected_sha256
        ):
            raise OSError("CAS blob failed verification")
        payload = b"".join(chunks)
    except (OSError, RuntimeError):
        read_failed = True
    if read_failed or payload is None:
        raise ServiceError("source_storage_unavailable", 503, "source storage is unavailable")
    return payload


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
