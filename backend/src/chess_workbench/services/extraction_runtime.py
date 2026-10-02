"""Small process-local limits for independent PDF extraction jobs."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from chess_workbench.extraction.provider import (
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
)

log = logging.getLogger(__name__)
_T = TypeVar("_T")


class ExtractionRuntime:
    def __init__(self, provider_concurrency: int, request_timeout_seconds: float) -> None:
        self.provider_slots = asyncio.Semaphore(provider_concurrency)
        self.local_stage = asyncio.Lock()
        # HTTPX's read timeout is an inactivity timeout. This is a total bound
        # after acquiring a provider slot, including streaming keepalives.
        self.request_timeout_seconds = request_timeout_seconds

    def limit(
        self, provider: StructuredGenerationProvider, *, run_id: str = ""
    ) -> StructuredGenerationProvider:
        return _LimitedProvider(provider, self, run_id)

    async def run_local(self, work: Callable[[], _T]) -> _T:
        async with self.local_stage:
            task = asyncio.create_task(asyncio.to_thread(work))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # asyncio.to_thread keeps running after its waiter is cancelled.
                await asyncio.shield(task)
                raise


class _LimitedProvider:
    def __init__(
        self, provider: StructuredGenerationProvider, runtime: ExtractionRuntime, run_id: str
    ) -> None:
        self.provider = provider
        self.runtime = runtime
        self.run_id = run_id

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResponse:
        queued_at = time.monotonic()
        async with self.runtime.provider_slots:
            started_at = time.monotonic()
            log.info(
                "pdf_provider_start run=%s queue_ms=%d",
                self.run_id,
                round((started_at - queued_at) * 1000),
            )
            try:
                async with asyncio.timeout(self.runtime.request_timeout_seconds):
                    response = await self.provider.generate(request)
            except TimeoutError:
                log.warning(
                    "pdf_provider_timeout run=%s elapsed_ms=%d",
                    self.run_id,
                    round((time.monotonic() - started_at) * 1000),
                )
                raise StructuredGenerationProviderError(
                    "timeout", "PDF provider request exceeded its total time limit", True
                ) from None
            finally:
                log.info(
                    "pdf_provider_end run=%s elapsed_ms=%d",
                    self.run_id,
                    round((time.monotonic() - started_at) * 1000),
                )
            return response


def provider_fingerprint(provider: StructuredGenerationProvider) -> dict[str, Any]:
    """Effective model settings, excluding credentials, for checkpoint identity."""
    if isinstance(provider, _LimitedProvider):
        provider = provider.provider
    return {
        "adapter": f"{type(provider).__module__}.{type(provider).__qualname__}",
        "endpoint": getattr(provider, "_endpoint", None),
        "model": getattr(provider, "_model", None),
        "thinking": getattr(provider, "_thinking_enabled", None),
        "reasoning_effort": getattr(provider, "_reasoning_effort", None),
        "json_output": getattr(provider, "_json_output_enabled", None),
        "output_limit": getattr(provider, "_max_output_tokens_limit", None),
    }
