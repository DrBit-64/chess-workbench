"""Focused outcome tests for the Stage 8D review ledger."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.config import Settings
from chess_workbench.schemas.domain import NormalizedBoundingBox, PageSpan
from chess_workbench.services.content import ContentService
from chess_workbench.services.pdf_review import PdfReviewReadService
from chess_workbench.services.pdf_review_ledger import PdfReviewLedgerService
from chess_workbench.store.base import Base
from chess_workbench.store.models import (
    ExtractionArtifact,
    ExtractionRun,
    PdfExtractionDocument,
    PdfReviewEvent,
    PdfReviewRevision,
    PdfReviewSession,
    SourceSpan,
    utc_now,
)


class _SyntheticPackage:
    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {"candidate": "synthetic-review-package"}


class _FakeSession:
    def __init__(self, run: ExtractionRun, artifact: ExtractionArtifact) -> None:
        self.run = run
        self.artifact = artifact
        self.sessions: list[PdfReviewSession] = []
        self.revisions: list[PdfReviewRevision] = []
        self.events: list[PdfReviewEvent] = []

    async def get(self, model: type[object], identity: object) -> object | None:
        if model is ExtractionRun and identity == self.run.id:
            return self.run
        if model is PdfExtractionDocument:
            return None
        if model is PdfReviewSession:
            return next((row for row in self.sessions if row.id == identity), None)
        return None

    async def scalar(self, statement: Any) -> object | None:
        entity = statement.column_descriptions[0]["entity"]
        if entity is PdfReviewSession:
            return self.sessions[0] if self.sessions else None
        return None

    async def scalars(self, statement: Any) -> list[object]:
        entity = statement.column_descriptions[0]["entity"]
        if entity is ExtractionArtifact:
            return [self.artifact]
        if entity is PdfReviewRevision:
            return list(self.revisions)
        if entity is PdfReviewEvent:
            return list(self.events)
        return []

    def add_all(self, rows: tuple[object, ...]) -> None:
        now = utc_now()
        for row in rows:
            if isinstance(row, PdfReviewSession):
                row.version = 1
                row.created_at = now
                row.updated_at = now
                self.sessions.append(row)
            elif isinstance(row, PdfReviewRevision):
                row.created_at = now
                self.revisions.append(row)
            elif isinstance(row, PdfReviewEvent):
                row.created_at = now
                self.events.append(row)

    async def flush(self) -> None:
        return None


def test_review_ledger_migration_matches_runtime_metadata() -> None:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    revisions = reversed(
        list(ScriptDirectory.from_config(config).walk_revisions(base="base", head="heads"))
    )
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                for revision in revisions:
                    revision.module.upgrade()
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_page_evidence_round_trips_fragment_hash_bbox_and_offsets() -> None:
    locator = PageSpan(
        page_number=12,
        bbox=NormalizedBoundingBox(x0=0.1, y0=0.2, x1=0.8, y1=0.9),
        start_offset=20,
        end_offset=44,
        fragment_sha256="b" * 64,
    )
    now = datetime.now(UTC)
    row = SourceSpan(
        id=uuid4(),
        source_version_id=uuid4(),
        source_file_id=uuid4(),
        **ContentService._locator_columns(locator),
        created_at=now,
        updated_at=now,
        version=1,
    )
    read = ContentService._source_span_read(row)
    assert read.locator == locator


async def test_open_session_persists_one_hash_bound_revision_and_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        source_storage_root=tmp_path / "storage",
        engine_worker_enabled=False,
    )
    package = _SyntheticPackage()
    package_bytes = (
        json.dumps(
            package.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    digest = hashlib.sha256(package_bytes).hexdigest()
    run_id = uuid4()
    run = ExtractionRun(
        id=run_id,
        pdf_asset_id=uuid4(),
        job_id=uuid4(),
        first_page=1,
        last_page=1,
        pipeline_version="pdf-extraction:v4",
        logical_fingerprint="4" * 64,
        effective_key_hash="5" * 64,
    )
    artifact = ExtractionArtifact(
        id=uuid4(),
        run_id=run.id,
        kind="normalized_ccef",
        page_number=None,
        relative_path=f"extractions/{digest[:2]}/{digest}.json",
        media_type="application/json",
        byte_size=len(package_bytes),
        content_sha256=digest,
        created_at=datetime.now(UTC),
    )
    fake_session = _FakeSession(run, artifact)

    async def _read_document(self: PdfReviewReadService, requested_id: object) -> object:
        del self
        assert requested_id == run_id
        return SimpleNamespace(package=package, normalized_ccef_sha256=digest)

    monkeypatch.setattr(PdfReviewReadService, "read_document", _read_document)
    service = PdfReviewLedgerService(cast(AsyncSession, fake_session), settings)
    created = await service.open_session(run_id)
    replayed = await service.open_session(run_id)
    assert created.replayed is False
    assert replayed.replayed is True
    assert replayed.session == created.session
    assert created.session.target_kind == "extraction_run"
    assert created.session.target_id == run_id
    assert created.session.baseline_normalized_ccef_sha256 == digest
    assert created.session.version == 1
    assert created.session.revisions[0].package_sha256 == digest
    assert created.session.events[0].kind == "created"
    assert created.session.events[0].parent_version == 0
    assert created.session.events[0].resulting_version == 1

    persisted = await service.get_session(created.session.id)
    assert persisted == created.session
    assert len(fake_session.sessions) == 1
    assert len(fake_session.revisions) == 1
    assert len(fake_session.events) == 1
