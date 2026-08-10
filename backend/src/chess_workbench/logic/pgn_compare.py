"""Complete, iterative semantic PGN comparison."""

from __future__ import annotations

from dataclasses import dataclass

from chess_workbench.logic.pgn import PgnDocument, PgnGame, PgnNode


@dataclass(frozen=True, slots=True)
class PgnCompareResult:
    equivalent: bool
    differences: tuple[str, ...]


def compare_documents(original: PgnDocument, reimported: PgnDocument) -> PgnCompareResult:
    differences: list[str] = []
    if len(original.games) != len(reimported.games):
        differences.append(f"document: {len(original.games)} vs {len(reimported.games)} games")
    for game_index, (left, right) in enumerate(zip(original.games, reimported.games, strict=False)):
        _compare_game(left, right, f"game[{game_index}]", differences)
    return PgnCompareResult(not differences, tuple(differences))


def compare_games(original: PgnGame, reimported: PgnGame) -> PgnCompareResult:
    differences: list[str] = []
    _compare_game(original, reimported, "game[0]", differences)
    return PgnCompareResult(not differences, tuple(differences))


def _compare_game(left: PgnGame, right: PgnGame, path: str, differences: list[str]) -> None:
    left_headers = tuple((item.name, item.value) for item in left.header_items)
    right_headers = tuple((item.name, item.value) for item in right.header_items)
    if left_headers != right_headers:
        differences.append(f"{path}: headers {left_headers!r} != {right_headers!r}")
    if left.result != right.result:
        differences.append(f"{path}: result {left.result!r} != {right.result!r}")

    stack: list[tuple[PgnNode, PgnNode, str]] = [(left.root, right.root, f"{path}/root")]
    while stack:
        left_node, right_node, node_path = stack.pop()
        for field in (
            "ply",
            "fen",
            "san",
            "uci",
            "nags",
            "starting_comment",
            "comment",
        ):
            left_value = getattr(left_node, field)
            right_value = getattr(right_node, field)
            if left_value != right_value:
                differences.append(f"{node_path}: {field} {left_value!r} != {right_value!r}")
        if len(left_node.children) != len(right_node.children):
            differences.append(
                f"{node_path}: {len(left_node.children)} vs {len(right_node.children)} children"
            )
        for child_index, (left_child, right_child) in reversed(
            list(enumerate(zip(left_node.children, right_node.children, strict=False)))
        ):
            stack.append(
                (
                    left_child,
                    right_child,
                    f"{node_path}/{child_index}:{left_child.uci or 'root'}",
                )
            )
