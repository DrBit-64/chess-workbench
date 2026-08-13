"""Transactional ownership for immutable PDF assets and extraction receipts."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.schemas.domain import SourceCreate, SourceFileCreate, SourceVersionCreate
from chess_workbench.services.content import ContentService, ServiceError
from chess_workbench.services.jobs import JobService
from chess_workbench.services.pdf import PreparedPdfAsset
from chess_workbench.store.models import (
    ExtractionArtifact,
    ExtractionRun,
    Job,
    PdfAsset,
    Source,
    SourceFile,
    SourceVersion,
)

PDF_EXTRACTION_JOB_KIND = "pdf_extraction"
PDF_EVIDENCE_PIPELINE_VERSION = "pdf-extraction:v1"
PDF_EXTRACTION_PIPELINE_VERSION = "pdf-extraction:v2"
PDF_EXTRACTION_FINGERPRINT_VERSION = "pdfium-text-lines+ccef-formal-consolidation:v5"
_SUPPORTED_PIPELINE_VERSIONS = frozenset(
    {PDF_EVIDENCE_PIPELINE_VERSION, PDF_EXTRACTION_PIPELINE_VERSION}
)


@dataclass(frozen=True, slots=True)
class PdfAssetRegistration:
    """Result of registering or replaying one content-addressed PDF."""

    asset: PdfAsset
    replayed: bool


@dataclass(frozen=True, slots=True)
class PdfExtractionEnqueue:
    """Atomic extraction-run and durable-job outcome."""

    run: ExtractionRun
    job: Job
    replayed: bool


@dataclass(frozen=True, slots=True)
class PdfAssetView:
    """Joined public metadata for one immutable PDF asset."""

    asset: PdfAsset
    source: Source
    source_version: SourceVersion
    source_file: SourceFile


@dataclass(frozen=True, slots=True)
class PdfExtractionView:
    """One immutable extraction receipt paired with its sole job state."""

    run: ExtractionRun
    job: Job
    profile: dict[str, JsonValue]
    artifacts: tuple[ExtractionArtifact, ...]


class PdfPersistenceService:
    """Create immutable PDF ownership records inside a caller-owned transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        fault_injector: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        self.session = session
        self.content = ContentService(session)
        self.jobs = JobService(session)
        self._fault_injector = fault_injector

    async def register_asset(self, prepared: PreparedPdfAsset) -> PdfAssetRegistration:
        """Create exactly one Source chain and PdfAsset for a content hash."""

        if not isinstance(prepared, PreparedPdfAsset):
            raise TypeError("prepared must be PreparedPdfAsset")
        existing = await self.session.scalar(
            select(PdfAsset).where(PdfAsset.content_sha256 == prepared.content_sha256)
        )
        if existing is not None:
            return PdfAssetRegistration(asset=existing, replayed=True)

        try:
            async with self.session.begin_nested():
                source = await self.content.create_source(
                    SourceCreate(kind="book", title=prepared.title, author=prepared.author)
                )
                self._fault("source", {"source_id": source.id})
                version = await self.content.create_source_version(
                    SourceVersionCreate(
                        source_id=source.id,
                        label=prepared.content_sha256,
                        edition=prepared.edition,
                    )
                )
                self._fault("source_version", {"source_version_id": version.id})
                source_file = await self.content.create_source_file(
                    SourceFileCreate(
                        source_version_id=version.id,
                        filename=prepared.filename,
                        relative_path=prepared.relative_path,
                        media_type="application/pdf",
                        size_bytes=prepared.size_bytes,
                        sha256=prepared.content_sha256,
                    )
                )
                self._fault("source_file", {"source_file_id": source_file.id})
                asset = PdfAsset(
                    content_sha256=prepared.content_sha256,
                    byte_size=prepared.size_bytes,
                    page_count=prepared.page_count,
                    source_id=source.id,
                    source_version_id=version.id,
                    source_file_id=source_file.id,
                )
                self.session.add(asset)
                await self.session.flush()
                self._fault("pdf_asset", {"pdf_asset_id": asset.id})
        except IntegrityError:
            collision = await self.session.scalar(
                select(PdfAsset).where(PdfAsset.content_sha256 == prepared.content_sha256)
            )
            if collision is None:
                raise
            return PdfAssetRegistration(asset=collision, replayed=True)
        except ServiceError as error:
            # ContentService deliberately maps repository uniqueness failures to
            # ambiguous_context. A concurrent identical upload can collide first
            # on SourceFile.relative_path, before its PdfAsset insert is visible.
            if error.code != "ambiguous_context":
                raise
            collision = await self.session.scalar(
                select(PdfAsset).where(PdfAsset.content_sha256 == prepared.content_sha256)
            )
            if collision is None:
                raise
            return PdfAssetRegistration(asset=collision, replayed=True)
        return PdfAssetRegistration(asset=asset, replayed=False)

    async def get_asset(self, asset_id: UUID) -> PdfAssetView | None:
        if not isinstance(asset_id, UUID):
            raise TypeError("asset_id must be UUID")
        statement = (
            select(PdfAsset, Source, SourceVersion, SourceFile)
            .join(Source, Source.id == PdfAsset.source_id)
            .join(
                SourceVersion,
                (SourceVersion.id == PdfAsset.source_version_id)
                & (SourceVersion.source_id == Source.id),
            )
            .join(
                SourceFile,
                (SourceFile.id == PdfAsset.source_file_id)
                & (SourceFile.source_version_id == SourceVersion.id),
            )
            .where(PdfAsset.id == asset_id)
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        return PdfAssetView(
            asset=row[0],
            source=row[1],
            source_version=row[2],
            source_file=row[3],
        )

    async def list_assets(self) -> list[PdfAssetView]:
        statement = (
            select(PdfAsset, Source, SourceVersion, SourceFile)
            .join(Source, Source.id == PdfAsset.source_id)
            .join(
                SourceVersion,
                (SourceVersion.id == PdfAsset.source_version_id)
                & (SourceVersion.source_id == Source.id),
            )
            .join(
                SourceFile,
                (SourceFile.id == PdfAsset.source_file_id)
                & (SourceFile.source_version_id == SourceVersion.id),
            )
            .order_by(PdfAsset.created_at.desc(), PdfAsset.id)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            PdfAssetView(
                asset=row[0],
                source=row[1],
                source_version=row[2],
                source_file=row[3],
            )
            for row in rows
        ]

    async def enqueue_extraction(
        self,
        *,
        pdf_asset_id: UUID,
        first_page: int,
        last_page: int,
        idempotency_key: str | None,
        profile: dict[str, JsonValue] | None = None,
        pipeline_version: str = PDF_EXTRACTION_PIPELINE_VERSION,
    ) -> PdfExtractionEnqueue:
        """Atomically create or replay one immutable run and its durable Job."""

        if not isinstance(pdf_asset_id, UUID):
            raise TypeError("pdf_asset_id must be UUID")
        if isinstance(first_page, bool) or not isinstance(first_page, int):
            raise TypeError("first_page must be int")
        if isinstance(last_page, bool) or not isinstance(last_page, int):
            raise TypeError("last_page must be int")
        if pipeline_version not in _SUPPORTED_PIPELINE_VERSIONS:
            raise ValueError("unsupported PDF extraction pipeline version")
        canonical_profile, profile_json = _validated_profile(profile)
        effective_key_from_header = _effective_idempotency_key(idempotency_key)

        asset = await self.session.get(PdfAsset, pdf_asset_id)
        if asset is None:
            raise ServiceError(
                "not_found",
                404,
                "PDF asset was not found",
                {"resource": "pdf_asset", "id": str(pdf_asset_id)},
            )
        if first_page < 1 or last_page < first_page or last_page > asset.page_count:
            raise ServiceError(
                "validation_error",
                422,
                "PDF page range is invalid",
                {
                    "first_page": first_page,
                    "last_page": last_page,
                    "page_count": asset.page_count,
                },
            )

        logical_fingerprint = _logical_fingerprint(
            asset.content_sha256,
            first_page=first_page,
            last_page=last_page,
            profile_json=profile_json,
            pipeline_version=pipeline_version,
        )
        effective_key_hash = effective_key_from_header or logical_fingerprint
        existing = await self._run_by_effective_key(effective_key_hash)
        if existing is not None:
            return await self._replay(existing, logical_fingerprint)

        run_id = uuid5(
            NAMESPACE_URL,
            f"chess-workbench:{PDF_EXTRACTION_JOB_KIND}:{effective_key_hash}",
        )
        payload: dict[str, object] = {
            "schema_version": 1,
            "run_id": str(run_id),
            "pdf_asset_id": str(asset.id),
            "first_page": first_page,
            "last_page": last_page,
            "pipeline_version": pipeline_version,
            "profile": canonical_profile,
        }
        try:
            job = await self.jobs.enqueue(
                kind=PDF_EXTRACTION_JOB_KIND,
                payload=payload,
                idempotency_key=effective_key_hash,
            )
        except ValueError:
            raise ServiceError(
                "idempotency_conflict",
                409,
                "Idempotency-Key is already bound to a different PDF extraction",
            ) from None
        self._fault("job", {"job_id": job.id})

        collision = await self.session.scalar(
            select(ExtractionRun).where(ExtractionRun.job_id == job.id)
        )
        if collision is not None:
            return await self._replay(collision, logical_fingerprint)

        run = ExtractionRun(
            id=run_id,
            pdf_asset_id=asset.id,
            job_id=job.id,
            first_page=first_page,
            last_page=last_page,
            pipeline_version=pipeline_version,
            logical_fingerprint=logical_fingerprint,
            effective_key_hash=effective_key_hash,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(run)
                await self.session.flush()
        except IntegrityError:
            existing = await self._run_by_effective_key(effective_key_hash)
            if existing is None:
                raise
            return await self._replay(existing, logical_fingerprint)
        self._fault("extraction_run", {"run_id": run.id})
        return PdfExtractionEnqueue(run=run, job=job, replayed=False)

    async def get_extraction(self, run_id: UUID) -> PdfExtractionView | None:
        if not isinstance(run_id, UUID):
            raise TypeError("run_id must be UUID")
        row = (
            await self.session.execute(
                select(ExtractionRun, Job)
                .join(Job, Job.id == ExtractionRun.job_id)
                .where(ExtractionRun.id == run_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return await self._extraction_view(row[0], row[1])

    async def list_extractions(
        self,
        *,
        status: str | None = None,
        has_conflicts: bool | None = None,
    ) -> list[PdfExtractionView]:
        # Candidate conflict state is verified from the completed Job result plus
        # immutable artifact slots at the HTTP read boundary, not stored twice.
        del has_conflicts
        statement = select(ExtractionRun, Job).join(Job, Job.id == ExtractionRun.job_id)
        if status is not None:
            statement = statement.where(Job.status == status)
        statement = statement.order_by(ExtractionRun.created_at.desc(), ExtractionRun.id)
        rows = (await self.session.execute(statement)).all()
        return [await self._extraction_view(row[0], row[1]) for row in rows]

    async def _extraction_view(self, run: ExtractionRun, job: Job) -> PdfExtractionView:
        profile = _profile_snapshot(job)
        artifacts = tuple(
            await self.session.scalars(
                select(ExtractionArtifact)
                .where(ExtractionArtifact.run_id == run.id)
                .order_by(ExtractionArtifact.kind, ExtractionArtifact.page_number)
            )
        )
        return PdfExtractionView(run=run, job=job, profile=profile, artifacts=artifacts)

    async def _run_by_effective_key(self, key_hash: str) -> ExtractionRun | None:
        row: ExtractionRun | None = await self.session.scalar(
            select(ExtractionRun).where(ExtractionRun.effective_key_hash == key_hash)
        )
        return row

    async def _replay(
        self,
        run: ExtractionRun,
        logical_fingerprint: str,
    ) -> PdfExtractionEnqueue:
        if run.logical_fingerprint != logical_fingerprint:
            raise ServiceError(
                "idempotency_conflict",
                409,
                "Idempotency-Key is already bound to a different PDF extraction",
            )
        job = await self.session.get(Job, run.job_id)
        if job is None:
            raise RuntimeError("ExtractionRun references a missing Job")
        return PdfExtractionEnqueue(run=run, job=job, replayed=True)

    def _fault(self, phase: str, context: dict[str, object]) -> None:
        if self._fault_injector is not None:
            self._fault_injector(phase, context)


def _effective_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("idempotency_key must be str or None")
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        encoded = b""
    if not 1 <= len(encoded) <= 128 or any(byte < 0x21 or byte > 0x7E for byte in encoded):
        raise ServiceError(
            "validation_error",
            422,
            "Idempotency-Key must be 1..128 visible ASCII bytes",
        )
    return sha256(encoded).hexdigest()


def _profile_snapshot(job: Job) -> dict[str, JsonValue]:
    profile = job.payload.get("profile")
    if not isinstance(profile, dict):
        raise RuntimeError("pdf_extraction Job payload has no object profile")
    try:
        snapshot, _ = _validated_profile(cast(dict[str, JsonValue], profile))
    except (ServiceError, TypeError) as error:
        raise RuntimeError("pdf_extraction Job payload has an invalid profile") from error
    return snapshot


def _validated_profile(
    profile: dict[str, JsonValue] | None,
) -> tuple[dict[str, JsonValue], str]:
    candidate: object = {} if profile is None else profile
    if not isinstance(candidate, dict):
        raise TypeError("profile must be dict or None")
    if not _is_finite_json(candidate):
        raise ServiceError("validation_error", 422, "PDF extraction profile must be finite JSON")
    try:
        encoded = json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        snapshot = json.loads(encoded)
    except (TypeError, ValueError):
        raise ServiceError(
            "validation_error", 422, "PDF extraction profile must be finite JSON"
        ) from None
    return cast(dict[str, JsonValue], snapshot), encoded


def _is_finite_json(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_finite_json(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_finite_json(item) for key, item in value.items())
    return False


def _logical_fingerprint(
    asset_content_sha256: str,
    *,
    first_page: int,
    last_page: int,
    profile_json: str,
    pipeline_version: str = PDF_EXTRACTION_PIPELINE_VERSION,
) -> str:
    identity = {
        "asset_content_sha256": asset_content_sha256,
        "extraction_fingerprint_version": PDF_EXTRACTION_FINGERPRINT_VERSION,
        "first_page": first_page,
        "last_page": last_page,
        "pipeline_version": pipeline_version,
        "profile": json.loads(profile_json),
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
