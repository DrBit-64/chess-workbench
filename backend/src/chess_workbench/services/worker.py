from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.config import Settings
from chess_workbench.services.engine import process_analysis_job
from chess_workbench.services.jobs import JobService
from chess_workbench.services.uci import EngineError
from chess_workbench.store.database import Database

JobHandler = Callable[[Database, Settings, dict[str, Any]], Awaitable[dict[str, Any]]]
_MONITOR_POLL_SECONDS = 0.1
_HEARTBEAT_INTERVAL_SECONDS = 10.0


class SqlWorker:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        worker_id: str,
        handlers: dict[str, JobHandler] | None = None,
        heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self.database = database
        self.settings = settings
        self.worker_id = worker_id
        self.handlers = dict(
            handlers if handlers is not None else {"engine_analysis": process_analysis_job}
        )
        if not self.handlers:
            raise ValueError("worker requires at least one registered job handler")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        self.heartbeat_interval_seconds = heartbeat_interval_seconds

    async def run_once(self) -> bool:
        async def claim(session: AsyncSession) -> Any:
            return await JobService(session).claim(
                worker_id=self.worker_id,
                allowed_kinds=self.handlers.keys(),
            )

        job = await self.database.run_write(claim)
        if job is None:
            return False
        job_id = job.id
        kind = job.kind
        payload = dict(job.payload)
        handler = self.handlers.get(kind)
        if handler is None:

            async def fail_unknown(session: AsyncSession) -> bool:
                return await JobService(session).fail(
                    job_id,
                    worker_id=self.worker_id,
                    code="unknown_job_kind",
                    message=f"no handler registered for {kind}",
                    retry_delay_seconds=0,
                )

            await self.database.run_write(fail_unknown)
            return True
        task = asyncio.create_task(self._run_handler(handler, payload))
        try:
            next_heartbeat = asyncio.get_running_loop().time() + self.heartbeat_interval_seconds
            while not task.done():
                await asyncio.wait({task}, timeout=_MONITOR_POLL_SECONDS)
                if task.done():
                    break
                if await self._cancellation_requested(job_id):
                    await self._cancel_handler(task)
                    await self._finish_cancelled(job_id)
                    return True
                now = asyncio.get_running_loop().time()
                if now >= next_heartbeat:
                    if not await self._heartbeat(job_id):
                        # Cancellation or lease loss means this worker no
                        # longer owns the durable operation.  Never leave its
                        # provider/engine handler detached in the background.
                        await self._cancel_handler(task)
                        await self._finish_cancelled(job_id)
                        return True
                    next_heartbeat = now + self.heartbeat_interval_seconds
            result = await task
            await self._succeed(job_id, result)
        except asyncio.CancelledError:
            await self._cancel_handler(task)
            # Worker shutdown is not a user cancellation. Leave the durable job and
            # its lease intact so another worker can recover it after lease expiry.
            raise
        except EngineError as error:
            await self._cancel_handler(task)
            await self._fail(job_id, code=error.code, message=str(error), retryable=error.retryable)
        except Exception as error:
            await self._cancel_handler(task)
            await self._fail(job_id, code="worker_error", message=str(error))
        return True

    async def _cancellation_requested(self, job_id: UUID) -> bool:
        async with self.database.session() as session:
            return await JobService(session).cancellation_requested(
                job_id, worker_id=self.worker_id
            )

    async def _heartbeat(self, job_id: UUID) -> bool:
        async def heartbeat(session: AsyncSession) -> bool:
            return await JobService(session).heartbeat(job_id, worker_id=self.worker_id)

        return await self.database.run_write(heartbeat)

    async def _succeed(self, job_id: UUID, result: dict[str, Any]) -> bool:
        async def succeed(session: AsyncSession) -> bool:
            return await JobService(session).succeed(
                job_id, worker_id=self.worker_id, result=result
            )

        return await self.database.run_write(succeed)

    async def _fail(
        self,
        job_id: UUID,
        *,
        code: str,
        message: str,
        retryable: bool = True,
    ) -> bool:
        async def fail(session: AsyncSession) -> bool:
            return await JobService(session).fail(
                job_id,
                worker_id=self.worker_id,
                code=code,
                message=message,
                retryable=retryable,
            )

        return await self.database.run_write(fail)

    async def _finish_cancelled(self, job_id: UUID) -> bool:
        async def finish(session: AsyncSession) -> bool:
            return await JobService(session).finish_cancelled(job_id, worker_id=self.worker_id)

        return await self.database.run_write(finish)

    @staticmethod
    async def _cancel_handler(task: asyncio.Task[dict[str, Any]]) -> None:
        if task.done():
            # Retrieve a racing terminal exception so the event loop does not
            # report an orphaned task after the supervisor has already chosen
            # its own durable failure transition.
            with suppress(asyncio.CancelledError):
                task.exception()
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run_handler(self, handler: JobHandler, payload: dict[str, Any]) -> dict[str, Any]:
        return await handler(self.database, self.settings, payload)

    async def run_forever(self) -> None:
        delay = self.settings.engine_worker_poll_ms / 1000
        while True:
            try:
                worked = await self.run_once()
            except Exception as error:
                if not self.database.is_transient_write_error(error):
                    raise
                worked = False
            if not worked:
                await asyncio.sleep(delay)
