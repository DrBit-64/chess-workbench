"""Focused tests for the pure PDF upload preparation boundary (packet DS-STAGE8A-PDF-PREPARE-01)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from chess_workbench.logic.pdf import MAX_PDF_BYTES, MAX_PDF_PAGES, PdfInspection, inspect_pdf
from chess_workbench.services import pdf as pdf_module
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf import PreparedPdfAsset, prepare_pdf_asset
from chess_workbench.services.source_storage import StoredSourceBlob
from pypdf import PdfWriter


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


def _files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


# --- success paths ---------------------------------------------------------


def test_one_page_preparation_stores_exact_blob(tmp_path: Path) -> None:
    data = make_pdf(1)
    storage_root = tmp_path / "storage"
    result = prepare_pdf_asset(
        data,
        filename="book.pdf",
        declared_media_type="application/pdf",
        title=None,
        author=None,
        edition=None,
        storage_root=storage_root,
    )
    assert isinstance(result, PreparedPdfAsset)
    digest = sha256(data).hexdigest()
    assert result.filename == "book.pdf"
    assert result.content_sha256 == digest
    assert result.content_sha256.islower()
    assert result.size_bytes == len(data)
    assert result.page_count == 1
    assert result.relative_path == f"sources/pdf/{digest[:2]}/{digest}.pdf"
    assert result.title == "book"
    assert result.author is None
    assert result.edition is None
    assert result.storage_reused is False
    destination = storage_root / result.relative_path
    assert destination.read_bytes() == data
    assert destination.stat().st_size == len(data)
    assert destination.stat().st_mode & 0o777 == 0o600
    assert _files_under(storage_root) == [destination]


def test_three_page_preparation_reports_physical_page_count(tmp_path: Path) -> None:
    data = make_pdf(3)
    result = prepare_pdf_asset(
        data,
        filename="theory.pdf",
        declared_media_type=None,
        title="Opening Theory",
        author="Dr. X",
        edition="2nd Edition",
        storage_root=tmp_path,
    )
    assert result.page_count == 3
    assert result.size_bytes == len(data)
    assert result.title == "Opening Theory"
    assert result.author == "Dr. X"
    assert result.edition == "2nd Edition"


def test_identical_bytes_replay_reuses_the_same_blob(tmp_path: Path) -> None:
    data = make_pdf(1)
    storage_root = tmp_path / "storage"
    first = prepare_pdf_asset(
        data,
        filename="a.pdf",
        declared_media_type=None,
        title=None,
        author=None,
        edition=None,
        storage_root=storage_root,
    )
    second = prepare_pdf_asset(
        data,
        filename="a.pdf",
        declared_media_type=None,
        title=None,
        author=None,
        edition=None,
        storage_root=storage_root,
    )
    assert second.relative_path == first.relative_path
    assert second.content_sha256 == first.content_sha256
    assert second.size_bytes == first.size_bytes
    assert second.storage_reused is True
    destination = storage_root / first.relative_path
    assert destination.read_bytes() == data
    assert destination.stat().st_mode & 0o777 == 0o600
    assert _files_under(storage_root) == [destination]


def test_result_is_frozen_with_exact_public_fields(tmp_path: Path) -> None:
    assert tuple(PreparedPdfAsset.__dataclass_fields__) == (
        "filename",
        "content_sha256",
        "size_bytes",
        "page_count",
        "relative_path",
        "title",
        "author",
        "edition",
        "storage_reused",
    )
    data = make_pdf(1)
    result = prepare_pdf_asset(
        data,
        filename="book.pdf",
        declared_media_type=None,
        title="Theory",
        author="A",
        edition="2",
        storage_root=tmp_path,
    )
    with pytest.raises(FrozenInstanceError):
        result.title = "changed"  # type: ignore[misc]
    digest = sha256(data).hexdigest()
    assert result.relative_path == f"sources/pdf/{digest[:2]}/{digest}.pdf"
    assert result.size_bytes == len(data)


# --- title fallback and metadata -------------------------------------------


def test_missing_title_defaults_to_filename_without_pdf_suffix(tmp_path: Path) -> None:
    data = make_pdf(1)
    result = prepare_pdf_asset(
        data,
        filename="Opening.BOOK.PDF",
        declared_media_type=None,
        title=None,
        author=None,
        edition=None,
        storage_root=tmp_path,
    )
    assert result.title == "Opening.BOOK"
    assert result.filename == "Opening.BOOK.PDF"


def test_programmer_metadata_type_misuse_raises_type_error(tmp_path: Path) -> None:
    data = make_pdf(1)
    with pytest.raises(TypeError):
        prepare_pdf_asset(
            data,
            filename="a.pdf",
            declared_media_type=None,
            title=123,  # type: ignore[arg-type]
            author=None,
            edition=None,
            storage_root=tmp_path,
        )
    with pytest.raises(TypeError):
        prepare_pdf_asset(
            data,
            filename="a.pdf",
            declared_media_type=None,
            title=None,
            author=False,  # type: ignore[arg-type]
            edition=None,
            storage_root=tmp_path,
        )
    with pytest.raises(TypeError):
        prepare_pdf_asset(
            data,
            filename="a.pdf",
            declared_media_type=None,
            title=None,
            author=None,
            edition=["1st"],  # type: ignore[arg-type]
            storage_root=tmp_path,
        )


def _prepare_with_metadata(data: bytes, field: str, value: str, storage_root: Path) -> None:
    title = value if field == "title" else None
    author = value if field == "author" else None
    edition = value if field == "edition" else None
    prepare_pdf_asset(
        data,
        filename="a.pdf",
        declared_media_type=None,
        title=title,
        author=author,
        edition=edition,
        storage_root=storage_root,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", " leading"),
        ("title", "trailing "),
        ("author", "\t"),
        ("edition", " \n "),
        ("title", ""),
        ("author", ""),
        ("edition", ""),
        ("title", "x" * 201),
        ("author", "x" * 201),
        ("edition", "x" * 201),
    ],
)
def test_invalid_metadata_families_are_frozen_validation_errors(
    tmp_path: Path, field: str, value: str
) -> None:
    data = make_pdf(1)
    storage_root = tmp_path / "storage"
    with pytest.raises(ServiceError) as excinfo:
        _prepare_with_metadata(data, field, value, storage_root)
    error = excinfo.value
    assert error.code == "validation_error"
    assert error.status == 422
    assert error.message == "PDF metadata is invalid"
    assert str(error) == "PDF metadata is invalid"
    assert error.details == {"field": field}
    assert error.__cause__ is None
    assert error.__context__ is None
    assert not storage_root.exists()


def test_metadata_boundary_of_200_code_points_is_accepted(tmp_path: Path) -> None:
    data = make_pdf(1)
    result = prepare_pdf_asset(
        data,
        filename="a.pdf",
        declared_media_type=None,
        title="x" * 200,
        author="y" * 200,
        edition="z" * 200,
        storage_root=tmp_path,
    )
    assert result.title == "x" * 200
    assert result.author == "y" * 200
    assert result.edition == "z" * 200


# --- inspection error mapping ----------------------------------------------


@pytest.mark.parametrize(
    ("raw", "filename", "declared", "max_bytes", "max_pages", "expected"),
    [
        pytest.param(
            b"",
            "a.pdf",
            None,
            MAX_PDF_BYTES,
            MAX_PDF_PAGES,
            ("validation_error", 422, "PDF upload is invalid", {"reason": "empty_pdf"}),
            id="empty_pdf",
        ),
        pytest.param(
            make_pdf(1),
            "a.pdf",
            None,
            1,
            MAX_PDF_PAGES,
            (
                "payload_too_large",
                413,
                "PDF payload exceeds the configured limit",
                {"limit_bytes": 1},
            ),
            id="payload_too_large",
        ),
        pytest.param(
            make_pdf(1),
            "a.txt",
            None,
            MAX_PDF_BYTES,
            MAX_PDF_PAGES,
            ("validation_error", 422, "PDF upload is invalid", {"reason": "invalid_filename"}),
            id="invalid_filename",
        ),
        pytest.param(
            make_pdf(1),
            "a.pdf",
            "text/plain",
            MAX_PDF_BYTES,
            MAX_PDF_PAGES,
            (
                "unsupported_media_type",
                415,
                "PDF media type is not supported",
                {"reason": "unsupported_media_type"},
            ),
            id="unsupported_media_type",
        ),
        pytest.param(
            make_zero_page_pdf(),
            "a.pdf",
            None,
            MAX_PDF_BYTES,
            MAX_PDF_PAGES,
            ("validation_error", 422, "PDF upload is invalid", {"reason": "invalid_pdf"}),
            id="invalid_pdf",
        ),
        pytest.param(
            make_encrypted_pdf(),
            "a.pdf",
            None,
            MAX_PDF_BYTES,
            MAX_PDF_PAGES,
            ("validation_error", 422, "PDF upload is invalid", {"reason": "encrypted_pdf"}),
            id="encrypted_pdf",
        ),
        pytest.param(
            make_pdf(3),
            "a.pdf",
            None,
            MAX_PDF_BYTES,
            2,
            ("validation_error", 422, "PDF upload is invalid", {"reason": "page_limit_exceeded"}),
            id="page_limit_exceeded",
        ),
    ],
)
def test_every_inspection_reason_maps_to_the_frozen_service_error(
    tmp_path: Path,
    raw: bytes,
    filename: str,
    declared: str | None,
    max_bytes: int,
    max_pages: int,
    expected: tuple[str, int, str, dict[str, object]],
) -> None:
    storage_root = tmp_path / "storage"
    with pytest.raises(ServiceError) as excinfo:
        prepare_pdf_asset(
            raw,
            filename=filename,
            declared_media_type=declared,
            title=None,
            author=None,
            edition=None,
            storage_root=storage_root,
            max_bytes=max_bytes,
            max_pages=max_pages,
        )
    error = excinfo.value
    code, status, message, details = expected
    assert error.code == code
    assert error.status == status
    assert error.message == message
    assert str(error) == message
    assert error.details == details
    assert error.__cause__ is None
    assert error.__context__ is None
    assert not storage_root.exists()


# --- CAS failure passthrough ------------------------------------------------


def test_cas_failure_passes_through_unchanged_and_is_not_overwritten(tmp_path: Path) -> None:
    data = make_pdf(1)
    storage_root = tmp_path / "storage"
    first = prepare_pdf_asset(
        data,
        filename="a.pdf",
        declared_media_type=None,
        title=None,
        author=None,
        edition=None,
        storage_root=storage_root,
    )
    destination = storage_root / first.relative_path
    corrupt = b"corrupt-bytes"
    destination.write_bytes(corrupt)
    with pytest.raises(ServiceError) as excinfo:
        prepare_pdf_asset(
            data,
            filename="a.pdf",
            declared_media_type=None,
            title=None,
            author=None,
            edition=None,
            storage_root=storage_root,
        )
    error = excinfo.value
    assert error.code == "source_storage_unavailable"
    assert error.status == 503
    assert error.message == "source storage is unavailable"
    assert str(error) == "source storage is unavailable"
    assert str(tmp_path) not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert destination.read_bytes() == corrupt


# --- ordering: inspect then metadata then CAS -------------------------------


def test_inspection_receives_exactly_the_five_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = make_pdf(1)
    real_inspect = inspect_pdf
    seen: dict[str, object] = {}

    def recording_inspect(
        raw_bytes: bytes,
        *,
        filename: str,
        declared_media_type: str | None,
        max_bytes: int,
        max_pages: int,
    ) -> PdfInspection:
        seen["raw_bytes"] = raw_bytes
        seen["filename"] = filename
        seen["declared_media_type"] = declared_media_type
        seen["max_bytes"] = max_bytes
        seen["max_pages"] = max_pages
        return real_inspect(
            raw_bytes,
            filename=filename,
            declared_media_type=declared_media_type,
            max_bytes=max_bytes,
            max_pages=max_pages,
        )

    monkeypatch.setattr(pdf_module, "inspect_pdf", recording_inspect)
    result = prepare_pdf_asset(
        data,
        filename="book.pdf",
        declared_media_type="application/pdf",
        title="Opening",
        author=None,
        edition=None,
        storage_root=tmp_path,
        max_bytes=12_345,
        max_pages=67,
    )
    assert seen["raw_bytes"] is data
    assert seen["filename"] == "book.pdf"
    assert seen["declared_media_type"] == "application/pdf"
    assert seen["max_bytes"] == 12_345
    assert seen["max_pages"] == 67
    assert result.page_count == 1


def test_metadata_validation_precedes_cas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = make_pdf(1)
    storage_root = tmp_path / "storage"
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def spy_store(*args: object, **kwargs: object) -> StoredSourceBlob:
        calls.append((args, kwargs))
        return StoredSourceBlob(
            relative_path="sources/pdf/aa/aa.pdf",
            sha256="a" * 64,
            size_bytes=len(data),
            reused=False,
        )

    monkeypatch.setattr(pdf_module, "store_content_addressed_bytes", spy_store)
    with pytest.raises(ServiceError):
        prepare_pdf_asset(
            data,
            filename="a.pdf",
            declared_media_type=None,
            title=" bad",
            author=None,
            edition=None,
            storage_root=storage_root,
        )
    assert calls == []
    assert not storage_root.exists()


def test_success_stores_original_bytes_with_exact_namespace_and_suffix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = make_pdf(1)
    storage_root = tmp_path / "storage"
    captured: dict[str, object] = {}

    def spy_store(
        storage_root_arg: Path, *, namespace: str, suffix: str, raw_bytes: bytes
    ) -> StoredSourceBlob:
        captured["storage_root"] = storage_root_arg
        captured["namespace"] = namespace
        captured["suffix"] = suffix
        captured["raw_bytes"] = raw_bytes
        return StoredSourceBlob(
            relative_path="sources/pdf/aa/aa.pdf",
            sha256="b" * 64,
            size_bytes=len(data),
            reused=True,
        )

    monkeypatch.setattr(pdf_module, "store_content_addressed_bytes", spy_store)
    result = prepare_pdf_asset(
        data,
        filename="book.pdf",
        declared_media_type="application/pdf",
        title="Opening",
        author="Author",
        edition="1st",
        storage_root=storage_root,
    )
    assert captured["storage_root"] == storage_root
    assert captured["namespace"] == "sources/pdf"
    assert captured["suffix"] == ".pdf"
    assert captured["raw_bytes"] is data
    assert result.content_sha256 == "b" * 64
    assert result.storage_reused is True
    assert result.relative_path == "sources/pdf/aa/aa.pdf"


# --- BaseException propagation ----------------------------------------------


def test_base_exception_from_inspection_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise KeyboardInterrupt()

    monkeypatch.setattr(pdf_module, "inspect_pdf", boom)
    with pytest.raises(KeyboardInterrupt):
        prepare_pdf_asset(
            b"not a pdf",
            filename="a.pdf",
            declared_media_type=None,
            title=None,
            author=None,
            edition=None,
            storage_root=tmp_path,
        )


def test_base_exception_from_metadata_access_propagates(tmp_path: Path) -> None:
    class HostileStr(str):
        def strip(self, chars: str | None = None) -> str:
            raise SystemExit("hostile strip")

    data = make_pdf(1)
    with pytest.raises(SystemExit):
        prepare_pdf_asset(
            data,
            filename="a.pdf",
            declared_media_type=None,
            title=HostileStr(" x "),
            author=None,
            edition=None,
            storage_root=tmp_path,
        )


def test_base_exception_from_cas_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise SystemExit(2)

    monkeypatch.setattr(pdf_module, "store_content_addressed_bytes", boom)
    with pytest.raises(SystemExit):
        prepare_pdf_asset(
            make_pdf(1),
            filename="a.pdf",
            declared_media_type=None,
            title=None,
            author=None,
            edition=None,
            storage_root=tmp_path,
        )
