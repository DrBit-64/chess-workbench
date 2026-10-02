"""Lightweight source-span hints for explicit multi-move chess notation.

These hints have no tree semantics. The interpreter still decides whether a
run is a played line, an alternative, or merely an explanatory mention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .prompting import CcefPromptContext

_NUMBER = re.compile(r"(?<![A-Za-z0-9-])[1-9]\d{0,2}(?:\s*\.{1,3}|…)?\s*")
_SAN_CORE = (
    r"(?:O-O(?:-O)?|0-0(?:-0)?|[a-h]?[xX]?[a-h][18]=?[QRBN]|[KQRBN♔♕♖♗♘♙♚♛♜♝♞♟]?[a-h]?[1-8]?[xX]?[a-h][1-8])"
    r"[+#]?[!?]*"
)
_MOVE = re.compile(_SAN_CORE + r"(?![A-Za-z0-9])")
_ADJACENT_MOVE = re.compile(_SAN_CORE)
_SPACE = re.compile(r"\s+")
_BOARD_GLYPH_ROW = re.compile(r"^[1-8]\s+[A-Za-z0-9]{8}$")
_BOARD_FILES = re.compile(r"^a\s+b\s+c\s+d\s+e\s+f\s+g\s+h$")


def is_board_glyph_line(text: str) -> bool:
    """Printed board artwork is visual evidence, not chess-book prose."""
    return bool(_BOARD_GLYPH_ROW.fullmatch(text.strip()) or _BOARD_FILES.fullmatch(text.strip()))


@dataclass(frozen=True)
class MoveRunHint:
    page: int
    order: int
    start: int
    end: int
    tokens: tuple[str, ...]
    paren_depth: int = 0


def _paren_depth(source: str, base: int, offset: int) -> int:
    value = base
    for char in source[:offset]:
        value = max(0, value + (char == "(") - (char == ")"))
    return value


def find_move_runs(context: CcefPromptContext) -> tuple[MoveRunHint, ...]:
    """Find runs of at least two SAN-like tokens following a printed move number."""
    hints: list[MoveRunHint] = []
    for page in context.pages:
        depth = 0
        for index, entry in enumerate(page.fragments):
            source = entry.fragment.text

            # A wrapped score may end one line after a white move and resume
            # with an unnumbered black move on the next line. Keep the first
            # printed token visible to the interpreter.
            if index > 0:
                previous = page.fragments[index - 1]
                wrapped_number = bool(_TRAILING_NUMBER.search(previous.fragment.text))
                carries_score = wrapped_number or any(
                    hint.page == page.physical_page
                    and hint.order == previous.order
                    and hint.end == len(previous.fragment.text.rstrip())
                    for hint in hints
                )
                leading = _MOVE.match(source)
                if carries_score and leading is not None:
                    cursor = leading.end()
                    tokens = [leading.group()]
                    while True:
                        gap = _SPACE.match(source, cursor)
                        if gap is None:
                            break
                        next_at = gap.end()
                        number_after = _NUMBER.match(source, next_at)
                        if number_after is not None:
                            next_at = number_after.end()
                        move = _MOVE.match(source, next_at)
                        if move is None:
                            break
                        tokens.append(move.group())
                        cursor = move.end()
                    first_gap = _SPACE.match(source, leading.end())
                    if (
                        len(tokens) >= 2
                        and first_gap is not None
                        and (wrapped_number or _NUMBER.match(source, first_gap.end()))
                    ):
                        hints.append(
                            MoveRunHint(
                                page=page.physical_page,
                                order=entry.order,
                                start=0,
                                end=cursor,
                                tokens=tuple(tokens),
                                paren_depth=depth,
                            )
                        )
            for number in _NUMBER.finditer(source):
                cursor = number.end()
                first = _MOVE.match(source, cursor)
                if first is None:
                    continue
                tokens = [first.group()]
                cursor = first.end()
                while True:
                    gap = _SPACE.match(source, cursor)
                    if gap is None:
                        break
                    next_at = gap.end()
                    number_after = _NUMBER.match(source, next_at)
                    if number_after is not None:
                        next_at = number_after.end()
                    move = _MOVE.match(source, next_at)
                    if move is None:
                        break
                    tokens.append(move.group())
                    cursor = move.end()
                if len(tokens) >= 2 and not any(
                    old.page == page.physical_page
                    and old.order == entry.order
                    and old.start <= number.start() < old.end
                    for old in hints
                ):
                    hints.append(
                        MoveRunHint(
                            page=page.physical_page,
                            order=entry.order,
                            start=number.start(),
                            end=cursor,
                            tokens=tuple(tokens),
                            paren_depth=_paren_depth(source, depth, number.start()),
                        )
                    )
            for char in source:
                depth = max(0, depth + (char == "(") - (char == ")"))
    return tuple(hints)


@dataclass(frozen=True)
class ChoiceHint:
    page: int
    options: tuple[str, ...]


_CHOICE_MOVE = re.compile(r"(?<![A-Za-z0-9])\d{1,3}(?:\.{1,3}|…)[KQRBNa-h][A-Za-z0-9xX+#?!]*")


def find_choice_hints(context: CcefPromptContext) -> tuple[ChoiceHint, ...]:
    """Flag explicit same-question printed options without choosing a mainline."""
    hints = []
    for page in context.pages:
        entries = page.fragments
        for index, entry in enumerate(entries):
            if "choice" not in entry.fragment.text.lower():
                continue
            nearby = " ".join(candidate.fragment.text for candidate in entries[index : index + 3])
            options = tuple(match.group() for match in _CHOICE_MOVE.finditer(nearby))
            if len(options) >= 2:
                hints.append(ChoiceHint(page=page.physical_page, options=options))
    return tuple(hints)


@dataclass(frozen=True)
class DiagramSeed:
    page: int
    order: int
    fen: str
    move_number: int
    side_to_move: str


def find_diagram_seeds(context: CcefPromptContext) -> tuple[DiagramSeed, ...]:
    """Read operational seeds already resolved by the local diagram recognizer."""
    import json

    seeds = []
    for page in context.pages:
        for entry in page.fragments:
            if entry.fragment.origin != "diagram":
                continue
            try:
                marker = json.loads(entry.fragment.text)
            except json.JSONDecodeError:
                continue
            if not isinstance(marker, dict) or marker.get("kind") != "chess_diagram":
                continue
            next_move = marker.get("next_formal_move")
            fen = marker.get("operational_fen")
            if not isinstance(next_move, dict) or not isinstance(fen, str):
                continue
            number, side = next_move.get("move_number"), next_move.get("side_to_move")
            if type(number) is int and side in {"w", "b"}:
                seeds.append(
                    DiagramSeed(
                        page=page.physical_page,
                        order=entry.order,
                        fen=fen,
                        move_number=number,
                        side_to_move=side,
                    )
                )
    return tuple(seeds)


@dataclass(frozen=True)
class NumberedMoveHint:
    page: int
    order: int
    quote: str
    context: str
    paren_depth: int


def find_numbered_move_hints(context: CcefPromptContext) -> tuple[NumberedMoveHint, ...]:
    """Expose printed move mentions and their advisory parenthesis nesting."""
    hints = []
    for page in context.pages:
        depth = 0
        for entry in page.fragments:
            source = entry.fragment.text
            if entry.fragment.origin == "diagram":
                continue
            cursor = 0
            for number in _NUMBER.finditer(source):
                for char in source[cursor : number.start()]:
                    depth = max(0, depth + (char == "(") - (char == ")"))
                move = _MOVE.match(source, number.end())
                if move is None:
                    cursor = number.end()
                    continue
                hints.append(
                    NumberedMoveHint(
                        page=page.physical_page,
                        order=entry.order,
                        quote=source[number.start() : move.end()],
                        context=source[
                            max(0, number.start() - 30) : min(len(source), move.end() + 30)
                        ],
                        paren_depth=depth,
                    )
                )
                cursor = move.end()
            for char in source[cursor:]:
                depth = max(0, depth + (char == "(") - (char == ")"))
    return tuple(hints)


@dataclass(frozen=True)
class WrappedMoveHint:
    page: int
    number_order: int
    move_order: int
    number_text: str
    move_text: str


_TRAILING_NUMBER = re.compile(r"(?<![A-Za-z0-9-])([1-9]\d{0,2}(?:\s*\.{1,3})?)\s*$")


def find_wrapped_moves(context: CcefPromptContext) -> tuple[WrappedMoveHint, ...]:
    """Find a move whose printed number is at the end of the previous line."""
    hints = []
    for page in context.pages:
        for previous, current in zip(page.fragments, page.fragments[1:], strict=False):
            numbered = _TRAILING_NUMBER.search(previous.fragment.text)
            move = _MOVE.match(current.fragment.text)
            if numbered is None or move is None:
                continue
            hints.append(
                WrappedMoveHint(
                    page=page.physical_page,
                    number_order=previous.order,
                    move_order=current.order,
                    number_text=numbered.group(1),
                    move_text=move.group(),
                )
            )
    return tuple(hints)
