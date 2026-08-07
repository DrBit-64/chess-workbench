"""Immutable PGN semantic tree used by the import/export pipeline.

The tree is constructed by ``parse_pgn()`` from raw PGN text using
``python-chess`` as the underlying parser.  It carries no database
dependencies — importing into the position-graph / occurrence layer
happens in Stage 3B.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chess import Board, Move


# ── public data types ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PgnNode:
    """One position within a PGN game tree.

    *children* are the legal continuations from this node (main line
    first, then side variations in source order).  A leaf node has an
    empty children list.
    """

    ply: int
    """Zero-based half-move index (0 = root)."""

    fen: str
    """Full six-field FEN *after* the move that reached this node.

    The root node holds the starting FEN.
    """

    san: str | None
    """SAN of the move that led here (``None`` for the root)."""

    uci: str | None
    """UCI of the move that led here (``None`` for the root)."""

    nag: int | None
    """Numeric annotation glyph (0–255), or ``None``."""

    comment: str
    """Comment text for this position (may be empty)."""

    children: tuple[PgnNode, ...]
    """Ordered list of child nodes (main-line continuation first)."""


@dataclass(frozen=True, slots=True)
class PgnGame:
    """The complete parsed content of a single PGN game."""

    headers: dict[str, str]
    """Key-value pairs from the PGN tag-pair section (lower-case keys)."""

    root: PgnNode
    """Root of the move tree (ply = 0, san = None, uci = None)."""


# ── parser ─────────────────────────────────────────────────────────


def parse_pgn(pgn_text: str) -> PgnGame:
    """Parse *pgn_text* into a :class:`PgnGame` tree.

    Only the **first** game in the text is returned.  The function
    calls ``python-chess`` for low-level PGN tokenisation and move
    legality, then walks the resulting visitor tree to build our
    immutable semantic representation.

    Raises :exc:`ValueError` when the text is not valid PGN (e.g.
    an illegal move or unclosed variation).
    """
    from io import StringIO

    import chess.pgn

    pgn_game = chess.pgn.read_game(StringIO(pgn_text))
    if pgn_game is None:
        raise ValueError("no PGN game found in input")

    if pgn_game.errors:
        errors = "; ".join(str(e) for e in pgn_game.errors)
        raise ValueError(f"PGN parse errors: {errors}")

    headers: dict[str, str] = {}
    if pgn_game.headers is not None:
        headers = {k.lower(): v for k, v in dict(pgn_game.headers).items()}

    root = _build_root(pgn_game)
    return PgnGame(headers=headers, root=root)


# ── internal helpers ───────────────────────────────────────────────


def _build_root(game: Any) -> PgnNode:
    """Return the root PgnNode from a parsed python-chess Game."""

    board: Board = game.board()
    root_fen = board.fen()

    # Top-level variations: first is main line, rest are side variations.
    variations: list[Any] = getattr(game, "variations", [])
    children = _walk_variations(variations, board)

    # Root may carry a comment / NAGs in python-chess >= 1.x.
    root_comment: str = getattr(game, "comment", "") or ""
    root_nags: set[int] = getattr(game, "nags", set()) or set()

    return PgnNode(
        ply=0,
        fen=root_fen,
        san=None,
        uci=None,
        nag=_pick_nag(root_nags),
        comment=root_comment,
        children=tuple(children),
    )


def _walk_variations(
    variations: list[Any],  # list[chess.pgn.ChildNode]
    board: Board,
) -> list[PgnNode]:
    """Convert a list of sibling ChildNode's to PgnNode's.

    Order is preserved: first child = main line, rest = side variations.
    """
    result: list[PgnNode] = []
    for child_node in variations:
        result.append(_build_child(child_node, board))
    return result


def _build_child(
    node: Any,  # chess.pgn.ChildNode
    board: Board,
) -> PgnNode:
    """Build a single PgnNode from a python-chess ChildNode."""
    import chess

    move: Move = node.move
    if not isinstance(move, chess.Move):
        raise ValueError("unexpected node without a chess.Move")

    new_board = board.copy()
    san_move = new_board.san(move)
    new_board.push(move)

    nag = _pick_nag(getattr(node, "nags", set()) or set())
    comment: str = getattr(node, "comment", "") or ""

    # Recurse into this node's children.
    sub_variations: list[Any] = getattr(node, "variations", [])
    children = _walk_variations(sub_variations, new_board) if sub_variations else []

    return PgnNode(
        ply=_ply_from_parent(node),
        fen=new_board.fen(),
        san=san_move,
        uci=move.uci(),
        nag=nag,
        comment=comment,
        children=tuple(children),
    )


def _ply_from_parent(node: Any) -> int:
    """Walk up parent chain to compute ply (0-based half-move count).

    The root Game node is ply 0. Each ChildNode adds 1.
    """
    depth = 1  # this node itself
    current: Any | None = getattr(node, "parent", None)
    while current is not None:
        # Only count ChildNode parents, stop at Game (which has no .move).
        if hasattr(current, "move") and current.move is not None:
            depth += 1
        current = getattr(current, "parent", None)
    return depth


def _pick_nag(nags: set[int]) -> int | None:
    """Return the first NAG (lowest numeric value), or None."""
    if nags:
        return min(nags)
    return None
