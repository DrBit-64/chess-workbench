"""Transactional identity boundary for incremental PDF extraction documents."""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from hashlib import sha256
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.services.content import ServiceError
from chess_workbench.services.jobs import JobService
from chess_workbench.services.pdf_persistence import (
    PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION,
)
from chess_workbench.services.pdf_review import PdfReviewReadService
from chess_workbench.services.source_storage import store_content_addressed_bytes
from chess_workbench.store.models import (
    ExtractionArtifact,
    ExtractionRun,
    Job,
    PdfAsset,
    PdfExtractionDocument,
    PdfExtractionDocumentAppend,
    PdfExtractionDocumentRevision,
    PdfExtractionDocumentSegment,
)

PDF_INCREMENTAL_EXTRACTION_JOB_KIND = "pdf_incremental_extraction"
PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION = "pdf-extraction:v5"
PDF_INCREMENTAL_EXTRACTION_FINGERPRINT_VERSION = "ccef-incremental-extraction:v1"
PDF_DOCUMENT_ADOPTION_ALGORITHM_VERSION = "ccef-document-adopt:v1"
PDF_DOCUMENT_COMPOSITION_ALGORITHM_VERSION = "ccef-document-compose:v1"
_ACTIVE_APPEND_STATUSES = frozenset({"queued", "running", "succeeded"})


@dataclass(frozen=True, slots=True)
class PdfDocumentAppendView:
    append: PdfExtractionDocumentAppend
    run: ExtractionRun
    job: Job


@dataclass(frozen=True, slots=True)
class PdfDocumentView:
    document: PdfExtractionDocument
    segments: tuple[PdfExtractionDocumentSegment, ...]
    revisions: tuple[PdfExtractionDocumentRevision, ...]
    append_attempts: tuple[PdfDocumentAppendView, ...]


@dataclass(frozen=True, slots=True)
class PdfDocumentAdoption:
    document: PdfExtractionDocument
    replayed: bool


@dataclass(frozen=True, slots=True)
class PdfDocumentAppendRegistration:
    append: PdfExtractionDocumentAppend
    run: ExtractionRun
    job: Job
    replayed: bool


@dataclass(frozen=True, slots=True)
class PdfDocumentAppendCommit:
    document: PdfExtractionDocument
    segment: PdfExtractionDocumentSegment
    revision: PdfExtractionDocumentRevision
    replayed: bool


class PdfDocumentService:
    """Own logical-document adoption and failure-safe append registration."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.jobs = JobService(session)

    async def adopt_run(self, run_id: UUID) -> PdfDocumentAdoption:
        """Adopt one verified CCEF 1.1 run as revision 1 without copying CAS bytes."""

        if type(run_id) is not UUID:
            raise TypeError("run_id must be UUID")
        existing_segment = await self.session.scalar(
            select(PdfExtractionDocumentSegment).where(
                PdfExtractionDocumentSegment.extraction_run_id == run_id
            )
        )
        if existing_segment is not None:
            document = await self.session.get(PdfExtractionDocument, existing_segment.document_id)
            if document is None:
                raise RuntimeError("PDF extraction document segment references a missing document")
            return PdfDocumentAdoption(document=document, replayed=True)

        row = (
            await self.session.execute(
                select(ExtractionRun, Job)
                .join(Job, Job.id == ExtractionRun.job_id)
                .where(ExtractionRun.id == run_id)
            )
        ).one_or_none()
        if row is None:
            raise ServiceError("not_found", 404, "PDF extraction run was not found")
        run, job = row
        if (
            run.pipeline_version != PDF_SEMANTIC_EXTRACTION_PIPELINE_VERSION
            or job.status != "succeeded"
        ):
            raise _incompatible_run()

        review = await PdfReviewReadService(self.session, self.settings).read_document(run_id)
        if review.package.schema_version != "chess-content-extraction/1.1":
            raise _incompatible_run()
        artifacts = tuple(
            await self.session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run.id,
                    ExtractionArtifact.kind == "normalized_ccef",
                    ExtractionArtifact.page_number.is_(None),
                )
            )
        )
        if len(artifacts) != 1:
            raise _incompatible_run()
        artifact = artifacts[0]
        if artifact.content_sha256 != review.normalized_ccef_sha256:
            raise _incompatible_run()

        document_id = uuid5(NAMESPACE_URL, f"chess-workbench:pdf-extraction-document:{run.id}")
        segment_id = uuid5(
            NAMESPACE_URL, f"chess-workbench:pdf-extraction-document-segment:{document_id}:1"
        )
        revision_id = uuid5(
            NAMESPACE_URL, f"chess-workbench:pdf-extraction-document-revision:{document_id}:1"
        )
        document = PdfExtractionDocument(
            id=document_id,
            pdf_asset_id=run.pdf_asset_id,
            first_page=run.first_page,
            last_page=run.last_page,
            normalized_ccef_sha256=artifact.content_sha256,
        )
        segment = PdfExtractionDocumentSegment(
            id=segment_id,
            document_id=document.id,
            extraction_run_id=run.id,
            ordinal=1,
            first_page=run.first_page,
            last_page=run.last_page,
            normalized_ccef_sha256=artifact.content_sha256,
        )
        revision = PdfExtractionDocumentRevision(
            id=revision_id,
            document_id=document.id,
            predecessor_revision_id=None,
            terminal_segment_id=segment.id,
            revision_number=1,
            segment_count=1,
            first_page=run.first_page,
            last_page=run.last_page,
            algorithm_version=PDF_DOCUMENT_ADOPTION_ALGORITHM_VERSION,
            relative_path=artifact.relative_path,
            media_type=artifact.media_type,
            byte_size=artifact.byte_size,
            normalized_ccef_sha256=artifact.content_sha256,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(document)
                await self.session.flush()
                self.session.add(segment)
                await self.session.flush()
                self.session.add(revision)
                await self.session.flush()
        except IntegrityError:
            collision = await self.session.scalar(
                select(PdfExtractionDocumentSegment).where(
                    PdfExtractionDocumentSegment.extraction_run_id == run.id
                )
            )
            if collision is None:
                raise
            existing_document = await self.session.get(PdfExtractionDocument, collision.document_id)
            if existing_document is None:
                raise RuntimeError(
                    "PDF extraction document segment references a missing document"
                ) from None
            return PdfDocumentAdoption(document=existing_document, replayed=True)
        return PdfDocumentAdoption(document=document, replayed=False)

    async def register_append(
        self,
        *,
        document_id: UUID,
        expected_version: int,
        first_page: int,
        last_page: int,
        profile: dict[str, JsonValue] | None,
        idempotency_key: str | None,
    ) -> PdfDocumentAppendRegistration:
        """Register one adjacent hash-bound attempt without advancing the document head."""

        if type(document_id) is not UUID:
            raise TypeError("document_id must be UUID")
        for name, value in (
            ("expected_version", expected_version),
            ("first_page", first_page),
            ("last_page", last_page),
        ):
            if type(value) is not int:
                raise TypeError(f"{name} must be int")
        canonical_profile, profile_json = _validated_profile(profile)
        explicit_key_hash = _idempotency_key_hash(idempotency_key)

        document = await self.session.scalar(
            select(PdfExtractionDocument)
            .where(PdfExtractionDocument.id == document_id)
            .with_for_update()
        )
        if document is None:
            raise ServiceError("not_found", 404, "PDF extraction document was not found")
        revision = await self.session.scalar(
            select(PdfExtractionDocumentRevision).where(
                PdfExtractionDocumentRevision.document_id == document.id,
                PdfExtractionDocumentRevision.revision_number == expected_version,
            )
        )
        if revision is None:
            raise _stale(document, expected_version)
        asset = await self.session.get(PdfAsset, document.pdf_asset_id)
        if asset is None:
            raise RuntimeError("PDF extraction document references a missing asset")
        if (
            first_page != revision.last_page + 1
            or last_page < first_page
            or last_page > asset.page_count
        ):
            raise ServiceError(
                "validation_error",
                422,
                "PDF document append page range must be adjacent and within the asset",
                {
                    "expected_first_page": revision.last_page + 1,
                    "first_page": first_page,
                    "last_page": last_page,
                    "page_count": asset.page_count,
                },
            )

        logical_fingerprint = _append_fingerprint(
            document=document,
            revision=revision,
            asset=asset,
            first_page=first_page,
            last_page=last_page,
            profile_json=profile_json,
        )
        effective_key_hash = explicit_key_hash or logical_fingerprint
        replay = await self._append_by_effective_key(effective_key_hash)
        if replay is not None:
            if replay.append.logical_fingerprint != logical_fingerprint:
                raise ServiceError(
                    "idempotency_conflict",
                    409,
                    "Idempotency-Key is already bound to a different PDF document append",
                )
            return PdfDocumentAppendRegistration(
                append=replay.append,
                run=replay.run,
                job=replay.job,
                replayed=True,
            )

        if document.version != expected_version:
            raise _stale(document, expected_version)
        active = await self.session.scalar(
            select(PdfExtractionDocumentAppend)
            .join(ExtractionRun, ExtractionRun.id == PdfExtractionDocumentAppend.extraction_run_id)
            .join(Job, Job.id == ExtractionRun.job_id)
            .where(
                PdfExtractionDocumentAppend.document_id == document.id,
                PdfExtractionDocumentAppend.expected_version == document.version,
                Job.status.in_(_ACTIVE_APPEND_STATUSES),
            )
            .limit(1)
        )
        if active is not None:
            raise ServiceError(
                "ambiguous_context",
                409,
                "PDF extraction document already has an active append",
                {"resource": "pdf_extraction_document", "id": str(document.id)},
            )

        run_id = uuid5(
            NAMESPACE_URL,
            f"chess-workbench:{PDF_INCREMENTAL_EXTRACTION_JOB_KIND}:{effective_key_hash}",
        )
        payload: dict[str, object] = {
            "schema_version": 1,
            "run_id": str(run_id),
            "document_id": str(document.id),
            "pdf_asset_id": str(document.pdf_asset_id),
            "first_page": first_page,
            "last_page": last_page,
            "pipeline_version": PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
            "profile": canonical_profile,
            "expected_document_version": expected_version,
            "predecessor_revision_id": str(revision.id),
            "predecessor_normalized_ccef_sha256": revision.normalized_ccef_sha256,
        }
        try:
            job = await self.jobs.enqueue(
                kind=PDF_INCREMENTAL_EXTRACTION_JOB_KIND,
                payload=payload,
                idempotency_key=effective_key_hash,
            )
        except ValueError:
            raise ServiceError(
                "idempotency_conflict",
                409,
                "Idempotency-Key is already bound to a different PDF document append",
            ) from None
        existing_run = await self.session.scalar(
            select(ExtractionRun).where(ExtractionRun.job_id == job.id)
        )
        if existing_run is not None:
            replay = await self._append_by_effective_key(effective_key_hash)
            if replay is None or replay.append.logical_fingerprint != logical_fingerprint:
                raise RuntimeError("incremental extraction Job has no matching append receipt")
            return PdfDocumentAppendRegistration(
                append=replay.append,
                run=replay.run,
                job=replay.job,
                replayed=True,
            )
        run = ExtractionRun(
            id=run_id,
            pdf_asset_id=document.pdf_asset_id,
            job_id=job.id,
            first_page=first_page,
            last_page=last_page,
            pipeline_version=PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
            logical_fingerprint=logical_fingerprint,
            effective_key_hash=effective_key_hash,
        )
        append = PdfExtractionDocumentAppend(
            document_id=document.id,
            predecessor_revision_id=revision.id,
            extraction_run_id=run.id,
            expected_version=expected_version,
            predecessor_normalized_ccef_sha256=revision.normalized_ccef_sha256,
            first_page=first_page,
            last_page=last_page,
            profile=cast(dict[str, object], canonical_profile),
            logical_fingerprint=logical_fingerprint,
            effective_key_hash=effective_key_hash,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(run)
                await self.session.flush()
                self.session.add(append)
                await self.session.flush()
        except IntegrityError:
            replay = await self._append_by_effective_key(effective_key_hash)
            if replay is None or replay.append.logical_fingerprint != logical_fingerprint:
                raise
            return PdfDocumentAppendRegistration(
                append=replay.append,
                run=replay.run,
                job=replay.job,
                replayed=True,
            )
        return PdfDocumentAppendRegistration(append=append, run=run, job=job, replayed=False)

    async def commit_verified_append(
        self,
        *,
        run_id: UUID,
        segment_normalized_ccef_sha256: str,
        aggregate: ExtractionPackageV1_1,
    ) -> PdfDocumentAppendCommit:
        """Advance one document head from an already verified append package.

        The append run keeps its own immutable normalized segment artifact.
        This method stores the composed aggregate as a revision blob and then
        advances the SQL head atomically; a retry replays the committed segment.
        """

        if type(run_id) is not UUID:
            raise TypeError("run_id must be UUID")
        if type(segment_normalized_ccef_sha256) is not str:
            raise TypeError("segment_normalized_ccef_sha256 must be str")
        if type(aggregate) is not ExtractionPackageV1_1:
            raise TypeError("aggregate must be ExtractionPackageV1_1")

        existing_segment = await self.session.scalar(
            select(PdfExtractionDocumentSegment).where(
                PdfExtractionDocumentSegment.extraction_run_id == run_id
            )
        )
        if existing_segment is not None:
            document = await self.session.get(PdfExtractionDocument, existing_segment.document_id)
            revision = await self.session.scalar(
                select(PdfExtractionDocumentRevision).where(
                    PdfExtractionDocumentRevision.terminal_segment_id == existing_segment.id
                )
            )
            if document is None or revision is None:
                raise RuntimeError("committed PDF document append is incomplete")
            return PdfDocumentAppendCommit(
                document=document,
                segment=existing_segment,
                revision=revision,
                replayed=True,
            )

        row = (
            await self.session.execute(
                select(PdfExtractionDocumentAppend, ExtractionRun, Job)
                .join(
                    ExtractionRun,
                    ExtractionRun.id == PdfExtractionDocumentAppend.extraction_run_id,
                )
                .join(Job, Job.id == ExtractionRun.job_id)
                .where(PdfExtractionDocumentAppend.extraction_run_id == run_id)
            )
        ).one_or_none()
        if row is None:
            raise ServiceError("not_found", 404, "PDF document append was not found")
        append, run, job = row
        if job.status not in {"running", "succeeded"}:
            raise ServiceError(
                "ambiguous_context", 409, "PDF document append is not ready to commit"
            )
        document = await self.session.scalar(
            select(PdfExtractionDocument)
            .where(PdfExtractionDocument.id == append.document_id)
            .with_for_update()
        )
        if document is None:
            raise RuntimeError("PDF document append references a missing document")
        if document.version != append.expected_version:
            raise _stale(document, append.expected_version)
        predecessor = await self.session.scalar(
            select(PdfExtractionDocumentRevision).where(
                PdfExtractionDocumentRevision.id == append.predecessor_revision_id,
                PdfExtractionDocumentRevision.document_id == document.id,
                PdfExtractionDocumentRevision.revision_number == document.version,
            )
        )
        if predecessor is None:
            raise RuntimeError("PDF document append predecessor is missing")
        if (
            append.predecessor_normalized_ccef_sha256 != predecessor.normalized_ccef_sha256
            or run.first_page != predecessor.last_page + 1
            or run.last_page != append.last_page
        ):
            raise ServiceError("ambiguous_context", 409, "PDF document append binding is invalid")
        segment_artifacts = tuple(
            await self.session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == run.id,
                    ExtractionArtifact.kind == "normalized_ccef",
                    ExtractionArtifact.page_number.is_(None),
                )
            )
        )
        if (
            len(segment_artifacts) != 1
            or segment_artifacts[0].content_sha256 != segment_normalized_ccef_sha256
        ):
            raise ServiceError(
                "ambiguous_context", 409, "PDF document append artifact is unavailable"
            )
        source_range = aggregate.source.page_range
        if (
            aggregate.package_id != document.id
            or source_range is None
            or source_range.start_page != document.first_page
            or source_range.end_page != run.last_page
        ):
            raise ServiceError("validation_error", 422, "composed PDF document range is invalid")

        aggregate_bytes = _canonical_ccef_bytes(aggregate)
        aggregate_blob = await asyncio.to_thread(
            store_content_addressed_bytes,
            self.settings.source_storage_root,
            namespace="derived/extraction",
            suffix=".json",
            raw_bytes=aggregate_bytes,
        )
        next_revision_number = document.version + 1
        segment = PdfExtractionDocumentSegment(
            id=uuid5(
                NAMESPACE_URL,
                f"chess-workbench:pdf-extraction-document-segment:{document.id}:"
                f"{next_revision_number}",
            ),
            document_id=document.id,
            extraction_run_id=run.id,
            ordinal=next_revision_number,
            first_page=run.first_page,
            last_page=run.last_page,
            normalized_ccef_sha256=segment_normalized_ccef_sha256,
        )
        revision = PdfExtractionDocumentRevision(
            id=uuid5(
                NAMESPACE_URL,
                f"chess-workbench:pdf-extraction-document-revision:{document.id}:"
                f"{next_revision_number}",
            ),
            document_id=document.id,
            predecessor_revision_id=predecessor.id,
            terminal_segment_id=segment.id,
            revision_number=next_revision_number,
            segment_count=next_revision_number,
            first_page=document.first_page,
            last_page=run.last_page,
            algorithm_version=PDF_DOCUMENT_COMPOSITION_ALGORITHM_VERSION,
            relative_path=aggregate_blob.relative_path,
            media_type="application/json",
            byte_size=aggregate_blob.size_bytes,
            normalized_ccef_sha256=aggregate_blob.sha256,
        )
        self.session.add(segment)
        await self.session.flush()
        self.session.add(revision)
        document.last_page = run.last_page
        document.normalized_ccef_sha256 = aggregate_blob.sha256
        await self.session.flush()
        if document.version != next_revision_number:
            raise RuntimeError("PDF document version did not advance with its revision")
        return PdfDocumentAppendCommit(
            document=document,
            segment=segment,
            revision=revision,
            replayed=False,
        )

    async def get_document(self, document_id: UUID) -> PdfDocumentView | None:
        if type(document_id) is not UUID:
            raise TypeError("document_id must be UUID")
        document = await self.session.get(PdfExtractionDocument, document_id)
        if document is None:
            return None
        return await self._document_view(document)

    async def list_documents(self) -> list[PdfDocumentView]:
        documents = tuple(
            await self.session.scalars(
                select(PdfExtractionDocument).order_by(
                    PdfExtractionDocument.updated_at.desc(), PdfExtractionDocument.id
                )
            )
        )
        return [await self._document_view(document) for document in documents]

    async def _document_view(self, document: PdfExtractionDocument) -> PdfDocumentView:
        segments = tuple(
            await self.session.scalars(
                select(PdfExtractionDocumentSegment)
                .where(PdfExtractionDocumentSegment.document_id == document.id)
                .order_by(PdfExtractionDocumentSegment.ordinal)
            )
        )
        revisions = tuple(
            await self.session.scalars(
                select(PdfExtractionDocumentRevision)
                .where(PdfExtractionDocumentRevision.document_id == document.id)
                .order_by(PdfExtractionDocumentRevision.revision_number)
            )
        )
        rows = (
            await self.session.execute(
                select(PdfExtractionDocumentAppend, ExtractionRun, Job)
                .join(
                    ExtractionRun,
                    ExtractionRun.id == PdfExtractionDocumentAppend.extraction_run_id,
                )
                .join(Job, Job.id == ExtractionRun.job_id)
                .where(PdfExtractionDocumentAppend.document_id == document.id)
                .order_by(PdfExtractionDocumentAppend.created_at, PdfExtractionDocumentAppend.id)
            )
        ).all()
        attempts = tuple(
            PdfDocumentAppendView(append=row[0], run=row[1], job=row[2]) for row in rows
        )
        return PdfDocumentView(
            document=document,
            segments=segments,
            revisions=revisions,
            append_attempts=attempts,
        )

    async def _append_by_effective_key(self, key_hash: str) -> PdfDocumentAppendView | None:
        row = (
            await self.session.execute(
                select(PdfExtractionDocumentAppend, ExtractionRun, Job)
                .join(
                    ExtractionRun,
                    ExtractionRun.id == PdfExtractionDocumentAppend.extraction_run_id,
                )
                .join(Job, Job.id == ExtractionRun.job_id)
                .where(PdfExtractionDocumentAppend.effective_key_hash == key_hash)
            )
        ).one_or_none()
        if row is None:
            return None
        return PdfDocumentAppendView(append=row[0], run=row[1], job=row[2])


def _incompatible_run() -> ServiceError:
    return ServiceError(
        "validation_error",
        409,
        "PDF extraction run is not compatible with incremental documents",
    )


def _stale(document: PdfExtractionDocument, expected_version: int) -> ServiceError:
    return ServiceError(
        "stale_version",
        409,
        "expected version does not match the current PDF extraction document",
        {
            "resource": "pdf_extraction_document",
            "id": str(document.id),
            "expected": expected_version,
            "actual": document.version,
        },
    )


def _idempotency_key_hash(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("idempotency_key must be str or None")
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        encoded = b""
    if not 1 <= len(encoded) <= 128 or any(byte < 0x21 or byte > 0x7E for byte in encoded):
        raise ServiceError(
            "validation_error", 422, "Idempotency-Key must be 1..128 visible ASCII bytes"
        )
    return sha256(encoded).hexdigest()


def _validated_profile(
    profile: dict[str, JsonValue] | None,
) -> tuple[dict[str, JsonValue], str]:
    candidate: object = {} if profile is None else profile
    if type(candidate) is not dict or not _is_finite_json(candidate):
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
    if type(value) is dict:
        return all(
            type(key) is str and _is_finite_json(item)
            for key, item in cast(dict[object, object], value).items()
        )
    return False


def _canonical_ccef_bytes(package: ExtractionPackageV1_1) -> bytes:
    return (
        json.dumps(
            package.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _append_fingerprint(
    *,
    document: PdfExtractionDocument,
    revision: PdfExtractionDocumentRevision,
    asset: PdfAsset,
    first_page: int,
    last_page: int,
    profile_json: str,
) -> str:
    identity = {
        "asset_content_sha256": asset.content_sha256,
        "document_id": str(document.id),
        "expected_document_version": revision.revision_number,
        "extraction_fingerprint_version": PDF_INCREMENTAL_EXTRACTION_FINGERPRINT_VERSION,
        "first_page": first_page,
        "last_page": last_page,
        "pipeline_version": PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION,
        "predecessor_normalized_ccef_sha256": revision.normalized_ccef_sha256,
        "predecessor_revision_id": str(revision.id),
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


__all__ = [
    "PDF_DOCUMENT_ADOPTION_ALGORITHM_VERSION",
    "PDF_INCREMENTAL_EXTRACTION_FINGERPRINT_VERSION",
    "PDF_INCREMENTAL_EXTRACTION_JOB_KIND",
    "PDF_INCREMENTAL_EXTRACTION_PIPELINE_VERSION",
    "PdfDocumentAdoption",
    "PdfDocumentAppendRegistration",
    "PdfDocumentAppendView",
    "PdfDocumentService",
    "PdfDocumentView",
]
