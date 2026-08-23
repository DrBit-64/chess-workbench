#!/usr/bin/env python3
"""Commit one already-verified incremental CCEF JSON as a document revision.

This operator command performs no model call.  It adopts the accepted baseline,
registers the adjacent append receipt, stores the verified segment and page
images, composes the aggregate package, and advances the document head.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackageV1_1, PageRange
from chess_workbench.extraction.evidence import RenderProfile
from chess_workbench.extraction.incremental import (
    build_ccef_continuation_context,
    compose_incremental_ccef,
)
from chess_workbench.extraction.pdfium import PdfiumPageRenderer
from chess_workbench.services.jobs import JobService
from chess_workbench.services.pdf_documents import PdfDocumentService
from chess_workbench.services.source_storage import (
    StoredSourceBlob,
    read_verified_content_addressed_bytes,
    store_content_addressed_bytes,
)
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    ExtractionArtifact,
    ExtractionRun,
    Job,
    PdfAsset,
    SourceFile,
    utc_now,
)
from sqlalchemy import select

_DEFAULT_BASE_RUN = UUID("4b33f70a-b623-5ec3-bc8e-5ed6a2a28e4a")
_WORKER_ID = "operator-incremental-commit"


def _canonical_bytes(package: ExtractionPackageV1_1) -> bytes:
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


async def _read_baseline(
    database: Database,
    settings: Settings,
    run_id: UUID,
) -> tuple[ExtractionPackageV1_1, str, ExtractionRun, Job, PdfAsset, SourceFile]:
    async with database.session() as session:
        row = (
            await session.execute(
                select(ExtractionRun, Job, PdfAsset, SourceFile)
                .join(Job, Job.id == ExtractionRun.job_id)
                .join(PdfAsset, PdfAsset.id == ExtractionRun.pdf_asset_id)
                .join(SourceFile, SourceFile.id == PdfAsset.source_file_id)
                .where(ExtractionRun.id == run_id)
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("baseline extraction run was not found")
        run, job, asset, source_file = row
        artifact = await session.scalar(
            select(ExtractionArtifact).where(
                ExtractionArtifact.run_id == run.id,
                ExtractionArtifact.kind == "normalized_ccef",
                ExtractionArtifact.page_number.is_(None),
            )
        )
        if artifact is None:
            raise RuntimeError("baseline normalized CCEF artifact was not found")
    raw = await asyncio.to_thread(
        read_verified_content_addressed_bytes,
        settings.source_storage_root,
        relative_path=artifact.relative_path,
        expected_sha256=artifact.content_sha256,
        expected_size=artifact.byte_size,
        max_bytes=64 * 1024 * 1024,
    )
    package = ExtractionPackageV1_1.model_validate_json(raw)
    if _canonical_bytes(package) != raw:
        raise RuntimeError("baseline normalized CCEF is not canonical")
    return package, artifact.content_sha256, run, job, asset, source_file


async def _render_and_store(
    settings: Settings,
    *,
    source_file: SourceFile,
    profile: RenderProfile,
    first_page: int,
    last_page: int,
) -> dict[int, StoredSourceBlob]:
    pdf_bytes = await asyncio.to_thread(
        read_verified_content_addressed_bytes,
        settings.source_storage_root,
        relative_path=source_file.relative_path,
        expected_sha256=source_file.sha256,
        expected_size=source_file.size_bytes,
        max_bytes=settings.pdf_max_bytes,
    )
    renderer = PdfiumPageRenderer()
    pages: dict[int, StoredSourceBlob] = {}
    for physical_page in range(first_page, last_page + 1):
        rendered = await asyncio.to_thread(
            renderer.render_page, pdf_bytes, physical_page, profile
        )
        pages[physical_page] = await asyncio.to_thread(
            store_content_addressed_bytes,
            settings.source_storage_root,
            namespace="derived/extraction",
            suffix=".png",
            raw_bytes=rendered.png_bytes,
        )
    return pages


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()
    database = Database(settings.database_url)
    try:
        base, base_sha, base_run, base_job, _asset, source_file = await _read_baseline(
            database, settings, args.base_run
        )
        incremental = ExtractionPackageV1_1.model_validate_json(
            Path(args.incremental_json).read_bytes()
        )
        incremental_range = incremental.source.page_range
        if incremental_range is None:
            raise RuntimeError("incremental package has no page range")
        context = build_ccef_continuation_context(
            base,
            base_normalized_ccef_sha256=base_sha,
            next_page_range=PageRange(
                start_page=incremental_range.start_page,
                end_page=incremental_range.end_page,
            ),
        )

        async with database.session() as session, session.begin():
            service = PdfDocumentService(session, settings)
            adoption = await service.adopt_run(base_run.id)
            document_id = adoption.document.id
        aggregate = compose_incremental_ccef(
            base,
            incremental,
            context=context,
            document_id=document_id,
        )
        incremental_bytes = _canonical_bytes(incremental)
        incremental_blob = await asyncio.to_thread(
            store_content_addressed_bytes,
            settings.source_storage_root,
            namespace="derived/extraction",
            suffix=".json",
            raw_bytes=incremental_bytes,
        )

        async with database.session() as session, session.begin():
            service = PdfDocumentService(session, settings)
            registration = await service.register_append(
                document_id=document_id,
                expected_version=1,
                first_page=incremental_range.start_page,
                last_page=incremental_range.end_page,
                profile={"source": "verified-local-json"},
                idempotency_key=(
                    f"verified-incremental:{base_sha}:"
                    f"{incremental_range.start_page}-{incremental_range.end_page}"
                ),
            )
            append_run_id = registration.run.id

        render_value = (
            base_job.payload.get("profile", {}).get("render", {})
            if isinstance(base_job.payload, dict)
            and isinstance(base_job.payload.get("profile", {}), dict)
            else {}
        )
        profile = RenderProfile.model_validate(render_value)
        rendered_pages = await _render_and_store(
            settings,
            source_file=source_file,
            profile=profile,
            first_page=incremental_range.start_page,
            last_page=incremental_range.end_page,
        )

        async with database.session() as session, session.begin():
            service = PdfDocumentService(session, settings)
            job = await session.scalar(
                select(Job)
                .join(ExtractionRun, ExtractionRun.job_id == Job.id)
                .where(ExtractionRun.id == append_run_id)
                .with_for_update()
            )
            if job is None:
                raise RuntimeError("append Job was not found")
            if job.status == "succeeded":
                outcome = await service.commit_verified_append(
                    run_id=append_run_id,
                    segment_normalized_ccef_sha256=incremental_blob.sha256,
                    aggregate=aggregate,
                )
            else:
                if job.status != "queued":
                    raise RuntimeError(
                        f"append Job cannot be committed from {job.status}"
                    )
                now = utc_now()
                job.status = "running"
                job.lease_owner = _WORKER_ID
                job.lease_expires_at = now + timedelta(hours=1)
                job.heartbeat_at = now
                job.started_at = job.started_at or now
                job.attempt_count += 1

                candidates: dict[
                    tuple[str, int | None], tuple[StoredSourceBlob, str]
                ] = {
                    ("normalized_ccef", None): (
                        incremental_blob,
                        "application/json",
                    )
                }
                candidates.update(
                    {
                        ("rendered_page", page): (blob, "image/png")
                        for page, blob in rendered_pages.items()
                    }
                )
                existing = {
                    (artifact.kind, artifact.page_number): artifact
                    for artifact in await session.scalars(
                        select(ExtractionArtifact).where(
                            ExtractionArtifact.run_id == append_run_id
                        )
                    )
                }
                for (kind, page), (blob, media_type) in candidates.items():
                    artifact = existing.get((kind, page))
                    if artifact is not None:
                        if (
                            artifact.content_sha256 != blob.sha256
                            or artifact.byte_size != blob.size_bytes
                            or artifact.media_type != media_type
                        ):
                            raise RuntimeError(
                                "append artifact slot conflicts with stored bytes"
                            )
                        continue
                    session.add(
                        ExtractionArtifact(
                            run_id=append_run_id,
                            kind=kind,
                            page_number=page,
                            relative_path=blob.relative_path,
                            media_type=media_type,
                            byte_size=blob.size_bytes,
                            content_sha256=blob.sha256,
                        )
                    )
                await session.flush()
                outcome = await service.commit_verified_append(
                    run_id=append_run_id,
                    segment_normalized_ccef_sha256=incremental_blob.sha256,
                    aggregate=aggregate,
                )
                succeeded = await JobService(session).succeed(
                    job.id,
                    worker_id=_WORKER_ID,
                    result={
                        "document_id": str(outcome.document.id),
                        "revision_id": str(outcome.revision.id),
                        "revision_number": outcome.revision.revision_number,
                        "normalized_ccef_sha256": outcome.revision.normalized_ccef_sha256,
                    },
                )
                if not succeeded:
                    raise RuntimeError("append Job could not be marked succeeded")

        move_count = sum(
            len(item.nodes) for item in aggregate.items if item.kind == "move_sequence"
        )
        print(
            json.dumps(
                {
                    "document_id": str(outcome.document.id),
                    "append_run_id": str(append_run_id),
                    "version": outcome.document.version,
                    "page_range": [
                        outcome.document.first_page,
                        outcome.document.last_page,
                    ],
                    "segment_count": outcome.revision.segment_count,
                    "normalized_ccef_sha256": outcome.revision.normalized_ccef_sha256,
                    "item_count": len(aggregate.items),
                    "move_node_count": move_count,
                    "review_url": (
                        f"/sources/pdf-extractions/{outcome.document.id}/review"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-run", type=UUID, default=_DEFAULT_BASE_RUN)
    parser.add_argument(
        "--incremental-json",
        default="data/debug/stage8d-incremental-pages-324-328.normalized.json",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
