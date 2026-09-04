"""Portable chess-diagram recognition values and replaceable local port."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterable
from typing import Annotated, Literal, Protocol, runtime_checkable

import chess
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .evidence import MAX_PIXELS, MAX_PNG_BYTES, EmbeddedPageImage, PixelBox

DIAGRAM_EVIDENCE_SCHEMA = "chess-workbench/chess-diagram-evidence/1.0"
DIAGRAM_RECOGNIZER_VERSION = "fenshot-onnx-v2+layout-v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ChessDiagramRecognitionRequest(_StrictModel):
    """One rendered PDF page plus generic embedded-image candidates."""

    physical_page: Annotated[int, Field(ge=1)]
    page_width: Annotated[int, Field(ge=1, le=10_000)]
    page_height: Annotated[int, Field(ge=1, le=10_000)]
    page_png_bytes: Annotated[bytes, Field(min_length=1, max_length=MAX_PNG_BYTES)]
    embedded_images: list[EmbeddedPageImage] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_page(self) -> ChessDiagramRecognitionRequest:
        if self.page_width * self.page_height > MAX_PIXELS:
            raise ValueError("page exceeds diagram-recognition pixel limit")
        if any(image.physical_page != self.physical_page for image in self.embedded_images):
            raise ValueError("embedded image physical page must match request")
        return self


class ChessDiagramRecognition(_StrictModel):
    """A locally recognized board placement with provenance and confidence."""

    physical_page: Annotated[int, Field(ge=1)]
    page_box: PixelBox
    image_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    piece_placement: Annotated[str, StringConstraints(min_length=15, max_length=100)]
    orientation: Literal["white", "black", "unknown"]
    mean_confidence: Annotated[float, Field(ge=0, le=1)]
    min_confidence: Annotated[float, Field(ge=0, le=1)]
    square_confidences: list[Annotated[float, Field(ge=0, le=1)]]
    engine_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    engine_version: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]

    @model_validator(mode="after")
    def _check_position(self) -> ChessDiagramRecognition:
        if len(self.square_confidences) != 64:
            raise ValueError("square_confidences must contain exactly 64 values")
        if abs(sum(self.square_confidences) / 64 - self.mean_confidence) > 1e-6:
            raise ValueError("mean_confidence must match square confidences")
        if abs(min(self.square_confidences) - self.min_confidence) > 1e-6:
            raise ValueError("min_confidence must match square confidences")
        try:
            boards = [chess.Board(f"{self.piece_placement} {side} - - 0 1") for side in ("w", "b")]
        except ValueError:
            raise ValueError("piece_placement must be valid FEN placement") from None
        if any(board.board_fen() != self.piece_placement for board in boards) or not any(
            board.is_valid() for board in boards
        ):
            raise ValueError("piece_placement must describe a locally valid chess position")
        return self


class ChessDiagramError(RuntimeError):
    """Sanitized local recognition failure."""

    def __init__(self, code: str, message: str) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


@runtime_checkable
class ChessDiagramRecognizer(Protocol):
    def recognize(
        self, request: ChessDiagramRecognitionRequest
    ) -> list[ChessDiagramRecognition]: ...


class NullChessDiagramRecognizer:
    """Configured fallback: ordinary PDF evidence still works without a model."""

    def recognize(self, request: ChessDiagramRecognitionRequest) -> list[ChessDiagramRecognition]:
        if type(request) is not ChessDiagramRecognitionRequest:
            raise TypeError("request must be ChessDiagramRecognitionRequest")
        return []


class ScriptedChessDiagramRecognizer:
    """Small deterministic fake for the shared PDF pipeline."""

    def __init__(
        self, outcomes: Iterable[list[ChessDiagramRecognition] | ChessDiagramError]
    ) -> None:
        values = [copy.deepcopy(outcome) for outcome in outcomes]
        if not values:
            raise ValueError("at least one scripted outcome is required")
        if any(
            not isinstance(outcome, ChessDiagramError)
            and (
                not isinstance(outcome, list)
                or any(type(item) is not ChessDiagramRecognition for item in outcome)
            )
            for outcome in values
        ):
            raise TypeError("outcomes must contain recognition lists or ChessDiagramError")
        self._outcomes = values
        self._calls: list[ChessDiagramRecognitionRequest] = []

    @property
    def calls(self) -> tuple[ChessDiagramRecognitionRequest, ...]:
        return tuple(copy.deepcopy(self._calls))

    def recognize(self, request: ChessDiagramRecognitionRequest) -> list[ChessDiagramRecognition]:
        if type(request) is not ChessDiagramRecognitionRequest:
            raise TypeError("request must be ChessDiagramRecognitionRequest")
        self._calls.append(copy.deepcopy(request))
        if not self._outcomes:
            raise AssertionError("ScriptedChessDiagramRecognizer exhausted")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, ChessDiagramError):
            raise outcome
        return copy.deepcopy(outcome)


def diagram_image_sha256(png_bytes: bytes) -> str:
    if type(png_bytes) is not bytes:
        raise TypeError("png_bytes must be bytes")
    return hashlib.sha256(png_bytes).hexdigest()


__all__ = [
    "DIAGRAM_EVIDENCE_SCHEMA",
    "DIAGRAM_RECOGNIZER_VERSION",
    "ChessDiagramError",
    "ChessDiagramRecognition",
    "ChessDiagramRecognitionRequest",
    "ChessDiagramRecognizer",
    "NullChessDiagramRecognizer",
    "ScriptedChessDiagramRecognizer",
    "diagram_image_sha256",
]
