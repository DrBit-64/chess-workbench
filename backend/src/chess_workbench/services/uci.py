from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

import chess
import chess.engine

from chess_workbench.schemas.engine import AnalysisLine, EngineParameters

_EngineFileIdentity = tuple[str, int, int, int, int, int]


class EngineError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be bool")
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class EngineIdentity:
    name: str
    version: str


_ENGINE_IDENTITIES: dict[_EngineFileIdentity, EngineIdentity] = {}


@dataclass(frozen=True)
class EngineResult:
    identity: EngineIdentity
    lines: list[AnalysisLine]
    depth: int | None
    seldepth: int | None
    nodes: int | None
    elapsed_ms: int


def _version_from_name(name: str) -> str:
    match = re.search(r"(?:^|\s)(\d+(?:\.\d+)*(?:-[A-Za-z0-9.]+)?)", name)
    return match.group(1) if match else "unknown"


def _identity(protocol: chess.engine.UciProtocol) -> EngineIdentity:
    name = protocol.id.get("name", "UCI engine").strip() or "UCI engine"
    return EngineIdentity(name=name, version=_version_from_name(name))


def _san_line(board: chess.Board, moves: list[chess.Move]) -> list[str]:
    cursor = board.copy(stack=False)
    san: list[str] = []
    for move in moves:
        if move not in cursor.legal_moves:
            raise EngineError("malformed_output", f"engine returned illegal PV move {move.uci()}")
        san.append(cursor.san(move))
        cursor.push(move)
    return san


def _line_from_info(board: chess.Board, rank: int, info: chess.engine.InfoDict) -> AnalysisLine:
    pv = list(info.get("pv", []))
    if not pv:
        raise EngineError("malformed_output", "engine returned an empty principal variation")
    pov_score = info.get("score")
    if pov_score is None:
        raise EngineError("malformed_output", "engine returned a PV without a score")
    white_score = pov_score.pov(chess.WHITE)
    mate = white_score.mate()
    score_cp = None if mate is not None else white_score.score()
    wdl_value: tuple[int, int, int] | None = None
    try:
        pov_wdl = pov_score.wdl(model="sf16", ply=board.ply()).pov(chess.WHITE)
        wdl_value = (pov_wdl.wins, pov_wdl.draws, pov_wdl.losses)
    except (KeyError, ValueError):
        pass
    return AnalysisLine(
        rank=rank,
        score_cp=score_cp,
        mate=mate,
        wdl=wdl_value,
        uci=[move.uci() for move in pv],
        san=_san_line(board, pv),
    )


class UciEngine:
    """One-operation UCI process wrapper with cleanup on every exit path."""

    def __init__(
        self,
        executable: Path,
        *,
        max_threads: int,
        max_hash_mb: int,
        max_time_ms: int,
    ) -> None:
        self.executable = executable
        self.max_threads = max_threads
        self.max_hash_mb = max_hash_mb
        self.max_time_ms = max_time_ms

    def validate_parameters(self, parameters: EngineParameters) -> None:
        if parameters.threads > self.max_threads:
            raise EngineError("resource_limit", "requested Threads exceeds the configured limit")
        if parameters.hash_mb > self.max_hash_mb:
            raise EngineError("resource_limit", "requested Hash exceeds the configured limit")
        if parameters.movetime_ms > self.max_time_ms:
            raise EngineError(
                "resource_limit", "requested analysis time exceeds the configured limit"
            )

    async def probe(self) -> EngineIdentity:
        transport, protocol = await self._open()
        try:
            return _identity(protocol)
        finally:
            await self._close(transport, protocol)

    async def probe_cached(self) -> EngineIdentity:
        """Reuse identity until the configured executable changes on disk."""

        try:
            resolved = self.executable.resolve(strict=True)
            stat = resolved.stat()
        except OSError:
            return await self.probe()
        file_identity: _EngineFileIdentity = (
            str(resolved),
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
        cached = _ENGINE_IDENTITIES.get(file_identity)
        if cached is not None:
            return cached
        identity = await self.probe()
        for key in tuple(_ENGINE_IDENTITIES):
            if key[0] == file_identity[0]:
                del _ENGINE_IDENTITIES[key]
        _ENGINE_IDENTITIES[file_identity] = identity
        return identity

    async def analyze(self, fen: str, parameters: EngineParameters) -> EngineResult:
        self.validate_parameters(parameters)
        try:
            board = chess.Board(fen)
        except ValueError as error:
            raise EngineError("invalid_fen", "analysis FEN is invalid") from error
        transport, protocol = await self._open()
        started = monotonic()
        start_task: asyncio.Task[chess.engine.AnalysisResult] | None = None
        analysis: chess.engine.AnalysisResult | None = None
        wait_task: asyncio.Task[chess.engine.BestMove] | None = None
        try:
            limit = chess.engine.Limit(
                time=None if parameters.depth is not None else parameters.movetime_ms / 1000,
                depth=parameters.depth,
            )
            timeout = min(self.max_time_ms, parameters.movetime_ms) / 1000 + 1
            start_task = asyncio.create_task(
                protocol.analysis(
                    board,
                    limit,
                    multipv=parameters.multipv,
                    options={
                        "Threads": parameters.threads,
                        "Hash": parameters.hash_mb,
                    },
                )
            )
            # Do not let cancellation of the HTTP/job coroutine cancel the
            # python-chess command future. UciAnalysisCommand may still be
            # waiting for a delayed ``readyok`` and unconditionally completes
            # that future when the reply arrives.
            analysis = await asyncio.shield(start_task)
            wait_task = asyncio.create_task(analysis.wait())
            done, _ = await asyncio.wait({wait_task}, timeout=timeout)
            if not done:
                analysis.stop()
                await asyncio.wait({wait_task}, timeout=0.1)
                exit_status = protocol.returncode.result() if protocol.returncode.done() else None
                if exit_status is not None:
                    raise EngineError(
                        "engine_crashed",
                        f"engine exited with status {exit_status}",
                    )
                raise EngineError("timeout", "engine analysis exceeded its deadline")
            wait_task.result()
            infos = analysis.multipv
            expected_pvs = min(parameters.multipv, board.legal_moves.count())
            if len(infos) < expected_pvs:
                raise EngineError(
                    "malformed_output",
                    f"engine returned {len(infos)} PVs, expected {expected_pvs}",
                )
            lines = [_line_from_info(board, index, info) for index, info in enumerate(infos, 1)]
            first = infos[0]
            return EngineResult(
                identity=_identity(protocol),
                lines=lines,
                depth=first.get("depth"),
                seldepth=first.get("seldepth"),
                nodes=first.get("nodes"),
                elapsed_ms=round((monotonic() - started) * 1000),
            )
        except asyncio.CancelledError:
            if analysis is not None:
                analysis.stop()
                await asyncio.sleep(0)
            raise
        except chess.engine.EngineTerminatedError as error:
            raise EngineError("engine_crashed", str(error)) from error
        except chess.engine.EngineError as error:
            message = str(error)
            code = "malformed_output" if "did not return" in message else "engine_crashed"
            raise EngineError(code, message) from error
        finally:
            await self._close(transport, protocol)
            if wait_task is not None:
                await self._drain_terminated_task(wait_task)
            if start_task is not None and analysis is None:
                await self._drain_abandoned_analysis_start(start_task)

    async def play(self, fen: str, *, strength: int) -> tuple[EngineIdentity, chess.Move]:
        board = chess.Board(fen)
        transport, protocol = await self._open()
        play_task: asyncio.Task[chess.engine.PlayResult] | None = None
        try:
            options: dict[str, str | int | bool | None] = {
                "Threads": 1,
                "Hash": min(128, self.max_hash_mb),
            }
            if "UCI_LimitStrength" in protocol.options:
                options["UCI_LimitStrength"] = True
                options["UCI_Elo"] = 1320 + strength * 180
            play_task = asyncio.create_task(
                protocol.play(
                    board, chess.engine.Limit(time=0.08 + strength * 0.09), options=options
                )
            )
            done, _ = await asyncio.wait({play_task}, timeout=3)
            if not done:
                exit_status = protocol.returncode.result() if protocol.returncode.done() else None
                if exit_status is not None:
                    raise EngineError(
                        "engine_crashed",
                        f"engine exited with status {exit_status}",
                    )
                raise EngineError("timeout", "engine move exceeded its deadline")
            result = play_task.result()
            if result.move is None or result.move not in board.legal_moves:
                raise EngineError("malformed_output", "engine did not return a legal move")
            return _identity(protocol), result.move
        except asyncio.CancelledError:
            raise
        except chess.engine.EngineTerminatedError as error:
            raise EngineError("engine_crashed", str(error)) from error
        except chess.engine.EngineError as error:
            raise EngineError("engine_crashed", str(error)) from error
        finally:
            await self._close(transport, protocol)
            if play_task is not None:
                await self._drain_terminated_task(play_task)

    async def _open(self) -> tuple[asyncio.SubprocessTransport, chess.engine.UciProtocol]:
        if not self.executable.is_file():
            raise EngineError("engine_unavailable", f"engine not found at {self.executable}")
        try:
            return await asyncio.wait_for(chess.engine.popen_uci([str(self.executable)]), timeout=5)
        except TimeoutError as error:
            raise EngineError("handshake_timeout", "UCI handshake timed out") from error
        except (OSError, chess.engine.EngineError) as error:
            raise EngineError("engine_unavailable", str(error)) from error

    @staticmethod
    async def _drain_abandoned_analysis_start(
        task: asyncio.Task[chess.engine.AnalysisResult],
    ) -> None:
        """Retrieve both layers of an analysis that was cancelled before startup."""

        try:
            analysis = await asyncio.wait_for(asyncio.shield(task), timeout=1)
        except (asyncio.CancelledError, TimeoutError, chess.engine.EngineTerminatedError):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, chess.engine.EngineTerminatedError):
                await task
            return

        with suppress(chess.engine.EngineTerminatedError):
            await analysis.wait()

    @staticmethod
    async def _drain_terminated_task(task: asyncio.Task[Any]) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1)
        except asyncio.CancelledError:
            pass
        except (TimeoutError, chess.engine.EngineTerminatedError):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, chess.engine.EngineTerminatedError):
                await task

    @staticmethod
    async def _close(
        transport: asyncio.SubprocessTransport, protocol: chess.engine.UciProtocol
    ) -> None:
        try:
            if not protocol.returncode.done() and not transport.is_closing():
                await asyncio.wait_for(protocol.quit(), timeout=1)
        except (
            TimeoutError,
            chess.engine.EngineError,
            ProcessLookupError,
            RuntimeError,
            OSError,
        ):
            if not protocol.returncode.done():
                with suppress(ProcessLookupError, RuntimeError, OSError):
                    transport.kill()
        finally:
            if not protocol.returncode.done():
                try:
                    await asyncio.wait_for(asyncio.shield(protocol.returncode), timeout=1)
                except TimeoutError:
                    with suppress(ProcessLookupError, RuntimeError, OSError):
                        transport.kill()
                    with suppress(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(protocol.returncode), timeout=1)
            if not transport.is_closing():
                with suppress(RuntimeError, OSError):
                    transport.close()
