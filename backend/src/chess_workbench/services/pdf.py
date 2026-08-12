"""Pure pre-transaction PDF upload preparation (packet DS-STAGE8A-PDF-PREPARE-01).

Validates one PDF through the bounded inspection boundary, validates display
metadata, persists the original bytes through the accepted generic source CAS
and returns an immutable prepared value for the later SQL service.  No SQL
session, ORM model, Job, HTTP request, worker or public API contract lives
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chess_workbench.logic.pdf import (
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    PdfInspection,
    PdfInspectionError,
    inspect_pdf,
)
from chess_workbench.services.content import ServiceError
from chess_workbench.services.source_storage import store_content_addressed_bytes

_MAX_METADATA_CODEPOINTS = 200


@dataclass(frozen=True, slots=True)
class PreparedPdfAsset:
    """Immutable prepared value for one accepted PDF upload."""

    filename: str
    content_sha256: str
    size_bytes: int
    page_count: int
    relative_path: str
    title: str
    author: str | None
    edition: str | None
    storage_reused: bool


def _validated_metadata(field: str, value: str | None) -> str | None:
    """Validate one optional display-metadata field without leaking its value."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None")
    if value != value.strip():
        raise ServiceError("validation_error", 422, "PDF metadata is invalid", {"field": field})
    if not 1 <= len(value) <= _MAX_METADATA_CODEPOINTS:
        raise ServiceError("validation_error", 422, "PDF metadata is invalid", {"field": field})
    return value


def _mapped_inspection_error(error: PdfInspectionError, max_bytes: int) -> ServiceError:
    """Map an inspection failure to the frozen public ServiceError contract."""

    if error.reason == "payload_too_large":
        return ServiceError(
            "payload_too_large",
            413,
            "PDF payload exceeds the configured limit",
            {"limit_bytes": max_bytes},
        )
    if error.reason == "unsupported_media_type":
        return ServiceError(
            "unsupported_media_type",
            415,
            "PDF media type is not supported",
            {"reason": error.reason},
        )
    return ServiceError(
        "validation_error",
        422,
        "PDF upload is invalid",
        {"reason": error.reason},
    )


def prepare_pdf_asset(
    raw_bytes: bytes,
    *,
    filename: str,
    declared_media_type: str | None,
    title: str | None,
    author: str | None,
    edition: str | None,
    storage_root: Path,
    max_bytes: int = MAX_PDF_BYTES,
    max_pages: int = MAX_PDF_PAGES,
) -> PreparedPdfAsset:
    """Validate, prepare and persist one PDF upload before any SQL transaction.

    Order is frozen: inspect first (before any filesystem operation), then
    validate display metadata, then store the original bytes through the
    content-addressed CAS under namespace ``sources/pdf`` with suffix ``.pdf``.
    Public inspection errors are constructed only after leaving the exception
    handler, so neither ``__cause__`` nor ``__context__`` is set, and no raw
    bytes, parser text or absolute path is ever exposed.  The generic sanitized
    ``source_storage_unavailable`` ServiceError passes through unchanged.
    """

    inspection_error: PdfInspectionError | None = None
    inspection: PdfInspection | None = None
    try:
        inspection = inspect_pdf(
            raw_bytes,
            filename=filename,
            declared_media_type=declared_media_type,
            max_bytes=max_bytes,
            max_pages=max_pages,
        )
    except PdfInspectionError as error:
        inspection_error = error
    if inspection_error is not None:
        raise _mapped_inspection_error(inspection_error, max_bytes)
    assert inspection is not None

    title = _validated_metadata("title", title)
    author = _validated_metadata("author", author)
    edition = _validated_metadata("edition", edition)

    stored = store_content_addressed_bytes(
        storage_root,
        namespace="sources/pdf",
        suffix=".pdf",
        raw_bytes=raw_bytes,
    )
    return PreparedPdfAsset(
        filename=inspection.filename,
        content_sha256=stored.sha256,
        size_bytes=inspection.size_bytes,
        page_count=inspection.page_count,
        relative_path=stored.relative_path,
        title=inspection.filename[:-4] if title is None else title,
        author=author,
        edition=edition,
        storage_reused=stored.reused,
    )
