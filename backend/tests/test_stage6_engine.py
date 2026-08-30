from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, cast

import chess
import pytest
import uvloop

from chess_workbench.config import Settings
from chess_workbench.schemas.engine import (
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
from chess_workbench.store.models import InvalidationEvent

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


def test_fake_uci_probe_works_under_sanic_uvloop() -> None:
    identity = uvloop.run(_uci().probe())

    assert identity.name == "FakeFish 1.2"
    assert identity.version == "1.2"


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
