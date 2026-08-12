from __future__ import annotations

import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from chess_workbench.extraction import (
    PADDLE_OCR_RUNNER_PROTOCOL,
    OcrAdapter,
    OcrRequest,
    PaddleOcrJsonAdapter,
    PdfEvidenceError,
    normalize_paddle_ocr_response,
)


def _request(**overrides: Any) -> OcrRequest:
    values: dict[str, Any] = {
        "physical_page": 7,
        "width": 120,
        "height": 80,
        "png_bytes": b"recorded-png",
        "language": "en",
        "profile": {"device": "cpu", "threshold": 0.5},
    }
    values.update(overrides)
    return OcrRequest(**values)


def _document(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "protocol": PADDLE_OCR_RUNNER_PROTOCOL,
        "physical_page": 7,
        "width": 120,
        "height": 80,
        "engine_version": "3.2.0",
        "rec_texts": ["  Classical  ", "第二行"],
        "rec_scores": [1, 0.75],
        "rec_polys": [
            [[30, 20], [10, 20], [10, 40], [30, 40]],
            [[40, 45], [70, 44], [72, 60], [39, 61]],
        ],
    }
    values.update(overrides)
    return values


def _payload(**overrides: Any) -> bytes:
    return json.dumps(_document(**overrides), ensure_ascii=False).encode()


def test_normalizer_preserves_order_text_and_normalizes_polygons() -> None:
    result = normalize_paddle_ocr_response(_payload(), _request())

    assert result.physical_page == 7
    assert result.width == 120
    assert result.height == 80
    assert result.engine_name == "paddleocr"
    assert result.engine_version == "3.2.0"
    assert [fragment.order for fragment in result.fragments] == [0, 1]
    assert [fragment.text for fragment in result.fragments] == ["  Classical  ", "第二行"]
    assert result.fragments[0].box.model_dump() == {"x0": 10, "y0": 20, "x1": 30, "y1": 40}
    assert result.fragments[1].box.model_dump() == {"x0": 39, "y0": 44, "x1": 72, "y1": 61}
    assert [fragment.confidence for fragment in result.fragments] == [1.0, 0.75]


def test_normalizer_accepts_empty_recorded_page() -> None:
    result = normalize_paddle_ocr_response(
        _payload(rec_texts=[], rec_scores=[], rec_polys=[]), _request()
    )
    assert result.fragments == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"extra": "no"},
        {"protocol": "future"},
        {"physical_page": 8},
        {"width": 119},
        {"height": 79},
        {"engine_version": " "},
        {"rec_texts": ["one"], "rec_scores": [], "rec_polys": []},
        {"rec_texts": [" ", "ok"]},
        {"rec_scores": [True, 0.5]},
        {"rec_scores": ["0.5", 0.5]},
        {"rec_scores": [math.inf, 0.5]},
        {"rec_scores": [-0.1, 0.5]},
        {"rec_polys": [[[0, 0], [1, 0], [1, 1]], [[0, 0], [1, 0], [1, 1], [0, 1]]]},
        {"rec_polys": [[[0, 0], [0, 0], [0, 2], [0, 2]], [[0, 0], [1, 0], [1, 1], [0, 1]]]},
        {"rec_polys": [[[0, 0], [121, 0], [121, 2], [0, 2]], [[0, 0], [1, 0], [1, 1], [0, 1]]]},
        {"rec_polys": [[[0.0, 0], [1, 0], [1, 1], [0, 1]], [[0, 0], [1, 0], [1, 1], [0, 1]]]},
    ],
)
def test_normalizer_maps_all_recorded_content_failures_to_one_error(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(PdfEvidenceError) as caught:
        normalize_paddle_ocr_response(_payload(**overrides), _request())

    assert caught.value.code == "ocr_invalid_output"
    assert str(caught.value) == "OCR runner returned invalid output"
    assert caught.value.retryable is False
    assert caught.value.__cause__ is None
    assert "Classical" not in str(caught.value)


@pytest.mark.parametrize("payload", [b"not-json", b"\xff", b"null", b"[]"])
def test_normalizer_sanitizes_decode_and_root_shape_failures(payload: bytes) -> None:
    with pytest.raises(PdfEvidenceError, match="^OCR runner returned invalid output$"):
        normalize_paddle_ocr_response(payload, _request())


def test_normalizer_rejects_programmer_misuse_without_evidence_error() -> None:
    with pytest.raises(TypeError, match="exact bytes"):
        normalize_paddle_ocr_response("{}", _request())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_paddle_ocr_response(b"", _request())
    with pytest.raises(TypeError, match="OcrRequest"):
        normalize_paddle_ocr_response(b"{}", object())  # type: ignore[arg-type]


_SUCCESS_RUNNER = r"""
import base64, json, os, sys
request = json.load(sys.stdin)
assert request["protocol"] == "chess-workbench/paddleocr-runner/1"
assert base64.b64decode(request["png_base64"]) == b"recorded-png"
assert request["language"] == "en"
assert request["profile"] == {"device": "cpu", "threshold": 0.5}
assert os.path.basename(os.getcwd()).startswith("chess-workbench-ocr-")
json.dump({
    "protocol": request["protocol"],
    "physical_page": request["physical_page"],
    "width": request["width"],
    "height": request["height"],
    "engine_version": "3.2.0",
    "rec_texts": ["runner text"],
    "rec_scores": [0.9],
    "rec_polys": [[[1, 2], [9, 2], [9, 8], [1, 8]]],
}, sys.stdout)
"""


@pytest.mark.asyncio
async def test_runner_uses_versioned_json_pipe_and_controlled_working_directory() -> None:
    argv = [sys.executable, "-c", _SUCCESS_RUNNER]
    adapter = PaddleOcrJsonAdapter(argv, timeout_seconds=2)
    argv[2] = "raise SystemExit(99)"

    assert isinstance(adapter, OcrAdapter)
    result = await adapter.recognize(_request())
    assert result.engine_name == "paddleocr"
    assert result.fragments[0].text == "runner text"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter", "expected_code", "retryable"),
    [
        (PaddleOcrJsonAdapter(None), "ocr_unavailable", True),
        (
            PaddleOcrJsonAdapter(["/definitely/missing/chess-workbench-ocr"]),
            "ocr_unavailable",
            True,
        ),
        (
            PaddleOcrJsonAdapter(
                [sys.executable, "-c", "import sys; sys.stderr.write('SECRET'); sys.exit(7)"]
            ),
            "ocr_runner_failed",
            True,
        ),
        (
            PaddleOcrJsonAdapter([sys.executable, "-c", "print('invalid json')"]),
            "ocr_invalid_output",
            False,
        ),
        (
            PaddleOcrJsonAdapter([sys.executable, "-c", "print('x' * 1000)"], max_stdout_bytes=10),
            "ocr_output_too_large",
            False,
        ),
        (
            PaddleOcrJsonAdapter(
                [sys.executable, "-c", "import sys; sys.stderr.write('x' * 1000)"],
                max_stderr_bytes=10,
            ),
            "ocr_output_too_large",
            False,
        ),
    ],
)
async def test_runner_maps_failures_without_leaking_details(
    adapter: PaddleOcrJsonAdapter, expected_code: str, retryable: bool
) -> None:
    with pytest.raises(PdfEvidenceError) as caught:
        await adapter.recognize(_request())
    assert caught.value.code == expected_code
    assert caught.value.retryable is retryable
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SECRET" not in str(caught.value)
    assert "/definitely" not in str(caught.value)


@pytest.mark.asyncio
async def test_runner_times_out_and_reaps() -> None:
    adapter = PaddleOcrJsonAdapter(
        [sys.executable, "-c", "import time; time.sleep(5)"], timeout_seconds=0.02
    )
    with pytest.raises(PdfEvidenceError) as caught:
        await adapter.recognize(_request())
    assert caught.value.code == "ocr_timeout"
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_runner_cancellation_is_not_translated() -> None:
    adapter = PaddleOcrJsonAdapter(
        [sys.executable, "-c", "import time; time.sleep(5)"], timeout_seconds=2
    )
    task = asyncio.create_task(adapter.recognize(_request()))
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PaddleOcrJsonAdapter([]),
        lambda: PaddleOcrJsonAdapter("python"),
        lambda: PaddleOcrJsonAdapter(cast(Any, ["python", 1])),
        lambda: PaddleOcrJsonAdapter(["python"], timeout_seconds=math.inf),
        lambda: PaddleOcrJsonAdapter(["python"], max_stdout_bytes=True),
        lambda: PaddleOcrJsonAdapter(["python"], max_stderr_bytes=1024 * 1024 + 1),
    ],
)
def test_runner_constructor_rejects_unsafe_or_unbounded_values(factory: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_module_has_no_paddle_network_sql_or_shell_import() -> None:
    source = Path("backend/src/chess_workbench/extraction/paddleocr.py").read_text()
    forbidden = (
        "paddle",
        "requests",
        "httpx",
        "sqlalchemy",
        "create_subprocess_shell",
        "shell=True",
    )
    lowered = source.lower()
    assert "import paddle" not in lowered
    assert all(token not in lowered for token in forbidden[1:])
