from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from chess_workbench.config import Settings
from chess_workbench.services.engine import process_analysis_job
from chess_workbench.services.jobs import JobService
from chess_workbench.services.uci import EngineError
from chess_workbench.store.database import Database

JobHandler = Callable[[Database, Settings, dict[str, Any]], Awaitable[dict[str, Any]]]


class SqlWorker:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        worker_id: str,
        handlers: dict[str, JobHandler] | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.worker_id = worker_id
        self.handlers = handlers or {"engine_analysis": process_analysis_job}

    async def run_once(self) -> bool:
        async with self.database.session() as session, session.begin():
            job = await JobService(session).claim(worker_id=self.worker_id)
            if job is None:
                return False
            job_id = job.id
            kind = job.kind
            payload = dict(job.payload)
        handler = self.handlers.get(kind)
        if handler is None:
            async with self.database.session() as session, session.begin():
                await JobService(session).fail(
                    job_id,
                    worker_id=self.worker_id,
                    code="unknown_job_kind",
                    message=f"no handler registered for {kind}",
                    retry_delay_seconds=0,
                )
            return True
        task = asyncio.create_task(self._run_handler(handler, payload))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.1)
                if task.done():
                    break
                async with self.database.session() as session, session.begin():
                    service = JobService(session)
                    if await service.cancellation_requested(job_id, worker_id=self.worker_id):
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
                        await service.finish_cancelled(job_id, worker_id=self.worker_id)
                        return True
                    await service.heartbeat(job_id, worker_id=self.worker_id)
            result = await task
            async with self.database.session() as session, session.begin():
                await JobService(session).succeed(job_id, worker_id=self.worker_id, result=result)
        except asyncio.CancelledError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            # Worker shutdown is not a user cancellation. Leave the durable job and
            # its lease intact so another worker can recover it after lease expiry.
            raise
        except EngineError as error:
            async with self.database.session() as session, session.begin():
                await JobService(session).fail(
                    job_id,
                    worker_id=self.worker_id,
                    code=error.code,
                    message=str(error),
                )
        except Exception as error:
            async with self.database.session() as session, session.begin():
                await JobService(session).fail(
                    job_id,
                    worker_id=self.worker_id,
                    code="worker_error",
                    message=str(error),
                )
        return True

    async def _run_handler(self, handler: JobHandler, payload: dict[str, Any]) -> dict[str, Any]:
        return await handler(self.database, self.settings, payload)

    async def run_forever(self) -> None:
        delay = self.settings.engine_worker_poll_ms / 1000
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(delay)
