"""Canonical standard-chess position identity and authoritative move validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Self

import chess

POSITION_KEY_VERSION = "v1"
POSITION_KEY_PREFIX = f"standard:{POSITION_KEY_VERSION}:"

_STANDARD_UCI = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
_STANDARD_CASTLING = re.compile(r"^(?:K?Q?k?q?|-)$")
_MATERIAL_ORDER: tuple[tuple[chess.PieceType, str], ...] = (
    (chess.KING, "K"),
    (chess.QUEEN, "Q"),
    (chess.ROOK, "R"),
    (chess.BISHOP, "B"),
    (chess.KNIGHT, "N"),
    (chess.PAWN, "P"),
)


class PositionErrorCode(StrEnum):
    """Stable machine-readable failures exposed by the position domain."""

    INVALID_FEN = "invalid_fen"
    ILLEGAL_POSITION = "illegal_position"
    INVALID_UCI = "invalid_uci"
    ILLEGAL_MOVE = "illegal_move"


_ERROR_MESSAGES: dict[PositionErrorCode, str] = {
    PositionErrorCode.INVALID_FEN: "FEN must contain six valid standard-chess fields.",
    PositionErrorCode.ILLEGAL_POSITION: (
        "FEN must describe a structurally legal standard-chess position."
    ),
    PositionErrorCode.INVALID_UCI: "Move must use standard UCI notation.",
    PositionErrorCode.ILLEGAL_MOVE: "Move is not legal in the supplied position.",
}


class PositionError(ValueError):
    """A domain failure whose code and message remain stable across adapters."""

    def __init__(self, code: PositionErrorCode) -> None:
        self.code = code
        self.message = _ERROR_MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True, init=False)
class PositionState:
    """A validated position with separate full state and graph identity.

    Construct through :meth:`from_fen` (or directly with a FEN string). The
    public constructor validates all invariants so callers cannot instantiate
    a partially canonical state.
    """

    position_key: str
    full_fen: str
    canonical_fen: str
    piece_placement: str
    side_to_move: Literal["w", "b"]
    castling_rights: str
    en_passant: str
    material_signature: str

    def __init__(self, fen: str) -> None:
        board = _validated_board(fen)
        values = _state_values(board)
        for field_name, value in values.items():
            object.__setattr__(self, field_name, value)

    @classmethod
    def from_fen(cls, fen: str) -> Self:
        """Parse and validate a six-field standard-chess FEN."""

        return cls(fen)

    def apply_uci(self, uci: str) -> MoveResult:
        """Validate and apply one UCI move, returning both immutable states."""

        return apply_uci_move(self, uci)


@dataclass(frozen=True, slots=True)
class MoveResult:
    """The authoritative result of applying a legal standard-chess move."""

    uci: str
    san: str
    before: PositionState
    after: PositionState


def parse_position(fen: str) -> PositionState:
    """Return a validated, canonicalized position state."""

    return PositionState.from_fen(fen)


def apply_uci_move(before: PositionState, uci: str) -> MoveResult:
    """Apply a standard UCI move using python-chess as the rules authority."""

    if not isinstance(uci, str) or _STANDARD_UCI.fullmatch(uci) is None:
        raise PositionError(PositionErrorCode.INVALID_UCI)

    try:
        move = chess.Move.from_uci(uci)
    except ValueError as error:
        raise PositionError(PositionErrorCode.INVALID_UCI) from error

    board = chess.Board(before.full_fen, chess960=False)
    if not board.is_legal(move):
        raise PositionError(PositionErrorCode.ILLEGAL_MOVE)

    san = board.san(move)
    board.push(move)
    after = PositionState.from_fen(board.fen(en_passant="fen"))
    return MoveResult(uci=move.uci(), san=san, before=before, after=after)


def _validated_board(fen: str) -> chess.Board:
    if not isinstance(fen, str):
        raise PositionError(PositionErrorCode.INVALID_FEN)

    normalized_input = fen.strip()
    fields = normalized_input.split()
    if len(fields) != 6:
        raise PositionError(PositionErrorCode.INVALID_FEN)
    piece_field, _, castling_field, _, _, _ = fields
    if "~" in piece_field or _STANDARD_CASTLING.fullmatch(castling_field) is None:
        raise PositionError(PositionErrorCode.INVALID_FEN)

    try:
        board = chess.Board(normalized_input, chess960=False)
    except ValueError as error:
        raise PositionError(PositionErrorCode.INVALID_FEN) from error

    if not board.is_valid():
        raise PositionError(PositionErrorCode.ILLEGAL_POSITION)
    return board


def _state_values(board: chess.Board) -> dict[str, str]:
    piece_placement = board.board_fen()
    side_to_move: Literal["w", "b"] = "w" if board.turn == chess.WHITE else "b"
    castling_rights = board.castling_xfen() or "-"
    en_passant = _legal_en_passant(board)
    identity = f"{piece_placement} {side_to_move} {castling_rights} {en_passant}"
    return {
        "position_key": f"{POSITION_KEY_PREFIX}{identity}",
        "full_fen": board.fen(en_passant="fen"),
        "canonical_fen": f"{identity} 0 1",
        "piece_placement": piece_placement,
        "side_to_move": side_to_move,
        "castling_rights": castling_rights,
        "en_passant": en_passant,
        "material_signature": _material_signature(board),
    }


def _legal_en_passant(board: chess.Board) -> str:
    if board.ep_square is None or not board.has_legal_en_passant():
        return "-"
    return chess.square_name(board.ep_square)


def _material_signature(board: chess.Board) -> str:
    def for_color(color: chess.Color) -> str:
        return "".join(
            f"{symbol}{len(board.pieces(piece_type, color))}"
            for piece_type, symbol in _MATERIAL_ORDER
        )

    return f"v1:w:{for_color(chess.WHITE)}|b:{for_color(chess.BLACK)}"
