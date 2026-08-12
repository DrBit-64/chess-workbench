"""PaddleOCR recorded-JSON normalization and controlled local runner.

The main backend never imports PaddlePaddle.  A separately installed local
runner receives one versioned JSON request on stdin and returns the small,
fixed PaddleOCR 3.x result subset accepted here on stdout.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import math
import tempfile
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self, final

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from .evidence import (
    MAX_FRAGMENTS,
    MAX_TEXT_CODE_POINTS,
    OcrPageResult,
    OcrRequest,
    PdfEvidenceError,
    PixelBox,
    TextFragment,
)

PADDLE_OCR_RUNNER_PROTOCOL = "chess-workbench/paddleocr-runner/1"

_INVALID_OUTPUT = (
    "ocr_invalid_output",
    "OCR runner returned invalid output",
    False,
)
_READ_CHUNK_BYTES = 64 * 1024
_MAX_ARGV_ITEMS = 32
_MAX_ARG_LENGTH = 4096
_MAX_RUNNER_OUTPUT_BYTES = 64 * 1024 * 1024
_MAX_RUNNER_STDERR_BYTES = 1024 * 1024


def _finite_confidence(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("confidence must be finite")
    return value


Confidence = Annotated[
    float,
    Field(ge=0.0, le=1.0),
    AfterValidator(_finite_confidence),
]
RecordedText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_TEXT_CODE_POINTS),
]
EngineVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _RecordedPaddleResult(_StrictModel):
    protocol: Literal["chess-workbench/paddleocr-runner/1"]
    physical_page: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(ge=1)]
    height: Annotated[int, Field(ge=1)]
    engine_version: EngineVersion
    rec_texts: Annotated[list[RecordedText], Field(max_length=MAX_FRAGMENTS)]
    rec_scores: Annotated[list[Confidence], Field(max_length=MAX_FRAGMENTS)]
    rec_polys: Annotated[list[list[list[int]]], Field(max_length=MAX_FRAGMENTS)]

    @model_validator(mode="after")
    def _check_parallel_arrays(self) -> Self:
        if not (len(self.rec_texts) == len(self.rec_scores) == len(self.rec_polys)):
            raise ValueError("recorded OCR arrays must have equal length")
        if any(not text.strip() for text in self.rec_texts):
            raise ValueError("recorded OCR text must not be whitespace-only")
        return self


def _invalid_output_error() -> PdfEvidenceError:
    return PdfEvidenceError(*_INVALID_OUTPUT)


def _normalize_validated(recorded: _RecordedPaddleResult, request: OcrRequest) -> OcrPageResult:
    if (
        recorded.physical_page != request.physical_page
        or recorded.width != request.width
        or recorded.height != request.height
    ):
        raise ValueError("runner result does not match its request")

    fragments: list[TextFragment] = []
    for order, (text, confidence, polygon) in enumerate(
        zip(recorded.rec_texts, recorded.rec_scores, recorded.rec_polys, strict=True)
    ):
        if len(polygon) != 4 or any(len(point) != 2 for point in polygon):
            raise ValueError("each recorded polygon must contain exactly four points")
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        if any(x < 0 or x > request.width for x in xs) or any(
            y < 0 or y > request.height for y in ys
        ):
            raise ValueError("recorded polygon lies outside the page")
        fragments.append(
            TextFragment(
                order=order,
                text=text,
                box=PixelBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys)),
                confidence=confidence,
            )
        )

    return OcrPageResult(
        physical_page=request.physical_page,
        width=request.width,
        height=request.height,
        fragments=fragments,
        engine_name="paddleocr",
        engine_version=recorded.engine_version,
    )


def normalize_paddle_ocr_response(payload: bytes, request: OcrRequest) -> OcrPageResult:
    """Normalize one strict recorded PaddleOCR result into the OCR port value."""
    if type(payload) is not bytes:
        raise TypeError("payload must be exact bytes")
    if not payload:
        raise ValueError("payload must not be empty")
    if type(request) is not OcrRequest:
        raise TypeError("request must be an OcrRequest")

    failed = False
    result: OcrPageResult | None = None
    try:
        recorded = _RecordedPaddleResult.model_validate_json(payload)
        result = _normalize_validated(recorded, request)
    except (ValidationError, ValueError, TypeError, OverflowError, UnicodeError):
        failed = True
    if failed or result is None:
        raise _invalid_output_error() from None
    return result


class _OutputTooLargeError(Exception):
    pass


async def _read_bounded(stream: asyncio.StreamReader, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(min(_READ_CHUNK_BYTES, limit - total + 1))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise _OutputTooLargeError
        chunks.append(chunk)


async def _send_input(writer: asyncio.StreamWriter, payload: bytes) -> None:
    try:
        writer.write(payload)
        await writer.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        writer.close()


async def _exchange(
    process: asyncio.subprocess.Process,
    payload: bytes,
    stdout_limit: int,
    stderr_limit: int,
) -> tuple[bytes, bytes, int]:
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise RuntimeError("runner pipes are unavailable")
    stdout_task = asyncio.create_task(_read_bounded(process.stdout, stdout_limit))
    stderr_task = asyncio.create_task(_read_bounded(process.stderr, stderr_limit))
    send_task = asyncio.create_task(_send_input(process.stdin, payload))
    tasks = (stdout_task, stderr_task, send_task)
    try:
        await send_task
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        return_code = process.returncode
        while return_code is None:
            await asyncio.sleep(0.001)
            return_code = process.returncode
        return stdout, stderr, return_code
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _kill_and_reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    # Python 3.13 can leave a second ``Process.wait()`` waiter unresolved
    # after pipe EOF even though the child watcher has already reaped the
    # process and populated ``returncode``.  The watcher-owned return code is
    # itself the reaping signal, so wait for that state without registering a
    # competing waiter.
    for _ in range(1000):
        if process.returncode is not None:
            return
        await asyncio.sleep(0.001)


def _validate_argv(argv: Sequence[str] | None) -> tuple[str, ...] | None:
    if argv is None:
        return None
    if isinstance(argv, (str, bytes)):
        raise TypeError("argv must be a sequence of strings")
    snapshot = tuple(argv)
    if not snapshot:
        raise ValueError("argv must not be empty")
    if len(snapshot) > _MAX_ARGV_ITEMS:
        raise ValueError(f"argv must contain at most {_MAX_ARGV_ITEMS} items")
    for item in snapshot:
        if type(item) is not str:
            raise TypeError("every argv item must be an exact string")
        if not item or len(item) > _MAX_ARG_LENGTH or "\0" in item:
            raise ValueError("argv items must be nonempty, bounded and contain no NUL")
    return snapshot


def _validate_positive_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0 or normalized > 3600:
        raise ValueError(f"{name} must be finite and in (0, 3600]")
    return normalized


def _validate_output_limit(value: int, name: str, maximum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact integer")
    if value <= 0 or value > maximum:
        raise ValueError(f"{name} must be in [1, {maximum}]")
    return value


def _runner_request_payload(request: OcrRequest) -> bytes:
    document: dict[str, Any] = {
        "protocol": PADDLE_OCR_RUNNER_PROTOCOL,
        "physical_page": request.physical_page,
        "width": request.width,
        "height": request.height,
        "language": request.language,
        "profile": request.profile,
        "png_base64": base64.b64encode(request.png_bytes).decode("ascii"),
    }
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


@final
class PaddleOcrJsonAdapter:
    """Run a configured local PaddleOCR bridge through a bounded JSON pipe."""

    def __init__(
        self,
        argv: Sequence[str] | None,
        *,
        timeout_seconds: float = 120.0,
        max_stdout_bytes: int = _MAX_RUNNER_OUTPUT_BYTES,
        max_stderr_bytes: int = _MAX_RUNNER_STDERR_BYTES,
    ) -> None:
        self._argv = _validate_argv(argv)
        self._timeout_seconds = _validate_positive_number(timeout_seconds, "timeout_seconds")
        self._max_stdout_bytes = _validate_output_limit(
            max_stdout_bytes, "max_stdout_bytes", _MAX_RUNNER_OUTPUT_BYTES
        )
        self._max_stderr_bytes = _validate_output_limit(
            max_stderr_bytes, "max_stderr_bytes", _MAX_RUNNER_STDERR_BYTES
        )

    async def recognize(self, request: OcrRequest) -> OcrPageResult:
        if type(request) is not OcrRequest:
            raise TypeError("request must be an OcrRequest")
        if self._argv is None:
            raise PdfEvidenceError("ocr_unavailable", "OCR runner is unavailable", True) from None

        payload = _runner_request_payload(request)
        process: asyncio.subprocess.Process | None = None
        spawn_failed = False
        timed_out = False
        output_too_large = False
        runner_io_failed = False
        stdout = b""
        return_code = -1
        with tempfile.TemporaryDirectory(prefix="chess-workbench-ocr-") as working_directory:
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    try:
                        process = await asyncio.create_subprocess_exec(
                            *self._argv,
                            stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            cwd=working_directory,
                            close_fds=True,
                            start_new_session=True,
                        )
                    except OSError:
                        spawn_failed = True
                    if process is not None:
                        try:
                            stdout, _stderr, return_code = await _exchange(
                                process,
                                payload,
                                self._max_stdout_bytes,
                                self._max_stderr_bytes,
                            )
                        except _OutputTooLargeError:
                            output_too_large = True
                        except (OSError, RuntimeError):
                            runner_io_failed = True
            except TimeoutError:
                timed_out = True
            except asyncio.CancelledError:
                if process is not None:
                    await asyncio.shield(_kill_and_reap(process))
                raise
            if process is not None and (timed_out or output_too_large or runner_io_failed):
                await _kill_and_reap(process)

        if spawn_failed or process is None:
            raise PdfEvidenceError("ocr_unavailable", "OCR runner is unavailable", True) from None
        if timed_out:
            raise PdfEvidenceError("ocr_timeout", "OCR runner timed out", True) from None
        if output_too_large:
            raise PdfEvidenceError(
                "ocr_output_too_large",
                "OCR runner output exceeds the configured limit",
                False,
            ) from None
        if runner_io_failed:
            raise PdfEvidenceError("ocr_runner_failed", "OCR runner failed", True) from None
        if return_code != 0:
            raise PdfEvidenceError("ocr_runner_failed", "OCR runner failed", True) from None
        return normalize_paddle_ocr_response(stdout, request)


__all__ = [
    "PADDLE_OCR_RUNNER_PROTOCOL",
    "PaddleOcrJsonAdapter",
    "normalize_paddle_ocr_response",
]
