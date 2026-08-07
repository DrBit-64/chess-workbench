"""Semantic PGN comparison (Stage 3C round-trip verifier)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chess_workbench.logic.pgn import PgnGame


class PgnCompareResult:
    """Outcome of a semantic PGN comparison."""

    __slots__ = ("equivalent", "differences")

    def __init__(self, equivalent: bool, differences: list[str]) -> None:
        self.equivalent = equivalent
        self.differences = differences


_STANDARD_HEADERS = frozenset(
    {
        "event",
        "site",
        "date",
        "round",
        "white",
        "black",
        "result",
        "fen",
        "setup",
    }
)


def compare_games(original: PgnGame, reimported: PgnGame) -> PgnCompareResult:
    """Compare two parsed PGN games for semantic equivalence.

    Returns a :class:`PgnCompareResult` whose ``equivalent`` field is
    ``True`` when the two games express the same chess content.
    """
    diffs: list[str] = []

    _compare_headers(original.headers, reimported.headers, diffs)
    _compare_nodes(original.root, reimported.root, path="root", diffs=diffs)

    return PgnCompareResult(
        equivalent=len(diffs) == 0,
        differences=diffs,
    )


# ── helpers ───────────────────────────────────────────────────────


def _compare_headers(
    orig: dict[str, str],
    reimp: dict[str, str],
    diffs: list[str],
) -> None:
    for key in _STANDARD_HEADERS:
        a = orig.get(key, "")
        b = reimp.get(key, "")
        if a != b:
            diffs.append(f"header [{key}]: {a!r} != {b!r}")


def _compare_nodes(
    orig: Any,
    reimp: Any,
    *,
    path: str,
    diffs: list[str],
) -> None:
    """Recursively compare two PgnNode trees."""
    # UCI comparison (non-root nodes only).
    if orig.uci is not None and reimp.uci is not None and orig.uci != reimp.uci:
        diffs.append(f"{path}: UCI {orig.uci} != {reimp.uci}")

    # NAG
    if orig.nag != reimp.nag:
        diffs.append(f"{path}: NAG {orig.nag} != {reimp.nag}")

    # Comment (trimmed).
    oc = orig.comment.strip() if orig.comment else ""
    rc = reimp.comment.strip() if reimp.comment else ""
    if oc != rc:
        diffs.append(f"{path}: comment {oc!r} != {rc!r}")

    # Variation count.
    if len(orig.children) != len(reimp.children):
        diffs.append(f"{path}: {len(orig.children)} vs {len(reimp.children)} children")
        return

    for i, (oc, rc) in enumerate(zip(orig.children, reimp.children, strict=False)):
        child_path = f"{path}/{oc.san or 'root'}[{i}]"
        _compare_nodes(oc, rc, path=child_path, diffs=diffs)
