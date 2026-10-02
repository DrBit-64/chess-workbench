"""Focused receipts and bounded independent worker behavior."""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from chess_workbench.config import Settings
from chess_workbench.extraction.chunks import generate_relation_chunks
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    RenderedPage,
    RenderProfile,
    SourceEvidenceFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.provider import (
    ScriptedStructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    StructuredMessage,
)
from chess_workbench.services.extraction_checkpoints import ExtractionCheckpoints
from chess_workbench.services.extraction_runtime import ExtractionRuntime
from chess_workbench.services.jobs import JobService
from chess_workbench.services.pdf_render import render_pdf_page
from chess_workbench.services.worker import SqlWorker
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import Job


def _context(content: str) -> CcefPromptContext:
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    fragment = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=content,
        origin="embedded_text",
        engine_name="test",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(1, box, content, "embedded_text", "test", "1"),
    )
    return CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000001"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="source",
        media_type="application/pdf",
        first_page=1,
        last_page=1,
        pages=[
            PromptEvidencePage(
                physical_page=1,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
            )
        ],
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )


def _request(content: str) -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        messages=[StructuredMessage(role="user", content=content)],
        response_schema_name="test",
        response_schema={"type": "object"},
        max_output_tokens=100,
    )


def _response(content: str) -> StructuredGenerationResponse:
    return StructuredGenerationResponse(content=content, provider="fixture", model="fixture")


def _checkpoints(root: Path, attempt: int, predecessor: str = "head-a") -> ExtractionCheckpoints:
    return ExtractionCheckpoints(
        root,
        run_id="test-run",
        attempt=attempt,
        pipeline="pdf-extraction:v8",
        source_sha256="source-a",
        predecessor_sha256=predecessor,
    )


async def test_paid_window_replays_before_next_dependent_window(tmp_path: Path) -> None:
    first = ScriptedStructuredGenerationProvider(
        [
            _response('{"first":1}'),
            StructuredGenerationProviderError("unavailable", "offline", True),
        ]
    )
    attempt_one = _checkpoints(tmp_path, 1)
    assert (
        await attempt_one.wrap(first, "relation").generate(_request("start"))
    ).content == '{"first":1}'
    try:
        await attempt_one.wrap(first, "relation").generate(_request("after first"))
    except StructuredGenerationProviderError:
        pass
    else:
        raise AssertionError("the second window must fail")

    second = ScriptedStructuredGenerationProvider([_response('{"second":2}')])
    attempt_two = _checkpoints(tmp_path, 2)
    resumed = attempt_two.wrap(second, "relation")
    assert (await resumed.generate(_request("start"))).content == '{"first":1}'
    assert (await resumed.generate(_request("after first"))).content == '{"second":2}'
    assert [call.messages[0].content for call in second.calls] == ["after first"]

    changed = ScriptedStructuredGenerationProvider([_response('{"fresh":3}')])
    assert (
        await _checkpoints(tmp_path, 2, "head-b")
        .wrap(changed, "relation")
        .generate(_request("start"))
    ).content == '{"fresh":3}'
    assert len(changed.calls) == 1


async def test_two_workers_overlap_network_and_leave_third_queued(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}",
        source_storage_root=tmp_path,
        engine_worker_enabled=False,
    )
    runtime = ExtractionRuntime(provider_concurrency=2, request_timeout_seconds=5)
    entered: asyncio.Queue[int] = asyncio.Queue()
    release = {number: asyncio.Event() for number in (1, 2, 3)}
    active = 0
    maximum = 0

    class WaitingProvider:
        async def generate(
            self, request: StructuredGenerationRequest
        ) -> StructuredGenerationResponse:
            nonlocal active, maximum
            number = int(request.messages[0].content)
            active += 1
            maximum = max(maximum, active)
            await entered.put(number)
            try:
                await release[number].wait()
                return _response(f'{{"task":{number}}}')
            finally:
                active -= 1

    provider = runtime.limit(WaitingProvider())

    async def handler(
        _database: Database, _settings: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        number = payload["number"]
        result = await provider.generate(_request(str(number)))
        return {"result": result.content}

    try:
        async with database.session() as session, session.begin():
            for number in (1, 2, 3):
                await JobService(session).enqueue(
                    kind="test", payload={"number": number}, idempotency_key=f"job-{number}"
                )
        workers = [
            SqlWorker(database, settings, worker_id=f"worker-{index}", handlers={"test": handler})
            for index in range(2)
        ]
        tasks = [asyncio.create_task(worker.run_once()) for worker in workers]
        assert {await asyncio.wait_for(entered.get(), 2) for _ in range(2)} == {1, 2}
        async with database.session() as session:
            rows = list(await session.scalars(select(Job).order_by(Job.created_at, Job.id)))
            assert [row.status for row in rows].count("running") == 2
            assert [row.status for row in rows].count("queued") == 1
        release[2].set()
        finished, _ = await asyncio.wait(tasks, timeout=3, return_when=asyncio.FIRST_COMPLETED)
        assert len(finished) == 1
        assert await next(iter(finished))
        third = asyncio.create_task(workers[tasks.index(next(iter(finished)))].run_once())
        assert await asyncio.wait_for(entered.get(), 2) == 3
        release[1].set()
        release[3].set()
        await asyncio.wait_for(asyncio.gather(*tasks, third), 3)
        assert maximum == 2
        async with database.session() as session:
            rows = list(await session.scalars(select(Job)))
            assert all(row.status == "succeeded" for row in rows)
    finally:
        for event in release.values():
            event.set()
        await database.close()


async def test_native_render_stays_serial_after_waiter_cancellation() -> None:
    active = 0
    maximum = 0

    class SlowRenderer:
        def render_page(self, _pdf: bytes, page: int, _profile: RenderProfile) -> RenderedPage:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            time.sleep(0.05)
            active -= 1
            return RenderedPage(
                physical_page=page,
                width=1,
                height=1,
                dpi=144,
                png_bytes=b"png",
                renderer_name="test",
                renderer_version="1",
            )

    renderer = SlowRenderer()
    first = asyncio.create_task(render_pdf_page(renderer, b"pdf", 1, RenderProfile()))
    await asyncio.sleep(0.01)
    first.cancel()
    second = asyncio.create_task(render_pdf_page(renderer, b"pdf", 2, RenderProfile()))
    with contextlib.suppress(asyncio.CancelledError):
        await first
    assert (await second).physical_page == 2
    assert maximum == 1


async def test_provider_total_timeout_releases_the_shared_slot() -> None:
    class FirstStalls:
        calls = 0

        async def generate(
            self, _request: StructuredGenerationRequest
        ) -> StructuredGenerationResponse:
            self.calls += 1
            if self.calls == 1:
                await asyncio.Event().wait()
            return _response('{"ok":true}')

    provider = FirstStalls()
    limited = ExtractionRuntime(1, 0.03).limit(provider)
    try:
        await limited.generate(_request("slow"))
    except StructuredGenerationProviderError as error:
        assert error.code == "timeout"
    else:
        raise AssertionError("the first call must time out")
    assert (await limited.generate(_request("next"))).content == '{"ok":true}'


async def test_output_exhaustion_splits_only_owned_output_with_full_reading_context() -> None:
    first = _context("The first example is explained here.")
    original = first.pages[0].fragments[0].fragment
    second_fragment = original.model_copy(
        update={
            "physical_page": 2,
            "text": "The second example is explained here.",
            "fragment_sha256": source_fragment_sha256(
                2,
                original.box,
                "The second example is explained here.",
                original.origin,
                original.engine_name,
                original.engine_version,
            ),
        }
    )
    second_page = first.pages[0].model_copy(
        update={
            "physical_page": 2,
            "fragments": [
                first.pages[0].fragments[0].model_copy(update={"fragment": second_fragment})
            ],
        }
    )
    context = CcefPromptContext.model_validate(
        first.model_copy(
            update={"last_page": 2, "pages": [first.pages[0], second_page]}
        ).model_dump(mode="python")
    )
    calls: list[StructuredGenerationRequest] = []

    class ExhaustOnce:
        async def generate(
            self, request: StructuredGenerationRequest
        ) -> StructuredGenerationResponse:
            calls.append(request)
            if len(calls) == 1:
                raise StructuredGenerationProviderError(
                    "invalid_response",
                    "Generation exhausted its output budget without final content "
                    "(48000 reasoning tokens)",
                    False,
                )
            return _response(
                '{"schema_version":"chess-source-relations/1","games":[],"segments":[],"notes":[],"unresolved":[]}'
            )

    result = await generate_relation_chunks(
        context,
        ExhaustOnce(),
        local_run=ExtractionRuntime(2, 5).run_local,
    )
    assert len(result.chunks) == 2
    assert len(calls) >= 3
    assert all(
        "s1_0" in request.messages[1].content and "s2_0" in request.messages[1].content
        for request in calls[:3]
    )
