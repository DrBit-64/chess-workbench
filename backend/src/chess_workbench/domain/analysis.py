from __future__ import annotations

from enum import StrEnum


class MoveVerdict(StrEnum):
    BEST = "best"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"


def engine_threshold_verdict(loss_cp: int) -> MoveVerdict:
    """Pure Stage 6 result; Stage 5 later maps this onto answer classification."""

    if loss_cp < 0:
        raise ValueError("centipawn loss cannot be negative")
    if loss_cp <= 10:
        return MoveVerdict.BEST
    if loss_cp <= 50:
        return MoveVerdict.GOOD
    if loss_cp <= 100:
        return MoveVerdict.INACCURACY
    if loss_cp <= 250:
        return MoveVerdict.MISTAKE
    return MoveVerdict.BLUNDER


class TablebaseVerdict(StrEnum):
    PRESERVES = "preserves"
    WORSENS = "worsens"
    THROWS_WIN = "throws_win"
    MISSES_DRAW = "misses_draw"


def tablebase_verdict(before_wdl: int, after_wdl_for_mover: int) -> TablebaseVerdict:
    """Compare Syzygy outcomes from the mover's point of view (-2..2)."""

    if before_wdl not in range(-2, 3) or after_wdl_for_mover not in range(-2, 3):
        raise ValueError("Syzygy WDL values must be between -2 and 2")
    if after_wdl_for_mover >= before_wdl:
        return TablebaseVerdict.PRESERVES
    if before_wdl > 0 and after_wdl_for_mover <= 0:
        return TablebaseVerdict.THROWS_WIN
    if before_wdl == 0 and after_wdl_for_mover < 0:
        return TablebaseVerdict.MISSES_DRAW
    return TablebaseVerdict.WORSENS
