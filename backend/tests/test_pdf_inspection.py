"""Focused tests for the bounded PDF inspection boundary (packet DS-STAGE8A-PDF-INSPECTION-01)."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pytest
from chess_workbench.logic import pdf as pdf_module
from chess_workbench.logic.pdf import (
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    PdfInspection,
    PdfInspectionError,
    inspect_pdf,
)
from pypdf import PdfWriter
from pypdf.errors import PdfReadError

FIXED_MESSAGES = {
    "empty_pdf": "The PDF payload is empty.",
    "payload_too_large": "The PDF payload exceeds the size limit.",
    "invalid_filename": "The filename is not a valid PDF filename.",
    "unsupported_media_type": "The declared media type is not application/pdf.",
    "invalid_pdf": "The file is not a readable PDF document.",
    "encrypted_pdf": "The PDF document is encrypted.",
    "page_limit_exceeded": "The PDF has more pages than the allowed limit.",
}


def make_pdf(page_count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def make_encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt(user_password="user-secret", owner_password="owner-secret")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def make_zero_page_pdf() -> bytes:
    writer = PdfWriter()
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def assert_error(
    raw: bytes,
    filename: str,
    declared: str | None,
    reason: str,
    **kwargs: Any,
) -> PdfInspectionError:
    with pytest.raises(PdfInspectionError) as excinfo:
        inspect_pdf(raw, filename=filename, declared_media_type=declared, **kwargs)
    error = excinfo.value
    assert error.reason == reason
    assert str(error) == FIXED_MESSAGES[reason]
    assert error.args == (FIXED_MESSAGES[reason],)
    assert error.__cause__ is None
    assert error.__context__ is None
    return error


# --- success paths ---------------------------------------------------------


def test_one_page_pdf_returns_exact_immutable_metadata() -> None:
    data = make_pdf(1)
    result = inspect_pdf(data, filename="book.pdf", declared_media_type="application/pdf")
    assert isinstance(result, PdfInspection)
    assert result.filename == "book.pdf"
    assert result.size_bytes == len(data)
    assert result.page_count == 1
    assert result.media_type == "application/pdf"


def test_three_page_pdf_returns_exact_physical_page_count() -> None:
    data = make_pdf(3)
    result = inspect_pdf(data, filename="theory.pdf", declared_media_type=None)
    assert result.size_bytes == len(data)
    assert result.page_count == 3
    assert result.media_type == "application/pdf"


def test_uppercase_pdf_suffix_and_empty_or_none_mime_work() -> None:
    data = make_pdf(1)
    for declared in (None, "", "  ", "APPLICATION/PDF", " application/pdf "):
        result = inspect_pdf(data, filename="BOOK.PDF", declared_media_type=declared)
        assert result.filename == "BOOK.PDF"
        assert result.page_count == 1
        assert result.media_type == "application/pdf"


def test_success_does_not_mutate_input_bytes() -> None:
    data = make_pdf(2)
    snapshot = bytes(data)
    result = inspect_pdf(data, filename="a.pdf", declared_media_type=None)
    assert data == snapshot
    assert result.size_bytes == len(snapshot)


# --- preflight failures: exact reasons -------------------------------------


def test_empty_bytes_is_empty_pdf() -> None:
    assert_error(b"", "a.pdf", None, "empty_pdf")


def test_empty_bytes_wins_over_other_preflight_checks() -> None:
    assert_error(b"", "", None, "empty_pdf")


def test_oversize_payload_is_payload_too_large() -> None:
    data = make_pdf(1)
    assert_error(data, "a.pdf", None, "payload_too_large", max_bytes=len(data) - 1)
    # exact boundary is accepted
    result = inspect_pdf(data, filename="a.pdf", declared_media_type=None, max_bytes=len(data))
    assert result.page_count == 1


INVALID_FILENAMES = [
    "",
    "." + "a" * 200,  # 201 code points total
    "a" * 196 + ".pdf" + "x",  # 201 code points
    " a.pdf",
    "a.pdf ",
    "\ta.pdf",
    "a.pdf\n",
    "../a.pdf",
    "/etc/a.pdf",
    "a\\b.pdf",
    "a\x00.pdf",
    "a\x01.pdf",
    "a\x1f.pdf",
    "a\x7f.pdf",
    "a\x80.pdf",
    "a\x9f.pdf",
    ".pdf",
    "..pdf",
    "a.txt",
    "a.PDFx",
    "a.pdf/",
    "a.pdf\\",
]


@pytest.mark.parametrize("filename", INVALID_FILENAMES)
def test_invalid_filename_families(filename: str) -> None:
    data = make_pdf(1)
    assert_error(data, filename, None, "invalid_filename")


INVALID_MEDIA_TYPES = [
    "text/plain",
    "application/x-pdf",
    "application/pdf; charset=utf-8",
    "application/pdf;charset=utf-8",
    "application/PDF; x=1",
    "application/pdff",
    "pdf",
    "application",
    "application/pdf " + "\x00",
]


@pytest.mark.parametrize("declared", INVALID_MEDIA_TYPES)
def test_wrong_or_parameterized_mime_is_unsupported(declared: str) -> None:
    data = make_pdf(1)
    assert_error(data, "a.pdf", declared, "unsupported_media_type")


BAD_HEADERS = [
    b"not a pdf at all",
    b"%PDF",
    b"%PDF-",
    b"%PDF-1",
    b"%PDF-1.",
    b"%PDF-x.y",
    b"%PDF-0.7",
    b"%PDF-3.0",
    b"%PDF-1.70",
    b"%pdf-1.7",
    b"%PDF-1.7" * 200,  # header present but unreadable content
    b"\x00" * 1024 + b"%PDF-1.7\nnot really a pdf",  # header after the window
]


@pytest.mark.parametrize("raw", BAD_HEADERS)
def test_missing_or_bad_signature_is_invalid_pdf(raw: bytes) -> None:
    assert_error(raw, "a.pdf", None, "invalid_pdf")


# --- parser-level failures -------------------------------------------------


def test_zero_page_writer_is_invalid_pdf() -> None:
    assert_error(make_zero_page_pdf(), "a.pdf", None, "invalid_pdf")


def test_encrypted_pdf_is_rejected() -> None:
    error = assert_error(make_encrypted_pdf(), "a.pdf", None, "encrypted_pdf")
    assert error.__cause__ is None
    assert error.__context__ is None


def test_page_limit_exceeded() -> None:
    data = make_pdf(3)
    assert_error(data, "a.pdf", None, "page_limit_exceeded", max_pages=2)
    # exact boundary is accepted
    result = inspect_pdf(data, filename="a.pdf", declared_media_type=None, max_pages=3)
    assert result.page_count == 3


def test_header_may_follow_short_binary_comment() -> None:
    data = make_pdf(1)
    prefixed = b"\x00\x01" + data
    result = inspect_pdf(prefixed, filename="a.pdf", declared_media_type=None)
    assert result.page_count == 1
    assert result.size_bytes == len(prefixed)


def test_header_after_1024_bytes_is_rejected_before_parser_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("PdfReader must not be constructed")

    monkeypatch.setattr(pdf_module, "PdfReader", boom)
    data = make_pdf(1)
    late = b"\x00" * 1024 + data
    assert_error(late, "a.pdf", None, "invalid_pdf")


# --- parser failure sanitization -------------------------------------------


def test_parser_failures_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    data = make_pdf(1)
    marker = "ATTACKER_PARSER_TEXT_98765"

    class BoomReader:
        def __init__(self, exc: Exception) -> None:
            self._exc = exc

        @property
        def is_encrypted(self) -> bool:
            raise self._exc

    for exc in (
        PdfReadError(marker),
        RecursionError(marker),
        ValueError(marker),
        TypeError(marker),
        KeyError(marker),
        IndexError(marker),
        OSError(marker),
    ):
        monkeypatch.setattr(pdf_module, "PdfReader", lambda *a, _exc=exc, **k: BoomReader(_exc))
        error = assert_error(data, "a.pdf", None, "invalid_pdf")
        assert marker not in str(error)
        assert marker not in repr(error)
        assert all(marker not in str(arg) for arg in error.args)


def test_data_failures_during_page_access_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = make_pdf(1)
    marker = "ATTACKER_DATA_TEXT_54321"

    class BoomReader:
        is_encrypted = False

        def __init__(self, exc: Exception) -> None:
            self._exc = exc

        @property
        def pages(self) -> Any:
            raise self._exc

    for exc in (
        PdfReadError(marker),
        RecursionError(marker),
        ValueError(marker),
        TypeError(marker),
        KeyError(marker),
        IndexError(marker),
        OSError(marker),
    ):
        monkeypatch.setattr(pdf_module, "PdfReader", lambda *a, _exc=exc, **k: BoomReader(_exc))
        error = assert_error(data, "a.pdf", None, "invalid_pdf")
        assert marker not in str(error)
        assert marker not in repr(error)


def test_parser_is_not_constructed_for_preflight_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("PdfReader must not be constructed")

    monkeypatch.setattr(pdf_module, "PdfReader", boom)
    data = make_pdf(1)
    assert_error(b"", "a.pdf", None, "empty_pdf")
    assert_error(data, "a.pdf", None, "payload_too_large", max_bytes=len(data) - 1)
    assert_error(data, "../a.pdf", None, "invalid_filename")
    assert_error(data, "a.pdf", "text/plain", "unsupported_media_type")
    assert_error(b"garbage that is not a pdf", "a.pdf", None, "invalid_pdf")


def test_injected_keyboard_interrupt_and_memory_error_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = make_pdf(1)

    for exc in (KeyboardInterrupt, MemoryError):

        def boom(*args: Any, _exc: type[BaseException] = exc, **kwargs: Any) -> Any:
            raise _exc

        monkeypatch.setattr(pdf_module, "PdfReader", boom)
        with pytest.raises(exc):
            inspect_pdf(data, filename="a.pdf", declared_media_type=None)


# --- programmer type/limit misuse ------------------------------------------


def test_programmer_type_misuse_raises_type_error() -> None:
    data = make_pdf(1)
    with pytest.raises(TypeError):
        inspect_pdf("not bytes", filename="a.pdf", declared_media_type=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        inspect_pdf(data, filename=123, declared_media_type=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        inspect_pdf(data, filename="a.pdf", declared_media_type=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        inspect_pdf(data, filename="a.pdf", declared_media_type=None, max_bytes=True)
    with pytest.raises(TypeError):
        inspect_pdf(data, filename="a.pdf", declared_media_type=None, max_pages=True)
    with pytest.raises(TypeError):
        inspect_pdf(data, filename="a.pdf", declared_media_type=None, max_bytes=1.5)  # type: ignore[arg-type]


def test_programmer_limit_misuse_raises_value_error() -> None:
    data = make_pdf(1)
    with pytest.raises(ValueError):
        inspect_pdf(data, filename="a.pdf", declared_media_type=None, max_bytes=0)
    with pytest.raises(ValueError):
        inspect_pdf(data, filename="a.pdf", declared_media_type=None, max_bytes=-1)
    with pytest.raises(ValueError):
        inspect_pdf(data, filename="a.pdf", declared_media_type=None, max_pages=0)
    with pytest.raises(ValueError):
        inspect_pdf(data, filename="a.pdf", declared_media_type=None, max_pages=-5)


# --- error construction contract -------------------------------------------


def test_error_reason_is_restricted_to_declared_literals() -> None:
    with pytest.raises(ValueError):
        PdfInspectionError("not_a_reason")  # type: ignore[arg-type]
    for reason in FIXED_MESSAGES:
        error = PdfInspectionError(reason)  # type: ignore[arg-type]
        assert error.reason == reason
        assert str(error) == FIXED_MESSAGES[reason]


def test_constants_are_as_frozen() -> None:
    assert MAX_PDF_BYTES == 256 * 1024 * 1024
    assert MAX_PDF_PAGES == 20_000
