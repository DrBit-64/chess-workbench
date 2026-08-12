"""Deterministic python-chess normalization of CCEF ``move_sequence`` items.

Reconstructs every source-ordered branch from its declared initial position
and writes authoritative SAN/UCI/before-after FEN values only for uniquely
legal and context-consistent nodes. Illegal, ambiguous, context-conflicting
and disconnected nodes are kept in place with stable review warnings.

Pure transformation: the input package is never mutated and no filesystem,
environment, network, clock, randomness or database access occurs. Bad chess
never raises here; it remains reviewable in the returned package.
"""

from __future__ import annotations

import copy
import re
from typing import Literal, NamedTuple

import chess

from .contracts import (
    ExtractionPackage,
    ExtractionWarning,
    MoveNode,
    MoveSequenceItem,
    StartPosition,
)

_WARNING_MESSAGES: dict[str, str] = {
    "ccef_chess_invalid_initial_position": (
        "The sequence initial position is not a legal standard-chess FEN."
    ),
    "ccef_chess_unresolved_parent": "The parent move could not be resolved to one position.",
    "ccef_chess_ambiguous_move": "The move text is ambiguous in the reconstructed position.",
    "ccef_chess_invalid_move": "The move text is not legal in the reconstructed position.",
    "ccef_chess_context_mismatch": "The move context conflicts with the reconstructed position.",
}
_VALIDATOR_WARNING_CODES = frozenset(_WARNING_MESSAGES)

# Source-token policy: at most one leading decimal move-number prefix in the
# forms ``N.`` or ``N...`` (spaces after the prefix are exposed by its removal).
_MOVE_NUMBER_PREFIX = re.compile(r"^\d+\.(?:\.\.)?\s*")
# Repeatedly removable trailing annotations: !, ?, !!, ??, !?, ?! and numeric
# NAG tokens $0..$255, allowing whitespace between suffixes. Out-of-range NAGs
# such as $256 are intentionally not matched and therefore survive to parsing.
_TRAILING_ANNOTATION = re.compile(
    r"\s*(?:[!?]{1,2}|\$(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]))$"
)
# Standard-chess castling rights: canonical ordered K?Q?k?q? form or ``-``.
# Shredder-FEN castling letters and any other ordering are rejected.
_STANDARD_CASTLING = re.compile(r"(?:K?Q?k?q?|-)")


class _Outcome(NamedTuple):
    status: Literal["valid", "invalid", "ambiguous"]
    warning_code: str | None
    san: str | None
    uci: str | None
    fen_before: str | None
    fen_after: str | None


def normalize_chess_moves(package: ExtractionPackage) -> ExtractionPackage:
    """Recompute every move node of a deep copy and return a fresh package.

    The input package is never mutated. The output is revalidated through
    ``ExtractionPackage`` before being returned.
    """
    result = copy.deepcopy(package)
    for item in result.items:
        if isinstance(item, MoveSequenceItem):
            _normalize_sequence(item)
    return ExtractionPackage.model_validate(result.model_dump(mode="json"))


def _normalize_sequence(item: MoveSequenceItem) -> None:
    initial = item.initial_position
    if isinstance(initial, StartPosition):
        initial_board: chess.Board | None = chess.Board()
    elif _fen_is_valid_standard(initial.fen):
        initial_board = chess.Board(initial.fen, chess960=False)
    else:
        initial_board = None

    boards: dict[str, chess.Board | None] = {}
    for node in item.nodes:
        _reset_node(node)
        if node.parent_id is None:
            # Root siblings are independent alternatives from the initial board.
            board = initial_board.copy() if initial_board is not None else None
        else:
            parent_board = boards.get(node.parent_id)
            board = parent_board.copy() if parent_board is not None else None
        outcome = _normalize_node(node, board)
        node.validation_status = outcome.status
        if outcome.warning_code is not None:
            node.warnings.append(
                ExtractionWarning(
                    code=outcome.warning_code,
                    message=_WARNING_MESSAGES[outcome.warning_code],
                    evidence=copy.deepcopy(node.evidence),
                )
            )
        if outcome.status == "valid":
            node.san_candidate = outcome.san
            node.uci_candidate = outcome.uci
            node.fen_before = outcome.fen_before
            node.fen_after = outcome.fen_after
            boards[node.id] = board
        else:
            # No unique after-board: descendants stay unresolved.
            boards[node.id] = None


def _reset_node(node: MoveNode) -> None:
    """Clear authoritative fields and prior validator warnings before recompute."""
    node.warnings = [w for w in node.warnings if w.code not in _VALIDATOR_WARNING_CODES]
    node.san_candidate = None
    node.uci_candidate = None
    node.fen_before = None
    node.fen_after = None


def _normalize_node(node: MoveNode, board: chess.Board | None) -> _Outcome:
    if board is None:
        if node.parent_id is None:
            return _Outcome(
                "invalid", "ccef_chess_invalid_initial_position", None, None, None, None
            )
        return _Outcome("invalid", "ccef_chess_unresolved_parent", None, None, None, None)
    token = _clean_move_token(node.move_text)
    if token is None:
        return _Outcome("invalid", "ccef_chess_invalid_move", None, None, None, None)
    try:
        move = board.parse_san(token)
    except chess.AmbiguousMoveError:
        return _Outcome("ambiguous", "ccef_chess_ambiguous_move", None, None, None, None)
    except ValueError:
        return _Outcome("invalid", "ccef_chess_invalid_move", None, None, None, None)
    # Null moves parse to Move.null(); they are never normalized.
    if move == chess.Move.null():
        return _Outcome("invalid", "ccef_chess_invalid_move", None, None, None, None)
    if node.side_to_move is not None and node.side_to_move != ("w" if board.turn else "b"):
        return _Outcome("invalid", "ccef_chess_context_mismatch", None, None, None, None)
    if node.move_number is not None and node.move_number != board.fullmove_number:
        return _Outcome("invalid", "ccef_chess_context_mismatch", None, None, None, None)
    san = board.san(move)
    uci = move.uci()
    fen_before = board.fen(en_passant="fen")
    board.push(move)
    fen_after = board.fen(en_passant="fen")
    return _Outcome("valid", None, san, uci, fen_before, fen_after)


def _clean_move_token(move_text: str) -> str | None:
    """Reduce a preserved source token to its conservative parse token."""
    token = _MOVE_NUMBER_PREFIX.sub("", move_text, count=1)
    while True:
        match = _TRAILING_ANNOTATION.search(token)
        if match is None:
            break
        token = token[: match.start()]
    if not token:
        return None
    return token


def _fen_is_valid_standard(fen: str) -> bool:
    fields = fen.split()
    if len(fields) != 6:
        return False
    placement, _, castling, *_ = fields
    if "~" in placement:
        return False
    if _STANDARD_CASTLING.fullmatch(castling) is None:
        return False
    try:
        board = chess.Board(fen, chess960=False)
    except ValueError:
        return False
    return board.is_valid()


__all__ = ["normalize_chess_moves"]
