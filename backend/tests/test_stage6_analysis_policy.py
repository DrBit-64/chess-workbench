import chess
import pytest
from chess_workbench.domain.analysis import (
    MoveVerdict,
    TablebaseVerdict,
    engine_threshold_verdict,
    tablebase_verdict,
)
from chess_workbench.schemas.engine import AnalysisLine, AnalysisRequest
from chess_workbench.services.engine import _score_for_side, _terminal_score_for_side
from chess_workbench.services.tablebase import _syzygy_rank_key
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("loss", "expected"),
    [
        (0, MoveVerdict.BEST),
        (10, MoveVerdict.BEST),
        (11, MoveVerdict.GOOD),
        (50, MoveVerdict.GOOD),
        (51, MoveVerdict.INACCURACY),
        (100, MoveVerdict.INACCURACY),
        (101, MoveVerdict.MISTAKE),
        (250, MoveVerdict.MISTAKE),
        (251, MoveVerdict.BLUNDER),
    ],
)
def test_engine_threshold_boundaries(loss: int, expected: MoveVerdict) -> None:
    assert engine_threshold_verdict(loss) is expected


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (2, 2, TablebaseVerdict.PRESERVES),
        (0, 1, TablebaseVerdict.PRESERVES),
        (2, 0, TablebaseVerdict.THROWS_WIN),
        (1, -1, TablebaseVerdict.THROWS_WIN),
        (0, -1, TablebaseVerdict.MISSES_DRAW),
        (-1, -2, TablebaseVerdict.WORSENS),
    ],
)
def test_tablebase_policy_boundaries(before: int, after: int, expected: TablebaseVerdict) -> None:
    assert tablebase_verdict(before, after) is expected


def test_syzygy_dtz_ranking_prefers_fast_wins_and_delayed_losses() -> None:
    assert _syzygy_rank_key(2, 1) > _syzygy_rank_key(2, 8)
    assert _syzygy_rank_key(-2, -8) > _syzygy_rank_key(-2, -1)
    assert _syzygy_rank_key(0, 0) > _syzygy_rank_key(0, 4)
    assert _syzygy_rank_key(2, 100) > _syzygy_rank_key(0, 0)


def test_terminal_score_handles_mate_and_draw_from_requested_side() -> None:
    black_is_mated = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
    stalemate = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
    assert _terminal_score_for_side(black_is_mated, "white") == 100_000
    assert _terminal_score_for_side(black_is_mated, "black") == -100_000
    assert _terminal_score_for_side(stalemate, "white") == 0
    assert _terminal_score_for_side(chess.STARTING_FEN, "white") is None


def test_score_for_side_handles_mate_cp_and_missing_scores() -> None:
    mate = AnalysisLine(rank=1, score_cp=None, mate=3, wdl=None, uci=["e2e4"], san=["e4"])
    mated = mate.model_copy(update={"mate": -2})
    centipawns = mate.model_copy(update={"mate": None, "score_cp": 75})
    unknown = mate.model_copy(update={"mate": None, "score_cp": None})

    assert _score_for_side(mate, "white") == 100_000
    assert _score_for_side(mate, "black") == -100_000
    assert _score_for_side(mated, "white") == -100_000
    assert _score_for_side(centipawns, "black") == -75
    assert _score_for_side(unknown, "white") == 0


def test_analysis_policy_rejects_out_of_domain_values() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        engine_threshold_verdict(-1)
    with pytest.raises(ValueError, match="between -2 and 2"):
        tablebase_verdict(3, 0)


def test_analysis_contract_rejects_parseable_but_illegal_position() -> None:
    with pytest.raises(ValidationError, match="legal standard chess position"):
        AnalysisRequest(fen="8/8/8/8/8/8/8/8 w - - 0 1")
