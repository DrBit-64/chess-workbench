"""Bounded PDF inspection boundary (packet DS-STAGE8A-PDF-INSPECTION-01).

Validates upload bytes, filename and declared media type, rejects encrypted or
unusable documents, and returns only immutable physical-page metadata.  This
module performs no storage, SQL, HTTP, OCR, rendering or source creation, and
no PDF content ever enters CCEF or ChessWorkbench models.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from pypdf import PdfReader
from pypdf.errors import PyPdfError

MAX_PDF_BYTES = 256 * 1024 * 1024
MAX_PDF_PAGES = 20_000

_HEADER_SEARCH_BYTES = 1024
# %PDF-<major>.<minor> with major 1 or 2 and exactly one decimal minor digit.
_PDF_HEADER = re.compile(rb"%PDF-[12]\.[0-9](?![0-9])")
_ASCII_WHITESPACE = " \t\n\r\x0b\x0c"
_MAX_FILENAME_CODEPOINTS = 200
# pypdf 6.15.0 keeps PdfReadError in ``pypdf.errors``; its base ``PyPdfError``
# covers PdfReadError and every sibling parser failure (ParseError, PdfStreamError,
# FileNotDecryptedError, EmptyFileError, ...).  Listing both would trip Ruff B014.
_PARSER_FAILURES = (
    PyPdfError,
    RecursionError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    OSError,
)

PdfInspectionReason = Literal[
    "empty_pdf",
    "payload_too_large",
    "invalid_filename",
    "unsupported_media_type",
    "invalid_pdf",
    "encrypted_pdf",
    "page_limit_exceeded",
]

_PDF_ERROR_MESSAGES: dict[str, str] = {
    "empty_pdf": "The PDF payload is empty.",
    "payload_too_large": "The PDF payload exceeds the size limit.",
    "invalid_filename": "The filename is not a valid PDF filename.",
    "unsupported_media_type": "The declared media type is not application/pdf.",
    "invalid_pdf": "The file is not a readable PDF document.",
    "encrypted_pdf": "The PDF document is encrypted.",
    "page_limit_exceeded": "The PDF has more pages than the allowed limit.",
}


@dataclass(frozen=True, slots=True)
class PdfInspection:
    """Immutable physical-page metadata of one accepted PDF upload."""

    filename: str
    size_bytes: int
    page_count: int
    media_type: Literal["application/pdf"] = "application/pdf"


class PdfInspectionError(ValueError):
    """Safe, structured PDF inspection failure with a fixed public message."""

    reason: PdfInspectionReason

    def __init__(self, reason: PdfInspectionReason) -> None:
        if reason not in _PDF_ERROR_MESSAGES:
            raise ValueError(f"unknown PDF inspection reason: {reason!r}")
        super().__init__(_PDF_ERROR_MESSAGES[reason])
        self.reason = reason


def _is_valid_filename(filename: str) -> bool:
    """Check the display filename without ever treating it as a path."""

    if not 1 <= len(filename) <= _MAX_FILENAME_CODEPOINTS:
        return False
    if filename != filename.strip():
        return False
    for ch in filename:
        if "\x00" <= ch <= "\x1f" or "\x7f" <= ch <= "\x9f":
            return False
        if ch in ("/", "\\"):
            return False
    if not filename.lower().endswith(".pdf"):
        return False
    basename = filename[:-4]
    return bool(basename) and basename != "." and bool(basename.strip())


def inspect_pdf(
    raw_bytes: bytes,
    *,
    filename: str,
    declared_media_type: str | None,
    max_bytes: int = MAX_PDF_BYTES,
    max_pages: int = MAX_PDF_PAGES,
) -> PdfInspection:
    """Validate and inspect a PDF upload, returning physical-page metadata.

    Validation order is fixed: programmer type/limit misuse first, then empty
    payload, size, filename, declared media type, the ``%PDF-`` header, and
    finally parser-level checks.  Public errors never contain raw bytes,
    parser text or absolute paths, and are constructed outside the parser
    exception handler so neither ``__cause__`` nor ``__context__`` is set.
    """

    if not isinstance(raw_bytes, bytes):
        raise TypeError("raw_bytes must be bytes")
    if not isinstance(filename, str):
        raise TypeError("filename must be str")
    if declared_media_type is not None and not isinstance(declared_media_type, str):
        raise TypeError("declared_media_type must be str or None")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
        raise TypeError("max_bytes must be an int")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be a positive int")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int):
        raise TypeError("max_pages must be an int")
    if max_pages <= 0:
        raise ValueError("max_pages must be a positive int")

    if not raw_bytes:
        raise PdfInspectionError("empty_pdf")
    if len(raw_bytes) > max_bytes:
        raise PdfInspectionError("payload_too_large")
    if not _is_valid_filename(filename):
        raise PdfInspectionError("invalid_filename")
    if declared_media_type is not None:
        normalized = declared_media_type.strip(_ASCII_WHITESPACE).lower()
        if normalized not in ("", "application/pdf"):
            raise PdfInspectionError("unsupported_media_type")
    if _PDF_HEADER.search(raw_bytes[:_HEADER_SEARCH_BYTES]) is None:
        raise PdfInspectionError("invalid_pdf")

    failure_reason: PdfInspectionReason | None = None
    encrypted = False
    page_count = 0
    try:
        reader = PdfReader(BytesIO(raw_bytes), strict=False, root_object_recovery_limit=10_000)
        encrypted = reader.is_encrypted
        if not encrypted:
            page_count = len(reader.pages)
    except _PARSER_FAILURES:
        failure_reason = "invalid_pdf"
    if failure_reason is not None:
        raise PdfInspectionError(failure_reason)
    if encrypted:
        raise PdfInspectionError("encrypted_pdf")
    if page_count == 0:
        raise PdfInspectionError("invalid_pdf")
    if page_count > max_pages:
        raise PdfInspectionError("page_limit_exceeded")
    return PdfInspection(filename=filename, size_bytes=len(raw_bytes), page_count=page_count)
