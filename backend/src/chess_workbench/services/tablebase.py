from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.syzygy

from chess_workbench.schemas.engine import TablebaseRead


@dataclass(frozen=True)
class TablebaseProbe:
    wdl: int
    dtz: int
    best_moves: list[str]


class TablebaseService:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def available(self) -> bool:
        return self.root.is_dir() and any(self.root.glob("*.rtbw"))

    @staticmethod
    def eligible(board: chess.Board) -> bool:
        return len(board.piece_map()) <= 7 and not board.castling_rights

    async def probe(self, fen: str) -> TablebaseRead:
        board = chess.Board(fen)
        if not self.eligible(board):
            return TablebaseRead(
                available=self.available,
                eligible=False,
                wdl=None,
                dtz=None,
                best_moves=[],
                reason="position is outside the configured Syzygy boundary",
            )
        if not self.available:
            return TablebaseRead(
                available=False,
                eligible=True,
                wdl=None,
                dtz=None,
                best_moves=[],
                reason="no local Syzygy WDL files are installed",
            )
        try:
            result = await asyncio.to_thread(self._probe_sync, board)
        except (KeyError, OSError, ValueError) as error:
            return TablebaseRead(
                available=True,
                eligible=True,
                wdl=None,
                dtz=None,
                best_moves=[],
                reason=f"required table is unavailable: {error}",
            )
        return TablebaseRead(
            available=True,
            eligible=True,
            wdl=result.wdl,
            dtz=result.dtz,
            best_moves=result.best_moves,
            reason=None,
        )

    def _probe_sync(self, board: chess.Board) -> TablebaseProbe:
        with chess.syzygy.open_tablebase(str(self.root)) as tablebase:
            wdl = tablebase.probe_wdl(board)
            dtz = tablebase.probe_dtz(board)
            candidates: list[tuple[int, int, str]] = []
            for move in board.legal_moves:
                child = board.copy(stack=False)
                child.push(move)
                try:
                    child_wdl = -tablebase.probe_wdl(child)
                    child_dtz = -tablebase.probe_dtz(child)
                except KeyError:
                    continue
                candidates.append((child_wdl, child_dtz, move.uci()))
            best_wdl = max((item[0] for item in candidates), default=None)
            ranked = [item for item in candidates if item[0] == best_wdl]
            ranked.sort(key=lambda item: _syzygy_rank_key(item[0], item[1]), reverse=True)
            best = [uci for _, _, uci in ranked[:5]]
            return TablebaseProbe(wdl=wdl, dtz=dtz, best_moves=best)


def _syzygy_rank_key(wdl: int, dtz: int) -> tuple[int, int]:
    """Prefer the best WDL, then fast wins/draw resets and delayed losses."""

    if wdl > 0:
        dtz_preference = -abs(dtz)
    elif wdl < 0:
        dtz_preference = abs(dtz)
    else:
        dtz_preference = -abs(dtz)
    return wdl, dtz_preference
