"""Bounded, lossless PGN semantic document parser.

PGN is an adapter format, not the internal course model.  This module has no
database or HTTP dependencies and deliberately exposes every semantic field
needed by ADR 0007/0008 before persistence begins.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
from typing import Any, Literal

import chess
import chess.pgn

MAX_GAMES = 1_000
MAX_MOVE_NODES = 50_000
MAX_RAV_DEPTH = 128
DEFAULT_DEADLINE_SECONDS = 15.0
RESULTS = frozenset({"1-0", "0-1", "1/2-1/2", "*"})

_TAG_LINE = re.compile(
    r'^\s*\[\s*([A-Za-z][A-Za-z0-9_]*)\s+"((?:\\.|[^"\\])*)"\s*\]\s*$',
)
_RESULT_TOKEN = re.compile(r"(?<!\S)(1-0|0-1|1/2-1/2|\*)(?!\S)")


@dataclass(frozen=True, slots=True)
class PgnHeader:
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class PgnNode:
    """One source-path position; children retain mainline/RAV order."""

    ply: int
    fen: str
    san: str | None
    uci: str | None
    nags: tuple[int, ...]
    starting_comment: str
    comment: str
    children: tuple[PgnNode, ...]

    @property
    def nag(self) -> int | None:
        """Compatibility view for the Stage 2 single-NAG occurrence field."""

        return self.nags[0] if self.nags else None


@dataclass(frozen=True, slots=True)
class PgnGame:
    """One game plus its exact semantic header set and source span."""

    headers: dict[str, str]
    header_items: tuple[PgnHeader, ...]
    root: PgnNode
    result: str
    source_start: int
    source_end: int

    def header(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name.lower(), default)


@dataclass(frozen=True, slots=True)
class PgnDocument:
    games: tuple[PgnGame, ...]
    move_count: int


class PgnError(ValueError):
    """Safe, structured parse failure suitable for an HTTP adapter."""

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        game_index: int | None = None,
        ply: int | None = None,
        path: tuple[int, ...] | None = None,
        line: int | None = None,
        column: int | None = None,
        token: str | None = None,
        kind: Literal["invalid_pgn", "pgn_limit_exceeded"] = "invalid_pgn",
    ) -> None:
        self.reason = reason
        self.game_index = game_index
        self.ply = ply
        self.path = path
        self.line = line
        self.column = column
        self.token = token
        self.kind = kind
        super().__init__(message)

    def details(self) -> dict[str, object]:
        values: dict[str, object] = {"reason": self.reason}
        for key in ("game_index", "ply", "path", "line", "column", "token"):
            value = getattr(self, key)
            if value is not None:
                values[key] = list(value) if key == "path" else value
        return values


@dataclass(slots=True)
class _DraftNode:
    python_node: Any
    ply: int
    path: tuple[int, ...]
    fen: str
    san: str
    uci: str


def parse_pgn_document(
    pgn_text: str,
    *,
    max_games: int = MAX_GAMES,
    max_move_nodes: int = MAX_MOVE_NODES,
    max_rav_depth: int = MAX_RAV_DEPTH,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
) -> PgnDocument:
    """Parse every game with fixed limits and without recursive tree walking."""

    if "\x00" in pgn_text:
        raise PgnError("nul_byte", "PGN input contains a NUL byte")
    if not pgn_text.strip():
        raise PgnError("empty_document", "no PGN game found in input")
    if min(max_games, max_move_nodes, max_rav_depth) < 1 or deadline_seconds <= 0:
        raise ValueError("PGN parser limits must be positive")

    deadline = time.monotonic() + deadline_seconds
    handle = StringIO(pgn_text)
    games: list[PgnGame] = []
    total_moves = 0

    while True:
        _check_deadline(deadline, len(games))
        source_start = handle.tell()
        game = chess.pgn.read_game(handle)
        source_end = handle.tell()
        if game is None:
            break
        game_index = len(games)
        if game_index >= max_games:
            raise _limit("game_count", game_index, f"PGN exceeds {max_games} games")
        if game.errors:
            raise PgnError(
                "parser_error",
                "PGN contains an illegal or malformed move",
                game_index=game_index,
                token=_safe_error_token(game.errors[0]),
            )

        raw_game = pgn_text[source_start:source_end]
        explicit_headers = _explicit_headers(raw_game, game_index, pgn_text, source_start)
        movetext_result = _movetext_result(raw_game)
        if movetext_result is None:
            raise PgnError(
                "missing_result",
                "PGN movetext is missing a termination marker",
                game_index=game_index,
            )
        explicit_result = next(
            (header.value for header in explicit_headers if header.name.lower() == "result"),
            None,
        )
        if explicit_result is not None and explicit_result != movetext_result:
            raise PgnError(
                "result_conflict",
                "PGN Result header conflicts with movetext termination",
                game_index=game_index,
                token=movetext_result,
            )

        header_items = _canonical_headers(game, explicit_headers, movetext_result)
        headers = {header.name.lower(): header.value for header in header_items}
        root, move_count = _build_tree(
            game,
            game_index=game_index,
            current_total=total_moves,
            max_move_nodes=max_move_nodes,
            max_rav_depth=max_rav_depth,
            deadline=deadline,
        )
        total_moves += move_count
        games.append(
            PgnGame(
                headers=headers,
                header_items=header_items,
                root=root,
                result=movetext_result,
                source_start=source_start,
                source_end=source_end,
            )
        )

    if not games:
        raise PgnError("empty_document", "no PGN game found in input")
    return PgnDocument(games=tuple(games), move_count=total_moves)


def parse_pgn(pgn_text: str) -> PgnGame:
    """Compatibility entry point for callers that explicitly require one game."""

    document = parse_pgn_document(pgn_text)
    if len(document.games) != 1:
        raise PgnError(
            "multiple_games",
            "parse_pgn requires exactly one game; use parse_pgn_document",
        )
    return document.games[0]


def semantic_hash(game: PgnGame) -> str:
    """Return a stable digest covering every semantic game field."""

    digest = sha256()

    def field(value: object) -> None:
        encoded = repr(value).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)

    field(tuple((header.name, header.value) for header in game.header_items))
    field(game.result)
    stack = [game.root]
    while stack:
        node = stack.pop()
        for value in (
            node.ply,
            node.fen,
            node.san,
            node.uci,
            node.nags,
            node.starting_comment,
            node.comment,
            len(node.children),
        ):
            field(value)
        stack.extend(reversed(node.children))
    return digest.hexdigest()


def _build_tree(
    game: chess.pgn.Game,
    *,
    game_index: int,
    current_total: int,
    max_move_nodes: int,
    max_rav_depth: int,
    deadline: float,
) -> tuple[PgnNode, int]:
    board = game.board()
    root_fen = board.fen(en_passant="fen")
    built: dict[int, PgnNode] = {}
    drafts: dict[int, _DraftNode] = {}
    move_count = 0

    # Actions share one mutable board. An exit always pops before the next
    # sibling is entered, so memory is O(tree nodes + current path), not one
    # board copy per pending ancestor.
    stack: list[tuple[str, Any, int, int, tuple[int, ...]]] = []
    for child_index in range(len(game.variations) - 1, -1, -1):
        stack.append(
            ("enter", game.variations[child_index], 1, int(child_index > 0), (child_index,))
        )

    while stack:
        action, python_node, ply, rav_depth, path = stack.pop()
        if action == "exit":
            children = tuple(built[id(child)] for child in python_node.variations)
            draft = drafts.pop(id(python_node))
            built[id(python_node)] = PgnNode(
                ply=draft.ply,
                fen=draft.fen,
                san=draft.san,
                uci=draft.uci,
                nags=_nags(python_node),
                starting_comment=str(getattr(python_node, "starting_comment", "") or ""),
                comment=str(getattr(python_node, "comment", "") or ""),
                children=children,
            )
            board.pop()
            continue

        _check_deadline(deadline, game_index, ply=ply, path=path)
        if rav_depth > max_rav_depth:
            raise _limit(
                "rav_depth",
                game_index,
                f"PGN exceeds RAV nesting limit {max_rav_depth}",
                ply=ply,
                path=path,
            )
        move_count += 1
        if current_total + move_count > max_move_nodes:
            raise _limit(
                "move_count",
                game_index,
                f"PGN exceeds {max_move_nodes} move occurrences",
                ply=ply,
                path=path,
            )
        move = python_node.move
        if not isinstance(move, chess.Move) or move not in board.legal_moves:
            raise PgnError(
                "illegal_move",
                "PGN contains an illegal move",
                game_index=game_index,
                ply=ply,
                path=path,
                token=str(move)[:80],
            )
        san = board.san(move)
        board.push(move)
        drafts[id(python_node)] = _DraftNode(
            python_node=python_node,
            ply=ply,
            path=path,
            fen=board.fen(en_passant="fen"),
            san=san,
            uci=move.uci().lower(),
        )
        stack.append(("exit", python_node, ply, rav_depth, path))
        for child_index in range(len(python_node.variations) - 1, -1, -1):
            child = python_node.variations[child_index]
            stack.append(
                (
                    "enter",
                    child,
                    ply + 1,
                    rav_depth + int(child_index > 0),
                    (*path, child_index),
                )
            )

    root = PgnNode(
        ply=0,
        fen=root_fen,
        san=None,
        uci=None,
        nags=_nags(game),
        starting_comment=str(getattr(game, "starting_comment", "") or ""),
        comment=str(getattr(game, "comment", "") or ""),
        children=tuple(built[id(child)] for child in game.variations),
    )
    return root, move_count


def _explicit_headers(
    raw_game: str,
    game_index: int,
    document: str,
    source_start: int,
) -> tuple[PgnHeader, ...]:
    headers: list[PgnHeader] = []
    names: set[str] = set()
    offset = source_start
    in_headers = True
    for line in raw_game.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            offset += len(line)
            if headers:
                in_headers = False
            continue
        match = _TAG_LINE.fullmatch(line.rstrip("\r\n")) if in_headers else None
        if match is None:
            break
        name = match.group(1)
        if name in names:
            line_number, column = _line_column(document, offset)
            raise PgnError(
                "duplicate_tag",
                f"PGN contains duplicate tag {name}",
                game_index=game_index,
                line=line_number,
                column=column,
                token=name,
            )
        names.add(name)
        headers.append(PgnHeader(name=name, value=_unescape_tag(match.group(2))))
        offset += len(line)
    return tuple(headers)


def _canonical_headers(
    game: chess.pgn.Game,
    explicit: tuple[PgnHeader, ...],
    result: str,
) -> tuple[PgnHeader, ...]:
    explicit_names = {item.name for item in explicit}
    items = list(explicit)
    for name, value in game.headers.items():
        if name not in explicit_names:
            items.append(PgnHeader(name=name, value=str(value)))
    for index, header in enumerate(items):
        if header.name.lower() == "result":
            items[index] = PgnHeader(name=header.name, value=result)
            break
    else:
        items.append(PgnHeader(name="Result", value=result))
    return tuple(items)


def _movetext_result(raw_game: str) -> str | None:
    # Remove the initial tag section before token scanning.
    lines = raw_game.splitlines(keepends=True)
    start = 0
    saw_tag = False
    for line in lines:
        if _TAG_LINE.fullmatch(line.rstrip("\r\n")):
            saw_tag = True
            start += len(line)
            continue
        if saw_tag and not line.strip():
            start += len(line)
            continue
        break
    text = raw_game[start:]
    cleaned: list[str] = []
    brace_depth = 0
    rav_depth = 0
    semicolon = False
    for char in text:
        if semicolon:
            if char in "\r\n":
                semicolon = False
                cleaned.append(" ")
            continue
        if brace_depth:
            if char == "}":
                brace_depth -= 1
            continue
        if char == "{":
            brace_depth = 1
            cleaned.append(" ")
        elif char == ";":
            semicolon = True
            cleaned.append(" ")
        elif char == "(":
            rav_depth += 1
            cleaned.append(" ")
        elif char == ")":
            rav_depth = max(0, rav_depth - 1)
            cleaned.append(" ")
        elif rav_depth == 0:
            cleaned.append(char)
        else:
            cleaned.append(" ")
    matches = list(_RESULT_TOKEN.finditer("".join(cleaned)))
    return matches[-1].group(1) if matches else None


def _nags(node: Any) -> tuple[int, ...]:
    return tuple(sorted({int(nag) for nag in (getattr(node, "nags", set()) or set())}))


def _unescape_tag(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\\", "\\")


def _line_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    return line, offset - last_newline


def _safe_error_token(error: Exception) -> str:
    return str(error).replace("\n", " ")[:160]


def _check_deadline(
    deadline: float,
    game_index: int,
    *,
    ply: int | None = None,
    path: tuple[int, ...] | None = None,
) -> None:
    if time.monotonic() > deadline:
        raise _limit(
            "deadline",
            game_index,
            "PGN parsing exceeded its deadline",
            ply=ply,
            path=path,
        )


def _limit(
    reason: str,
    game_index: int,
    message: str,
    *,
    ply: int | None = None,
    path: tuple[int, ...] | None = None,
) -> PgnError:
    return PgnError(
        reason,
        message,
        game_index=game_index,
        ply=ply,
        path=path,
        kind="pgn_limit_exceeded",
    )
