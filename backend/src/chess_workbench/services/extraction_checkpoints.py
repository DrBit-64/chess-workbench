"""Per-run paid-response receipts for ordered PDF relation windows."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from chess_workbench.extraction.provider import (
    StructuredGenerationProvider,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
)
from chess_workbench.services.extraction_runtime import ExtractionRuntime, provider_fingerprint
from chess_workbench.services.source_storage import store_content_addressed_bytes

log = logging.getLogger(__name__)
_SCHEMA = "pdf-relation-response-checkpoint/1"


def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class ExtractionCheckpoints:
    def __init__(
        self,
        root: Path,
        *,
        run_id: str,
        attempt: int,
        pipeline: str,
        source_sha256: str,
        predecessor_sha256: str | None,
        runtime: ExtractionRuntime | None = None,
    ) -> None:
        self.root = root
        self.runtime = runtime
        self.run_id = run_id
        self.attempt = attempt
        self.binding = {
            "run_id": run_id,
            "pipeline": pipeline,
            "source_sha256": source_sha256,
            "predecessor_sha256": predecessor_sha256,
        }
        self.next_chunk = 0

    def wrap(
        self, provider: StructuredGenerationProvider, kind: str
    ) -> StructuredGenerationProvider:
        return _CheckpointedProvider(self, provider, kind)

    def _identity(
        self,
        request: StructuredGenerationRequest,
        provider: StructuredGenerationProvider,
        kind: str,
    ) -> str:
        return hashlib.sha256(
            _bytes(
                {
                    "schema": _SCHEMA,
                    "binding": self.binding,
                    "kind": kind,
                    "provider": provider_fingerprint(provider),
                    "request": request.model_dump(mode="json"),
                }
            )
        ).hexdigest()

    def _previous(self, chunk: int, fingerprint: str) -> StructuredGenerationResponse | None:
        for attempt in range(self.attempt - 1, 0, -1):
            directory = (
                self.root
                / "debug"
                / "source-extraction"
                / self.run_id
                / f"attempt-{attempt}"
                / f"chunk-{chunk}"
            )
            for path in directory.glob("*/*.json"):
                try:
                    raw = path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != path.stem:
                        continue
                    receipt = json.loads(raw)
                    if (
                        receipt.get("schema") != _SCHEMA
                        or receipt.get("fingerprint") != fingerprint
                    ):
                        continue
                    return StructuredGenerationResponse.model_validate(receipt["response"])
                except (OSError, ValueError, TypeError, KeyError):
                    continue
        return None

    async def generate(
        self,
        provider: StructuredGenerationProvider,
        kind: str,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResponse:
        self.next_chunk += 1
        chunk = self.next_chunk
        fingerprint = self._identity(request, provider, kind)
        previous = await asyncio.to_thread(self._previous, chunk, fingerprint)
        if previous is not None:
            log.info(
                "pdf_checkpoint_replay run=%s attempt=%d chunk=%d", self.run_id, self.attempt, chunk
            )
            return previous
        response = await provider.generate(request)
        receipt = _bytes(
            {
                "schema": _SCHEMA,
                "fingerprint": fingerprint,
                "binding": self.binding,
                "kind": kind,
                "request": request.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
            }
        )

        def store() -> None:
            store_content_addressed_bytes(
                self.root,
                namespace=f"debug/source-extraction/{self.run_id}/attempt-{self.attempt}/chunk-{chunk}",
                suffix=".json",
                raw_bytes=receipt,
            )

        if self.runtime is not None:
            await self.runtime.run_local(store)
        else:
            task = asyncio.create_task(asyncio.to_thread(store))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.shield(task)
                raise
        log.info(
            "pdf_checkpoint_saved run=%s attempt=%d chunk=%d", self.run_id, self.attempt, chunk
        )
        return response


class _CheckpointedProvider:
    def __init__(
        self, checkpoints: ExtractionCheckpoints, provider: StructuredGenerationProvider, kind: str
    ) -> None:
        self.checkpoints = checkpoints
        self.provider = provider
        self.kind = kind

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResponse:
        return await self.checkpoints.generate(self.provider, self.kind, request)
