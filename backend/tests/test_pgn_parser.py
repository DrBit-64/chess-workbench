"""Golden-file tests for the PGN semantic tree parser (Stage 3A)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import pytest
from chess_workbench.logic.pgn import (
    PgnError,
    PgnNode,
    parse_pgn,
    parse_pgn_document,
    semantic_hash,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pgn"


class Fixture(NamedTuple):
    stem: str
    text: str


def _fixtures() -> Iterator[Fixture]:
    for path in sorted(FIXTURE_DIR.glob("*.pgn")):
        yield Fixture(stem=path.stem, text=path.read_text(encoding="utf-8"))


def _leaves(node: PgnNode) -> int:
    """Count leaf nodes in the tree (nodes with no children)."""
    if not node.children:
        return 1
    return sum(_leaves(c) for c in node.children)


def _count_nodes(node: PgnNode) -> int:
    """Count all nodes in the tree."""
    return 1 + sum(_count_nodes(c) for c in node.children)


def _collect_plies(node: PgnNode) -> set[int]:
    """Collect all ply values reachable from *node*."""
    result = {node.ply}
    for child in node.children:
        result |= _collect_plies(child)
    return result


# ── basic structural tests ──────────────────────────────────────────


def test_parser_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="no PGN game found"):
        parse_pgn("")


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f.stem)
def test_all_fixtures_parse_without_error(fixture: Fixture) -> None:
    """Every golden fixture must parse successfully."""
    parse_pgn(fixture.text)


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f.stem)
def test_root_node_is_ply_zero(fixture: Fixture) -> None:
    """The root of every parsed game has ply == 0."""
    game = parse_pgn(fixture.text)
    assert game.root.ply == 0


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f.stem)
def test_root_node_has_no_move(fixture: Fixture) -> None:
    """Root never carries a move (san==None, uci==None)."""
    game = parse_pgn(fixture.text)
    assert game.root.san is None
    assert game.root.uci is None


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f.stem)
def test_headers_are_lowercase_keys(fixture: Fixture) -> None:
    """All header keys are lower-cased."""
    game = parse_pgn(fixture.text)
    for key in game.headers:
        assert key == key.lower()


# ── specific fixture assertions ─────────────────────────────────────


def test_mainline_fixture_structure() -> None:
    """01_mainline: single main line, no variations, 16 plies."""
    game = parse_pgn((FIXTURE_DIR / "01_mainline.pgn").read_text())

    # Walk down main line: 8 white + 8 black moves = 16 plies.
    node = game.root
    ply_count = 0
    while node.children:
        assert len(node.children) == 1, f"ply {node.ply} should have 1 child"
        node = node.children[0]
        ply_count += 1
    assert ply_count == 16  # 8 moves * 2 plies


def test_one_variation_structure() -> None:
    """02_one_variation: main line with one side variation at ply 1."""
    game = parse_pgn((FIXTURE_DIR / "02_one_variation.pgn").read_text())

    root = game.root
    assert len(root.children) == 1  # 1. e4
    e4 = root.children[0]
    assert e4.san == "e4"
    assert e4.ply == 1

    # Black has two choices: 1... e5 (main) and 1... c5 (variation)
    assert len(e4.children) == 2
    assert e4.children[0].san == "e5"
    assert e4.children[1].san == "c5"


def test_nested_variations_structure() -> None:
    """03_nested_variations: nested parentheses."""
    game = parse_pgn((FIXTURE_DIR / "03_nested_variations.pgn").read_text())
    root = game.root
    e4 = root.children[0]
    assert e4.san == "e4"
    # Black's e5 (main) and c5 (side)
    assert len(e4.children) == 2

    c5 = e4.children[1]
    assert c5.san == "c5"
    # After 1... c5, white has Nf3 and c3 as variations
    assert len(c5.children) == 2
    assert c5.children[0].san == "Nf3"
    assert c5.children[1].san == "c3"


def test_nag_annotations() -> None:
    """04_nag: each move has a NAG."""
    game = parse_pgn((FIXTURE_DIR / "04_nag.pgn").read_text())
    node = game.root.children[0]  # 1. e4
    assert node.nag is not None
    # Walk main line and check NAGs
    assert node.nag == 1  # $1 = good move
    node = node.children[0]
    assert node.nag == 2  # $2 = mistake


def test_braces_comment() -> None:
    """05_braces_comment: comments in braces."""
    game = parse_pgn((FIXTURE_DIR / "05_braces_comment.pgn").read_text())
    root_comment = game.root.comment
    assert "Starting" in root_comment

    e4 = game.root.children[0]
    assert "good opening" in e4.comment


def test_unicode_comment() -> None:
    """07_unicode_comment: Chinese characters in comments and headers."""
    game = parse_pgn((FIXTURE_DIR / "07_unicode_comment.pgn").read_text())
    assert game.headers.get("white") is not None
    root = game.root
    assert "开局" in root.comment
    # Comment "{黑方回应王兵，中心对称}" is before 1... e5, so on the e5 node.
    e4 = root.children[0]  # 1. e4 — no comment
    e5 = e4.children[0]  # 1... e5
    assert "黑方回应" in e5.comment
    # "{白方出马攻击e5兵}" is before 2... Nc6
    nf3 = e5.children[0]  # 2. Nf3
    nc6 = nf3.children[0]  # 2... Nc6
    assert "白方出马" in nc6.comment


def test_setup_fen() -> None:
    """08_setup_fen: non-standard starting position."""
    game = parse_pgn((FIXTURE_DIR / "08_setup_fen.pgn").read_text())
    assert game.headers.get("fen") is not None
    assert game.headers.get("setup") == "1"
    # Root FEN should NOT be the standard starting position
    assert "4p3" in game.root.fen  # black pawn on e5


def test_multiple_variations_structure() -> None:
    """11_multiple_variations: 4 variations at the root level."""
    game = parse_pgn((FIXTURE_DIR / "11_multiple_variations.pgn").read_text())
    root = game.root
    # 1. e4 (main) + 3 side variations = 4 children
    assert len(root.children) == 4
    assert root.children[0].san == "e4"  # main line
    assert root.children[1].san == "d4"  # first side variation
    assert root.children[2].san == "c4"
    assert root.children[3].san == "Nf3"


def test_illegal_move_pgn_is_rejected() -> None:
    """A PGN with an illegal move raises ValueError."""
    with pytest.raises(ValueError, match="illegal"):
        parse_pgn("1. e4 e5 2. Ke2 Ke7 3. Qe1 Qxe1#")  # no, this is legal...
    # Use something actually illegal
    with pytest.raises(ValueError, match="illegal"):
        parse_pgn("1. e4 e5 2. Kf3")  # King can't go to f3


def test_promotion_is_parsed() -> None:
    """PGN with pawn promotion moves parses correctly."""
    game = parse_pgn('[FEN "8/P7/8/8/8/8/7p/8 w - - 0 1"]\n[SetUp "1"]\n\n1. a8=Q h1=R *')
    leaves = _leaves(game.root)
    assert leaves >= 1


def test_tree_totals_are_consistent() -> None:
    """Every fixture: total nodes > leaves > 0."""
    for fixture in _fixtures():
        game = parse_pgn(fixture.text)
        total = _count_nodes(game.root)
        leaf_count = _leaves(game.root)
        assert total > 0
        assert leaf_count > 0
        assert total >= leaf_count


def test_ply_values_increase_monotonically() -> None:
    """For every fixture, children have ply == parent.ply + 1."""
    for fixture in _fixtures():
        game = parse_pgn(fixture.text)
        _assert_ply_monotonic(game.root)


def _assert_ply_monotonic(node: PgnNode) -> None:
    for child in node.children:
        assert child.ply == node.ply + 1, (
            f"child ply {child.ply} != parent ply {node.ply} + 1 (child san={child.san})"
        )
        _assert_ply_monotonic(child)


def test_document_parser_preserves_all_games_and_source_order() -> None:
    first = (FIXTURE_DIR / "01_mainline.pgn").read_text()
    second = (FIXTURE_DIR / "07_unicode_comment.pgn").read_text()

    document = parse_pgn_document(first + "\n" + second)

    assert len(document.games) == 2
    assert [game.header("event") for game in document.games] == [
        "Simple mainline",
        "Unicode comment — 中文",
    ]
    assert document.games[0].source_start < document.games[0].source_end
    assert document.games[0].source_end <= document.games[1].source_start
    with pytest.raises(PgnError, match="exactly one game"):
        parse_pgn(first + "\n" + second)


def test_parser_preserves_all_nags_starting_comments_and_full_fen() -> None:
    game = parse_pgn(
        '[Event "Semantics"]\n'
        '[Result "*"]\n'
        '[SetUp "1"]\n'
        '[FEN "8/8/8/3pP3/8/8/8/K6k w - d6 7 42"]\n\n'
        "{root} 42. exd6 $1 $3 {normal} ( {variation start} 42. Ka2 $2 ) *"
    )

    assert game.root.fen == "8/8/8/3pP3/8/8/8/K6k w - d6 7 42"
    assert game.root.comment == "root"
    assert game.root.children[0].nags == (1, 3)
    assert game.root.children[0].comment == "normal"
    assert game.root.children[1].starting_comment == "variation start"
    assert game.root.children[1].nags == (2,)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ('[Event "A"]\n[Event "B"]\n[Result "*"]\n\n*', "duplicate_tag"),
        ('[Result "1-0"]\n\n1. e4 0-1', "result_conflict"),
        ('[Result "*"]\n\n1. e4', "missing_result"),
        ('[Result "*"]\n\n*\x00', "nul_byte"),
    ],
)
def test_parser_rejects_lossy_or_ambiguous_inputs(text: str, reason: str) -> None:
    with pytest.raises(PgnError) as captured:
        parse_pgn_document(text)
    assert captured.value.reason == reason


def test_parser_reports_move_and_rav_limits_with_location() -> None:
    nested = (FIXTURE_DIR / "03_nested_variations.pgn").read_text()
    with pytest.raises(PgnError) as depth_error:
        parse_pgn_document(nested, max_rav_depth=1)
    assert depth_error.value.kind == "pgn_limit_exceeded"
    assert depth_error.value.reason == "rav_depth"
    assert depth_error.value.path is not None

    mainline = (FIXTURE_DIR / "01_mainline.pgn").read_text()
    with pytest.raises(PgnError) as count_error:
        parse_pgn_document(mainline, max_move_nodes=3)
    assert count_error.value.reason == "move_count"
    assert count_error.value.ply == 4


def test_parser_handles_5000_ply_without_python_recursion() -> None:
    moves: list[str] = []
    for fullmove in range(1, 2501):
        if fullmove % 2:
            moves.append(f"{fullmove}. Nf3 Nf6")
        else:
            moves.append(f"{fullmove}. Ng1 Ng8")
    text = '[Event "Long"]\n[Result "*"]\n\n' + " ".join(moves) + " *"

    document = parse_pgn_document(text, deadline_seconds=15)

    assert document.move_count == 5_000
    node = document.games[0].root
    visited = 0
    while node.children:
        node = node.children[0]
        visited += 1
    assert visited == 5_000


def test_semantic_hash_covers_headers_result_and_tree_fields() -> None:
    game = parse_pgn((FIXTURE_DIR / "03_nested_variations.pgn").read_text())
    original_hash = semantic_hash(game)
    assert semantic_hash(game) == original_hash
    assert semantic_hash(replace(game, result="1-0")) != original_hash
    assert semantic_hash(replace(game, root=replace(game.root, comment="changed"))) != original_hash


def test_structured_error_details_and_remaining_limits() -> None:
    multi = (
        (FIXTURE_DIR / "01_mainline.pgn").read_text()
        + "\n"
        + (FIXTURE_DIR / "02_one_variation.pgn").read_text()
    )
    with pytest.raises(PgnError) as game_limit:
        parse_pgn_document(multi, max_games=1)
    assert game_limit.value.reason == "game_count"
    assert game_limit.value.details()["game_index"] == 1

    with pytest.raises(ValueError, match="limits must be positive"):
        parse_pgn_document("*", max_move_nodes=0)
    with pytest.raises(PgnError) as deadline:
        parse_pgn_document(
            (FIXTURE_DIR / "01_mainline.pgn").read_text(),
            deadline_seconds=1e-12,
        )
    assert deadline.value.reason == "deadline"
