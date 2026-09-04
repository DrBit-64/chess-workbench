"""Local ONNX chess-diagram recognizer for the shared PDF evidence pipeline.

Board detection and tile preparation are Python/Numpy adaptations of the MIT
fenshot project by SORTINO LABS S.R.L. (coachess.app).  The classifier model is
installed separately and remains replaceable through ``ChessDiagramRecognizer``.
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Literal, NamedTuple, cast, final

import chess
import numpy as np
import numpy.typing as npt
from PIL import Image

# ONNX Runtime enables POSIX telemetry during module initialization. Keep this
# local-first feature offline unless the operator explicitly overrides it.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

import onnxruntime  # type: ignore[import-untyped]  # noqa: E402

from .diagram import (
    DIAGRAM_RECOGNIZER_VERSION,
    ChessDiagramError,
    ChessDiagramRecognition,
    ChessDiagramRecognitionRequest,
    diagram_image_sha256,
)
from .evidence import EmbeddedPageImage, PixelBox

_LABELS = "1KQRBNPkqrbnp"
_CONFIDENCE_FLOOR = 0.7
_MAX_DETECT_DIM = 1600
_PEAK_KEEP_RATIO = 0.2
_MIN_SEQUENCE_LENGTH = 7
_SEQUENCE_ERROR_PX = 5
_MAX_CANDIDATE_SEQUENCES = 5

FloatImage = npt.NDArray[np.float32]
FloatVector = npt.NDArray[np.float64]


class _Corners(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float


def _gray_image(png_bytes: bytes) -> tuple[FloatImage, float]:
    try:
        image = Image.open(BytesIO(png_bytes)).convert("L")
    except (OSError, ValueError):
        raise ChessDiagramError("diagram_invalid_image", "Chess diagram image is invalid") from None
    scale = min(1.0, _MAX_DETECT_DIM / max(image.size))
    if scale < 1:
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.BILINEAR,
        )
    return np.asarray(image, dtype=np.float32), scale


def _hough_response(gradient: FloatImage, axis: int) -> FloatVector:
    positive = np.maximum(gradient, 0).sum(axis=axis, dtype=np.float64)
    negative = -np.minimum(gradient, 0).sum(axis=axis, dtype=np.float64)
    return np.asarray(positive * negative, dtype=np.float64)


def _nonmax_suppress(values: FloatVector, window: int = 5) -> FloatVector:
    result = values.copy()
    size = len(values)
    for index in range(size):
        left = 0.0 if index == 0 else float(values[max(0, index - window) : index].max())
        right = (
            0.0
            if index >= size - 2
            else float(values[index + 1 : min(size - 1, index + window)].max())
        )
        if values[index] < left or values[index] <= right:
            result[index] = 0
    return result


def _all_sequences(points: list[int]) -> list[list[int]]:
    if len(points) < _MIN_SEQUENCE_LENGTH:
        return []
    sequences: list[list[int]] = []
    for left in range(len(points) - 1):
        for right in range(left + 1, len(points)):
            if any(
                points[left] == prior[index] and points[right] == prior[index + 1]
                for prior in sequences
                for index in range(len(prior) - 1)
            ):
                continue
            distance = points[right] - points[left]
            if distance < _SEQUENCE_ERROR_PX:
                continue
            sequence = [points[left], points[right]]
            expected = sequence[-1] + distance
            while points:
                nearest = min(points, key=lambda value: abs(value - expected))
                if abs(nearest - expected) >= _SEQUENCE_ERROR_PX:
                    break
                sequence.append(nearest)
                expected = sequence[-1] + distance
            if len(sequence) >= _MIN_SEQUENCE_LENGTH:
                sequences.append(sequence)
    return sequences


def _trim_sequence(sequence: list[int], strengths: list[float]) -> tuple[list[int], list[float]]:
    points = list(sequence)
    values = list(strengths)
    if len(points) > 9:
        while len(points) > 7:
            if values[0] > values[-1]:
                points.pop()
                values.pop()
            else:
                points.pop(0)
                values.pop(0)
    return points, values


def _ranked_sequences(response: FloatVector) -> list[tuple[list[int], list[int]]]:
    suppressed = _nonmax_suppress(response)
    peak = float(suppressed.max(initial=0))
    if peak <= 0:
        return []
    positions = [
        index for index, value in enumerate(suppressed) if value / peak >= _PEAK_KEEP_RATIO
    ]
    strengths = {position: float(suppressed[position] / peak) for position in positions}
    scored: list[tuple[float, list[int], list[int]]] = []
    for sequence in _all_sequences(positions):
        trimmed, values = _trim_sequence(sequence, [strengths.get(value, 0) for value in sequence])
        scored.append((sum(values) / len(values), trimmed, sequence))
    scored.sort(reverse=True, key=lambda value: value[0])
    unique: list[tuple[list[int], list[int]]] = []
    for _, trimmed, full in scored:
        if full not in [candidate[1] for candidate in unique]:
            unique.append((trimmed, full))
        if len(unique) >= _MAX_CANDIDATE_SEQUENCES:
            break
    return unique


def _checkerboard_score(image: FloatImage, corners: _Corners) -> float:
    width = corners.x1 - corners.x0
    height = corners.y1 - corners.y0
    if width <= 0 or height <= 0:
        return 0
    ys = np.floor(corners.y0 + np.arange(64) * height / 64).astype(np.int64)
    xs = np.floor(corners.x0 + np.arange(64) * width / 64).astype(np.int64)
    sample = np.zeros((64, 64), dtype=np.float32)
    valid_y = (ys >= 0) & (ys < image.shape[0])
    valid_x = (xs >= 0) & (xs < image.shape[1])
    valid_y_indexes = np.flatnonzero(valid_y)
    valid_x_indexes = np.flatnonzero(valid_x)
    sample[np.ix_(valid_y_indexes, valid_x_indexes)] = image[np.ix_(ys[valid_y], xs[valid_x])]
    tile = np.indices((64, 64)).sum(axis=0) // 8
    kernel = np.where(tile % 2 == 0, 1.0, -1.0)
    return float((sample * kernel).sum() / 64)


def _snap_corners(image: FloatImage, corners: _Corners) -> _Corners:
    tile = (corners.x1 - corners.x0) / 8
    radius = max(2, round(tile / 3))
    best = (float("-inf"), 0, 0)

    def consider(dx: int, dy: int) -> None:
        nonlocal best
        shifted = _Corners(
            corners.x0 + dx,
            corners.y0 + dy,
            corners.x1 + dx,
            corners.y1 + dy,
        )
        score = _checkerboard_score(image, shifted)
        if score > best[0]:
            best = (score, dx, dy)

    for dy in range(-radius, radius + 1, 2):
        for dx in range(-radius, radius + 1, 2):
            consider(dx, dy)
    center_x, center_y = best[1], best[2]
    for dy in range(center_y - 2, center_y + 3):
        for dx in range(center_x - 2, center_x + 3):
            consider(dx, dy)
    return _Corners(
        corners.x0 + best[1],
        corners.y0 + best[2],
        corners.x1 + best[1],
        corners.y1 + best[2],
    )


def _repair_parity(image: FloatImage, corners: _Corners) -> _Corners:
    score = _checkerboard_score(image, corners)
    if score >= 0:
        return corners
    tile = round((corners.x1 - corners.x0) / 8)
    best = (score, corners)
    for dx, dy in ((tile, 0), (-tile, 0), (0, tile), (0, -tile)):
        shifted = _Corners(
            corners.x0 + dx,
            corners.y0 + dy,
            corners.x1 + dx,
            corners.y1 + dy,
        )
        candidate = _checkerboard_score(image, shifted)
        if candidate > best[0]:
            best = (candidate, shifted)
    return best[1]


def _reconstruct_square(
    image: FloatImage, sequences: list[tuple[list[int], list[int]]], axis: int
) -> list[_Corners]:
    """Recover the weak board axis from a clean grid on the other axis.

    Printed diagrams frequently have strong piece edges on one axis and faint
    grid edges on the other.  A chessboard is square, so every plausible grid
    extent can be slid over the weak axis and ranked by checkerboard contrast.
    """

    candidates: list[_Corners] = []
    weak_limit = image.shape[0] if axis == 0 else image.shape[1]
    for _, full in sequences:
        distance = float(np.median(np.diff(full)))
        if distance <= 0:
            continue
        extents: list[tuple[int, int]] = [(round(full[0]), round(full[-1]))]
        pad = round(distance)
        for index in range(len(full) - 6):
            extent = (round(full[index]) - pad, round(full[index + 6]) + pad)
            if not any(
                abs(extent[0] - existing[0]) <= 2 and abs(extent[1] - existing[1]) <= 2
                for existing in extents
            ):
                extents.append(extent)
        for strong_start, strong_end in extents:
            span = strong_end - strong_start
            if span <= 0:
                continue
            step = max(2, round(distance / 8))
            best: tuple[float, _Corners] | None = None
            for weak_start in range(-span, weak_limit + 1, step):
                if axis == 0:
                    value = _Corners(
                        strong_start,
                        weak_start,
                        strong_end,
                        weak_start + span,
                    )
                else:
                    value = _Corners(
                        weak_start,
                        strong_start,
                        weak_start + span,
                        strong_end,
                    )
                score = _checkerboard_score(image, value)
                if best is None or score > best[0]:
                    best = (score, value)
            if best is not None:
                candidates.append(best[1])
    return candidates


def _find_corners(image: FloatImage) -> _Corners | None:
    raw_gradient_y, raw_gradient_x = np.gradient(image)
    gradient_y = np.asarray(raw_gradient_y, dtype=np.float32)
    gradient_x = np.asarray(raw_gradient_x, dtype=np.float32)
    sequences_y = _ranked_sequences(_hough_response(gradient_y, axis=1))
    sequences_x = _ranked_sequences(_hough_response(gradient_x, axis=0))
    candidates: list[_Corners] = []
    if sequences_x and sequences_y:
        lines_x = sequences_x[0][0]
        lines_y = sequences_y[0][0]
        distance_x = float(np.median(np.diff(lines_x)))
        distance_y = float(np.median(np.diff(lines_y)))
        for start_x in range(max(1, len(lines_x) - 6)):
            sub_x = lines_x[start_x : start_x + 7]
            if len(sub_x) != 7:
                continue
            for start_y in range(max(1, len(lines_y) - 6)):
                sub_y = lines_y[start_y : start_y + 7]
                if len(sub_y) != 7:
                    continue
                candidates.append(
                    _Corners(
                        round(sub_x[0] - distance_x),
                        round(sub_y[0] - distance_y),
                        round(sub_x[6] + distance_x),
                        round(sub_y[6] + distance_y),
                    )
                )
    # Also arbitrate one-axis reconstructions even when the other axis has
    # false-positive piece-edge sequences. This is important for hatched
    # printed diagrams and remains a general geometric rule.
    candidates.extend(_reconstruct_square(image, sequences_x, 0))
    candidates.extend(_reconstruct_square(image, sequences_y, 1))
    best: tuple[float, _Corners] | None = None
    for candidate in candidates:
        score = _checkerboard_score(image, candidate)
        if best is None or score > best[0]:
            best = (score, candidate)
    return None if best is None else _repair_parity(image, best[1])


def _border_candidates(image: FloatImage) -> list[_Corners]:
    """Find square candidates bounded by long dark printed border lines.

    This complements internal-grid detection for scans where pieces or hatch
    marks dominate the gradient response. It is based only on image geometry:
    a candidate needs long dark lines on opposite sides and a nearly square
    extent. Nearby boundary pixels are ranked by checkerboard correlation and
    later arbitrated by the piece classifier.
    """

    height, width = image.shape
    if min(width, height) < 80:
        return []
    dark = image < 80
    vertical = np.flatnonzero(dark.sum(axis=0) >= height * 0.65).tolist()
    horizontal = np.flatnonzero(dark.sum(axis=1) >= width * 0.65).tolist()
    if not vertical or not horizontal:
        return []

    def anchors(values: list[int], limit: int) -> tuple[int, int] | None:
        lower = [value for value in values if value < limit / 2]
        upper = [value for value in values if value > limit / 2]
        if not lower or not upper:
            return None
        return max(lower) + 1, min(upper)

    x_anchors = anchors(vertical, width)
    y_anchors = anchors(horizontal, height)
    if x_anchors is None or y_anchors is None:
        return []
    scored: list[tuple[float, _Corners]] = []
    for x0 in range(x_anchors[0] - 3, x_anchors[0] + 4):
        for x1 in range(x_anchors[1] - 3, x_anchors[1] + 4):
            board_width = x1 - x0
            if board_width <= 0:
                continue
            for y0 in range(y_anchors[0] - 3, y_anchors[0] + 4):
                for y1 in range(y_anchors[1] - 3, y_anchors[1] + 4):
                    if abs(board_width - (y1 - y0)) > 3:
                        continue
                    candidate = _Corners(x0, y0, x1, y1)
                    scored.append((_checkerboard_score(image, candidate), candidate))
    scored.sort(reverse=True, key=lambda value: value[0])
    return [candidate for _, candidate in scored[:12]]


def _sample_bilinear(image: FloatImage, xs: FloatImage, ys: FloatImage) -> FloatImage:
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    x1 = x0 + 1
    y1 = y0 + 1
    wx = xs - x0
    wy = ys - y0
    x0 = np.clip(x0, 0, image.shape[1] - 1)
    x1 = np.clip(x1, 0, image.shape[1] - 1)
    y0 = np.clip(y0, 0, image.shape[0] - 1)
    y1 = np.clip(y1, 0, image.shape[0] - 1)
    sampled = (
        image[y0, x0] * (1 - wx) * (1 - wy)
        + image[y0, x1] * wx * (1 - wy)
        + image[y1, x0] * (1 - wx) * wy
        + image[y1, x1] * wx * wy
    ).astype(np.float32)
    return cast(FloatImage, sampled)


def _extract_tiles(image: FloatImage, corners: _Corners) -> FloatImage:
    ys = (
        corners.y0
        + (np.arange(256, dtype=np.float32) + 0.5) * (corners.y1 - corners.y0) / 256
        - 0.5
    )
    xs = (
        corners.x0
        + (np.arange(256, dtype=np.float32) + 0.5) * (corners.x1 - corners.x0) / 256
        - 0.5
    )
    grid_x, grid_y = (np.asarray(value, dtype=np.float32) for value in np.meshgrid(xs, ys))
    board = _sample_bilinear(image, grid_x, grid_y) / 255
    return np.stack(
        [
            board[(7 - rank) * 32 : (8 - rank) * 32, file * 32 : (file + 1) * 32].reshape(1024)
            for rank in range(8)
            for file in range(8)
        ]
    ).astype(np.float32)


def _placement(probabilities: FloatImage) -> tuple[str, list[float]]:
    indexes = probabilities.argmax(axis=1)
    confidences = probabilities.max(axis=1).astype(float).tolist()
    names = [_LABELS[index] for index in indexes]
    ranks: list[str] = []
    for rank in range(7, -1, -1):
        row = names[rank * 8 : rank * 8 + 8]
        rendered = ""
        empty = 0
        for name in row:
            if name == "1":
                empty += 1
            else:
                if empty:
                    rendered += str(empty)
                    empty = 0
                rendered += name
        if empty:
            rendered += str(empty)
        ranks.append(rendered)
    return "/".join(ranks), confidences


def _flip_placement(placement: str) -> str:
    return "/".join(rank[::-1] for rank in placement.split("/")[::-1])


def _orientation(
    placement: str,
) -> tuple[str, Literal["white", "black", "unknown"]]:
    def pawn_score(value: str) -> float | None:
        white: list[int] = []
        black: list[int] = []
        for index, row in enumerate(value.split("/")):
            rank = 8 - index
            for character in row:
                if character == "P":
                    white.append(rank)
                elif character == "p":
                    black.append(rank)
        if not white or not black:
            return None
        return sum(black) / len(black) - sum(white) / len(white)

    flipped = _flip_placement(placement)
    original_score = pawn_score(placement)
    flipped_score = pawn_score(flipped)
    if original_score is not None and flipped_score is not None and flipped_score > original_score:
        return flipped, "black"
    return placement, "white" if original_score is not None else "unknown"


def _plausible(placement: str) -> bool:
    return placement.count("K") == 1 and placement.count("k") == 1


def _page_box(image: EmbeddedPageImage, corners: _Corners, scale: float) -> PixelBox:
    local_x0 = corners.x0 / scale
    local_y0 = corners.y0 / scale
    local_x1 = corners.x1 / scale
    local_y1 = corners.y1 / scale
    width = image.page_box.x1 - image.page_box.x0
    height = image.page_box.y1 - image.page_box.y0
    return PixelBox(
        x0=max(image.page_box.x0, round(image.page_box.x0 + local_x0 / image.width * width)),
        y0=max(image.page_box.y0, round(image.page_box.y0 + local_y0 / image.height * height)),
        x1=min(image.page_box.x1, round(image.page_box.x0 + local_x1 / image.width * width)),
        y1=min(image.page_box.y1, round(image.page_box.y0 + local_y1 / image.height * height)),
    )


@final
class OnnxChessDiagramRecognizer:
    """Detect axis-aligned printed boards and classify their 64 squares locally."""

    def __init__(self, model_path: Path) -> None:
        if not isinstance(model_path, Path):
            raise TypeError("model_path must be Path")
        if not model_path.is_file():
            raise ChessDiagramError(
                "diagram_model_unavailable", "Chess diagram model is unavailable"
            )
        try:
            self._session = onnxruntime.InferenceSession(
                str(model_path), providers=["CPUExecutionProvider"]
            )
        except (OSError, ValueError, RuntimeError):
            raise ChessDiagramError(
                "diagram_model_invalid", "Chess diagram model could not be loaded"
            ) from None
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if (
            len(inputs) != 1
            or inputs[0].name != "tiles"
            or inputs[0].shape != ["n", 1024]
            or len(outputs) != 1
            or outputs[0].name != "probs"
            or outputs[0].shape != ["n", 13]
        ):
            raise ChessDiagramError(
                "diagram_model_invalid", "Chess diagram model has an unsupported interface"
            )

    def _classify(self, image: FloatImage, corners: _Corners) -> tuple[str, list[float], _Corners]:
        candidates = [corners]
        snapped = _snap_corners(image, corners)
        if snapped != corners:
            candidates.append(snapped)
        best: tuple[float, str, list[float], _Corners] | None = None
        for candidate in candidates:
            probabilities = self._session.run(
                ["probs"], {"tiles": _extract_tiles(image, candidate)}
            )[0]
            placement, confidences = _placement(np.asarray(probabilities, dtype=np.float32))
            mean = sum(confidences) / 64
            if best is None or mean > best[0]:
                best = (mean, placement, confidences, candidate)
        if best is None:
            raise AssertionError("diagram classification produced no candidates")
        return best[1], best[2], best[3]

    def _recognize_image(self, image: EmbeddedPageImage) -> ChessDiagramRecognition | None:
        gray, scale = _gray_image(image.png_bytes)
        candidates = _border_candidates(gray)
        detected = _find_corners(gray)
        if detected is not None:
            candidates.append(detected)
        candidates = list(dict.fromkeys(candidates))
        if not candidates:
            return None
        best: tuple[float, str, list[float], _Corners] | None = None
        for corners in candidates:
            placement, confidences, accepted_corners = self._classify(gray, corners)
            if min(confidences) < _CONFIDENCE_FLOOR or not _plausible(placement):
                continue
            mean = sum(confidences) / 64
            if best is None or mean > best[0]:
                best = (mean, placement, confidences, accepted_corners)
        if best is None:
            return None
        placement, confidences, accepted_corners = best[1], best[2], best[3]
        placement, orientation = _orientation(placement)
        if orientation == "black":
            confidences = list(reversed(confidences))
        try:
            positions = [chess.Board(f"{placement} {side} - - 0 1") for side in ("w", "b")]
        except ValueError:
            return None
        if not any(board.is_valid() for board in positions):
            return None
        return ChessDiagramRecognition(
            physical_page=image.physical_page,
            page_box=_page_box(image, accepted_corners, scale),
            image_sha256=diagram_image_sha256(image.png_bytes),
            piece_placement=placement,
            orientation=orientation,
            mean_confidence=sum(confidences) / 64,
            min_confidence=min(confidences),
            square_confidences=confidences,
            engine_name="fenshot-onnx",
            engine_version=DIAGRAM_RECOGNIZER_VERSION,
        )

    def recognize(self, request: ChessDiagramRecognitionRequest) -> list[ChessDiagramRecognition]:
        if type(request) is not ChessDiagramRecognitionRequest:
            raise TypeError("request must be ChessDiagramRecognitionRequest")
        results = [
            result
            for image in request.embedded_images
            if (result := self._recognize_image(image)) is not None
        ]
        if results:
            return results
        page_image = EmbeddedPageImage(
            physical_page=request.physical_page,
            width=request.page_width,
            height=request.page_height,
            page_box=PixelBox(x0=0, y0=0, x1=request.page_width, y1=request.page_height),
            png_bytes=request.page_png_bytes,
            content_sha256=diagram_image_sha256(request.page_png_bytes),
        )
        fallback = self._recognize_image(page_image)
        return [] if fallback is None else [fallback]


__all__ = ["OnnxChessDiagramRecognizer"]
