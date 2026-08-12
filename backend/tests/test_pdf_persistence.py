"""Black-box service tests for the Codex-owned transactional PDF persistence core
(packet DS-STAGE8A-PDF-PERSISTENCE-TESTS-01).

Proves the frozen public behavior of
``services.pdf_persistence.PdfPersistenceService`` with a temporary SQLite
``Database`` and directly constructed immutable ``PreparedPdfAsset`` values:
ownership chains, caller-owned transaction rollback, idempotent registration,
physical-page range validation, canonical logical fingerprints, SHA-256-only
idempotency keys, exact queued-job payloads and job/run atomicity under fault
injection.  No production file is touched and no private helper is asserted.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf import PreparedPdfAsset, prepare_pdf_asset
from chess_workbench.services.pdf_persistence import (
    PDF_EXTRACTION_JOB_KIND,
    PDF_EXTRACTION_PIPELINE_VERSION,
    PdfAssetRegistration,
    PdfPersistenceService,
)
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    ExtractionRun,
    InvalidationEvent,
    Job,
    PdfAsset,
    Source,
    SourceFile,
    SourceVersion,
)
from pypdf import PdfWriter
from sqlalchemy import func, select

HASH_A = "a" * 64
HASH_B = "b" * 64
PAGE_COUNT = 100
KEY = "extraction-key-01"

FOUR_TABLES = (Source, SourceVersion, SourceFile, PdfAsset)


# ── helpers ───────────────────────────────────────────────────────


def _prepared(
    *,
    content_sha256: str = HASH_A,
    filename: str = "opening-book.pdf",
    relative_path: str | None = None,
    title: str = "Opening Book",
    author: str | None = "A. Author",
    edition: str | None = "First Edition",
    page_count: int = PAGE_COUNT,
) -> PreparedPdfAsset:
    return PreparedPdfAsset(
        filename=filename,
        content_sha256=content_sha256,
        size_bytes=1024,
        page_count=page_count,
        relative_path=relative_path or f"sources/pdf/{content_sha256[:2]}/{content_sha256}.pdf",
        title=title,
        author=author,
        edition=edition,
        storage_reused=False,
    )


async def _db(tmp_path: Path, name: str) -> Database:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return database


async def _count(db: Database, model: type) -> int:
    async with db.session() as session, session.begin():
        return await session.scalar(select(func.count()).select_from(model)) or 0


async def _register(db: Database, prepared: PreparedPdfAsset) -> PdfAssetRegistration:
    async with db.session() as session, session.begin():
        return await PdfPersistenceService(session).register_asset(prepared)


def _fail_at(phase: str) -> Callable[[str, dict[str, object]], None]:
    def inject(fault_phase: str, _: dict[str, object]) -> None:
        if fault_phase == phase:
            raise RuntimeError(f"injected {phase} failure")

    return inject


# ── register_asset: ownership chain and replay ────────────────────


async def test_register_asset_creates_one_linked_chain(tmp_path: Path) -> None:
    db = await _db(tmp_path, "register-one.db")
    try:
        prepared = _prepared()
        async with db.session() as session, session.begin():
            registration = await PdfPersistenceService(session).register_asset(prepared)

        assert registration.replayed is False
        assert registration.asset.content_sha256 == prepared.content_sha256
        assert registration.asset.byte_size == prepared.size_bytes
        assert registration.asset.page_count == prepared.page_count
        for model in FOUR_TABLES:
            assert await _count(db, model) == 1

        async with db.session() as session, session.begin():
            source = (await session.scalars(select(Source))).one()
            version = (await session.scalars(select(SourceVersion))).one()
            source_file = (await session.scalars(select(SourceFile))).one()
            asset = (await session.scalars(select(PdfAsset))).one()

        assert source.kind == "book"
        assert source.title == prepared.title
        assert source.author == prepared.author
        assert version.source_id == source.id
        assert version.label == prepared.content_sha256
        assert version.edition == prepared.edition
        assert source_file.source_version_id == version.id
        assert source_file.filename == prepared.filename
        assert source_file.relative_path == prepared.relative_path
        assert source_file.media_type == "application/pdf"
        assert source_file.size_bytes == prepared.size_bytes
        assert source_file.sha256 == prepared.content_sha256
        assert asset.id == registration.asset.id
        assert asset.source_id == source.id
        assert asset.source_version_id == version.id
        assert asset.source_file_id == source_file.id
    finally:
        await db.close()


async def test_register_asset_same_hash_replays_without_new_rows(tmp_path: Path) -> None:
    db = await _db(tmp_path, "register-replay.db")
    try:
        first = _prepared(title="First Title", author="First Author", edition="First Edition")
        second = _prepared(title="Second Title", author="Second Author", edition="Second Edition")
        async with db.session() as session, session.begin():
            service = PdfPersistenceService(session)
            registration_a = await service.register_asset(first)
            registration_b = await service.register_asset(second)

        assert registration_a.replayed is False
        assert registration_b.replayed is True
        assert registration_b.asset.id == registration_a.asset.id
        for model in FOUR_TABLES:
            assert await _count(db, model) == 1

        async with db.session() as session, session.begin():
            source = (await session.scalars(select(Source))).one()
            version = (await session.scalars(select(SourceVersion))).one()
        # The first display metadata is retained, never overwritten.
        assert source.title == "First Title"
        assert source.author == "First Author"
        assert version.edition == "First Edition"
    finally:
        await db.close()


async def test_pdf_bytes_to_cas_and_sql_replay_end_to_end(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    stream = BytesIO()
    writer.write(stream)
    raw_bytes = stream.getvalue()
    storage_root = tmp_path / "storage"
    first_prepared = prepare_pdf_asset(
        raw_bytes,
        filename="chapter.pdf",
        declared_media_type="application/pdf",
        title="First title",
        author=None,
        edition=None,
        storage_root=storage_root,
    )
    replay_prepared = prepare_pdf_asset(
        raw_bytes,
        filename="chapter.pdf",
        declared_media_type="application/pdf",
        title="Ignored replay title",
        author=None,
        edition=None,
        storage_root=storage_root,
    )
    db = await _db(tmp_path, "prepare-register-integration.db")
    try:
        async with db.session() as session, session.begin():
            service = PdfPersistenceService(session)
            first = await service.register_asset(first_prepared)
            replay = await service.register_asset(replay_prepared)

        assert first.replayed is False
        assert replay.replayed is True
        assert replay.asset.id == first.asset.id
        assert replay_prepared.storage_reused is True
        assert len([path for path in storage_root.rglob("*") if path.is_file()]) == 1
        for model in FOUR_TABLES:
            assert await _count(db, model) == 1
        async with db.session() as session:
            source = (await session.scalars(select(Source))).one()
            source_file = (await session.scalars(select(SourceFile))).one()
        assert source.title == "First title"
        assert source_file.relative_path == first_prepared.relative_path
    finally:
        await db.close()


async def test_register_asset_rejects_non_prepared_value(tmp_path: Path) -> None:
    db = await _db(tmp_path, "register-typemisuse.db")
    try:
        with pytest.raises(TypeError, match="prepared must be PreparedPdfAsset"):
            async with db.session() as session, session.begin():
                await PdfPersistenceService(session).register_asset(
                    cast(PreparedPdfAsset, "not-a-prepared-value")
                )
    finally:
        await db.close()


@pytest.mark.parametrize("phase", ["source", "source_version", "source_file", "pdf_asset"])
async def test_register_asset_fault_at_every_phase_leaves_zero_rows(
    tmp_path: Path, phase: str
) -> None:
    db = await _db(tmp_path, f"register-fault-{phase}.db")
    try:
        with pytest.raises(RuntimeError, match=f"injected {phase} failure"):
            async with db.session() as session, session.begin():
                await PdfPersistenceService(session, fault_injector=_fail_at(phase)).register_asset(
                    _prepared()
                )
        for model in FOUR_TABLES:
            assert await _count(db, model) == 0, phase
    finally:
        await db.close()


async def test_register_asset_caller_rollback_leaves_zero_rows(tmp_path: Path) -> None:
    db = await _db(tmp_path, "register-rollback.db")
    try:
        async with db.session() as session:
            await PdfPersistenceService(session).register_asset(_prepared())
            await session.rollback()
        for model in FOUR_TABLES:
            assert await _count(db, model) == 0
    finally:
        await db.close()


# ── enqueue_extraction: queued job and run receipts ───────────────


async def test_enqueue_extraction_creates_exact_queued_job_payload(tmp_path: Path) -> None:
    db = await _db(tmp_path, "enqueue-payload.db")
    try:
        registration = await _register(db, _prepared(page_count=50))
        async with db.session() as session, session.begin():
            result = await PdfPersistenceService(session).enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=4,
                last_page=12,
                idempotency_key=None,
                profile={"engine": "ocr-v2", "nested": {"lang": "eng"}},
            )

        run, job = result.run, result.job
        assert result.replayed is False
        assert run.pdf_asset_id == registration.asset.id
        assert run.first_page == 4
        assert run.last_page == 12
        assert run.pipeline_version == PDF_EXTRACTION_PIPELINE_VERSION
        # Without an explicit key the logical fingerprint is the effective key.
        assert run.effective_key_hash == run.logical_fingerprint
        assert run.id == uuid5(
            NAMESPACE_URL, f"chess-workbench:{PDF_EXTRACTION_JOB_KIND}:{run.effective_key_hash}"
        )
        assert job.kind == PDF_EXTRACTION_JOB_KIND
        assert job.status == "queued"
        assert job.payload == {
            "schema_version": 1,
            "run_id": str(run.id),
            "pdf_asset_id": str(registration.asset.id),
            "first_page": 4,
            "last_page": 12,
            "pipeline_version": PDF_EXTRACTION_PIPELINE_VERSION,
            "profile": {"engine": "ocr-v2", "nested": {"lang": "eng"}},
        }
        async with db.session() as session, session.begin():
            events = list(await session.scalars(select(InvalidationEvent)))
        assert len(events) == 1
        assert events[0].resource_type == "job"
        assert events[0].resource_id == str(job.id)
        assert events[0].reason == "queued"
    finally:
        await db.close()


async def test_enqueue_extraction_without_key_exact_replay_returns_same_run_job(
    tmp_path: Path,
) -> None:
    db = await _db(tmp_path, "enqueue-replay-nokey.db")
    try:
        registration = await _register(db, _prepared())
        async with db.session() as session, session.begin():
            service = PdfPersistenceService(session)
            first = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=None,
                profile={"engine": "ocr-v1"},
            )
            second = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=None,
                profile={"engine": "ocr-v1"},
            )

        assert first.replayed is False
        assert second.replayed is True
        assert second.run.id == first.run.id
        assert second.job.id == first.job.id
        assert await _count(db, ExtractionRun) == 1
        assert await _count(db, Job) == 1
        assert await _count(db, InvalidationEvent) == 1
    finally:
        await db.close()


# ── enqueue_extraction: rejection leaves no SQL writes ────────────


async def test_enqueue_extraction_unknown_asset_raises_not_found(tmp_path: Path) -> None:
    db = await _db(tmp_path, "enqueue-missing.db")
    try:
        missing = UUID(int=1)
        with pytest.raises(ServiceError) as exc_info:
            async with db.session() as session, session.begin():
                await PdfPersistenceService(session).enqueue_extraction(
                    pdf_asset_id=missing,
                    first_page=1,
                    last_page=2,
                    idempotency_key=None,
                    profile=None,
                )
        error = exc_info.value
        assert error.code == "not_found"
        assert error.status == 404
        assert error.message == "PDF asset was not found"
        assert error.details == {"resource": "pdf_asset", "id": str(missing)}
        assert await _count(db, ExtractionRun) == 0
        assert await _count(db, Job) == 0
        assert await _count(db, InvalidationEvent) == 0
    finally:
        await db.close()


@pytest.mark.parametrize(
    ("first_page", "last_page"),
    [
        (0, 2),  # first page below one
        (3, 2),  # reversed range
        (2, 101),  # beyond the physical page count
    ],
)
async def test_enqueue_extraction_rejects_invalid_page_range(
    tmp_path: Path, first_page: int, last_page: int
) -> None:
    db = await _db(tmp_path, f"enqueue-range-{first_page}-{last_page}.db")
    try:
        registration = await _register(db, _prepared(page_count=PAGE_COUNT))
        with pytest.raises(ServiceError) as exc_info:
            async with db.session() as session, session.begin():
                await PdfPersistenceService(session).enqueue_extraction(
                    pdf_asset_id=registration.asset.id,
                    first_page=first_page,
                    last_page=last_page,
                    idempotency_key=None,
                    profile=None,
                )
        error = exc_info.value
        assert error.code == "validation_error"
        assert error.status == 422
        assert error.message == "PDF page range is invalid"
        assert error.details == {
            "first_page": first_page,
            "last_page": last_page,
            "page_count": PAGE_COUNT,
        }
        assert await _count(db, ExtractionRun) == 0
        assert await _count(db, Job) == 0
        assert await _count(db, InvalidationEvent) == 0
        assert await _count(db, PdfAsset) == 1
    finally:
        await db.close()


# ── enqueue_extraction: logical fingerprint and profile ───────────


async def test_enqueue_extraction_profile_key_order_does_not_matter(tmp_path: Path) -> None:
    db = await _db(tmp_path, "enqueue-keyorder.db")
    try:
        registration = await _register(db, _prepared())
        async with db.session() as session, session.begin():
            service = PdfPersistenceService(session)
            first = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=None,
                profile={"a": 1, "b": {"y": 2, "x": 1}},
            )
            second = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=None,
                profile={"b": {"x": 1, "y": 2}, "a": 1},
            )

        assert first.replayed is False
        assert second.replayed is True
        assert second.run.id == first.run.id
        assert second.job.id == first.job.id
        assert await _count(db, ExtractionRun) == 1
        assert await _count(db, Job) == 1
    finally:
        await db.close()


async def test_enqueue_extraction_distinct_logical_requests_create_distinct_runs(
    tmp_path: Path,
) -> None:
    db = await _db(tmp_path, "enqueue-distinct.db")
    try:
        registration = await _register(db, _prepared())
        async with db.session() as session, session.begin():
            service = PdfPersistenceService(session)
            pages_a = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=None,
                profile=None,
            )
            pages_b = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=3,
                idempotency_key=None,
                profile=None,
            )
            profile_b = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=None,
                profile={"lang": "eng"},
            )

        assert pages_a.replayed is False
        assert pages_b.replayed is False
        assert profile_b.replayed is False
        assert len({pages_a.run.id, pages_b.run.id, profile_b.run.id}) == 3
        assert len({pages_a.job.id, pages_b.job.id, profile_b.job.id}) == 3
        assert (
            len(
                {
                    pages_a.run.logical_fingerprint,
                    pages_b.run.logical_fingerprint,
                    profile_b.run.logical_fingerprint,
                }
            )
            == 3
        )
        assert await _count(db, ExtractionRun) == 3
        assert await _count(db, Job) == 3
    finally:
        await db.close()


async def test_enqueue_extraction_job_payload_owns_deep_profile_snapshot(tmp_path: Path) -> None:
    db = await _db(tmp_path, "enqueue-snapshot.db")
    try:
        registration = await _register(db, _prepared())
        nested: dict[str, Any] = {"lang": "eng", "flags": [1, 2]}
        profile: dict[str, Any] = {"engine": "ocr-v2", "nested": nested}
        async with db.session() as session, session.begin():
            service = PdfPersistenceService(session)
            result = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=5,
                idempotency_key=None,
                profile=profile,
            )
            stored_profile = result.job.payload["profile"]
            assert stored_profile == {
                "engine": "ocr-v2",
                "nested": {"flags": [1, 2], "lang": "eng"},
            }
            assert stored_profile is not profile
            # Mutating the caller-owned profile cannot change the stored snapshot.
            profile["engine"] = "mutated"
            nested["lang"] = "mutated"
            nested["flags"] = [1, 2, 99]
            assert result.job.payload["profile"] == {
                "engine": "ocr-v2",
                "nested": {"flags": [1, 2], "lang": "eng"},
            }
    finally:
        await db.close()


@pytest.mark.parametrize(
    "bad_profile",
    [
        {"x": float("inf")},
        {"x": float("-inf")},
        {"x": float("nan")},
        {"nested": {"x": float("nan")}},
        {"x": object()},
        {"x": {1, 2}},
    ],
)
async def test_enqueue_extraction_rejects_non_finite_or_non_json_profile(
    tmp_path: Path, bad_profile: dict[str, Any]
) -> None:
    db = await _db(tmp_path, "enqueue-badprofile.db")
    try:
        registration = await _register(db, _prepared())
        with pytest.raises(ServiceError) as exc_info:
            async with db.session() as session, session.begin():
                await PdfPersistenceService(session).enqueue_extraction(
                    pdf_asset_id=registration.asset.id,
                    first_page=1,
                    last_page=2,
                    idempotency_key=None,
                    profile=bad_profile,
                )
        error = exc_info.value
        assert error.code == "validation_error"
        assert error.status == 422
        assert error.message == "PDF extraction profile must be finite JSON"
        assert error.details is None
        assert await _count(db, ExtractionRun) == 0
        assert await _count(db, Job) == 0
        assert await _count(db, InvalidationEvent) == 0
    finally:
        await db.close()


@pytest.mark.parametrize("bad_profile", [[1, 2], "json", 5, 3.5])
async def test_enqueue_extraction_rejects_non_dict_profile(
    tmp_path: Path, bad_profile: Any
) -> None:
    db = await _db(tmp_path, "enqueue-nondict.db")
    try:
        registration = await _register(db, _prepared())
        with pytest.raises(TypeError, match="profile must be dict or None"):
            async with db.session() as session, session.begin():
                await PdfPersistenceService(session).enqueue_extraction(
                    pdf_asset_id=registration.asset.id,
                    first_page=1,
                    last_page=2,
                    idempotency_key=None,
                    profile=bad_profile,
                )
    finally:
        await db.close()


# ── enqueue_extraction: explicit idempotency keys ─────────────────


async def test_enqueue_extraction_explicit_key_stored_only_as_sha256(tmp_path: Path) -> None:
    db = await _db(tmp_path, "enqueue-keyhash.db")
    try:
        registration = await _register(db, _prepared())
        async with db.session() as session, session.begin():
            result = await PdfPersistenceService(session).enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=KEY,
                profile=None,
            )
        key_hash = sha256(KEY.encode("ascii")).hexdigest()
        assert result.run.effective_key_hash == key_hash
        assert result.job.idempotency_key == key_hash
        assert result.run.effective_key_hash != KEY
    finally:
        await db.close()


async def test_enqueue_extraction_same_key_same_request_replays(tmp_path: Path) -> None:
    db = await _db(tmp_path, "enqueue-keyreplay.db")
    try:
        registration = await _register(db, _prepared())
        async with db.session() as session, session.begin():
            service = PdfPersistenceService(session)
            first = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=KEY,
                profile={"engine": "ocr-v1"},
            )
            second = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=KEY,
                profile={"engine": "ocr-v1"},
            )

        assert first.replayed is False
        assert second.replayed is True
        assert second.run.id == first.run.id
        assert second.job.id == first.job.id
        assert await _count(db, ExtractionRun) == 1
        assert await _count(db, Job) == 1
        assert await _count(db, InvalidationEvent) == 1
    finally:
        await db.close()


async def test_enqueue_extraction_same_key_different_request_conflicts(tmp_path: Path) -> None:
    db = await _db(tmp_path, "enqueue-keyconflict.db")
    try:
        registration = await _register(db, _prepared())
        async with db.session() as session, session.begin():
            await PdfPersistenceService(session).enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key=KEY,
                profile=None,
            )

        with pytest.raises(ServiceError) as exc_info:
            async with db.session() as session, session.begin():
                await PdfPersistenceService(session).enqueue_extraction(
                    pdf_asset_id=registration.asset.id,
                    first_page=1,
                    last_page=3,
                    idempotency_key=KEY,
                    profile=None,
                )
        error = exc_info.value
        assert error.code == "idempotency_conflict"
        assert error.status == 409
        assert error.message == "Idempotency-Key is already bound to a different PDF extraction"
        assert error.details is None
        # Zero new rows: the original run, Job and event are untouched.
        assert await _count(db, ExtractionRun) == 1
        assert await _count(db, Job) == 1
        assert await _count(db, InvalidationEvent) == 1
    finally:
        await db.close()


async def test_enqueue_extraction_different_keys_share_logical_fingerprint(tmp_path: Path) -> None:
    db = await _db(tmp_path, "enqueue-twokeys.db")
    try:
        registration = await _register(db, _prepared())
        async with db.session() as session, session.begin():
            service = PdfPersistenceService(session)
            first = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key="key-one",
                profile=None,
            )
            second = await service.enqueue_extraction(
                pdf_asset_id=registration.asset.id,
                first_page=1,
                last_page=2,
                idempotency_key="key-two",
                profile=None,
            )

        assert first.replayed is False
        assert second.replayed is False
        assert first.run.id != second.run.id
        assert first.job.id != second.job.id
        assert first.run.logical_fingerprint == second.run.logical_fingerprint
        assert first.run.effective_key_hash != second.run.effective_key_hash
        assert await _count(db, ExtractionRun) == 2
        assert await _count(db, Job) == 2
    finally:
        await db.close()


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "x" * 129,
        "key with space",
        "key\twith\ttab",
        "ctrl-\x01",
        "ünïcode",
        "padded ",
    ],
)
async def test_enqueue_extraction_rejects_invalid_idempotency_key(
    tmp_path: Path, bad_key: str
) -> None:
    db = await _db(tmp_path, "enqueue-badkey.db")
    try:
        registration = await _register(db, _prepared())
        with pytest.raises(ServiceError) as exc_info:
            async with db.session() as session, session.begin():
                await PdfPersistenceService(session).enqueue_extraction(
                    pdf_asset_id=registration.asset.id,
                    first_page=1,
                    last_page=2,
                    idempotency_key=bad_key,
                    profile=None,
                )
        error = exc_info.value
        assert error.code == "validation_error"
        assert error.status == 422
        assert error.message == "Idempotency-Key must be 1..128 visible ASCII bytes"
        assert error.details is None
        assert await _count(db, ExtractionRun) == 0
        assert await _count(db, Job) == 0
        assert await _count(db, InvalidationEvent) == 0
    finally:
        await db.close()


# ── enqueue_extraction: job/run atomicity under fault ─────────────


@pytest.mark.parametrize("phase", ["job", "extraction_run"])
async def test_enqueue_extraction_fault_rolls_back_run_job_event_keeps_asset(
    tmp_path: Path, phase: str
) -> None:
    db = await _db(tmp_path, f"enqueue-fault-{phase}.db")
    try:
        registration = await _register(db, _prepared())
        assert await _count(db, PdfAsset) == 1

        with pytest.raises(RuntimeError, match=f"injected {phase} failure"):
            async with db.session() as session, session.begin():
                await PdfPersistenceService(
                    session, fault_injector=_fail_at(phase)
                ).enqueue_extraction(
                    pdf_asset_id=registration.asset.id,
                    first_page=1,
                    last_page=2,
                    idempotency_key=None,
                    profile=None,
                )

        assert await _count(db, ExtractionRun) == 0
        assert await _count(db, Job) == 0
        assert await _count(db, InvalidationEvent) == 0
        assert await _count(db, PdfAsset) == 1
        assert await _count(db, Source) == 1
    finally:
        await db.close()


# ── enqueue_extraction: programmer type misuse ────────────────────


@pytest.mark.parametrize(
    ("mutations", "message"),
    [
        ({"pdf_asset_id": "not-a-uuid"}, "pdf_asset_id must be UUID"),
        ({"pdf_asset_id": True}, "pdf_asset_id must be UUID"),
        ({"first_page": True}, "first_page must be int"),
        ({"first_page": "1"}, "first_page must be int"),
        ({"last_page": True}, "last_page must be int"),
        ({"last_page": 2.5}, "last_page must be int"),
        ({"idempotency_key": 123}, "idempotency_key must be str or None"),
        ({"profile": [1, 2]}, "profile must be dict or None"),
        ({"profile": "json"}, "profile must be dict or None"),
    ],
)
async def test_enqueue_extraction_type_misuse_raises_type_error(
    tmp_path: Path, mutations: dict[str, Any], message: str
) -> None:
    db = await _db(tmp_path, "enqueue-typemisuse.db")
    try:
        kwargs: dict[str, Any] = {
            "pdf_asset_id": UUID(int=2),
            "first_page": 1,
            "last_page": 2,
            "idempotency_key": None,
            "profile": None,
        }
        kwargs.update(mutations)
        with pytest.raises(TypeError, match=message):
            async with db.session() as session, session.begin():
                await PdfPersistenceService(session).enqueue_extraction(**kwargs)
    finally:
        await db.close()
