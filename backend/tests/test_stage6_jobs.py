from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from chess_workbench.config import Settings
from chess_workbench.domain.jobs import (
    InvalidJobTransition,
    JobEvent,
    JobStatus,
    failure_decision,
    transition_job,
)
from chess_workbench.services.jobs import JobService
from chess_workbench.services.uci import EngineError
from chess_workbench.services.worker import SqlWorker
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import Job, utc_now
from chess_workbench.store.models.engine import InvalidationEvent
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import select


@given(st.sampled_from(JobStatus), st.sampled_from(JobEvent))
def test_job_state_machine_never_invents_a_state(status: JobStatus, event: JobEvent) -> None:
    try:
        result = transition_job(status, event)
    except InvalidJobTransition:
        return
    assert result in JobStatus
    if status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
        assert event is JobEvent.CANCEL
        assert result is status


def test_failure_decision_rejects_preclaim_attempt_counts() -> None:
    with pytest.raises(ValueError, match="attempt counts must be positive"):
        failure_decision(attempt_count=0, max_attempts=3)
    with pytest.raises(ValueError, match="attempt counts must be positive"):
        failure_decision(attempt_count=1, max_attempts=0)


async def _database(tmp_path: Path) -> Database:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return database


async def test_two_workers_claim_one_job_once(tmp_path: Path) -> None:
    database = await _database(tmp_path)
    try:
        async with database.session() as session, session.begin():
            queued = await JobService(session).enqueue(
                kind="test", payload={"value": 1}, idempotency_key="once"
            )
            job_id = queued.id

        async with database.session() as first, first.begin():
            claimed = await JobService(first).claim(worker_id="worker-a", allowed_kinds={"test"})
            assert claimed is not None and claimed.id == job_id
        async with database.session() as second, second.begin():
            assert (
                await JobService(second).claim(worker_id="worker-b", allowed_kinds={"test"}) is None
            )

        async with database.session() as session:
            row = await session.get(Job, job_id)
            assert row is not None
            assert row.attempt_count == 1
            assert row.lease_owner == "worker-a"
    finally:
        await database.close()


async def test_expired_lease_recovers_then_preserves_final_error(tmp_path: Path) -> None:
    database = await _database(tmp_path)
    try:
        async with database.session() as session, session.begin():
            row = await JobService(session).enqueue(
                kind="test", payload={}, idempotency_key="recover", max_attempts=2
            )
            job_id = row.id
        async with database.session() as session, session.begin():
            first_claim = await JobService(session).claim(worker_id="dead", allowed_kinds={"test"})
            assert first_claim is not None
            first_claim.lease_expires_at = utc_now() - timedelta(seconds=1)
        async with database.session() as session, session.begin():
            recovered = await JobService(session).claim(
                worker_id="replacement", allowed_kinds={"test"}
            )
            assert recovered is not None
            assert recovered.attempt_count == 2
            recovered.lease_expires_at = utc_now() - timedelta(seconds=1)
        async with database.session() as session, session.begin():
            assert (
                await JobService(session).claim(worker_id="third", allowed_kinds={"test"}) is None
            )
        async with database.session() as session:
            final = await session.get(Job, job_id)
            assert final is not None
            assert final.status == "failed"
            assert final.last_error_code == "lease_expired"
            assert final.last_error_message
    finally:
        await database.close()


async def test_claim_and_lease_recovery_are_isolated_by_registered_kind(
    tmp_path: Path,
) -> None:
    database = await _database(tmp_path)
    try:
        async with database.session() as session, session.begin():
            pdf_job = await JobService(session).enqueue(
                kind="pdf_extraction",
                payload={},
                idempotency_key="pdf",
            )
            engine_job = await JobService(session).enqueue(
                kind="engine_analysis",
                payload={},
                idempotency_key="engine",
            )
            pdf_job_id = pdf_job.id
            engine_job_id = engine_job.id

        async with database.session() as session, session.begin():
            with pytest.raises(ValueError, match="at least one"):
                await JobService(session).claim(
                    worker_id="invalid",
                    allowed_kinds=set(),
                )
            claimed_pdf = await JobService(session).claim(
                worker_id="pdf-worker",
                allowed_kinds={"pdf_extraction"},
            )
            assert claimed_pdf is not None and claimed_pdf.id == pdf_job_id
            claimed_pdf.lease_expires_at = utc_now() - timedelta(seconds=1)

        async with database.session() as session, session.begin():
            claimed_engine = await JobService(session).claim(
                worker_id="engine-worker",
                allowed_kinds={"engine_analysis"},
            )
            assert claimed_engine is not None and claimed_engine.id == engine_job_id

        async with database.session() as session:
            untouched_pdf = await session.get(Job, pdf_job_id)
            assert untouched_pdf is not None
            assert untouched_pdf.status == "running"
            assert untouched_pdf.attempt_count == 1
            assert untouched_pdf.lease_owner == "pdf-worker"
            assert untouched_pdf.last_error_code is None
    finally:
        await database.close()


async def test_cancellation_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    database = await _database(tmp_path)
    try:
        async with database.session() as session, session.begin():
            queued = await JobService(session).enqueue(
                kind="test", payload={}, idempotency_key="queued"
            )
            queued_id = queued.id
            running = await JobService(session).enqueue(
                kind="test", payload={}, idempotency_key="running"
            )
            running_id = running.id
        async with database.session() as session, session.begin():
            first = await JobService(session).cancel(queued_id)
            second = await JobService(session).cancel(queued_id)
            assert first is second
            assert second is not None and second.status == "cancelled"
        async with database.session() as session, session.begin():
            claimed = await JobService(session).claim(worker_id="worker", allowed_kinds={"test"})
            assert claimed is not None and claimed.id == running_id
        async with database.session() as session, session.begin():
            requested = await JobService(session).cancel(running_id)
            assert requested is not None and requested.status == "running"
        async with database.session() as session, session.begin():
            assert await JobService(session).finish_cancelled(running_id, worker_id="worker")
            completed = await JobService(session).cancel(running_id)
            assert completed is not None and completed.status == "cancelled"
    finally:
        await database.close()


async def test_idempotency_replays_only_identical_payload(tmp_path: Path) -> None:
    database = await _database(tmp_path)
    try:
        async with database.session() as session, session.begin():
            service = JobService(session)
            first = await service.enqueue(kind="test", payload={"a": 1}, idempotency_key="key")
            replay = await service.enqueue(kind="test", payload={"a": 1}, idempotency_key="key")
            assert replay.id == first.id
            with pytest.raises(ValueError, match="different payload"):
                await service.enqueue(kind="test", payload={"a": 2}, idempotency_key="key")
        async with database.session() as session:
            assert len(list(await session.scalars(select(Job)))) == 1
    finally:
        await database.close()


async def test_heartbeat_retry_success_and_terminal_cancel_are_owner_safe(
    tmp_path: Path,
) -> None:
    database = await _database(tmp_path)
    try:
        async with database.session() as session, session.begin():
            queued = await JobService(session).enqueue(
                kind="test", payload={}, idempotency_key="lifecycle", max_attempts=3
            )
            job_id = queued.id
        async with database.session() as session, session.begin():
            claimed = await JobService(session).claim(worker_id="owner", allowed_kinds={"test"})
            assert claimed is not None
            service = JobService(session)
            assert await service.heartbeat(job_id, worker_id="intruder") is False
            assert await service.heartbeat(job_id, worker_id="owner") is True
            assert await service.succeed(job_id, worker_id="intruder", result={}) is False
            assert await service.fail(
                job_id,
                worker_id="owner",
                code="temporary",
                message="try again",
                retry_delay_seconds=0,
            )
        async with database.session() as session, session.begin():
            claimed = await JobService(session).claim(worker_id="owner-2", allowed_kinds={"test"})
            assert claimed is not None and claimed.attempt_count == 2
            assert await JobService(session).succeed(
                job_id, worker_id="owner-2", result={"ok": True}
            )
        async with database.session() as session, session.begin():
            replay = await JobService(session).cancel(job_id)
            assert replay is not None
            assert replay.status == "succeeded"
            assert replay.result == {"ok": True}
    finally:
        await database.close()


async def test_non_retryable_failure_keeps_last_error(tmp_path: Path) -> None:
    database = await _database(tmp_path)
    try:
        async with database.session() as session, session.begin():
            row = await JobService(session).enqueue(
                kind="test", payload={}, idempotency_key="final", max_attempts=1
            )
            job_id = row.id
        async with database.session() as session, session.begin():
            claimed = await JobService(session).claim(worker_id="owner", allowed_kinds={"test"})
            assert claimed is not None
            assert await JobService(session).fail(
                job_id,
                worker_id="owner",
                code="permanent",
                message="final failure",
            )
        async with database.session() as session:
            final = await session.get(Job, job_id)
            assert final is not None
            assert final.status == "failed"
            assert final.last_error_code == "permanent"
            assert final.last_error_message == "final failure"
    finally:
        await database.close()


async def test_missing_and_cancel_requested_jobs_use_terminal_guard_paths(tmp_path: Path) -> None:
    database = await _database(tmp_path)
    missing_id = uuid4()
    try:
        async with database.session() as session, session.begin():
            service = JobService(session)
            assert await service.cancel(missing_id) is None
            assert not await service.fail(
                missing_id,
                worker_id="nobody",
                code="missing",
                message="missing",
            )
            queued = await service.enqueue(
                kind="test",
                payload={},
                idempotency_key="cancel-before-failure",
            )
            job_id = queued.id
        async with database.session() as session, session.begin():
            claimed = await JobService(session).claim(worker_id="owner", allowed_kinds={"test"})
            assert claimed is not None
            requested = await JobService(session).cancel(job_id)
            assert requested is not None and requested.cancel_requested_at is not None
            assert await JobService(session).fail(
                job_id,
                worker_id="owner",
                code="ignored",
                message="cancel wins",
            )
        async with database.session() as session:
            final = await session.get(Job, job_id)
            assert final is not None and final.status == "cancelled"
            assert final.last_error_code is None
    finally:
        await database.close()


async def test_worker_handles_empty_unknown_and_handler_failure_paths(tmp_path: Path) -> None:
    database = await _database(tmp_path)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}",
        engine_worker_enabled=False,
    )

    async def engine_failure(
        database: Database, settings: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        del database, settings, payload
        raise EngineError("test_engine_failure", "expected engine failure")

    async def unexpected_failure(
        database: Database, settings: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        del database, settings, payload
        raise RuntimeError("expected unexpected failure")

    class OneIdlePollWorker(SqlWorker):
        poll_count = 0

        async def run_once(self) -> bool:
            self.poll_count += 1
            if self.poll_count == 1:
                return False
            if self.poll_count == 2:
                return True
            raise asyncio.CancelledError

    try:
        empty_worker = SqlWorker(database, settings, worker_id="empty")
        assert not await empty_worker.run_once()

        async with database.session() as session, session.begin():
            jobs = [
                await JobService(session).enqueue(
                    kind=kind,
                    payload={},
                    idempotency_key=kind,
                    max_attempts=1,
                )
                for kind in ("unknown", "engine-failure", "unexpected-failure")
            ]
            job_ids = [job.id for job in jobs]

        worker = SqlWorker(
            database,
            settings,
            worker_id="errors",
            handlers={
                "engine-failure": engine_failure,
                "unexpected-failure": unexpected_failure,
            },
        )
        assert await worker.run_once()
        assert await worker.run_once()
        assert not await worker.run_once()

        async with database.session() as session:
            finished = [await session.get(Job, job_id) for job_id in job_ids]
        assert finished[0] is not None
        assert finished[0].status == "queued"
        assert finished[0].attempt_count == 0
        assert finished[0].last_error_code is None
        assert [job.last_error_code for job in finished[1:] if job is not None] == [
            "test_engine_failure",
            "worker_error",
        ]

        polling_worker = OneIdlePollWorker(database, settings, worker_id="polling")
        with pytest.raises(asyncio.CancelledError):
            await polling_worker.run_forever()
        assert polling_worker.poll_count == 3
    finally:
        await database.close()


async def test_running_cancel_interrupts_handler_and_reaches_terminal_state(
    tmp_path: Path,
) -> None:
    database = await _database(tmp_path)
    started = asyncio.Event()
    interrupted = asyncio.Event()

    async def blocking_handler(
        database: Any, settings: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        del database, settings, payload
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            interrupted.set()
        return {}

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}",
        engine_worker_enabled=False,
    )
    worker = SqlWorker(
        database,
        settings,
        worker_id="cancel-worker",
        handlers={"blocking": blocking_handler},
    )
    try:
        async with database.session() as session, session.begin():
            job = await JobService(session).enqueue(
                kind="blocking", payload={}, idempotency_key="cancel-running"
            )
            job_id = job.id
        worker_task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(started.wait(), timeout=1)
        async with database.session() as session, session.begin():
            requested = await JobService(session).cancel(job_id)
            assert requested is not None and requested.cancel_requested_at is not None
        assert await asyncio.wait_for(worker_task, timeout=2) is True
        assert interrupted.is_set()
        async with database.session() as session:
            final = await session.get(Job, job_id)
            assert final is not None and final.status == "cancelled"
    finally:
        await database.close()


async def test_worker_shutdown_leaves_job_recoverable(tmp_path: Path) -> None:
    database = await _database(tmp_path)
    started = asyncio.Event()
    interrupted = asyncio.Event()

    async def blocking_handler(
        database: Any, settings: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        del database, settings, payload
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            interrupted.set()
        return {}

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}",
        engine_worker_enabled=False,
    )
    worker = SqlWorker(
        database,
        settings,
        worker_id="shutdown-worker",
        handlers={"blocking": blocking_handler},
    )
    try:
        async with database.session() as session, session.begin():
            job = await JobService(session).enqueue(
                kind="blocking", payload={}, idempotency_key="shutdown-running"
            )
            job_id = job.id
        worker_task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(started.wait(), timeout=1)
        worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker_task
        assert interrupted.is_set()
        async with database.session() as session, session.begin():
            still_running = await session.get(Job, job_id)
            assert still_running is not None
            assert still_running.status == "running"
            assert still_running.cancel_requested_at is None
            still_running.lease_expires_at = utc_now() - timedelta(seconds=1)
        async with database.session() as session, session.begin():
            recovered = await JobService(session).claim(
                worker_id="replacement", allowed_kinds={"blocking"}
            )
            assert recovered is not None and recovered.id == job_id
            assert recovered.attempt_count == 2
    finally:
        await database.close()


async def test_handler_across_heartbeat_succeeds_without_sqlite_lock(tmp_path: Path) -> None:
    """Handler running longer than the 100ms heartbeat interval must still
    succeed on SQLite.  Verifies the short-transaction design does not
    hold a read transaction across the long external computation."""
    database = await _database(tmp_path)
    done = asyncio.Event()
    written_row_id: list[int] = [0]

    async def slow_handler(
        database: Database, settings: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        del settings, payload
        # Phase 1: real short read transaction → close immediately.
        async with database.session() as s, s.begin():
            _ = await s.scalar(select(Job.id).where(Job.id == job_id))

        # Phase 2: external work spanning at least one heartbeat interval.
        await asyncio.sleep(0.3)

        # Phase 3: short write transaction — must succeed despite
        # concurrent heartbeat writes from the worker polling loop.
        async with database.session() as s, s.begin():
            ev = InvalidationEvent(
                resource_type="analysis", resource_id="test-entity", reason="test"
            )
            s.add(ev)
            await s.flush()
            written_row_id[0] = ev.id

        done.set()
        return {"value": 42}

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}",
        engine_worker_enabled=False,
    )
    worker = SqlWorker(
        database,
        settings,
        worker_id="slow-worker",
        handlers={"slow": slow_handler},
    )
    try:
        async with database.session() as session, session.begin():
            job = await JobService(session).enqueue(
                kind="slow", payload={}, idempotency_key="slow-heartbeat"
            )
            job_id = job.id
        worker_task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(done.wait(), timeout=5)
        assert await asyncio.wait_for(worker_task, timeout=2) is True

        # Verify job outcome.
        async with database.session() as session:
            final = await session.get(Job, job_id)
            assert final is not None
            assert final.status == "succeeded", (
                f"expected succeeded, got {final.status} "
                f"({final.last_error_code}: {final.last_error_message})"
            )
            assert final.attempt_count == 1
            assert final.result == {"value": 42}
            assert final.last_error_code is None
            assert final.last_error_message is None

        # Verify the InvalidationEvent row was actually persisted.
        async with database.session() as session:
            row = await session.get(InvalidationEvent, written_row_id[0])
            assert row is not None
            assert row.resource_type == "analysis"
            assert row.resource_id == "test-entity"
    finally:
        await database.close()
