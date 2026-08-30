from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.domain.jobs import JobStatus, failure_decision
from chess_workbench.schemas.jobs import JobRead
from chess_workbench.store.models import InvalidationEvent, Job, utc_now


def stable_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _clear_lease() -> dict[str, None]:
    return {"lease_owner": None, "lease_expires_at": None, "heartbeat_at": None}


def _affected_rows(result: Any) -> int:
    return int(result.rowcount)


def _validated_allowed_kinds(allowed_kinds: Collection[str]) -> tuple[str, ...]:
    if isinstance(allowed_kinds, (str, bytes)):
        raise TypeError("allowed_kinds must be a collection of job kind strings")
    supplied_kinds = tuple(allowed_kinds)
    if not supplied_kinds:
        raise ValueError("allowed_kinds must contain at least one job kind")
    if any(not isinstance(kind, str) for kind in supplied_kinds):
        raise TypeError("allowed_kinds must contain only strings")
    kinds = tuple(dict.fromkeys(supplied_kinds))
    if any(not kind or len(kind) > 64 for kind in kinds):
        raise ValueError("job kinds must contain between 1 and 64 characters")
    return kinds


def job_read(row: Job) -> JobRead:
    """Serialize the generic durable job without coupling callers to engine code."""

    return JobRead(
        id=row.id,
        kind=row.kind,
        status=cast(Any, row.status),
        payload=row.payload,
        result=row.result,
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        cancel_requested_at=row.cancel_requested_at,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class JobService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> Job:
        existing = await self.session.scalar(
            select(Job).where(Job.kind == kind, Job.idempotency_key == idempotency_key)
        )
        request_hash = stable_payload_hash(payload)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("idempotency key was already used for a different payload")
            return existing
        now = utc_now()
        row = Job(
            kind=kind,
            status=JobStatus.QUEUED.value,
            payload=payload,
            result=None,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=now,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            collision: Job | None = await self.session.scalar(
                select(Job).where(Job.kind == kind, Job.idempotency_key == idempotency_key)
            )
            if collision is None:
                raise
            if collision.request_hash != request_hash:
                raise ValueError(
                    "idempotency key was already used for a different payload"
                ) from None
            return collision
        await self.emit("job", str(row.id), "queued")
        return row

    async def get(self, job_id: UUID) -> Job | None:
        return await self.session.get(Job, job_id)

    async def cancel(self, job_id: UUID) -> Job | None:
        row = await self.session.get(Job, job_id)
        if row is None:
            return None
        if row.status == JobStatus.QUEUED.value:
            now = utc_now()
            row.status = JobStatus.CANCELLED.value
            row.cancel_requested_at = now
            row.finished_at = now
            await self.emit("job", str(row.id), "cancelled")
        elif row.status == JobStatus.RUNNING.value and row.cancel_requested_at is None:
            row.cancel_requested_at = utc_now()
            await self.emit("job", str(row.id), "cancel_requested")
        await self.session.flush()
        return row

    async def archive(self, job_id: UUID) -> Job | None:
        """Cancel active work and hide the Job without deleting its receipt."""

        row = await self.cancel(job_id)
        if row is None:
            return None
        if row.archived_at is None:
            row.archived_at = utc_now()
            await self.emit("job", str(row.id), "archived")
            await self.session.flush()
        return row

    async def recover_expired(self, *, allowed_kinds: Collection[str]) -> int:
        kinds = _validated_allowed_kinds(allowed_kinds)
        now = utc_now()
        query = select(Job).where(
            Job.status == JobStatus.RUNNING.value,
            Job.kind.in_(kinds),
            Job.lease_expires_at.is_not(None),
            Job.lease_expires_at <= now,
        )
        if self.session.bind is not None and self.session.bind.dialect.name == "mysql":
            query = query.with_for_update(skip_locked=True)
        rows = list(await self.session.scalars(query))
        for row in rows:
            if row.cancel_requested_at is not None:
                row.status = JobStatus.CANCELLED.value
                row.finished_at = now
                reason = "cancelled"
            else:
                decision = failure_decision(
                    attempt_count=row.attempt_count, max_attempts=row.max_attempts
                )
                row.status = decision.status.value
                row.available_at = now
                row.finished_at = None if decision.should_retry else now
                row.last_error_code = "lease_expired"
                row.last_error_message = "worker lease expired before completion"
                reason = "lease_recovered" if decision.should_retry else "failed"
            for field, value in _clear_lease().items():
                setattr(row, field, value)
            await self.emit("job", str(row.id), reason)
        await self.session.flush()
        return len(rows)

    async def claim(
        self,
        *,
        worker_id: str,
        allowed_kinds: Collection[str],
        lease_seconds: int = 30,
    ) -> Job | None:
        kinds = _validated_allowed_kinds(allowed_kinds)
        await self.recover_expired(allowed_kinds=kinds)
        now = utc_now()
        query: Select[tuple[Job]] = (
            select(Job)
            .where(
                Job.status == JobStatus.QUEUED.value,
                Job.kind.in_(kinds),
                Job.available_at <= now,
                Job.cancel_requested_at.is_(None),
            )
            .order_by(Job.created_at, Job.id)
            .limit(1)
        )
        if self.session.bind is not None and self.session.bind.dialect.name == "mysql":
            query = query.with_for_update(skip_locked=True)
        candidate = await self.session.scalar(query)
        if candidate is None:
            return None
        result = await self.session.execute(
            update(Job)
            .where(Job.id == candidate.id, Job.status == JobStatus.QUEUED.value)
            .values(
                status=JobStatus.RUNNING.value,
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                heartbeat_at=now,
                started_at=candidate.started_at or now,
                attempt_count=Job.attempt_count + 1,
            )
        )
        if _affected_rows(result) != 1:
            self.session.expire_all()
            return None
        await self.session.flush()
        row = await self.session.get(Job, candidate.id, populate_existing=True)
        assert row is not None
        await self.emit("job", str(row.id), "running")
        return row

    async def heartbeat(self, job_id: UUID, *, worker_id: str, lease_seconds: int = 30) -> bool:
        now = utc_now()
        result = await self.session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING.value,
                Job.lease_owner == worker_id,
                Job.cancel_requested_at.is_(None),
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
        )
        return _affected_rows(result) == 1

    async def cancellation_requested(self, job_id: UUID, *, worker_id: str) -> bool:
        return bool(
            await self.session.scalar(
                select(Job.cancel_requested_at).where(
                    Job.id == job_id,
                    Job.status == JobStatus.RUNNING.value,
                    Job.lease_owner == worker_id,
                )
            )
        )

    async def succeed(self, job_id: UUID, *, worker_id: str, result: dict[str, Any]) -> bool:
        now = utc_now()
        updated = await self.session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING.value,
                Job.lease_owner == worker_id,
                Job.cancel_requested_at.is_(None),
            )
            .values(
                status=JobStatus.SUCCEEDED.value,
                result=result,
                finished_at=now,
                last_error_code=None,
                last_error_message=None,
                **_clear_lease(),
            )
        )
        if _affected_rows(updated) == 1:
            await self.emit("job", str(job_id), "succeeded")
            return True
        return await self.finish_cancelled(job_id, worker_id=worker_id)

    async def fail(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        code: str,
        message: str,
        retry_delay_seconds: int = 1,
        retryable: bool = True,
    ) -> bool:
        row = await self.session.scalar(
            select(Job).where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING.value,
                Job.lease_owner == worker_id,
            )
        )
        if row is None:
            return False
        if row.cancel_requested_at is not None:
            return await self.finish_cancelled(job_id, worker_id=worker_id)
        now = utc_now()
        decision = failure_decision(
            attempt_count=row.attempt_count,
            max_attempts=row.max_attempts,
            retryable=retryable,
        )
        row.status = decision.status.value
        row.last_error_code = code
        row.last_error_message = message[:4000]
        row.available_at = now + timedelta(seconds=retry_delay_seconds)
        row.finished_at = None if decision.should_retry else now
        for field, value in _clear_lease().items():
            setattr(row, field, value)
        await self.emit("job", str(job_id), "retrying" if decision.should_retry else "failed")
        await self.session.flush()
        return True

    async def finish_cancelled(self, job_id: UUID, *, worker_id: str) -> bool:
        now = utc_now()
        result = await self.session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING.value,
                Job.lease_owner == worker_id,
            )
            .values(
                status=JobStatus.CANCELLED.value,
                cancel_requested_at=now,
                finished_at=now,
                **_clear_lease(),
            )
        )
        if _affected_rows(result) == 1:
            await self.emit("job", str(job_id), "cancelled")
            return True
        return False

    async def emit(self, resource_type: str, resource_id: str, reason: str) -> None:
        self.session.add(
            InvalidationEvent(
                resource_type=resource_type,
                resource_id=resource_id,
                reason=reason,
            )
        )

    async def events_after(self, after_id: int, *, limit: int = 100) -> list[InvalidationEvent]:
        return list(
            await self.session.scalars(
                select(InvalidationEvent)
                .where(InvalidationEvent.id > after_id)
                .order_by(InvalidationEvent.id)
                .limit(limit)
            )
        )
