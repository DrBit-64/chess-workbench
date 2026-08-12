from __future__ import annotations

from typing import Literal
from uuid import UUID

import chess
from pydantic import Field, field_validator

from chess_workbench.schemas.domain import NonEmptyText, StrictContract, UciMove, UtcDateTime
from chess_workbench.schemas.jobs import JobRead as JobRead
from chess_workbench.schemas.jobs import JobStatusValue as JobStatusValue

EngineSource = Literal["engine", "tablebase"]


def _legal_fen(value: str) -> str:
    try:
        board = chess.Board(value)
    except ValueError as error:
        raise ValueError("fen must describe a valid standard chess position") from error
    if not board.is_valid():
        raise ValueError("fen must describe a legal standard chess position")
    return board.fen(en_passant="fen")


class EngineParameters(StrictContract):
    multipv: int = Field(default=4, ge=1, le=5)
    movetime_ms: int = Field(default=800, ge=100, le=30_000)
    depth: int | None = Field(default=None, ge=1, le=50)
    threads: int = Field(default=1, ge=1, le=32)
    hash_mb: int = Field(default=128, ge=16, le=4096)
    ponder: Literal[False] = False


class AnalysisRequest(StrictContract):
    fen: NonEmptyText = chess.STARTING_FEN
    parameters: EngineParameters = Field(default_factory=EngineParameters)

    _validate_fen = field_validator("fen")(_legal_fen)


class AnalysisJobRequest(AnalysisRequest):
    idempotency_key: str = Field(min_length=1, max_length=128)


class AnalysisLine(StrictContract):
    rank: int = Field(ge=1, le=5)
    score_cp: int | None
    mate: int | None
    wdl: tuple[int, int, int] | None
    uci: list[UciMove]
    san: list[NonEmptyText]


class AnalysisRead(StrictContract):
    id: UUID
    fen: NonEmptyText
    source: EngineSource
    engine_name: NonEmptyText
    engine_version: NonEmptyText
    parameters: EngineParameters
    lines: list[AnalysisLine]
    depth: int | None
    seldepth: int | None
    nodes: int | None
    elapsed_ms: int = Field(ge=0)
    from_cache: bool
    created_at: UtcDateTime


class EngineCapabilities(StrictContract):
    available: bool
    engine_path: str
    engine_name: str | None
    engine_version: str | None
    syzygy_available: bool
    syzygy_path: str
    default_parameters: EngineParameters
    max_threads: int
    max_hash_mb: int
    max_time_ms: int
    time_presets_ms: list[int]
    multipv_max: int = 5
    install_hint: str | None


class InvalidationRead(StrictContract):
    id: int
    resource_type: NonEmptyText
    resource_id: NonEmptyText
    reason: NonEmptyText
    created_at: UtcDateTime


class TablebaseRead(StrictContract):
    available: bool
    eligible: bool
    wdl: int | None
    dtz: int | None
    best_moves: list[UciMove]
    reason: str | None


class EngineGameCreate(StrictContract):
    fen: NonEmptyText = chess.STARTING_FEN
    user_color: Literal["white", "black"] = "white"
    strength: int = Field(default=5, ge=1, le=8)

    _validate_fen = field_validator("fen")(_legal_fen)


class EngineGameMoveCreate(StrictContract):
    uci: UciMove
    expected_version: int = Field(ge=1)


class EngineGameMoveRead(StrictContract):
    ply: int
    actor: Literal["user", "engine"]
    before_fen: NonEmptyText
    after_fen: NonEmptyText
    uci: UciMove
    san: NonEmptyText


class EngineGameRead(StrictContract):
    id: UUID
    version: int
    initial_fen: NonEmptyText
    current_fen: NonEmptyText
    user_color: Literal["white", "black"]
    strength: int
    status: Literal["active", "finished", "abandoned"]
    result: str | None
    engine_name: NonEmptyText
    engine_version: NonEmptyText
    moves: list[EngineGameMoveRead]
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ReviewFinding(StrictContract):
    ply: int
    fen: NonEmptyText
    played_uci: UciMove
    best_uci: UciMove
    loss_cp: int = Field(ge=0)
    verdict: Literal["best", "good", "inaccuracy", "mistake", "blunder"]
    explanation: str


class EngineGameReviewRead(StrictContract):
    game_id: UUID
    findings: list[ReviewFinding]
    analyzed_positions: int
    created_at: UtcDateTime


class SaveReviewDraftRequest(StrictContract):
    title: str = Field(min_length=1, max_length=200)
    finding_plies: list[int] = Field(min_length=1, max_length=100)


class SaveReviewDraftRead(StrictContract):
    course_id: UUID
    module_ids: list[UUID]
