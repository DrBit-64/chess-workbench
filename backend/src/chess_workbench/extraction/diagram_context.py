"""Resolve local chess-diagram reads into the shared text evidence stream."""

from __future__ import annotations

import json
import re
from typing import Annotated, Self

import chess
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .diagram import DIAGRAM_EVIDENCE_SCHEMA, ChessDiagramRecognition
from .evidence import NormalizedBox, SourceEvidenceFragment, source_fragment_sha256

_FORMAL_MOVE = re.compile(
    r"(?<![\w.])(?P<number>[1-9][0-9]{0,2})\."
    r"(?P<black>\.\.)?\s*"
    r"(?P<move>(?:O-O-O|O-O|0-0-0|0-0|"
    r"[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?)[+#?!]*)"
)
_MOVE_ANNOTATION = re.compile(r"[!?]+$")
_MAX_LOOKAHEAD_PAGES = 2
_MAX_MOVE_CANDIDATES = 16


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class DiagramEvidencePage(_StrictModel):
    physical_page: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(ge=1, le=10_000)]
    height: Annotated[int, Field(ge=1, le=10_000)]
    fragments: list[SourceEvidenceFragment] = Field(default_factory=list)
    recognitions: list[ChessDiagramRecognition] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_page(self) -> Self:
        if any(fragment.physical_page != self.physical_page for fragment in self.fragments):
            raise ValueError("fragment physical page must match diagram evidence page")
        if any(
            recognition.physical_page != self.physical_page for recognition in self.recognitions
        ):
            raise ValueError("recognition physical page must match diagram evidence page")
        return self


class ResolvedDiagramEvidencePage(_StrictModel):
    physical_page: Annotated[int, Field(ge=1)]
    fragments: list[SourceEvidenceFragment]
    diagram_count: Annotated[int, Field(ge=0)]
    unresolved_diagram_count: Annotated[int, Field(ge=0)]


def _rotate_placement(piece_placement: str) -> str:
    rows: list[str] = []
    for row in piece_placement.split("/"):
        expanded = "".join("1" * int(value) if value.isdigit() else value for value in row)
        rotated = expanded[::-1]
        compact = ""
        empty = 0
        for value in rotated:
            if value == "1":
                empty += 1
            else:
                if empty:
                    compact += str(empty)
                    empty = 0
                compact += value
        if empty:
            compact += str(empty)
        rows.append(compact)
    return "/".join(rows[::-1])


def _move_candidates(
    pages: list[DiagramEvidencePage], recognition: ChessDiagramRecognition
) -> list[tuple[int, str, str]]:
    candidates: list[tuple[int, str, str]] = []
    for page in pages:
        if not (
            recognition.physical_page
            <= page.physical_page
            <= recognition.physical_page + _MAX_LOOKAHEAD_PAGES
        ):
            continue
        for fragment in page.fragments:
            if (
                page.physical_page == recognition.physical_page
                and fragment.box.y1 <= recognition.page_box.y0 / page.height
            ):
                continue
            for match in _FORMAL_MOVE.finditer(fragment.text):
                candidates.append(
                    (
                        int(match.group("number")),
                        "b" if match.group("black") else "w",
                        match.group("move"),
                    )
                )
                if len(candidates) >= _MAX_MOVE_CANDIDATES:
                    return candidates
    return candidates


def _resolve_operational_position(
    pages: list[DiagramEvidencePage], recognition: ChessDiagramRecognition
) -> tuple[str, int, str, str] | None:
    placements = [recognition.piece_placement]
    if recognition.orientation == "unknown":
        rotated = _rotate_placement(recognition.piece_placement)
        if rotated != placements[0]:
            placements.append(rotated)
    for move_number, side, source_move in _move_candidates(pages, recognition):
        legal: list[tuple[str, str]] = []
        san = _MOVE_ANNOTATION.sub("", source_move.replace("0", "O"))
        for placement in placements:
            try:
                board = chess.Board(f"{placement} {side} - - 0 {move_number}")
                board.parse_san(san)
            except ValueError:
                continue
            if board.is_valid():
                legal.append((placement, board.fen(en_passant="fen")))
        if len(legal) == 1:
            return legal[0][1], move_number, side, source_move
    return None


def _diagram_fragment(
    pages: list[DiagramEvidencePage],
    page: DiagramEvidencePage,
    recognition: ChessDiagramRecognition,
) -> SourceEvidenceFragment:
    resolved = _resolve_operational_position(pages, recognition)
    box = NormalizedBox(
        x0=recognition.page_box.x0 / page.width,
        y0=recognition.page_box.y0 / page.height,
        x1=recognition.page_box.x1 / page.width,
        y1=recognition.page_box.y1 / page.height,
    )
    document: dict[str, object] = {
        "schema": DIAGRAM_EVIDENCE_SCHEMA,
        "kind": "chess_diagram",
        "piece_placement": recognition.piece_placement,
        "orientation": recognition.orientation,
        "operational_fen": None if resolved is None else resolved[0],
        "next_formal_move": (
            None
            if resolved is None
            else {
                "move_number": resolved[1],
                "side_to_move": resolved[2],
                "source_token": resolved[3],
            }
        ),
        "fen_assumptions": {
            "castling": "unavailable_assume_none",
            "en_passant": "unavailable_assume_none",
            "halfmove_clock": "unavailable_assume_zero",
        },
        "recognition": {
            "image_sha256": recognition.image_sha256,
            "mean_confidence": recognition.mean_confidence,
            "min_confidence": recognition.min_confidence,
            "engine_name": recognition.engine_name,
            "engine_version": recognition.engine_version,
        },
    }
    text = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = source_fragment_sha256(
        page.physical_page,
        box,
        text,
        "diagram",
        recognition.engine_name,
        recognition.engine_version,
    )
    return SourceEvidenceFragment(
        physical_page=page.physical_page,
        box=box,
        text=text,
        origin="diagram",
        confidence=recognition.mean_confidence,
        engine_name=recognition.engine_name,
        engine_version=recognition.engine_version,
        fragment_sha256=digest,
    )


def resolve_diagram_evidence(
    pages: list[DiagramEvidencePage],
) -> list[ResolvedDiagramEvidencePage]:
    """Insert recognized diagrams into existing page evidence without a new pipeline."""

    if type(pages) is not list or any(type(page) is not DiagramEvidencePage for page in pages):
        raise TypeError("pages must be a list of DiagramEvidencePage")
    if [page.physical_page for page in pages] != sorted(
        page.physical_page for page in pages
    ) or len({page.physical_page for page in pages}) != len(pages):
        raise ValueError("diagram evidence pages must be unique and ascending")

    resolved_pages: list[ResolvedDiagramEvidencePage] = []
    for page in pages:
        additions = [
            _diagram_fragment(pages, page, recognition)
            for recognition in sorted(
                page.recognitions,
                key=lambda value: (value.page_box.y0, value.page_box.x0),
            )
        ]
        merged = list(page.fragments)
        for addition in additions:
            insert_at = next(
                (
                    index
                    for index, fragment in enumerate(merged)
                    if fragment.box.y0 >= addition.box.y0
                ),
                len(merged),
            )
            merged.insert(insert_at, addition)
        resolved_pages.append(
            ResolvedDiagramEvidencePage(
                physical_page=page.physical_page,
                fragments=merged,
                diagram_count=len(additions),
                unresolved_diagram_count=sum(
                    '"operational_fen":null' in addition.text for addition in additions
                ),
            )
        )
    return resolved_pages


__all__ = [
    "DiagramEvidencePage",
    "ResolvedDiagramEvidencePage",
    "resolve_diagram_evidence",
]
