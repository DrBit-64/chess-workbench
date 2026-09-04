from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import chess
import pytest
import uvloop

from chess_workbench.config import Settings
from chess_workbench.schemas.engine import (
    AnalysisCacheLookupRequest,
    AnalysisRequest,
    EngineGameCreate,
    EngineGameMoveCreate,
    EngineParameters,
)
from chess_workbench.services.content import ContentService
from chess_workbench.services.engine import (
    EngineService,
    analysis_cache_key,
    play_game_move,
)
from chess_workbench.services.tablebase import TablebaseService
from chess_workbench.services.uci import (
    EngineError,
    EngineIdentity,
    UciEngine,
    _line_from_info,
    _san_line,
    _version_from_name,
)
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import EngineAnalysis, InvalidationEvent

FIXTURE_ENGINE = Path(__file__).parent / "fixtures" / "fake_uci_engine.py"
SYZYGY_FIXTURE = Path(__file__).parent / "fixtures" / "syzygy"


@pytest.fixture(autouse=True)
def normal_fake_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_UCI_MODE", "normal")


def _uci() -> UciEngine:
    return UciEngine(FIXTURE_ENGINE, max_threads=4, max_hash_mb=512, max_time_ms=2000)


async def test_fake_uci_handshake_options_four_legal_pvs_and_cleanup() -> None:
    result = await _uci().analyze(chess.STARTING_FEN, EngineParameters())
    assert result.identity.name == "FakeFish 1.2"
    assert result.identity.version == "1.2"
    assert len(result.lines) == 4
    for line in result.lines:
        board = chess.Board()
        for uci in line.uci:
            move = chess.Move.from_uci(uci)
            assert move in board.legal_moves
            board.push(move)
        assert len(line.san) == len(line.uci)
    assert result.lines[0].score_cp == 34
    assert result.lines[0].wdl is not None


async def test_uci_accepts_fewer_pvs_when_the_position_has_only_three_legal_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_UCI_MODE", "limited-multipv")
    checked_fen = "2kr1b1r/ppp2ppp/8/3P3q/2P1p1n1/4Bn1P/PP3PP1/RN1Q1RK1 w - - 1 13"

    result = await _uci().analyze(
        checked_fen,
        EngineParameters(multipv=4, movetime_ms=100),
    )

    assert [line.san for line in result.lines] == [["Kh1"], ["Qxf3"], ["gxf3"]]


def test_fake_uci_probe_works_under_sanic_uvloop() -> None:
    identity = uvloop.run(_uci().probe())

    assert identity.name == "FakeFish 1.2"
    assert identity.version == "1.2"


async def test_cached_probe_reuses_identity_until_the_executable_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "engine"
    executable.write_bytes(b"engine-v1")
    engine = UciEngine(executable, max_threads=1, max_hash_mb=128, max_time_ms=1000)
    probe = AsyncMock(
        side_effect=[
            EngineIdentity(name="FakeFish 1", version="1"),
            EngineIdentity(name="FakeFish 2", version="2"),
        ]
    )
    monkeypatch.setattr(engine, "probe", probe)

    assert (await engine.probe_cached()).version == "1"
    assert (await engine.probe_cached()).version == "1"
    assert probe.await_count == 1

    executable.write_bytes(b"engine-version-two")
    assert (await engine.probe_cached()).version == "2"
    assert probe.await_count == 2


async def test_cache_lookup_returns_only_current_engine_and_parameter_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ScalarRows:
        def __init__(self, rows: list[EngineAnalysis]) -> None:
            self.rows = rows

        def __iter__(self) -> Iterator[EngineAnalysis]:
            return iter(self.rows)

    class Session:
        async def scalars(self, _statement: object) -> ScalarRows:
            return ScalarRows(rows)

    parameters = EngineParameters()
    second_fen = chess.Board(chess.STARTING_FEN)
    second_fen.push_uci("e2e4")
    rows = [
        EngineAnalysis(
            cache_key="a" * 64,
            fen=chess.STARTING_FEN,
            source="engine",
            engine_name="FakeFish",
            engine_version="2",
            parameters=parameters.model_dump(mode="json"),
            lines=[],
            elapsed_ms=0,
            from_cache=False,
        ),
        EngineAnalysis(
            cache_key="b" * 64,
            fen=second_fen.fen(en_passant="fen"),
            source="engine",
            engine_name="FakeFish",
            engine_version="1",
            parameters=parameters.model_dump(mode="json"),
            lines=[],
            elapsed_ms=0,
            from_cache=False,
        ),
    ]
    executable = tmp_path / "engine"
    executable.write_bytes(b"engine")
    settings = Settings(
        stockfish_path=executable,
        syzygy_path=tmp_path / "missing",
        engine_worker_enabled=False,
    )
    service = EngineService(cast(Any, Session()), settings)
    monkeypatch.setattr(
        service.uci,
        "probe_cached",
        AsyncMock(return_value=EngineIdentity(name="FakeFish", version="2")),
    )

    result = await service.lookup_cached_fens(
        AnalysisCacheLookupRequest(
            fens=[chess.STARTING_FEN, second_fen.fen(en_passant="fen")],
            parameters=parameters,
        )
    )

    assert result.cached_fens == [chess.STARTING_FEN]
    assert result.missing_fens == [second_fen.fen(en_passant="fen")]


async def test_fake_uci_play_returns_a_legal_move() -> None:
    identity, move = await _uci().play(chess.STARTING_FEN, strength=5)
    assert identity.version == "1.2"
    assert move in chess.Board().legal_moves


@pytest.mark.parametrize(
    ("mode", "code"),
    [("malformed", "malformed_output"), ("crash", "engine_crashed")],
)
async def test_fake_uci_rejects_malformed_output_and_crash(
    monkeypatch: pytest.MonkeyPatch, mode: str, code: str
) -> None:
    monkeypatch.setenv("FAKE_UCI_MODE", mode)
    with pytest.raises(EngineError) as captured:
        await _uci().analyze(
            chess.STARTING_FEN,
            EngineParameters(multipv=1, movetime_ms=100),
        )
    assert captured.value.code == code


async def test_engine_resource_limits_are_checked_before_spawn() -> None:
    with pytest.raises(EngineError, match="Threads"):
        await _uci().analyze(chess.STARTING_FEN, EngineParameters(threads=5))
    with pytest.raises(EngineError, match="Hash"):
        await _uci().analyze(chess.STARTING_FEN, EngineParameters(hash_mb=1024))
    with pytest.raises(EngineError, match="analysis time"):
        await _uci().analyze(chess.STARTING_FEN, EngineParameters(movetime_ms=2001))


async def test_uci_preflight_and_parser_failures_are_explicit(tmp_path: Path) -> None:
    with pytest.raises(EngineError) as invalid_fen:
        await _uci().analyze("not a fen", EngineParameters(multipv=1))
    assert invalid_fen.value.code == "invalid_fen"

    missing = UciEngine(
        tmp_path / "missing-engine",
        max_threads=1,
        max_hash_mb=128,
        max_time_ms=1000,
    )
    with pytest.raises(EngineError) as unavailable:
        await missing.probe()
    assert unavailable.value.code == "engine_unavailable"

    board = chess.Board()
    legal_move = chess.Move.from_uci("e2e4")
    illegal_move = chess.Move.from_uci("e2e5")
    with pytest.raises(EngineError, match="empty principal variation"):
        _line_from_info(board, 1, {})
    with pytest.raises(EngineError, match="without a score"):
        _line_from_info(board, 1, {"pv": [legal_move]})
    with pytest.raises(EngineError, match="illegal PV move"):
        _san_line(board, [illegal_move])

    assert _version_from_name("Engine without version") == "unknown"


async def test_fake_uci_timeout_and_cancellation_leave_no_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FAKE_UCI_MODE", "timeout")
    pid_file = tmp_path / "engine.pid"
    monkeypatch.setenv("FAKE_UCI_PID_FILE", str(pid_file))
    with pytest.raises(EngineError) as captured:
        await _uci().analyze(chess.STARTING_FEN, EngineParameters(multipv=1, movetime_ms=100))
    assert captured.value.code == "timeout"
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)

    pid_file.unlink()
    analysis_task = asyncio.create_task(
        _uci().analyze(chess.STARTING_FEN, EngineParameters(multipv=1, movetime_ms=1000))
    )
    for _ in range(20):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    analysis_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await analysis_task
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_cancelled_analysis_does_not_report_late_transport_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FAKE_UCI_MODE", "timeout")
    pid_file = tmp_path / "cancelled-engine.pid"
    monkeypatch.setenv("FAKE_UCI_PID_FILE", str(pid_file))
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    unexpected: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: unexpected.append(context))
    try:
        task = asyncio.create_task(
            _uci().analyze(
                chess.STARTING_FEN,
                EngineParameters(multipv=1, movetime_ms=1000),
            )
        )
        for _ in range(100):
            if pid_file.exists():
                await asyncio.sleep(0.05)
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_handler)

    assert unexpected == []


def test_cancelled_analysis_during_ready_handshake_has_no_late_callback_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FAKE_UCI_MODE", "delayed-ready")
    pid_file = tmp_path / "delayed-ready-engine.pid"
    monkeypatch.setenv("FAKE_UCI_PID_FILE", str(pid_file))

    async def exercise() -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        unexpected: list[dict[str, Any]] = []
        loop.set_exception_handler(lambda _loop, context: unexpected.append(context))
        task = asyncio.create_task(
            _uci().analyze(
                chess.STARTING_FEN,
                EngineParameters(multipv=1, movetime_ms=1000),
            )
        )
        for _ in range(100):
            if pid_file.exists():
                await asyncio.sleep(0.05)
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.3)
        return unexpected

    assert uvloop.run(exercise()) == []
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_cancelled_engine_play_leaves_no_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FAKE_UCI_MODE", "timeout")
    pid_file = tmp_path / "play-engine.pid"
    monkeypatch.setenv("FAKE_UCI_PID_FILE", str(pid_file))
    task = asyncio.create_task(_uci().play(chess.STARTING_FEN, strength=5))
    for _ in range(100):
        if pid_file.exists():
            await asyncio.sleep(0.05)
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_uci_cleanup_tolerates_a_transport_closed_before_quit() -> None:
    returncode: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    class ClosedDuringQuitProtocol:
        async def quit(self) -> None:
            raise RuntimeError("handler is closed")

    class ClosingTransport:
        killed = False

        def is_closing(self) -> bool:
            return False

        def kill(self) -> None:
            self.killed = True
            returncode.set_result(-9)

        def close(self) -> None:
            return None

    protocol = ClosedDuringQuitProtocol()
    protocol.returncode = returncode  # type: ignore[attr-defined]
    transport = ClosingTransport()

    await UciEngine._close(cast(Any, transport), cast(Any, protocol))

    assert transport.killed is True


def test_analysis_cache_key_covers_full_fen_version_and_every_parameter() -> None:
    base = EngineParameters()
    original = analysis_cache_key(
        chess.STARTING_FEN,
        source="engine",
        engine_name="FakeFish",
        engine_version="1",
        parameters=base,
    )
    variants = [
        (chess.STARTING_FEN.replace("0 1", "1 1"), "FakeFish", "1", base),
        (chess.STARTING_FEN, "Other", "1", base),
        (chess.STARTING_FEN, "FakeFish", "2", base),
        (chess.STARTING_FEN, "FakeFish", "1", base.model_copy(update={"multipv": 3})),
        (chess.STARTING_FEN, "FakeFish", "1", base.model_copy(update={"movetime_ms": 801})),
        (chess.STARTING_FEN, "FakeFish", "1", base.model_copy(update={"threads": 2})),
        (chess.STARTING_FEN, "FakeFish", "1", base.model_copy(update={"hash_mb": 256})),
        (chess.STARTING_FEN, "FakeFish", "1", base.model_copy(update={"depth": 12})),
    ]
    assert len(
        {
            analysis_cache_key(
                fen,
                source="engine",
                engine_name=name,
                engine_version=version,
                parameters=parameters,
            )
            for fen, name, version, parameters in variants
        }
    ) == len(variants)
    assert all(
        analysis_cache_key(
            fen,
            source="engine",
            engine_name=name,
            engine_version=version,
            parameters=parameters,
        )
        != original
        for fen, name, version, parameters in variants
    )


async def test_engine_service_persists_and_reuses_cache(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'engine.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'engine.db'}",
        stockfish_path=FIXTURE_ENGINE,
        syzygy_path=tmp_path / "missing",
        engine_worker_enabled=False,
    )
    try:
        request = AnalysisRequest()
        async with database.session() as session, session.begin():
            first = await EngineService(session, settings).analyze(request)
        async with database.session() as session, session.begin():
            second = await EngineService(session, settings).analyze(request)
        assert first.from_cache is False
        assert second.from_cache is True
        assert first.id == second.id
        assert len(second.lines) == 4
    finally:
        await database.close()


async def test_play_review_and_save_course_draft_use_existing_knowledge_layer(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'game.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'game.db'}",
        stockfish_path=FIXTURE_ENGINE,
        syzygy_path=tmp_path / "missing",
        engine_worker_enabled=False,
    )
    try:
        async with database.session() as session, session.begin():
            game = await EngineService(session, settings).create_game(EngineGameCreate())
        async with database.session() as session, session.begin():
            game = await EngineService(session, settings).play_move(
                game.id, EngineGameMoveCreate(uci="e2e4", expected_version=game.version)
            )
        assert [move.uci for move in game.moves] == ["e2e4", "e7e5"]
        assert game.version == 2
        assert game.current_fen.split()[1] == "w"

        async with database.session() as session, session.begin():
            review = await EngineService(session, settings).review_game(game.id)
        assert review.analyzed_positions == 1
        assert review.findings[0].played_uci == "e2e4"
        assert review.findings[0].best_uci == "e2e4"

        async with database.session() as session, session.begin():
            draft = await EngineService(session, settings).save_review_draft(
                game.id,
                title="Engine findings",
                finding_plies=[review.findings[0].ply],
            )
        assert len(draft.module_ids) == 1
        async with database.session() as session:
            course = await ContentService(session).get_course(draft.course_id)
            modules = await ContentService(session).list_modules(draft.course_id)
            editor = await ContentService(session).get_module_editor(draft.course_id, modules[0].id)
        assert course.status == "draft"
        assert course.mode == "traditional"
        assert editor.notes[0].review_status == "draft"
        assert "Human review required" in editor.notes[0].rendered_markdown
    finally:
        await database.close()


async def test_interactive_move_does_not_hold_sqlite_transaction_during_engine_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'concurrent-game.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'concurrent-game.db'}",
        stockfish_path=FIXTURE_ENGINE,
        syzygy_path=tmp_path / "missing",
        engine_worker_enabled=False,
    )
    engine_started = asyncio.Event()
    allow_engine = asyncio.Event()

    async def delayed_play(
        engine: UciEngine, fen: str, *, strength: int
    ) -> tuple[EngineIdentity, chess.Move]:
        del engine, fen, strength
        engine_started.set()
        await allow_engine.wait()
        return EngineIdentity(name="FakeFish", version="1.2"), chess.Move.from_uci("e7e5")

    try:
        async with database.session() as session, session.begin():
            game = await EngineService(session, settings).create_game(EngineGameCreate())
        monkeypatch.setattr(UciEngine, "play", delayed_play)
        move_task = asyncio.create_task(
            play_game_move(
                database,
                settings,
                game.id,
                EngineGameMoveCreate(uci="e2e4", expected_version=game.version),
            )
        )
        await asyncio.wait_for(engine_started.wait(), timeout=1)

        # This models a worker heartbeat/outbox write while Stockfish thinks.
        # It must commit before the engine is released, proving the read
        # transaction was closed rather than merely relying on a busy timeout.
        async with database.session() as session, session.begin():
            session.add(
                InvalidationEvent(
                    resource_type="job",
                    resource_id="concurrent-heartbeat",
                    reason="running",
                )
            )

        allow_engine.set()
        updated = await asyncio.wait_for(move_task, timeout=2)
        assert [move.uci for move in updated.moves] == ["e2e4", "e7e5"]
        assert updated.version == 2
    finally:
        allow_engine.set()
        await database.close()


async def test_game_created_from_terminal_fen_is_immediately_finished(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'terminal-game.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'terminal-game.db'}",
        stockfish_path=FIXTURE_ENGINE,
        syzygy_path=tmp_path / "missing",
        engine_worker_enabled=False,
    )
    try:
        async with database.session() as session, session.begin():
            game = await EngineService(session, settings).create_game(
                EngineGameCreate(
                    fen="7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
                    user_color="black",
                )
            )
        assert game.status == "finished"
        assert game.result == "1-0"
        assert game.moves == []
    finally:
        await database.close()


async def test_missing_syzygy_is_an_explicit_engine_fallback(tmp_path: Path) -> None:
    service = TablebaseService(tmp_path / "missing")
    result = await service.probe("8/8/8/8/8/8/4K3/6k1 w - - 0 1")
    assert result.eligible is True
    assert result.available is False
    assert result.wdl is None
    assert "no local Syzygy" in (result.reason or "")


async def test_small_real_syzygy_fixture_probes_wdl_dtz_and_best_moves() -> None:
    result = await TablebaseService(SYZYGY_FIXTURE).probe("k7/8/1QK5/8/8/8/8/8 w - - 0 1")
    assert result.available is True
    assert result.eligible is True
    assert result.wdl == 2
    assert result.dtz is not None
    assert result.best_moves
    board = chess.Board("k7/8/1QK5/8/8/8/8/8 w - - 0 1")
    assert all(chess.Move.from_uci(uci) in board.legal_moves for uci in result.best_moves)


def test_fake_engine_fixture_is_executable() -> None:
    assert os.access(FIXTURE_ENGINE, os.X_OK)
