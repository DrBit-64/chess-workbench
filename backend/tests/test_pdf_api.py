"""Deterministic black-box HTTP tests for the Codex-owned Stage 8A PDF routes
(packet DS-STAGE8A-PDF-API-TESTS-01, 8A-3C).

Production code is read-only for this packet.  These tests prove the frozen
public behavior of ``/api/pdf-assets`` and ``/api/pdf-extractions`` with an
isolated Sanic app (temporary SQLite + storage, ``engine_worker_enabled=False``,
a small explicit ``pdf_max_bytes`` and ``Base.metadata.create_all``).  All PDFs
are tiny and generated deterministically in memory with ``pypdf``; no
``data/books``, network, provider, sleep, randomness or private helper is used.

Covered behaviors: upload envelope/replay with exact CAS layout, asset
discovery in newest-first order without paths, extraction enqueue with
deterministic run IDs and exact queued-job fields, idempotent replay and
explicit-key conflicts, missing-asset/page-range rejection with zero SQL
writes, list filters and their strict 422 handling, the engine ``SqlWorker``
registered-kind invariant, transport/validation rejection with no row or byte
leakage, the request-size cap rule, and the absence of Course/Knowledge rows.
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pypdf import PdfWriter
from sqlalchemy import func, select

from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings
from chess_workbench.services.pdf_persistence import PdfPersistenceService
from chess_workbench.services.worker import SqlWorker
from chess_workbench.store.base import Base
from chess_workbench.store.models import (
    Course,
    ExtractionArtifact,
    ExtractionRun,
    InvalidationEvent,
    Job,
    KnowledgeNote,
    PdfAsset,
    Source,
    SourceFile,
    SourceVersion,
)

PDF_EXTRACTION_PIPELINE_VERSION = "pdf-extraction:v2"
PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION = "pdf-extraction:v4"
MISSING_UUID = "00000000-0000-0000-0000-000000000000"

ASSET_TABLES = (PdfAsset, Source, SourceVersion, SourceFile)


# ── deterministic fixtures and helpers ───────────────────────────────────────


def make_pdf(page_count: int = 1) -> bytes:
    """Generate one tiny deterministic blank-page PDF in memory."""
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def build_app(
    tmp_path: Path,
    name: str,
    *,
    pdf_max_bytes: int = 64 * 1024,
) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-pdf-api-{name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}",
            source_storage_root=tmp_path / "storage",
            engine_worker_enabled=False,
            pdf_max_bytes=pdf_max_bytes,
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def count_rows(app: ChessWorkbenchApp, model: type) -> int:
    async with app.ctx.database.session() as session:
        return (await session.scalar(select(func.count()).select_from(model))) or 0


async def upload_pdf(
    client: Any,
    pdf: bytes,
    *,
    filename: str = "chapter.pdf",
    metadata: dict[str, Any] | None = None,
    media_type: str = "application/pdf",
) -> Any:
    payload: dict[str, Any] = {"files": {"file": (filename, pdf, media_type)}}
    if metadata is not None:
        payload["data"] = {"metadata": json.dumps(metadata)}
    return (await client.post("/api/pdf-assets", **payload))[1]


def multipart_only_metadata(boundary: str = "X-CW-META-1") -> tuple[bytes, str]:
    """A multipart/form-data body with a metadata part but no file part."""
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="metadata"\r\n\r\n'
        "{}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    return body, f"multipart/form-data; boundary={boundary}"


def multipart_file_with_duplicate_metadata(
    pdf: bytes,
    boundary: str = "X-CW-DUPMETA-1",
) -> tuple[bytes, str]:
    """A multipart/form-data body with one file part and two metadata parts."""
    file_part = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="chapter.pdf"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode()
        + pdf
        + b"\r\n"
    )
    metadata_parts = b"".join(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n{{}}\r\n'
        ).encode()
        for _ in range(2)
    )
    tail = f"--{boundary}--\r\n".encode()
    return file_part + metadata_parts + tail, f"multipart/form-data; boundary={boundary}"


def expected_run_id(
    asset_content_sha256: str,
    *,
    first_page: int,
    last_page: int,
    profile: dict[str, Any],
    pipeline_version: str = PDF_EXTRACTION_PIPELINE_VERSION,
) -> UUID:
    """Replicate the frozen deterministic run id for an enqueue request.

    This helper independently mirrors the production canonical fingerprint
    identity (including the frozen fingerprint-version field) without calling
    the production private helper.
    """
    fingerprint_version = (
        "pdfium-text-lines+diagram+ccef-semantic-consolidation:v14"
        if pipeline_version == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION
        else "pdfium-text-lines+ccef-formal-consolidation:v5"
    )
    identity = {
        "asset_content_sha256": asset_content_sha256,
        "extraction_fingerprint_version": fingerprint_version,
        "first_page": first_page,
        "last_page": last_page,
        "pipeline_version": pipeline_version,
        "profile": profile,
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return uuid5(NAMESPACE_URL, f"chess-workbench:pdf_extraction:{fingerprint}")


async def db_asset_ids(app: ChessWorkbenchApp) -> list[str]:
    """Persistence-order (created_at desc, id) of every PdfAsset row."""
    async with app.ctx.database.session() as session:
        rows = list(
            (
                await session.execute(
                    select(PdfAsset).order_by(PdfAsset.created_at.desc(), PdfAsset.id)
                )
            ).scalars()
        )
    return [str(row.id) for row in rows]


# ── upload: envelope, CAS blob, replay ───────────────────────────────────────


async def test_upload_returns_201_envelope_and_exact_cas_blob(tmp_path: Path) -> None:
    app = build_app(tmp_path, "upload")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        pdf = make_pdf(2)
        response = await upload_pdf(
            client,
            pdf,
            filename="theory.pdf",
            metadata={"title": "Opening Theory", "author": "Dr. X", "edition": "2nd"},
        )
        assert response.status == 201
        assert response.headers["idempotency-replayed"] == "false"
        body = response.json
        assert body["replayed"] is False
        assert set(body.keys()) == {"replayed", "asset"}
        asset = body["asset"]
        assert set(asset.keys()) == {
            "id",
            "content_sha256",
            "byte_size",
            "page_count",
            "source_id",
            "source_version_id",
            "source_file_id",
            "filename",
            "title",
            "author",
            "edition",
            "created_at",
        }
        digest = hashlib.sha256(pdf).hexdigest()
        assert asset["content_sha256"] == digest
        assert asset["byte_size"] == len(pdf)
        assert asset["page_count"] == 2
        assert asset["filename"] == "theory.pdf"
        assert asset["title"] == "Opening Theory"
        assert asset["author"] == "Dr. X"
        assert asset["edition"] == "2nd"
        assert response.headers["location"] == f"/api/pdf-assets/{asset['id']}"
        # No relative or absolute path is exposed anywhere in the payload.
        assert "sources/pdf" not in response.text
        storage_root = app.ctx.settings.source_storage_root
        assert str(storage_root) not in response.text

        blob = storage_root / "sources" / "pdf" / digest[:2] / f"{digest}.pdf"
        assert blob.is_file()
        assert blob.read_bytes() == pdf
        assert blob.stat().st_mode & 0o777 == 0o600
        assert [path for path in storage_root.rglob("*") if path.is_file()] == [blob]
        for model in ASSET_TABLES:
            assert await count_rows(app, model) == 1
        # Uploads never create Course or Knowledge content.
        assert await count_rows(app, Course) == 0
        assert await count_rows(app, KnowledgeNote) == 0
        assert await count_rows(app, Job) == 0
    finally:
        await app.ctx.database.close()


async def test_upload_same_bytes_replays_with_original_metadata(tmp_path: Path) -> None:
    app = build_app(tmp_path, "replay")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        pdf = make_pdf()
        first = await upload_pdf(
            client,
            pdf,
            filename="original.pdf",
            metadata={"title": "First Title", "author": "A. Author", "edition": "1st"},
        )
        assert first.status == 201
        first_asset = first.json["asset"]

        replay = await upload_pdf(
            client,
            pdf,
            filename="renamed.PDF",
            metadata={"title": "Ignored Replay Title"},
        )
        assert replay.status == 200
        assert replay.headers["idempotency-replayed"] == "true"
        body = replay.json
        assert body["replayed"] is True
        asset = body["asset"]
        # Same content bytes replay the identical immutable read model.
        assert asset["id"] == first_asset["id"]
        assert asset["content_sha256"] == first_asset["content_sha256"]
        assert asset["source_id"] == first_asset["source_id"]
        assert asset["source_version_id"] == first_asset["source_version_id"]
        assert asset["source_file_id"] == first_asset["source_file_id"]
        assert asset["byte_size"] == first_asset["byte_size"]
        assert asset["page_count"] == first_asset["page_count"]
        assert asset["created_at"] == first_asset["created_at"]
        # The first display metadata and filename are retained, never overwritten.
        assert asset["filename"] == "original.pdf"
        assert asset["title"] == "First Title"
        assert asset["author"] == "A. Author"
        assert asset["edition"] == "1st"
        # Exactly one Source chain and one CAS blob exist.
        for model in ASSET_TABLES:
            assert await count_rows(app, model) == 1
        digest = hashlib.sha256(pdf).hexdigest()
        files = [path for path in app.ctx.settings.source_storage_root.rglob("*") if path.is_file()]
        assert [path.name for path in files] == [f"{digest}.pdf"]
    finally:
        await app.ctx.database.close()


async def db_run_ids(app: ChessWorkbenchApp) -> list[str]:
    """Persistence-order (created_at desc, id) of every ExtractionRun row."""
    async with app.ctx.database.session() as session:
        rows = list(
            (
                await session.execute(
                    select(ExtractionRun).order_by(
                        ExtractionRun.created_at.desc(), ExtractionRun.id
                    )
                )
            ).scalars()
        )
    return [str(row.id) for row in rows]


# ── asset discovery ──────────────────────────────────────────────────────────


async def test_asset_get_and_list_agree_with_persistence_order(tmp_path: Path) -> None:
    app = build_app(tmp_path, "discover")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        first_pdf = make_pdf(1)
        second_pdf = make_pdf(3)
        first = await upload_pdf(client, first_pdf, filename="one.pdf")
        second = await upload_pdf(client, second_pdf, filename="three.pdf")
        assert first.status == second.status == 201
        first_asset = first.json["asset"]
        second_asset = second.json["asset"]
        assert first_asset["content_sha256"] != second_asset["content_sha256"]

        # GET one returns the exact same read model as the upload envelope.
        _, got = await client.get(f"/api/pdf-assets/{first_asset['id']}")
        assert got.status == 200
        assert got.json == first_asset

        # GET list discovers every persisted asset in newest-first order.
        _, listing = await client.get("/api/pdf-assets")
        assert listing.status == 200
        items = listing.json["items"]
        assert len(items) == 2
        assert {item["id"] for item in items} == {first_asset["id"], second_asset["id"]}
        assert [item["id"] for item in items] == await db_asset_ids(app)
        for item in items:
            assert set(item.keys()) == set(first_asset.keys())
        assert "sources/pdf" not in listing.text
        assert str(app.ctx.settings.source_storage_root) not in listing.text

        # Missing UUID resources return the stable 404 error shape.
        _, missing = await client.get(f"/api/pdf-assets/{MISSING_UUID}")
        assert missing.status == 404
        assert missing.json["code"] == "not_found"
        assert missing.json["message"] == "PDF asset not found"
    finally:
        await app.ctx.database.close()


# ── extraction enqueue: 202, deterministic run id, exact job ─────────────────


async def test_extraction_enqueue_returns_202_with_exact_job(tmp_path: Path) -> None:
    app = build_app(tmp_path, "enqueue")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        pdf = make_pdf(3)
        asset = (await upload_pdf(client, pdf, filename="theory.pdf")).json["asset"]
        profile = {"engine": "ocr-v1", "nested": {"lang": "eng"}, "confidence": 0.5}
        request_body = {
            "pdf_asset_id": asset["id"],
            "first_page": 1,
            "last_page": 2,
            "profile": profile,
        }
        response = (await client.post("/api/pdf-extractions", json=request_body))[1]
        assert response.status == 202
        assert response.headers["idempotency-replayed"] == "false"
        body = response.json
        assert body["replayed"] is False

        run_id = expected_run_id(
            asset["content_sha256"],
            first_page=1,
            last_page=2,
            profile=profile,
            pipeline_version=PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
        )
        extraction = body["extraction"]
        assert extraction["id"] == str(run_id)
        assert response.headers["location"] == f"/api/pdf-extractions/{run_id}"
        assert extraction["pdf_asset_id"] == asset["id"]
        assert extraction["first_page"] == 1
        assert extraction["last_page"] == 2
        assert extraction["pipeline_version"] == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION
        assert extraction["profile"] == profile
        assert extraction["has_conflicts"] is False
        # The nested generic Job is exact: queued, attempt 0, finite payload.
        job = extraction["job"]
        assert job["kind"] == "pdf_extraction"
        assert job["status"] == "queued"
        assert job["attempt_count"] == 0
        assert job["max_attempts"] == 3
        assert job["cancel_requested_at"] is None
        assert job["last_error_code"] is None
        assert job["last_error_message"] is None
        assert job["result"] is None
        assert job["payload"] == {
            "schema_version": 1,
            "run_id": str(run_id),
            "pdf_asset_id": asset["id"],
            "first_page": 1,
            "last_page": 2,
            "pipeline_version": PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
            "profile": profile,
        }
        assert await count_rows(app, ExtractionRun) == 1
        assert await count_rows(app, Job) == 1
        assert await count_rows(app, InvalidationEvent) == 1
        assert await count_rows(app, Course) == 0
        assert await count_rows(app, KnowledgeNote) == 0
    finally:
        await app.ctx.database.close()


async def test_archive_extraction_cancels_active_jobs_and_hides_all_states(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "archive")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        runs: list[dict[str, Any]] = []
        for index in range(3):
            _, response = await client.post(
                "/api/pdf-extractions",
                json={
                    "pdf_asset_id": asset["id"],
                    "first_page": 1,
                    "last_page": index + 1,
                },
                headers={"Idempotency-Key": f"archive-{index}"},
            )
            assert response.status == 202
            runs.append(response.json["extraction"])

        async with app.ctx.database.session() as session, session.begin():
            running = await session.get(Job, UUID(runs[1]["job"]["id"]))
            failed = await session.get(Job, UUID(runs[2]["job"]["id"]))
            assert running is not None and failed is not None
            running.status = "running"
            running.lease_owner = "archive-test"
            failed.status = "failed"

        for run in runs:
            _, archived = await client.delete(f"/api/pdf-extractions/{run['id']}")
            assert archived.status == 204

        _, listing = await client.get("/api/pdf-extractions")
        assert listing.status == 200
        assert listing.json == {"items": []}

        async with app.ctx.database.session() as session:
            queued = await session.get(Job, UUID(runs[0]["job"]["id"]))
            running = await session.get(Job, UUID(runs[1]["job"]["id"]))
            failed = await session.get(Job, UUID(runs[2]["job"]["id"]))
            assert queued is not None and running is not None and failed is not None
            assert queued.status == "cancelled"
            assert running.status == "running"
            assert running.cancel_requested_at is not None
            assert failed.status == "failed"
            assert all(job.archived_at is not None for job in (queued, running, failed))

        # Archival affects discovery, not immutable receipt or audit access.
        _, direct = await client.get(f"/api/pdf-extractions/{runs[2]['id']}")
        assert direct.status == 200
        assert direct.json["job"]["status"] == "failed"
    finally:
        await app.ctx.database.close()


async def test_extraction_exact_replay_returns_200_same_run(tmp_path: Path) -> None:
    app = build_app(tmp_path, "enqueue-replay")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        request_body = {"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 2}
        first = (await client.post("/api/pdf-extractions", json=request_body))[1]
        replay = (await client.post("/api/pdf-extractions", json=request_body))[1]
        assert first.status == 202
        assert replay.status == 200
        assert first.headers["idempotency-replayed"] == "false"
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json["replayed"] is True
        assert replay.json["extraction"]["id"] == first.json["extraction"]["id"]
        assert await count_rows(app, ExtractionRun) == 1
        assert await count_rows(app, Job) == 1
        assert await count_rows(app, InvalidationEvent) == 1
    finally:
        await app.ctx.database.close()


async def test_extraction_explicit_key_replays_and_conflicts_without_rows(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "enqueue-key")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        headers = {"Idempotency-Key": "stable-key"}
        first = (
            await client.post(
                "/api/pdf-extractions",
                json={"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 2},
                headers=headers,
            )
        )[1]
        assert first.status == 202
        assert first.headers["idempotency-replayed"] == "false"

        replay = (
            await client.post(
                "/api/pdf-extractions",
                json={"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 2},
                headers=headers,
            )
        )[1]
        assert replay.status == 200
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json["extraction"]["id"] == first.json["extraction"]["id"]

        # Same explicit key with a different profile is a conflict.
        different_profile = (
            await client.post(
                "/api/pdf-extractions",
                json={
                    "pdf_asset_id": asset["id"],
                    "first_page": 1,
                    "last_page": 2,
                    "profile": {"engine": "ocr-v2"},
                },
                headers=headers,
            )
        )[1]
        assert different_profile.status == 409
        assert different_profile.json["code"] == "idempotency_conflict"
        assert (
            different_profile.json["message"]
            == "Idempotency-Key is already bound to a different PDF extraction"
        )

        # Same explicit key with a different page range is a conflict too.
        different_pages = (
            await client.post(
                "/api/pdf-extractions",
                json={"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 3},
                headers=headers,
            )
        )[1]
        assert different_pages.status == 409
        assert different_pages.json["code"] == "idempotency_conflict"

        # Zero new run/job/event rows: only the original request persisted.
        assert await count_rows(app, ExtractionRun) == 1
        assert await count_rows(app, Job) == 1
        assert await count_rows(app, InvalidationEvent) == 1
    finally:
        await app.ctx.database.close()


async def test_extraction_missing_asset_and_invalid_ranges_create_no_rows(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "enqueue-reject")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]

        _, missing = await client.post(
            "/api/pdf-extractions",
            json={"pdf_asset_id": MISSING_UUID, "first_page": 1, "last_page": 1},
        )
        assert missing.status == 404
        assert missing.json["code"] == "not_found"
        assert missing.json["message"] == "PDF asset was not found"

        _, reverse = await client.post(
            "/api/pdf-extractions",
            json={"pdf_asset_id": asset["id"], "first_page": 2, "last_page": 1},
        )
        assert reverse.status == 422
        assert reverse.json["code"] == "validation_error"

        _, out_of_range = await client.post(
            "/api/pdf-extractions",
            json={"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 99},
        )
        assert out_of_range.status == 422
        assert out_of_range.json["code"] == "validation_error"
        assert out_of_range.json["message"] == "PDF page range is invalid"
        assert out_of_range.json["details"] == {
            "first_page": 1,
            "last_page": 99,
            "page_count": 3,
        }

        _, zero_page = await client.post(
            "/api/pdf-extractions",
            json={"pdf_asset_id": asset["id"], "first_page": 0, "last_page": 1},
        )
        assert zero_page.status == 422
        assert zero_page.json["code"] == "validation_error"

        # Every rejection left the asset intact and created no run/job/event.
        assert await count_rows(app, PdfAsset) == 1
        assert await count_rows(app, ExtractionRun) == 0
        assert await count_rows(app, Job) == 0
        assert await count_rows(app, InvalidationEvent) == 0
    finally:
        await app.ctx.database.close()


# ── extraction read back: GET-one, list and strict filters ───────────────────


async def test_extraction_get_and_list_agree_and_filters_are_strict(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "extraction-list")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        first = (
            await client.post(
                "/api/pdf-extractions",
                json={
                    "pdf_asset_id": asset["id"],
                    "first_page": 1,
                    "last_page": 1,
                    "profile": {"engine": "ocr-v1"},
                },
            )
        )[1]
        second = (
            await client.post(
                "/api/pdf-extractions",
                json={
                    "pdf_asset_id": asset["id"],
                    "first_page": 1,
                    "last_page": 2,
                    "profile": {"engine": "ocr-v2"},
                },
            )
        )[1]
        assert first.status == second.status == 202
        run_ids = [first.json["extraction"]["id"], second.json["extraction"]["id"]]
        assert len(set(run_ids)) == 2

        # GET-one and the list expose exactly the same run/job state.
        get_ones = {}
        for run_id in run_ids:
            _, got = await client.get(f"/api/pdf-extractions/{run_id}")
            assert got.status == 200
            get_ones[run_id] = got.json
        _, listing = await client.get("/api/pdf-extractions")
        assert listing.status == 200
        items = listing.json["items"]
        expected_order = await db_run_ids(app)
        assert [item["id"] for item in items] == expected_order
        assert set(expected_order) == set(run_ids)
        for item in items:
            assert item == get_ones[item["id"]]
            assert item["job"]["kind"] == "pdf_extraction"
            assert item["job"]["status"] == "queued"
            assert item["job"]["attempt_count"] == 0
            assert item["has_conflicts"] is False

        # status=queued and has_conflicts=false include both queued runs.
        _, queued = await client.get("/api/pdf-extractions?status=queued")
        assert queued.status == 200
        assert [item["id"] for item in queued.json["items"]] == expected_order
        _, no_conflicts = await client.get("/api/pdf-extractions?has_conflicts=false")
        assert no_conflicts.status == 200
        assert [item["id"] for item in no_conflicts.json["items"]] == expected_order

        # Other valid statuses and has_conflicts=true exclude every queued run.
        _, conflicted = await client.get("/api/pdf-extractions?has_conflicts=true")
        assert conflicted.status == 200
        assert conflicted.json["items"] == []
        for status in ("running", "succeeded", "failed", "cancelled"):
            _, filtered = await client.get(f"/api/pdf-extractions?status={status}")
            assert filtered.status == 200
            assert filtered.json["items"] == []

        # Unknown/duplicate/non-lowercase filters return the stable 422.
        bad_queries = (
            "status=bogus",
            "status=queued&status=running",
            "status=QUEUED",
            "has_conflicts=true&has_conflicts=false",
            "has_conflicts=True",
            "has_conflicts=yes",
        )
        for query in bad_queries:
            _, bad = await client.get(f"/api/pdf-extractions?{query}")
            assert bad.status == 422, query
            assert bad.json["code"] == "validation_error", query

        # Missing run resources return the stable 404 error shape.
        _, missing = await client.get(f"/api/pdf-extractions/{MISSING_UUID}")
        assert missing.status == 404
        assert missing.json["code"] == "not_found"
        assert missing.json["message"] == "PDF extraction not found"
    finally:
        await app.ctx.database.close()


async def test_extraction_read_exposes_only_a_complete_committed_evidence_summary(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "evidence-summary")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(2))).json["asset"]
        created = (
            await client.post(
                "/api/pdf-extractions",
                json={"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 2},
            )
        )[1]
        run_id = UUID(created.json["extraction"]["id"])
        assert created.json["extraction"]["evidence"] is None

        async with app.ctx.database.session() as session, session.begin():
            run = await session.get(ExtractionRun, run_id)
            assert run is not None
            job = await session.get(Job, run.job_id)
            assert job is not None
            job.status = "succeeded"
            job.attempt_count = 1
            job.result = {
                "result_schema": "chess-workbench/pdf-extraction-result/2.0",
                "run_id": str(run_id),
                "evidence": {
                    "render_manifest_sha256": "a" * 64,
                    "ocr_manifest_sha256": "b" * 64,
                    "page_count": 2,
                    "fragment_count": 37,
                    "warning_count": 1,
                },
                "candidate": {
                    "provider_response_sha256": "1" * 64,
                    "request_sha256": "2" * 64,
                    "response_sha256": "3" * 64,
                    "raw_ccef_sha256": "4" * 64,
                    "normalized_ccef_sha256": "5" * 64,
                    "summary": {
                        "item_count": 9,
                        "move_node_count": 12,
                        "figure_count": 0,
                        "unresolved_item_count": 1,
                        "warning_count": 2,
                        "error_count": 0,
                        "invalid_move_count": 1,
                        "ambiguous_move_count": 0,
                        "has_conflicts": True,
                    },
                },
            }
            for kind, page_number, digest, media_type in (
                ("rendered_page", 1, "c" * 64, "image/png"),
                ("rendered_page", 2, "d" * 64, "image/png"),
                ("ocr_fragment", 1, "e" * 64, "application/json"),
                ("ocr_fragment", 2, "f" * 64, "application/json"),
                ("render_manifest", None, "a" * 64, "application/json"),
                ("ocr_manifest", None, "b" * 64, "application/json"),
                ("provider_response", None, "1" * 64, "application/json"),
                ("raw_ccef", None, "4" * 64, "application/json"),
                ("normalized_ccef", None, "5" * 64, "application/json"),
            ):
                session.add(
                    ExtractionArtifact(
                        run_id=run_id,
                        kind=kind,
                        page_number=page_number,
                        relative_path=f"derived/extraction/{digest[:2]}/{digest}.bin",
                        media_type=media_type,
                        byte_size=10,
                        content_sha256=digest,
                    )
                )

        _, got = await client.get(f"/api/pdf-extractions/{run_id}")
        assert got.status == 200
        assert got.json["evidence"] == {
            "status": "committed",
            "page_count": 2,
            "fragment_count": 37,
            "warning_count": 1,
            "render_manifest_sha256": "a" * 64,
            "ocr_manifest_sha256": "b" * 64,
        }
        assert got.json["candidate"] == {
            "status": "committed",
            "provider_response_sha256": "1" * 64,
            "request_sha256": "2" * 64,
            "response_sha256": "3" * 64,
            "raw_ccef_sha256": "4" * 64,
            "normalized_ccef_sha256": "5" * 64,
            "item_count": 9,
            "move_node_count": 12,
            "figure_count": 0,
            "unresolved_item_count": 1,
            "warning_count": 2,
            "error_count": 0,
            "invalid_move_count": 1,
            "ambiguous_move_count": 0,
            "has_conflicts": True,
        }
        assert got.json["has_conflicts"] is True
        assert "relative_path" not in got.text
        assert "derived/extraction" not in got.text

        _, listing = await client.get("/api/pdf-extractions")
        assert listing.status == 200
        assert listing.json["items"][0]["evidence"] == got.json["evidence"]
        assert listing.json["items"][0]["candidate"] == got.json["candidate"]
        _, conflicted = await client.get("/api/pdf-extractions?has_conflicts=true")
        assert [item["id"] for item in conflicted.json["items"]] == [str(run_id)]
        _, clean = await client.get("/api/pdf-extractions?has_conflicts=false")
        assert clean.json["items"] == []

        async with app.ctx.database.session() as session, session.begin():
            artifact = await session.scalar(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run_id,
                    ExtractionArtifact.kind == "rendered_page",
                    ExtractionArtifact.page_number == 2,
                )
            )
            assert artifact is not None
            await session.delete(artifact)

        _, incomplete = await client.get(f"/api/pdf-extractions/{run_id}")
        assert incomplete.status == 200
        assert incomplete.json["job"]["status"] == "succeeded"
        assert incomplete.json["evidence"] is None
        assert incomplete.json["candidate"] is None
        assert incomplete.json["has_conflicts"] is False
    finally:
        await app.ctx.database.close()


# ── HTTP v3 cutover and v2/v3 read compatibility ─────────────────────────────


async def _enqueue_direct(
    app: ChessWorkbenchApp,
    asset_id: str,
    *,
    first_page: int,
    last_page: int,
    profile: dict[str, Any] | None,
    idempotency_key: str | None,
    pipeline_version: str,
) -> UUID:
    async with app.ctx.database.session() as session, session.begin():
        outcome = await PdfPersistenceService(session).enqueue_extraction(
            pdf_asset_id=UUID(asset_id),
            first_page=first_page,
            last_page=last_page,
            idempotency_key=idempotency_key,
            profile=profile,
            pipeline_version=pipeline_version,
        )
    return outcome.run.id


async def _commit_completed_run(
    app: ChessWorkbenchApp, run_id: UUID, *, normalized_sha: str = "5" * 64
) -> None:
    async with app.ctx.database.session() as session, session.begin():
        run = await session.get(ExtractionRun, run_id)
        assert run is not None
        job = await session.get(Job, run.job_id)
        assert job is not None
        job.status = "succeeded"
        job.attempt_count = 1
        job.result = {
            "result_schema": "chess-workbench/pdf-extraction-result/2.0",
            "run_id": str(run_id),
            "evidence": {
                "render_manifest_sha256": "a" * 64,
                "ocr_manifest_sha256": "b" * 64,
                "page_count": 2,
                "fragment_count": 37,
                "warning_count": 1,
            },
            "candidate": {
                "provider_response_sha256": "1" * 64,
                "request_sha256": "2" * 64,
                "response_sha256": "3" * 64,
                "raw_ccef_sha256": "4" * 64,
                "normalized_ccef_sha256": "5" * 64,
                "summary": {
                    "item_count": 9,
                    "move_node_count": 12,
                    "figure_count": 0,
                    "unresolved_item_count": 1,
                    "warning_count": 2,
                    "error_count": 0,
                    "invalid_move_count": 1,
                    "ambiguous_move_count": 0,
                    "has_conflicts": True,
                },
            },
        }
        for kind, page_number, digest, media_type in (
            ("rendered_page", 1, "c" * 64, "image/png"),
            ("rendered_page", 2, "d" * 64, "image/png"),
            ("ocr_fragment", 1, "e" * 64, "application/json"),
            ("ocr_fragment", 2, "f" * 64, "application/json"),
            ("render_manifest", None, "a" * 64, "application/json"),
            ("ocr_manifest", None, "b" * 64, "application/json"),
            ("provider_response", None, "1" * 64, "application/json"),
            ("raw_ccef", None, "4" * 64, "application/json"),
            ("normalized_ccef", None, normalized_sha, "application/json"),
        ):
            session.add(
                ExtractionArtifact(
                    run_id=run_id,
                    kind=kind,
                    page_number=page_number,
                    relative_path=f"derived/extraction/{digest[:2]}/{digest}.bin",
                    media_type=media_type,
                    byte_size=10,
                    content_sha256=digest,
                )
            )


async def test_http_post_creates_v4_distinct_from_existing_v2_and_replays_stable(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "v4-cutover")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        profile = {"engine": "ocr-v1"}
        v2_run = await _enqueue_direct(
            app,
            asset["id"],
            first_page=1,
            last_page=2,
            profile=profile,
            idempotency_key=None,
            pipeline_version=PDF_EXTRACTION_PIPELINE_VERSION,
        )
        created = (
            await client.post(
                "/api/pdf-extractions",
                json={
                    "pdf_asset_id": asset["id"],
                    "first_page": 1,
                    "last_page": 2,
                    "profile": profile,
                },
            )
        )[1]
        assert created.status == 202
        assert created.headers["idempotency-replayed"] == "false"
        v3_run = UUID(created.json["extraction"]["id"])
        assert v3_run != v2_run
        assert (
            created.json["extraction"]["pipeline_version"]
            == PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION
        )
        # The POST binds the exact deterministic v7 fingerprint identity.
        assert v3_run == expected_run_id(
            asset["content_sha256"],
            first_page=1,
            last_page=2,
            profile=profile,
            pipeline_version=PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
        )
        # Replay of the v4 identity stays stable and never returns the v2 run.
        replay = (
            await client.post(
                "/api/pdf-extractions",
                json={
                    "pdf_asset_id": asset["id"],
                    "first_page": 1,
                    "last_page": 2,
                    "profile": profile,
                },
            )
        )[1]
        assert replay.status == 200
        assert UUID(replay.json["extraction"]["id"]) == v3_run
        assert await count_rows(app, ExtractionRun) == 2
    finally:
        await app.ctx.database.close()


async def test_explicit_key_bound_to_v2_is_not_rebound_to_v4(tmp_path: Path) -> None:
    app = build_app(tmp_path, "key-v2-v3")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        await _enqueue_direct(
            app,
            asset["id"],
            first_page=1,
            last_page=2,
            profile=None,
            idempotency_key="fixed-key",
            pipeline_version=PDF_EXTRACTION_PIPELINE_VERSION,
        )
        response = (
            await client.post(
                "/api/pdf-extractions",
                json={"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 2},
                headers={"Idempotency-Key": "fixed-key"},
            )
        )[1]
        assert response.status == 409
        assert response.json["code"] == "idempotency_conflict"
        assert (
            response.json["message"]
            == "Idempotency-Key is already bound to a different PDF extraction"
        )
        assert await count_rows(app, ExtractionRun) == 1
        assert await count_rows(app, Job) == 1
    finally:
        await app.ctx.database.close()


async def test_committed_v2_and_v3_runs_expose_identical_summary_shapes(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "read-compat")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        v2_run = await _enqueue_direct(
            app,
            asset["id"],
            first_page=1,
            last_page=2,
            profile=None,
            idempotency_key=None,
            pipeline_version=PDF_EXTRACTION_PIPELINE_VERSION,
        )
        v3_run = UUID(
            (
                await client.post(
                    "/api/pdf-extractions",
                    json={"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 2},
                )
            )[1].json["extraction"]["id"]
        )
        await _commit_completed_run(app, v2_run)
        await _commit_completed_run(app, v3_run)

        _, v2_get = await client.get(f"/api/pdf-extractions/{v2_run}")
        _, v3_get = await client.get(f"/api/pdf-extractions/{v3_run}")
        assert v2_get.status == v3_get.status == 200
        expected_evidence = {
            "status": "committed",
            "page_count": 2,
            "fragment_count": 37,
            "warning_count": 1,
            "render_manifest_sha256": "a" * 64,
            "ocr_manifest_sha256": "b" * 64,
        }
        expected_candidate = {
            "status": "committed",
            "provider_response_sha256": "1" * 64,
            "request_sha256": "2" * 64,
            "response_sha256": "3" * 64,
            "raw_ccef_sha256": "4" * 64,
            "normalized_ccef_sha256": "5" * 64,
            "item_count": 9,
            "move_node_count": 12,
            "figure_count": 0,
            "unresolved_item_count": 1,
            "warning_count": 2,
            "error_count": 0,
            "invalid_move_count": 1,
            "ambiguous_move_count": 0,
            "has_conflicts": True,
        }
        assert v2_get.json["evidence"] == expected_evidence
        assert v3_get.json["evidence"] == expected_evidence
        assert v2_get.json["candidate"] == expected_candidate
        assert v3_get.json["candidate"] == expected_candidate
        assert v2_get.json["has_conflicts"] is True
        assert v3_get.json["has_conflicts"] is True
        assert "relative_path" not in v2_get.text
        assert "derived/extraction" not in v3_get.text

        _, listing = await client.get("/api/pdf-extractions")
        listed = {item["id"]: item for item in listing.json["items"]}
        assert listed[str(v2_run)]["evidence"] == expected_evidence
        assert listed[str(v3_run)]["evidence"] == expected_evidence
        assert listed[str(v2_run)]["candidate"] == expected_candidate
        assert listed[str(v3_run)]["candidate"] == expected_candidate
        _, conflicted = await client.get("/api/pdf-extractions?has_conflicts=true")
        assert {item["id"] for item in conflicted.json["items"]} == {str(v2_run), str(v3_run)}
        _, clean = await client.get("/api/pdf-extractions?has_conflicts=false")
        assert clean.json["items"] == []
    finally:
        await app.ctx.database.close()


async def test_forged_v1_or_unsupported_pipeline_envelopes_are_not_exposed(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "forged")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        run_id = UUID(
            (
                await client.post(
                    "/api/pdf-extractions",
                    json={"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 2},
                )
            )[1].json["extraction"]["id"]
        )
        for forged in ("pdf-extraction:v1", "pdf-extraction:v9"):
            async with app.ctx.database.session() as session, session.begin():
                run = await session.get(ExtractionRun, run_id)
                assert run is not None
                run.pipeline_version = forged
                job = await session.get(Job, run.job_id)
                assert job is not None
                job.status = "succeeded"
                job.attempt_count = 1
                job.result = {
                    "result_schema": "chess-workbench/pdf-extraction-result/2.0",
                    "run_id": str(run_id),
                    "evidence": {
                        "render_manifest_sha256": "a" * 64,
                        "ocr_manifest_sha256": "b" * 64,
                        "page_count": 2,
                        "fragment_count": 37,
                        "warning_count": 1,
                    },
                    "candidate": {
                        "provider_response_sha256": "1" * 64,
                        "request_sha256": "2" * 64,
                        "response_sha256": "3" * 64,
                        "raw_ccef_sha256": "4" * 64,
                        "normalized_ccef_sha256": "5" * 64,
                        "summary": {
                            "item_count": 9,
                            "move_node_count": 12,
                            "figure_count": 0,
                            "unresolved_item_count": 1,
                            "warning_count": 2,
                            "error_count": 0,
                            "invalid_move_count": 1,
                            "ambiguous_move_count": 0,
                            "has_conflicts": True,
                        },
                    },
                }
            _, got = await client.get(f"/api/pdf-extractions/{run_id}")
            assert got.status == 200
            assert got.json["evidence"] is None
            assert got.json["candidate"] is None
            assert got.json["has_conflicts"] is False
    finally:
        await app.ctx.database.close()


async def test_malformed_v2_run_fails_closed(tmp_path: Path) -> None:
    app = build_app(tmp_path, "malformed-v2")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        v2_run = await _enqueue_direct(
            app,
            asset["id"],
            first_page=1,
            last_page=2,
            profile=None,
            idempotency_key=None,
            pipeline_version=PDF_EXTRACTION_PIPELINE_VERSION,
        )
        await _commit_completed_run(app, v2_run)
        async with app.ctx.database.session() as session, session.begin():
            artifact = await session.scalar(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == v2_run,
                    ExtractionArtifact.kind == "rendered_page",
                    ExtractionArtifact.page_number == 1,
                )
            )
            assert artifact is not None
            await session.delete(artifact)
        _, got = await client.get(f"/api/pdf-extractions/{v2_run}")
        assert got.status == 200
        assert got.json["job"]["status"] == "succeeded"
        assert got.json["evidence"] is None
        assert got.json["candidate"] is None
        assert got.json["has_conflicts"] is False
    finally:
        await app.ctx.database.close()


# ── engine worker registered-kind invariant ──────────────────────────────────


async def test_engine_worker_with_default_handlers_leaves_pdf_job_queued(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "worker")
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        asset = (await upload_pdf(client, make_pdf(3))).json["asset"]
        enqueued = (
            await client.post(
                "/api/pdf-extractions",
                json={"pdf_asset_id": asset["id"], "first_page": 1, "last_page": 2},
            )
        )[1]
        assert enqueued.status == 202
        run_id = enqueued.json["extraction"]["id"]

        worker = SqlWorker(app.ctx.database, app.ctx.settings, worker_id="engine-only")
        assert await worker.run_once() is False

        async with app.ctx.database.session() as session:
            job = (await session.scalars(select(Job))).one()
            run = (await session.scalars(select(ExtractionRun))).one()
        assert job.kind == "pdf_extraction"
        assert job.status == "queued"
        assert job.attempt_count == 0
        assert job.last_error_code is None
        assert job.last_error_message is None
        assert run.id == UUID(run_id)
    finally:
        await app.ctx.database.close()


# ── transport and validation rejection ───────────────────────────────────────


async def test_transport_rejections_use_stable_errors_and_create_no_rows(
    tmp_path: Path,
) -> None:
    app = build_app(tmp_path, "rejections", pdf_max_bytes=512)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    try:
        pdf = make_pdf()
        storage_root = app.ctx.settings.source_storage_root

        async def expect(response: Any, status: int, code: str) -> dict[str, Any]:
            assert response.status == status, response.text
            body: dict[str, Any] = response.json
            assert body["code"] == code, response.text
            # Invalid input must not expose bytes, absolute paths or parser text.
            assert str(storage_root) not in response.text, response.text
            return body

        # Non-multipart media is rejected before multipart parsing.
        _, raw = await client.post(
            "/api/pdf-assets", content=pdf, headers={"content-type": "application/pdf"}
        )
        body = await expect(raw, 415, "unsupported_media_type")
        assert body["message"] == "Content-Type must be multipart/form-data"

        # Multipart without a file part.
        only_metadata, metadata_ct = multipart_only_metadata()
        _, missing = await client.post(
            "/api/pdf-assets", content=only_metadata, headers={"content-type": metadata_ct}
        )
        body = await expect(missing, 422, "validation_error")
        assert body["message"] == "multipart body must contain exactly one file part"

        # Duplicate file parts.
        _, duplicate = await client.post(
            "/api/pdf-assets",
            files=[
                ("file", ("a.pdf", pdf, "application/pdf")),
                ("file", ("b.pdf", pdf, "application/pdf")),
            ],
        )
        body = await expect(duplicate, 422, "validation_error")
        assert body["message"] == "multipart body must contain exactly one file part"

        # Unknown form part.
        _, unknown = await client.post(
            "/api/pdf-assets",
            files={"file": ("a.pdf", pdf, "application/pdf")},
            data={"extra": "not allowed"},
        )
        body = await expect(unknown, 422, "validation_error")
        assert body["message"] == "multipart body contains an unknown part"

        # Duplicate metadata parts.
        dup_meta, dup_meta_ct = multipart_file_with_duplicate_metadata(pdf)
        _, duplicate_metadata = await client.post(
            "/api/pdf-assets", content=dup_meta, headers={"content-type": dup_meta_ct}
        )
        body = await expect(duplicate_metadata, 422, "validation_error")
        assert body["message"] == "multipart body has duplicate metadata parts"

        # Metadata that is not strict JSON.
        _, bad_json = await client.post(
            "/api/pdf-assets",
            files={"file": ("a.pdf", pdf, "application/pdf")},
            data={"metadata": "not-json"},
        )
        body = await expect(bad_json, 422, "validation_error")
        assert body["message"] == "multipart metadata failed validation"

        # Unknown metadata fields are forbidden.
        _, unknown_meta = await client.post(
            "/api/pdf-assets",
            files={"file": ("a.pdf", pdf, "application/pdf")},
            data={"metadata": json.dumps({"unknown": 1})},
        )
        body = await expect(unknown_meta, 422, "validation_error")
        assert body["message"] == "multipart metadata failed validation"
        assert body["details"]["errors"][0]["loc"] == ["unknown"]

        # Fake PDF bytes fail inspection with the sanitized reason.
        fake = b"not a pdf"
        _, fake_pdf = await client.post(
            "/api/pdf-assets", files={"file": ("fake.pdf", fake, "application/pdf")}
        )
        body = await expect(fake_pdf, 422, "validation_error")
        assert body["message"] == "PDF upload is invalid"
        assert body["details"] == {"reason": "invalid_pdf"}
        assert "not a pdf" not in fake_pdf.text

        # Declared non-PDF MIME is rejected even for valid PDF bytes.
        _, bad_mime = await client.post(
            "/api/pdf-assets", files={"file": ("book.pdf", pdf, "text/plain")}
        )
        body = await expect(bad_mime, 415, "unsupported_media_type")
        assert body["message"] == "PDF media type is not supported"

        # A payload over the configured pdf_max_bytes is a 413 with no row.
        oversize = b"x" * 2048
        _, too_large = await client.post(
            "/api/pdf-assets", files={"file": ("big.pdf", oversize, "application/pdf")}
        )
        body = await expect(too_large, 413, "payload_too_large")
        assert body["message"] == "PDF payload exceeds the configured limit"
        assert body["details"] == {"limit_bytes": 512}
        assert "xxxx" not in too_large.text

        # Every rejection created no authoritative SQL rows and no CAS blob.
        for model in (*ASSET_TABLES, Job, ExtractionRun, InvalidationEvent):
            assert await count_rows(app, model) == 0
        assert [path for path in storage_root.rglob("*") if path.is_file()] == []
    finally:
        await app.ctx.database.close()


# ── request-size cap rule ────────────────────────────────────────────────────


async def test_request_size_cap_tracks_pdf_max_bytes_without_reducing_default(
    tmp_path: Path,
) -> None:
    from sanic import Sanic

    pristine_default = int(
        Sanic("pristine-cap-probe", configure_logging=False).config.REQUEST_MAX_SIZE
    )
    small = build_app(tmp_path, "cap-small", pdf_max_bytes=512)
    large = build_app(tmp_path, "cap-large", pdf_max_bytes=200 * 1024 * 1024)
    try:
        # Down-configuring pdf_max_bytes must not reduce Sanic's larger default cap.
        assert pristine_default == small.config.REQUEST_MAX_SIZE
        assert small.ctx.settings.pdf_max_bytes + 1024 * 1024 <= small.config.REQUEST_MAX_SIZE
        # Above the default the cap tracks pdf_max_bytes + 1 MiB exactly.
        assert large.config.REQUEST_MAX_SIZE == 200 * 1024 * 1024 + 1024 * 1024
        assert large.ctx.settings.pdf_max_bytes + 1024 * 1024 <= large.config.REQUEST_MAX_SIZE
    finally:
        await small.ctx.database.close()
        await large.ctx.database.close()
