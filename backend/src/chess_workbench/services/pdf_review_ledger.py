"""Transactional persistence boundary for the Stage 8D review ledger."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackage, ExtractionPackageV1_1
from chess_workbench.review.editing import apply_review_edit
from chess_workbench.review.inspection import inspect_review_candidate
from chess_workbench.schemas.review import (
    PdfReviewAcknowledgeCommand,
    PdfReviewApproveCommand,
    PdfReviewCommandEnvelope,
    PdfReviewCommandRequest,
    PdfReviewDocumentRead,
    PdfReviewEditCommand,
    PdfReviewEventRead,
    PdfReviewRejectCommand,
    PdfReviewReopenCommand,
    PdfReviewRevisionRead,
    PdfReviewSessionRead,
)
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pdf_review import PdfReviewReadService
from chess_workbench.services.source_storage import (
    read_verified_content_addressed_bytes,
    store_content_addressed_bytes,
)
from chess_workbench.store.models import (
    ExtractionArtifact,
    ExtractionRun,
    PdfExtractionDocument,
    PdfExtractionDocumentRevision,
    PdfReviewEvent,
    PdfReviewRevision,
    PdfReviewSession,
    utc_now,
)

_SESSION_MISSING = "PDF review session was not found"
_SESSION_UNAVAILABLE = "PDF review session is not available"
_MAX_REVIEW_PACKAGE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PdfReviewSessionCreation:
    session: PdfReviewSessionRead
    replayed: bool


@dataclass(frozen=True, slots=True)
class _Baseline:
    target_kind: Literal["extraction_run", "document"]
    target_id: UUID
    artifact_id: UUID | None
    document_revision_id: UUID | None
    relative_path: str
    media_type: str
    byte_size: int
    package_sha256: str


class PdfReviewLedgerService:
    """Create, read and append commands to hash-bound review sessions."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def open_session(self, target_id: UUID) -> PdfReviewSessionCreation:
        if type(target_id) is not UUID:
            raise TypeError("target_id must be UUID")

        document = await PdfReviewReadService(self.session, self.settings).read_document(target_id)
        package_bytes = _canonical_package_bytes(document.package.model_dump(mode="json"))
        if hashlib.sha256(package_bytes).hexdigest() != document.normalized_ccef_sha256:
            raise _unavailable() from None
        baseline = await self._baseline(target_id, document.normalized_ccef_sha256)
        existing = await self._session_for_baseline(baseline)
        if existing is not None:
            return PdfReviewSessionCreation(
                session=await self._read(existing),
                replayed=True,
            )

        session_id = uuid5(
            NAMESPACE_URL,
            "chess-workbench:pdf-review-session:"
            f"{baseline.target_kind}:{target_id}:{baseline.package_sha256}",
        )
        revision_id = uuid5(NAMESPACE_URL, f"chess-workbench:pdf-review-revision:{session_id}:1")
        event_id = uuid5(NAMESPACE_URL, f"chess-workbench:pdf-review-event:{session_id}:1")
        session = PdfReviewSession(
            id=session_id,
            extraction_run_id=(target_id if baseline.target_kind == "extraction_run" else None),
            document_id=(target_id if baseline.target_kind == "document" else None),
            baseline_artifact_id=baseline.artifact_id,
            baseline_document_revision_id=baseline.document_revision_id,
            baseline_ccef_sha256=baseline.package_sha256,
            status="open",
        )
        revision = PdfReviewRevision(
            id=revision_id,
            session_id=session_id,
            parent_revision_id=None,
            revision_number=1,
            relative_path=baseline.relative_path,
            media_type=baseline.media_type,
            byte_size=baseline.byte_size,
            package_sha256=baseline.package_sha256,
        )
        event = PdfReviewEvent(
            id=event_id,
            session_id=session_id,
            revision_id=revision_id,
            parent_version=0,
            resulting_version=1,
            kind="created",
            decisions={
                "baseline_normalized_ccef_sha256": baseline.package_sha256,
                "target_kind": baseline.target_kind,
            },
        )
        # These ledger rows intentionally do not expose ORM relationships.  Flush each
        # foreign-key layer explicitly so SQLAlchemy cannot insert the event before its
        # new session/revision when database FK enforcement is enabled.
        self.session.add_all((session,))
        await self.session.flush()
        self.session.add_all((revision,))
        await self.session.flush()
        self.session.add_all((event,))
        await self.session.flush()
        return PdfReviewSessionCreation(session=await self._read(session), replayed=False)

    async def get_session(self, session_id: UUID) -> PdfReviewSessionRead:
        if type(session_id) is not UUID:
            raise TypeError("session_id must be UUID")
        session = await self.session.get(PdfReviewSession, session_id)
        if session is None:
            raise ServiceError("not_found", 404, _SESSION_MISSING)
        return await self._read(session)

    async def get_target_document(self, target_id: UUID) -> PdfReviewDocumentRead:
        """Return the current review revision, or the verified baseline before editing."""
        if type(target_id) is not UUID:
            raise TypeError("target_id must be UUID")
        baseline_document = await PdfReviewReadService(self.session, self.settings).read_document(
            target_id
        )
        baseline = await self._baseline(target_id, baseline_document.normalized_ccef_sha256)
        review_session = await self._session_for_baseline(baseline)
        if review_session is None:
            return baseline_document
        return await self._document(review_session, baseline_document)

    async def get_session_document(self, session_id: UUID) -> PdfReviewDocumentRead:
        if type(session_id) is not UUID:
            raise TypeError("session_id must be UUID")
        review_session = await self.session.get(PdfReviewSession, session_id)
        if review_session is None:
            raise ServiceError("not_found", 404, _SESSION_MISSING)
        target_id = self._target(review_session)[1]
        baseline_document = await PdfReviewReadService(self.session, self.settings).read_document(
            target_id
        )
        if baseline_document.normalized_ccef_sha256 != review_session.baseline_ccef_sha256:
            raise _unavailable() from None
        return await self._document(review_session, baseline_document)

    async def get_current_package(
        self, session_id: UUID
    ) -> ExtractionPackage | ExtractionPackageV1_1:
        """Load the current immutable revision without advancing a document baseline."""
        if type(session_id) is not UUID:
            raise TypeError("session_id must be UUID")
        review_session = await self.session.get(PdfReviewSession, session_id)
        if review_session is None:
            raise ServiceError("not_found", 404, _SESSION_MISSING)
        return await self._revision_package(await self._revision(review_session))

    async def apply_command(
        self, session_id: UUID, request: PdfReviewCommandRequest
    ) -> PdfReviewCommandEnvelope:
        """Append exactly one expected-version command and immutable revision/event."""
        if type(session_id) is not UUID:
            raise TypeError("session_id must be UUID")
        review_session = cast(
            PdfReviewSession | None,
            await self.session.scalar(
                select(PdfReviewSession).where(PdfReviewSession.id == session_id).with_for_update()
            ),
        )
        if review_session is None:
            raise ServiceError("not_found", 404, _SESSION_MISSING)
        if review_session.version != request.expected_version:
            raise ServiceError(
                "stale_version",
                409,
                "expected version does not match the current PDF review session",
                {
                    "resource": "pdf_review_session",
                    "id": str(session_id),
                    "expected": request.expected_version,
                    "actual": review_session.version,
                },
            )

        current_revision = await self._revision(review_session)
        package = await self._revision_package(current_revision)
        inspection = inspect_review_candidate(package)
        command = request.command
        status = review_session.status
        next_status = status
        decisions: dict[str, JsonValue]
        stored_path = current_revision.relative_path
        stored_media_type = current_revision.media_type
        stored_size = current_revision.byte_size
        stored_sha256 = current_revision.package_sha256

        if isinstance(command, PdfReviewEditCommand):
            if status != "open":
                raise _command_conflict("only an open review session can be edited")
            try:
                edited = apply_review_edit(package, command.operation)
                package = edited.package
                inspection = inspect_review_candidate(package)
            except (TypeError, ValueError, ValidationError) as exc:
                raise ServiceError(
                    "validation_error", 422, "review edit could not be applied"
                ) from exc
            package_bytes = _canonical_package_bytes(package.model_dump(mode="json"))
            stored = await asyncio.to_thread(
                store_content_addressed_bytes,
                self.settings.source_storage_root,
                namespace="review-revisions",
                suffix=".json",
                raw_bytes=package_bytes,
            )
            stored_path = stored.relative_path
            stored_media_type = "application/json"
            stored_size = stored.size_bytes
            stored_sha256 = stored.sha256
            decisions = edited.decisions
            event_kind = "edited"
        elif isinstance(command, PdfReviewAcknowledgeCommand):
            if status != "open":
                raise _command_conflict("only an open review session can acknowledge issues")
            known = {issue.issue_id for issue in inspection.issues if not issue.blocking}
            if not set(command.issue_ids).issubset(known):
                raise ServiceError(
                    "validation_error",
                    422,
                    "only current non-blocking review issues can be acknowledged",
                )
            decisions = {"issue_ids": list(command.issue_ids)}
            event_kind = "acknowledged"
        elif isinstance(command, PdfReviewApproveCommand):
            if status != "open":
                raise _command_conflict("only an open review session can be approved")
            if inspection.blocking_issue_count:
                raise _command_conflict("blocking review issues must be resolved before approval")
            acknowledged = await self._acknowledged_issue_ids(review_session.id)
            required = {issue.issue_id for issue in inspection.issues if not issue.blocking}
            if not required.issubset(acknowledged):
                raise _command_conflict("all current review warnings must be acknowledged")
            next_status = "approved"
            decisions = {"issue_count": inspection.issue_count}
            event_kind = "approved"
        elif isinstance(command, PdfReviewRejectCommand):
            if status != "open":
                raise _command_conflict("only an open review session can be rejected")
            next_status = "rejected"
            decisions = {"reason": command.reason}
            event_kind = "rejected"
        elif isinstance(command, PdfReviewReopenCommand):
            if status == "open":
                raise _command_conflict("review session is already open")
            next_status = "open"
            decisions = {"reason": command.reason}
            event_kind = "reopened"
        else:  # pragma: no cover - discriminated request contract is exhaustive.
            raise TypeError("unsupported PDF review command")

        next_version = review_session.version + 1
        revision_id = uuid5(
            NAMESPACE_URL,
            f"chess-workbench:pdf-review-revision:{review_session.id}:{next_version}",
        )
        event_id = uuid5(
            NAMESPACE_URL,
            f"chess-workbench:pdf-review-event:{review_session.id}:{next_version}",
        )
        revision = PdfReviewRevision(
            id=revision_id,
            session_id=review_session.id,
            parent_revision_id=current_revision.id,
            revision_number=next_version,
            relative_path=stored_path,
            media_type=stored_media_type,
            byte_size=stored_size,
            package_sha256=stored_sha256,
        )
        event = PdfReviewEvent(
            id=event_id,
            session_id=review_session.id,
            revision_id=revision_id,
            parent_version=review_session.version,
            resulting_version=next_version,
            kind=event_kind,
            decisions=decisions,
        )
        review_session.version = next_version
        review_session.status = next_status
        review_session.updated_at = utc_now()
        # The event references the new immutable revision.  Without an ORM
        # relationship SQLAlchemy is free to order these INSERTs incorrectly.
        self.session.add_all((revision,))
        await self.session.flush()
        self.session.add_all((event,))
        await self.session.flush()

        target_id = self._target(review_session)[1]
        baseline_document = await PdfReviewReadService(self.session, self.settings).read_document(
            target_id
        )
        document = PdfReviewDocumentRead(
            run_id=target_id,
            normalized_ccef_sha256=stored_sha256,
            package=package,
            inspection=inspection,
            pages=baseline_document.pages,
        )
        return PdfReviewCommandEnvelope(
            session=await self._read(review_session),
            document=document,
        )

    async def _baseline(self, target_id: UUID, package_sha256: str) -> _Baseline:
        run = await self.session.get(ExtractionRun, target_id)
        document = await self.session.get(PdfExtractionDocument, target_id)
        if run is not None and document is not None:
            raise _unavailable() from None
        if document is not None:
            revision = await self.session.scalar(
                select(PdfExtractionDocumentRevision).where(
                    PdfExtractionDocumentRevision.document_id == document.id,
                    PdfExtractionDocumentRevision.revision_number == document.version,
                )
            )
            if revision is None or revision.normalized_ccef_sha256 != package_sha256:
                raise _unavailable() from None
            return _Baseline(
                target_kind="document",
                target_id=target_id,
                artifact_id=None,
                document_revision_id=revision.id,
                relative_path=revision.relative_path,
                media_type=revision.media_type,
                byte_size=revision.byte_size,
                package_sha256=package_sha256,
            )
        if run is not None:
            artifacts = tuple(
                await self.session.scalars(
                    select(ExtractionArtifact).where(
                        ExtractionArtifact.run_id == run.id,
                        ExtractionArtifact.kind == "normalized_ccef",
                        ExtractionArtifact.page_number.is_(None),
                    )
                )
            )
            if len(artifacts) != 1 or artifacts[0].content_sha256 != package_sha256:
                raise _unavailable() from None
            artifact = artifacts[0]
            return _Baseline(
                target_kind="extraction_run",
                target_id=target_id,
                artifact_id=artifact.id,
                document_revision_id=None,
                relative_path=artifact.relative_path,
                media_type=artifact.media_type,
                byte_size=artifact.byte_size,
                package_sha256=package_sha256,
            )
        raise _unavailable() from None

    async def _session_for_baseline(self, baseline: _Baseline) -> PdfReviewSession | None:
        target_column = (
            PdfReviewSession.extraction_run_id
            if baseline.target_kind == "extraction_run"
            else PdfReviewSession.document_id
        )
        return cast(
            PdfReviewSession | None,
            await self.session.scalar(
                select(PdfReviewSession).where(
                    target_column == baseline.target_id,
                    PdfReviewSession.baseline_ccef_sha256 == baseline.package_sha256,
                )
            ),
        )

    async def _read(self, session: PdfReviewSession) -> PdfReviewSessionRead:
        revisions = tuple(
            await self.session.scalars(
                select(PdfReviewRevision)
                .where(PdfReviewRevision.session_id == session.id)
                .order_by(PdfReviewRevision.revision_number)
            )
        )
        events = tuple(
            await self.session.scalars(
                select(PdfReviewEvent)
                .where(PdfReviewEvent.session_id == session.id)
                .order_by(PdfReviewEvent.resulting_version)
            )
        )
        if (session.extraction_run_id is None) == (session.document_id is None):
            raise _unavailable() from None
        target_kind: Literal["extraction_run", "document"]
        target_id: UUID
        if session.extraction_run_id is not None:
            target_kind = "extraction_run"
            target_id = session.extraction_run_id
        else:
            assert session.document_id is not None
            target_kind = "document"
            target_id = session.document_id
        try:
            return PdfReviewSessionRead(
                id=session.id,
                target_kind=target_kind,
                target_id=target_id,
                baseline_normalized_ccef_sha256=session.baseline_ccef_sha256,
                status=cast(Literal["open", "approved", "rejected"], session.status),
                version=session.version,
                revisions=[
                    PdfReviewRevisionRead(
                        id=revision.id,
                        parent_revision_id=revision.parent_revision_id,
                        revision_number=revision.revision_number,
                        package_sha256=revision.package_sha256,
                        created_at=revision.created_at,
                    )
                    for revision in revisions
                ],
                events=[
                    PdfReviewEventRead(
                        id=event.id,
                        revision_id=event.revision_id,
                        parent_version=event.parent_version,
                        resulting_version=event.resulting_version,
                        kind=cast(
                            Literal[
                                "created",
                                "edited",
                                "acknowledged",
                                "approved",
                                "rejected",
                                "reopened",
                            ],
                            event.kind,
                        ),
                        decisions=cast(dict[str, JsonValue], event.decisions),
                        created_at=event.created_at,
                    )
                    for event in events
                ],
                created_at=session.created_at,
                updated_at=session.updated_at,
            )
        except (ValidationError, ValueError):
            raise _unavailable() from None

    def _target(
        self, session: PdfReviewSession
    ) -> tuple[Literal["extraction_run", "document"], UUID]:
        if (session.extraction_run_id is None) == (session.document_id is None):
            raise _unavailable() from None
        if session.extraction_run_id is not None:
            return "extraction_run", session.extraction_run_id
        assert session.document_id is not None
        return "document", session.document_id

    async def _revision(self, session: PdfReviewSession) -> PdfReviewRevision:
        revision = cast(
            PdfReviewRevision | None,
            await self.session.scalar(
                select(PdfReviewRevision).where(
                    PdfReviewRevision.session_id == session.id,
                    PdfReviewRevision.revision_number == session.version,
                )
            ),
        )
        if revision is None:
            raise _unavailable() from None
        return revision

    async def _revision_package(
        self, revision: PdfReviewRevision
    ) -> ExtractionPackage | ExtractionPackageV1_1:
        try:
            raw_bytes = await asyncio.to_thread(
                read_verified_content_addressed_bytes,
                self.settings.source_storage_root,
                relative_path=revision.relative_path,
                expected_sha256=revision.package_sha256,
                expected_size=revision.byte_size,
                max_bytes=_MAX_REVIEW_PACKAGE_BYTES,
            )
            raw = json.loads(raw_bytes)
            if not isinstance(raw, dict):
                raise ValueError
            if raw.get("schema_version") == "chess-content-extraction/1.1":
                package: ExtractionPackage | ExtractionPackageV1_1 = (
                    ExtractionPackageV1_1.model_validate(raw)
                )
            elif raw.get("schema_version") == "chess-content-extraction/1.0":
                package = ExtractionPackage.model_validate(raw)
            else:
                raise ValueError
            if _canonical_package_bytes(package.model_dump(mode="json")) != raw_bytes:
                raise ValueError
            return package
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError):
            raise _unavailable() from None

    async def _document(
        self,
        session: PdfReviewSession,
        baseline_document: PdfReviewDocumentRead,
    ) -> PdfReviewDocumentRead:
        revision = await self._revision(session)
        package = await self._revision_package(revision)
        try:
            return PdfReviewDocumentRead(
                run_id=baseline_document.run_id,
                normalized_ccef_sha256=revision.package_sha256,
                package=package,
                inspection=inspect_review_candidate(package),
                pages=baseline_document.pages,
            )
        except (ValidationError, ValueError):
            raise _unavailable() from None

    async def _acknowledged_issue_ids(self, session_id: UUID) -> set[str]:
        events = tuple(
            await self.session.scalars(
                select(PdfReviewEvent)
                .where(PdfReviewEvent.session_id == session_id)
                .order_by(PdfReviewEvent.resulting_version)
            )
        )
        acknowledged: set[str] = set()
        for event in events:
            if event.kind == "edited":
                acknowledged.clear()
            elif event.kind == "acknowledged":
                issue_ids = event.decisions.get("issue_ids")
                if isinstance(issue_ids, list):
                    acknowledged.update(item for item in issue_ids if isinstance(item, str))
        return acknowledged


def _canonical_package_bytes(document: dict[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError):
        raise _unavailable() from None


def _unavailable() -> ServiceError:
    return ServiceError("ambiguous_context", 409, _SESSION_UNAVAILABLE)


def _command_conflict(message: str) -> ServiceError:
    return ServiceError("ambiguous_context", 409, message)


__all__ = ["PdfReviewLedgerService", "PdfReviewSessionCreation"]
