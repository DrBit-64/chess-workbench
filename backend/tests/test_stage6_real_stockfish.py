from pathlib import Path
from uuid import UUID

import chess
import pytest
from chess_workbench.config import PROJECT_ROOT, Settings
from chess_workbench.schemas.engine import AnalysisRequest, EngineParameters
from chess_workbench.services.engine import EngineService
from chess_workbench.services.jobs import JobService
from chess_workbench.services.uci import UciEngine
from chess_workbench.services.worker import SqlWorker
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database

STOCKFISH = PROJECT_ROOT / "data" / "engines" / "stockfish-18" / "stockfish"


@pytest.mark.skipif(not STOCKFISH.is_file(), reason="run make install-stockfish")
async def test_real_stockfish_18_returns_four_legal_versioned_pvs() -> None:
    result = await UciEngine(STOCKFISH, max_threads=2, max_hash_mb=256, max_time_ms=2000).analyze(
        chess.STARTING_FEN,
        EngineParameters(multipv=4, movetime_ms=200, threads=1, hash_mb=64),
    )
    assert result.identity.version == "18"
    assert len(result.lines) == 4
    for line in result.lines:
        board = chess.Board()
        for uci in line.uci:
            move = chess.Move.from_uci(uci)
            assert move in board.legal_moves
            board.push(move)


@pytest.mark.skipif(not STOCKFISH.is_file(), reason="run make install-stockfish")
async def test_real_stockfish_analysis_job_persists_versioned_multipv(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'real-engine-job.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'real-engine-job.db'}",
        stockfish_path=STOCKFISH,
        syzygy_path=tmp_path / "missing",
        engine_worker_enabled=False,
    )
    request = AnalysisRequest(
        parameters=EngineParameters(multipv=4, movetime_ms=200, threads=1, hash_mb=64)
    )
    try:
        async with database.session() as session, session.begin():
            job = await JobService(session).enqueue(
                kind="engine_analysis",
                payload=request.model_dump(mode="json"),
                idempotency_key="real-stockfish",
            )
            job_id = job.id
        assert await SqlWorker(database, settings, worker_id="real-test").run_once()
        async with database.session() as session:
            completed = await JobService(session).get(job_id)
            assert completed is not None
            assert completed.status == "succeeded"
            assert completed.attempt_count == 1
            assert completed.last_error_code is None
            assert completed.last_error_message is None
            assert completed.result is not None
            result = await EngineService(session, settings).get_analysis(
                UUID(str(completed.result["analysis_id"]))
            )
        assert result.engine_version == "18"
        assert len(result.lines) == 4
    finally:
        await database.close()


@pytest.mark.skipif(
    not (Path(__file__).parent / "fixtures" / "syzygy").is_dir(),
    reason="Syzygy fixture not installed",
)
async def test_background_job_respects_syzygy_first_without_stockfish(tmp_path: Path) -> None:
    """When Syzygy covers the position and Stockfish is absent, the
    background job must still succeed with source="tablebase"."""
    syzygy = Path(__file__).parent / "fixtures" / "syzygy"
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'syzygy-job.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'syzygy-job.db'}",
        stockfish_path=tmp_path / "nonexistent-stockfish",
        syzygy_path=syzygy,
        engine_worker_enabled=False,
    )
    request = AnalysisRequest(
        fen="k7/8/1QK5/8/8/8/8/8 w - - 0 1",
        parameters=EngineParameters(multipv=1, movetime_ms=200, threads=1, hash_mb=64),
    )
    try:
        async with database.session() as session, session.begin():
            job = await JobService(session).enqueue(
                kind="engine_analysis",
                payload=request.model_dump(mode="json"),
                idempotency_key="syzygy-job",
            )
            job_id = job.id
        assert await SqlWorker(database, settings, worker_id="syzygy-test").run_once()
        async with database.session() as session:
            completed = await JobService(session).get(job_id)
            assert completed is not None
            assert completed.status == "succeeded"
            assert completed.attempt_count == 1
            assert completed.last_error_code is None
            assert completed.last_error_message is None
            assert completed.result is not None
            analysis = await EngineService(session, settings).get_analysis(
                UUID(str(completed.result["analysis_id"]))
            )
        assert analysis.source == "tablebase"
        assert analysis.engine_name == "Syzygy"
    finally:
        await database.close()
