from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from typing import Any, cast
from uuid import UUID

import chess
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from chess_workbench.config import Settings
from chess_workbench.domain.analysis import engine_threshold_verdict
from chess_workbench.schemas.domain import (
    CourseCreate,
    CourseKnowledgeNoteBlockCreate,
    CourseModuleCreate,
)
from chess_workbench.schemas.engine import (
    AnalysisCacheLookupRead,
    AnalysisCacheLookupRequest,
    AnalysisLine,
    AnalysisRead,
    AnalysisRequest,
    EngineCapabilities,
    EngineGameCreate,
    EngineGameMoveCreate,
    EngineGameMoveRead,
    EngineGameRead,
    EngineGameReviewRead,
    EngineParameters,
    ReviewFinding,
    SaveReviewDraftRead,
    TablebaseRead,
)
from chess_workbench.services.content import ContentService
from chess_workbench.services.jobs import JobService
from chess_workbench.services.jobs import job_read as job_read
from chess_workbench.services.tablebase import TablebaseService
from chess_workbench.services.uci import EngineError, EngineIdentity, EngineResult, UciEngine
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    EngineAnalysis,
    EngineGame,
    EngineGameMove,
    EngineGameReview,
)


def analysis_cache_key(
    fen: str,
    *,
    source: str,
    engine_name: str,
    engine_version: str,
    parameters: EngineParameters,
) -> str:
    board = chess.Board(fen)
    identity = {
        "fen": board.fen(en_passant="fen"),
        "source": source,
        "engine_name": engine_name,
        "engine_version": engine_version,
        "parameters": parameters.model_dump(mode="json"),
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _analysis_read(row: EngineAnalysis, *, from_cache: bool) -> AnalysisRead:
    return AnalysisRead(
        id=row.id,
        fen=row.fen,
        source=cast(Any, row.source),
        engine_name=row.engine_name,
        engine_version=row.engine_version,
        parameters=EngineParameters.model_validate(row.parameters),
        lines=[AnalysisLine.model_validate(line) for line in row.lines],
        depth=row.depth,
        seldepth=row.seldepth,
        nodes=row.nodes,
        elapsed_ms=row.elapsed_ms,
        from_cache=from_cache,
        created_at=row.created_at,
    )


class EngineService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.uci = UciEngine(
            settings.stockfish_path,
            max_threads=settings.engine_max_threads,
            max_hash_mb=settings.engine_max_hash_mb,
            max_time_ms=settings.engine_max_time_ms,
        )
        self.tablebase = TablebaseService(settings.syzygy_path)

    async def capabilities(self) -> EngineCapabilities:
        identity: EngineIdentity | None = None
        if self.settings.stockfish_path.is_file():
            with suppress(EngineError):
                identity = await self.uci.probe_cached()
        return EngineCapabilities(
            available=identity is not None,
            engine_path=str(self.settings.stockfish_path),
            engine_name=identity.name if identity else None,
            engine_version=identity.version if identity else None,
            syzygy_available=self.tablebase.available,
            syzygy_path=str(self.settings.syzygy_path),
            default_parameters=EngineParameters(),
            max_threads=self.settings.engine_max_threads,
            max_hash_mb=self.settings.engine_max_hash_mb,
            max_time_ms=self.settings.engine_max_time_ms,
            time_presets_ms=[500, 800, 2000, 4000, 6000, 8000, 10000, 12000, 15000, 20000, 30000],
            install_hint=None
            if identity
            else "run `make install-stockfish` from the repository root",
        )

    async def analyze(self, request: AnalysisRequest) -> AnalysisRead:
        tablebase = await self.tablebase.probe(request.fen)
        if tablebase.available and tablebase.wdl is not None:
            return await self._tablebase_analysis(request, tablebase)

        identity = await self.uci.probe_cached()
        key = analysis_cache_key(
            request.fen,
            source="engine",
            engine_name=identity.name,
            engine_version=identity.version,
            parameters=request.parameters,
        )
        cached = await self.session.scalar(
            select(EngineAnalysis).where(EngineAnalysis.cache_key == key)
        )
        if cached is not None:
            return _analysis_read(cached, from_cache=True)
        result = await self.uci.analyze(request.fen, request.parameters)
        if result.identity != identity:
            key = analysis_cache_key(
                request.fen,
                source="engine",
                engine_name=result.identity.name,
                engine_version=result.identity.version,
                parameters=request.parameters,
            )
        return await self._persist_result(request, key, result)

    async def lookup_cached_fens(
        self,
        request: AnalysisCacheLookupRequest,
    ) -> AnalysisCacheLookupRead:
        rows = list(
            await self.session.scalars(
                select(EngineAnalysis).where(EngineAnalysis.fen.in_(request.fens))
            )
        )
        identity: EngineIdentity | None = None
        if self.settings.stockfish_path.is_file():
            with suppress(EngineError):
                identity = await self.uci.probe_cached()
        parameters = request.parameters.model_dump(mode="json")
        cached = {
            row.fen
            for row in rows
            if row.parameters == parameters
            and (
                (
                    row.source == "tablebase"
                    and row.engine_name == "Syzygy"
                    and row.engine_version == "v1"
                )
                or (
                    identity is not None
                    and row.source == "engine"
                    and row.engine_name == identity.name
                    and row.engine_version == identity.version
                )
            )
        }
        return AnalysisCacheLookupRead(
            cached_fens=[fen for fen in request.fens if fen in cached],
            missing_fens=[fen for fen in request.fens if fen not in cached],
        )

    async def get_analysis(self, analysis_id: UUID) -> AnalysisRead:
        row = await self.session.get(EngineAnalysis, analysis_id)
        if row is None:
            raise LookupError("engine analysis not found")
        return _analysis_read(row, from_cache=False)

    async def _persist_result(
        self, request: AnalysisRequest, key: str, result: EngineResult
    ) -> AnalysisRead:
        row = EngineAnalysis(
            cache_key=key,
            fen=chess.Board(request.fen).fen(en_passant="fen"),
            source="engine",
            engine_name=result.identity.name,
            engine_version=result.identity.version,
            parameters=request.parameters.model_dump(mode="json"),
            lines=[line.model_dump(mode="json") for line in result.lines],
            depth=result.depth,
            seldepth=result.seldepth,
            nodes=result.nodes,
            elapsed_ms=result.elapsed_ms,
            from_cache=False,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(EngineAnalysis).where(EngineAnalysis.cache_key == key)
            )
            if existing is None:
                raise
            return _analysis_read(existing, from_cache=True)
        await JobService(self.session).emit("analysis", str(row.id), "created")
        return _analysis_read(row, from_cache=False)

    async def _tablebase_analysis(
        self, request: AnalysisRequest, tablebase: TablebaseRead
    ) -> AnalysisRead:
        key = analysis_cache_key(
            request.fen,
            source="tablebase",
            engine_name="Syzygy",
            engine_version="v1",
            parameters=request.parameters,
        )
        cached = await self.session.scalar(
            select(EngineAnalysis).where(EngineAnalysis.cache_key == key)
        )
        if cached is not None:
            return _analysis_read(cached, from_cache=True)
        board = chess.Board(request.fen)
        assert tablebase.wdl is not None
        white_wdl = tablebase.wdl if board.turn == chess.WHITE else -tablebase.wdl
        distribution = (
            (1000, 0, 0) if white_wdl > 0 else (0, 0, 1000) if white_wdl < 0 else (0, 1000, 0)
        )
        lines: list[AnalysisLine] = []
        for rank, uci in enumerate(tablebase.best_moves[: request.parameters.multipv], 1):
            move = chess.Move.from_uci(uci)
            lines.append(
                AnalysisLine(
                    rank=rank,
                    score_cp=None,
                    mate=None,
                    wdl=distribution,
                    uci=[uci],
                    san=[board.san(move)],
                )
            )
        row = EngineAnalysis(
            cache_key=key,
            fen=board.fen(en_passant="fen"),
            source="tablebase",
            engine_name="Syzygy",
            engine_version="v1",
            parameters=request.parameters.model_dump(mode="json"),
            lines=[line.model_dump(mode="json") for line in lines],
            depth=None,
            seldepth=None,
            nodes=None,
            elapsed_ms=0,
            from_cache=False,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(EngineAnalysis).where(EngineAnalysis.cache_key == key)
            )
            if existing is None:
                raise
            return _analysis_read(existing, from_cache=True)
        await JobService(self.session).emit("analysis", str(row.id), "created")
        return _analysis_read(row, from_cache=False)

    async def create_game(self, data: EngineGameCreate) -> EngineGameRead:
        identity = await self.uci.probe_cached()
        board = chess.Board(data.fen)
        row = EngineGame(
            initial_fen=board.fen(en_passant="fen"),
            current_fen=board.fen(en_passant="fen"),
            user_color=data.user_color,
            strength=data.strength,
            status="active",
            result=None,
            engine_name=identity.name,
            engine_version=identity.version,
            moves=[],
        )
        self.session.add(row)
        await self.session.flush()
        if board.is_game_over(claim_draw=True):
            self._finish_game(row, board)
        elif (board.turn == chess.WHITE) != (data.user_color == "white"):
            await self._append_engine_move(row)
        await JobService(self.session).emit("engine_game", str(row.id), "created")
        return await self.get_game(row.id)

    async def get_game(self, game_id: UUID) -> EngineGameRead:
        row = await self.session.scalar(
            select(EngineGame)
            .where(EngineGame.id == game_id)
            .options(selectinload(EngineGame.moves))
        )
        if row is None:
            raise LookupError("engine game not found")
        return self._game_read(row)

    async def play_move(self, game_id: UUID, data: EngineGameMoveCreate) -> EngineGameRead:
        row = await self.session.scalar(
            select(EngineGame)
            .where(EngineGame.id == game_id)
            .options(selectinload(EngineGame.moves))
        )
        if row is None:
            raise LookupError("engine game not found")
        if row.version != data.expected_version:
            raise ValueError("stale_version")
        if row.status != "active":
            raise ValueError("game is not active")
        board = chess.Board(row.current_fen)
        user_turn = (board.turn == chess.WHITE) == (row.user_color == "white")
        if not user_turn:
            raise ValueError("it is not the user's turn")
        try:
            move = chess.Move.from_uci(data.uci)
        except ValueError as error:
            raise ValueError("invalid move") from error
        if move not in board.legal_moves:
            raise ValueError("illegal move")
        self._append_move(row, board, move, "user")
        if row.status == "active":
            await self._append_engine_move(row)
        await JobService(self.session).emit("engine_game", str(row.id), "moved")
        await self.session.flush()
        return await self.get_game(row.id)

    async def _append_engine_move(self, row: EngineGame) -> None:
        board = chess.Board(row.current_fen)
        if board.is_game_over(claim_draw=True):
            self._finish_game(row, board)
            return
        _, move = await self.uci.play(row.current_fen, strength=row.strength)
        self._append_move(row, board, move, "engine")

    def _append_move(
        self, row: EngineGame, board: chess.Board, move: chess.Move, actor: str
    ) -> None:
        before = board.fen(en_passant="fen")
        san = board.san(move)
        board.push(move)
        after = board.fen(en_passant="fen")
        row.moves.append(
            EngineGameMove(
                game_id=row.id,
                ply=len(row.moves) + 1,
                actor=actor,
                before_fen=before,
                after_fen=after,
                uci=move.uci(),
                san=san,
            )
        )
        row.current_fen = after
        if board.is_game_over(claim_draw=True):
            self._finish_game(row, board)

    @staticmethod
    def _finish_game(row: EngineGame, board: chess.Board) -> None:
        row.status = "finished"
        row.result = board.result(claim_draw=True)

    @staticmethod
    def _game_read(row: EngineGame) -> EngineGameRead:
        moves = sorted(row.moves, key=lambda move: move.ply)
        return EngineGameRead(
            id=row.id,
            version=row.version,
            initial_fen=row.initial_fen,
            current_fen=row.current_fen,
            user_color=cast(Any, row.user_color),
            strength=row.strength,
            status=cast(Any, row.status),
            result=row.result,
            engine_name=row.engine_name,
            engine_version=row.engine_version,
            moves=[
                EngineGameMoveRead(
                    ply=move.ply,
                    actor=cast(Any, move.actor),
                    before_fen=move.before_fen,
                    after_fen=move.after_fen,
                    uci=move.uci,
                    san=move.san,
                )
                for move in moves
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def review_game(self, game_id: UUID) -> EngineGameReviewRead:
        existing = await self.session.scalar(
            select(EngineGameReview).where(EngineGameReview.game_id == game_id)
        )
        if existing is not None:
            return self._review_read(existing)
        game = await self.session.scalar(
            select(EngineGame)
            .where(EngineGame.id == game_id)
            .options(selectinload(EngineGame.moves))
        )
        if game is None:
            raise LookupError("engine game not found")
        findings: list[ReviewFinding] = []
        user_moves = [move for move in game.moves if move.actor == "user"]
        review_parameters = EngineParameters(multipv=1, movetime_ms=500, threads=1, hash_mb=128)
        for move in sorted(user_moves, key=lambda item: item.ply):
            best = await self.analyze(
                AnalysisRequest(fen=move.before_fen, parameters=review_parameters)
            )
            best_cp = _score_for_side(best.lines[0], game.user_color)
            after_cp = _terminal_score_for_side(move.after_fen, game.user_color)
            if after_cp is None:
                after = await self.analyze(
                    AnalysisRequest(fen=move.after_fen, parameters=review_parameters)
                )
                after_cp = _score_for_side(after.lines[0], game.user_color)
            loss = max(0, best_cp - after_cp)
            verdict = engine_threshold_verdict(loss)
            findings.append(
                ReviewFinding(
                    ply=move.ply,
                    fen=move.before_fen,
                    played_uci=move.uci,
                    best_uci=best.lines[0].uci[0],
                    loss_cp=loss,
                    verdict=verdict.value,
                    explanation=f"{verdict.value}: lost approximately {loss / 100:.2f} pawns",
                )
            )
        report = {
            "findings": [finding.model_dump(mode="json") for finding in findings],
            "analyzed_positions": len(user_moves),
        }
        row = EngineGameReview(game_id=game.id, report=report)
        self.session.add(row)
        await self.session.flush()
        await JobService(self.session).emit("engine_game_review", str(game.id), "created")
        return self._review_read(row)

    @staticmethod
    def _review_read(row: EngineGameReview) -> EngineGameReviewRead:
        return EngineGameReviewRead(
            game_id=row.game_id,
            findings=[ReviewFinding.model_validate(item) for item in row.report["findings"]],
            analyzed_positions=int(row.report["analyzed_positions"]),
            created_at=row.created_at,
        )

    async def save_review_draft(
        self, game_id: UUID, *, title: str, finding_plies: list[int]
    ) -> SaveReviewDraftRead:
        review = await self.review_game(game_id)
        selected = [item for item in review.findings if item.ply in set(finding_plies)]
        if not selected:
            raise ValueError("no requested review findings exist")
        content = ContentService(self.session)
        course = await content.create_course(
            CourseCreate(
                title=title,
                description="Engine-game findings awaiting human review.",
                category="Engine review",
                tags=["engine-review"],
                status="draft",
                mode="traditional",
            )
        )
        module_ids: list[UUID] = []
        for index, finding in enumerate(selected):
            module = await content.create_module(
                CourseModuleCreate(
                    course_id=course.id,
                    title=f"Move {finding.ply}: {finding.played_uci}",
                    description="Draft generated from engine review; verify before publishing.",
                    start_fen=finding.fen,
                    sort_order=index,
                )
            )
            assert module.start_occurrence_id is not None
            await content.create_course_knowledge_note_block(
                module.id,
                CourseKnowledgeNoteBlockCreate(
                    occurrence_id=module.start_occurrence_id,
                    note_type="candidate_comparison",
                    markdown=(
                        f"Played `{finding.played_uci}`; engine candidate `{finding.best_uci}`. "
                        f"Estimated loss: **{finding.loss_cp / 100:.2f}** pawns "
                        f"({finding.verdict}).\n\nHuman review required."
                    ),
                    review_status="draft",
                ),
            )
            module_ids.append(module.id)
        return SaveReviewDraftRead(course_id=course.id, module_ids=module_ids)


async def play_game_move(
    database: Database,
    settings: Settings,
    game_id: UUID,
    data: EngineGameMoveCreate,
) -> EngineGameRead:
    """Compute an engine reply outside SQL, then persist both plies atomically.

    SQLite cannot safely upgrade a long-lived read transaction after another
    connection (for example the SQL job worker heartbeat) has written. Take a
    read snapshot, perform the bounded UCI call without a transaction, and use
    the aggregate version/current FEN as the compare-and-swap guard in one
    short write transaction.
    """

    async with database.session() as read_session:
        snapshot = await read_session.scalar(
            select(EngineGame)
            .where(EngineGame.id == game_id)
            .options(selectinload(EngineGame.moves))
        )
        if snapshot is None:
            raise LookupError("engine game not found")
        if snapshot.version != data.expected_version:
            raise ValueError("stale_version")
        if snapshot.status != "active":
            raise ValueError("game is not active")
        snapshot_fen = snapshot.current_fen
        user_color = snapshot.user_color
        strength = snapshot.strength

    board = chess.Board(snapshot_fen)
    user_turn = (board.turn == chess.WHITE) == (user_color == "white")
    if not user_turn:
        raise ValueError("it is not the user's turn")
    try:
        user_move = chess.Move.from_uci(data.uci)
    except ValueError as error:
        raise ValueError("invalid move") from error
    if user_move not in board.legal_moves:
        raise ValueError("illegal move")

    board.push(user_move)
    engine_move: chess.Move | None = None
    if not board.is_game_over(claim_draw=True):
        uci = UciEngine(
            settings.stockfish_path,
            max_threads=settings.engine_max_threads,
            max_hash_mb=settings.engine_max_hash_mb,
            max_time_ms=settings.engine_max_time_ms,
        )
        _, engine_move = await uci.play(board.fen(en_passant="fen"), strength=strength)

    try:
        async with database.session() as write_session, write_session.begin():
            row = await write_session.scalar(
                select(EngineGame)
                .where(EngineGame.id == game_id)
                .options(selectinload(EngineGame.moves))
            )
            if (
                row is None
                or row.version != data.expected_version
                or row.current_fen != snapshot_fen
            ):
                raise ValueError("stale_version")
            service = EngineService(write_session, settings)
            persisted_board = chess.Board(row.current_fen)
            service._append_move(row, persisted_board, user_move, "user")
            if engine_move is not None:
                if engine_move not in persisted_board.legal_moves:
                    raise EngineError("malformed_output", "engine did not return a legal move")
                service._append_move(row, persisted_board, engine_move, "engine")
            await JobService(write_session).emit("engine_game", str(row.id), "moved")
            await write_session.flush()
            return service._game_read(row)
    except StaleDataError as error:
        raise ValueError("stale_version") from error


def _score_for_side(line: AnalysisLine, color: str) -> int:
    if line.mate is not None:
        white_score = 100_000 if line.mate > 0 else -100_000
    else:
        white_score = line.score_cp or 0
    return white_score if color == "white" else -white_score


def _terminal_score_for_side(fen: str, color: str) -> int | None:
    board = chess.Board(fen)
    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        return None
    if outcome.winner is None:
        return 0
    requested_color = chess.WHITE if color == "white" else chess.BLACK
    return 100_000 if outcome.winner == requested_color else -100_000


async def process_analysis_job(
    database: Database, settings: Settings, payload: dict[str, Any]
) -> dict[str, Any]:
    """Handler for ``engine_analysis`` jobs.

    Uses short-lived database transactions so that concurrent
    heartbeat writes do not cause SQLite ``database is locked``.
    Respects the Syzygy-first decision (Stage 6C): tablebase probe
    happens before any database transaction or Stockfish spawn.
    """
    from chess_workbench.services.tablebase import TablebaseService

    request = AnalysisRequest.model_validate(payload)

    # ── Syzygy-first (no transaction) ──────────────────────────
    tablebase = TablebaseService(settings.syzygy_path)
    tb_probe = await tablebase.probe(request.fen)

    if tb_probe.available and tb_probe.wdl is not None:
        # Tablebase hit: read/persist in short transactions.
        tb_key = analysis_cache_key(
            request.fen,
            source="tablebase",
            engine_name="Syzygy",
            engine_version="v1",
            parameters=request.parameters,
        )
        async with database.session() as tb_sess, tb_sess.begin():
            cached = await tb_sess.scalar(
                select(EngineAnalysis).where(EngineAnalysis.cache_key == tb_key)
            )
            if cached is not None:
                return {"analysis_id": str(cached.id), "from_cache": True}

        # Build tablebase lines (no DB).
        board = chess.Board(request.fen)
        assert tb_probe.wdl is not None and tb_probe.best_moves is not None
        white_wdl = tb_probe.wdl if board.turn == chess.WHITE else -tb_probe.wdl
        distribution = (
            (1000, 0, 0) if white_wdl > 0 else (0, 0, 1000) if white_wdl < 0 else (0, 1000, 0)
        )
        tb_lines: list[AnalysisLine] = []
        for rank, uci in enumerate(tb_probe.best_moves[: request.parameters.multipv], 1):
            move = chess.Move.from_uci(uci)
            tb_lines.append(
                AnalysisLine(
                    rank=rank,
                    score_cp=None,
                    mate=None,
                    wdl=distribution,
                    uci=[uci],
                    san=[board.san(move)],
                )
            )

        async with database.session() as tb_persist, tb_persist.begin():
            row = EngineAnalysis(
                cache_key=tb_key,
                fen=board.fen(en_passant="fen"),
                source="tablebase",
                engine_name="Syzygy",
                engine_version="v1",
                parameters=request.parameters.model_dump(mode="json"),
                lines=[line.model_dump(mode="json") for line in tb_lines],
                depth=None,
                seldepth=None,
                nodes=None,
                elapsed_ms=0,
                from_cache=False,
            )
            try:
                async with tb_persist.begin_nested():
                    tb_persist.add(row)
                    await tb_persist.flush()
            except IntegrityError:
                existing = await tb_persist.scalar(
                    select(EngineAnalysis).where(EngineAnalysis.cache_key == tb_key)
                )
                if existing is not None:
                    return {"analysis_id": str(existing.id), "from_cache": True}
                raise
            await JobService(tb_persist).emit("analysis", str(row.id), "created")
            return {"analysis_id": str(row.id), "from_cache": False}

    # ── Syzygy unavailable; use Stockfish ──────────────────────

    # Probe Stockfish identity (no DB).
    sf_engine = UciEngine(
        settings.stockfish_path,
        max_threads=settings.engine_max_threads,
        max_hash_mb=settings.engine_max_hash_mb,
        max_time_ms=settings.engine_max_time_ms,
    )
    identity = await sf_engine.probe_cached()

    # Check engine cache (short transaction).
    sf_key = analysis_cache_key(
        request.fen,
        source="engine",
        engine_name=identity.name,
        engine_version=identity.version,
        parameters=request.parameters,
    )
    async with database.session() as cache_sess, cache_sess.begin():
        cached = await cache_sess.scalar(
            select(EngineAnalysis).where(EngineAnalysis.cache_key == sf_key)
        )
        if cached is not None:
            return {"analysis_id": str(cached.id), "from_cache": True}

    # Run Stockfish (no DB).
    sf_result = await sf_engine.analyze(request.fen, request.parameters)
    if sf_result.identity != identity:
        sf_key = analysis_cache_key(
            request.fen,
            source="engine",
            engine_name=sf_result.identity.name,
            engine_version=sf_result.identity.version,
            parameters=request.parameters,
        )

    # Persist (short transaction).
    async with database.session() as persist_sess, persist_sess.begin():
        row = EngineAnalysis(
            cache_key=sf_key,
            fen=chess.Board(request.fen).fen(en_passant="fen"),
            source="engine",
            engine_name=sf_result.identity.name,
            engine_version=sf_result.identity.version,
            parameters=request.parameters.model_dump(mode="json"),
            lines=[line.model_dump(mode="json") for line in sf_result.lines],
            depth=sf_result.depth,
            seldepth=sf_result.seldepth,
            nodes=sf_result.nodes,
            elapsed_ms=sf_result.elapsed_ms,
            from_cache=False,
        )
        try:
            async with persist_sess.begin_nested():
                persist_sess.add(row)
                await persist_sess.flush()
        except IntegrityError:
            existing = await persist_sess.scalar(
                select(EngineAnalysis).where(EngineAnalysis.cache_key == sf_key)
            )
            if existing is not None:
                return {"analysis_id": str(existing.id), "from_cache": True}
            raise
        await JobService(persist_sess).emit("analysis", str(row.id), "created")
        return {"analysis_id": str(row.id), "from_cache": False}
