from __future__ import annotations

import asyncio
import json as json_module
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sanic import Blueprint, Request
from sanic.response import HTTPResponse, json
from sanic_ext import openapi

from chess_workbench.api.contracts import openapi_schema, parse_body
from chess_workbench.api.errors import ApiError
from chess_workbench.config import Settings
from chess_workbench.schemas.domain import ErrorResponse
from chess_workbench.schemas.engine import (
    AnalysisCacheLookupRead,
    AnalysisCacheLookupRequest,
    AnalysisJobRequest,
    AnalysisRead,
    AnalysisRequest,
    EngineCapabilities,
    EngineGameCreate,
    EngineGameMoveCreate,
    EngineGameRead,
    EngineGameReviewRead,
    InvalidationRead,
    JobRead,
    SaveReviewDraftRead,
    SaveReviewDraftRequest,
    TablebaseRead,
)
from chess_workbench.services.engine import (
    EngineService,
    job_read,
    play_game_move,
    process_analysis_job,
)
from chess_workbench.services.jobs import JobService
from chess_workbench.services.uci import EngineError
from chess_workbench.store.database import Database

engine_blueprint = Blueprint("engine", url_prefix="/api")


def _media(model: type[BaseModel]) -> dict[str, Any]:
    return {"application/json": openapi_schema(model)}


ERROR_SCHEMA = _media(ErrorResponse)


def _json(model: BaseModel, *, status: int = 200) -> HTTPResponse:
    return json(model.model_dump(mode="json"), status=status)


def _context(request: Request) -> tuple[Database, Settings]:
    return cast(Database, request.app.ctx.database), cast(Settings, request.app.ctx.settings)


def _engine_api_error(error: EngineError) -> ApiError:
    if error.code == "engine_unavailable":
        return ApiError(
            status=503,
            code="engine_unavailable",
            message=str(error),
            details={"engine_code": error.code},
        )
    return ApiError(
        status=422,
        code="engine_failure",
        message=str(error),
        details={"engine_code": error.code},
    )


@engine_blueprint.get("/engine/capabilities", name="engine_capabilities")
@openapi.operation("getEngineCapabilities")
@openapi.tag("engine")
@openapi.response(200, _media(EngineCapabilities), "Local engine capabilities")
async def engine_capabilities(request: Request) -> HTTPResponse:
    database, settings = _context(request)
    async with database.session() as session:
        payload = await EngineService(session, settings).capabilities()
    return _json(payload)


@engine_blueprint.post("/engine/analyses", name="create_analysis")
@openapi.operation("createEngineAnalysis")
@openapi.tag("engine")
@openapi.body(_media(AnalysisRequest), required=True)
@openapi.response(200, _media(AnalysisRead), "Analysis result or cache hit")
@openapi.response(503, ERROR_SCHEMA, "Engine unavailable")
async def create_analysis(request: Request) -> HTTPResponse:
    body = parse_body(request, AnalysisRequest)
    database, settings = _context(request)
    try:
        result = await process_analysis_job(database, settings, body.model_dump(mode="json"))
        analysis_id = UUID(result["analysis_id"])
        async with database.session() as session:
            payload = await EngineService(session, settings).get_analysis(analysis_id)
        payload = payload.model_copy(update={"from_cache": bool(result["from_cache"])})
    except EngineError as error:
        raise _engine_api_error(error) from error
    return _json(payload)


@engine_blueprint.post("/engine/analyses/cache-lookup", name="lookup_analysis_cache")
@openapi.operation("lookupEngineAnalysisCache")
@openapi.tag("engine")
@openapi.body(_media(AnalysisCacheLookupRequest), required=True)
@openapi.response(200, _media(AnalysisCacheLookupRead), "Persisted analysis cache coverage")
async def lookup_analysis_cache(request: Request) -> HTTPResponse:
    body = parse_body(request, AnalysisCacheLookupRequest)
    database, settings = _context(request)
    async with database.session() as session:
        payload = await EngineService(session, settings).lookup_cached_fens(body)
    return _json(payload)


@engine_blueprint.get("/engine/analyses/<analysis_id:uuid>", name="get_analysis")
@openapi.operation("getEngineAnalysis")
@openapi.tag("engine")
@openapi.response(200, _media(AnalysisRead), "Persisted analysis")
async def get_analysis(request: Request, analysis_id: UUID) -> HTTPResponse:
    database, settings = _context(request)
    try:
        async with database.session() as session:
            payload = await EngineService(session, settings).get_analysis(analysis_id)
    except LookupError as error:
        raise ApiError(404, "not_found", str(error)) from error
    return _json(payload)


@engine_blueprint.post("/engine/analysis-jobs", name="create_analysis_job")
@openapi.operation("createEngineAnalysisJob")
@openapi.tag("engine")
@openapi.body(_media(AnalysisJobRequest), required=True)
@openapi.response(202, _media(JobRead), "Analysis queued")
async def create_analysis_job(request: Request) -> HTTPResponse:
    body = parse_body(request, AnalysisJobRequest)
    database, settings = _context(request)
    if not settings.stockfish_path.is_file():
        raise ApiError(
            503,
            "engine_unavailable",
            "Stockfish is not installed; run make install-stockfish",
        )
    try:
        async with database.session() as session, session.begin():
            row = await JobService(session).enqueue(
                kind="engine_analysis",
                payload=AnalysisRequest(fen=body.fen, parameters=body.parameters).model_dump(
                    mode="json"
                ),
                idempotency_key=body.idempotency_key,
            )
            payload = job_read(row)
    except ValueError as error:
        raise ApiError(409, "idempotency_conflict", str(error)) from error
    return _json(payload, status=202)


@engine_blueprint.get("/jobs/<job_id:uuid>", name="get_job")
@openapi.operation("getJob")
@openapi.tag("jobs")
@openapi.response(200, _media(JobRead), "Job")
async def get_job(request: Request, job_id: UUID) -> HTTPResponse:
    database, _ = _context(request)
    async with database.session() as session:
        row = await JobService(session).get(job_id)
    if row is None:
        raise ApiError(404, "not_found", "job not found")
    return _json(job_read(row))


@engine_blueprint.post("/jobs/<job_id:uuid>/cancel", name="cancel_job")
@openapi.operation("cancelJob")
@openapi.tag("jobs")
@openapi.response(200, _media(JobRead), "Job cancellation state")
async def cancel_job(request: Request, job_id: UUID) -> HTTPResponse:
    database, _ = _context(request)
    async with database.session() as session, session.begin():
        row = await JobService(session).cancel(job_id)
        if row is None:
            raise ApiError(404, "not_found", "job not found")
        payload = job_read(row)
    return _json(payload)


@engine_blueprint.get("/invalidations", name="list_invalidations")
@openapi.operation("listInvalidations")
@openapi.tag("invalidation")
@openapi.parameter("after", int, "query", required=False)
@openapi.response(
    200,
    {"application/json": {"type": "array", "items": openapi_schema(InvalidationRead)}},
    "Durable invalidations",
)
async def list_invalidations(request: Request) -> HTTPResponse:
    try:
        after = max(0, int(request.args.get("after", "0")))
    except ValueError as error:
        raise ApiError(422, "validation_error", "after must be an integer") from error
    database, _ = _context(request)
    async with database.session() as session:
        rows = await JobService(session).events_after(after)
    payload = [
        InvalidationRead(
            id=row.id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            reason=row.reason,
            created_at=row.created_at,
        ).model_dump(mode="json")
        for row in rows
    ]
    return json(payload)


@engine_blueprint.websocket("/invalidations/ws", name="invalidation_socket")
async def invalidation_socket(request: Request, websocket: Any) -> None:
    try:
        cursor = max(0, int(request.args.get("after", "0")))
    except ValueError:
        cursor = 0
    database, settings = _context(request)
    while True:
        async with database.session() as session:
            rows = await JobService(session).events_after(cursor)
        for row in rows:
            cursor = row.id
            await websocket.send(
                json_module.dumps(
                    InvalidationRead(
                        id=row.id,
                        resource_type=row.resource_type,
                        resource_id=row.resource_id,
                        reason=row.reason,
                        created_at=row.created_at,
                    ).model_dump(mode="json")
                )
            )
        await asyncio.sleep(settings.engine_worker_poll_ms / 1000)


@engine_blueprint.post("/tablebase/probe", name="probe_tablebase")
@openapi.operation("probeTablebase")
@openapi.tag("engine")
@openapi.body(_media(AnalysisRequest), required=True)
@openapi.response(200, _media(TablebaseRead), "Syzygy probe or fallback reason")
async def probe_tablebase(request: Request) -> HTTPResponse:
    body = parse_body(request, AnalysisRequest)
    database, settings = _context(request)
    async with database.session() as session:
        payload = await EngineService(session, settings).tablebase.probe(body.fen)
    return _json(payload)


@engine_blueprint.post("/engine/games", name="create_engine_game")
@openapi.operation("createEngineGame")
@openapi.tag("engine games")
@openapi.body(_media(EngineGameCreate), required=True)
@openapi.response(201, _media(EngineGameRead), "Engine game created")
async def create_engine_game(request: Request) -> HTTPResponse:
    body = parse_body(request, EngineGameCreate)
    database, settings = _context(request)
    try:
        async with database.session() as session, session.begin():
            payload = await EngineService(session, settings).create_game(body)
    except EngineError as error:
        raise _engine_api_error(error) from error
    return _json(payload, status=201)


@engine_blueprint.get("/engine/games/<game_id:uuid>", name="get_engine_game")
@openapi.operation("getEngineGame")
@openapi.tag("engine games")
@openapi.response(200, _media(EngineGameRead), "Engine game")
async def get_engine_game(request: Request, game_id: UUID) -> HTTPResponse:
    database, settings = _context(request)
    try:
        async with database.session() as session:
            payload = await EngineService(session, settings).get_game(game_id)
    except LookupError as error:
        raise ApiError(404, "not_found", str(error)) from error
    return _json(payload)


@engine_blueprint.post("/engine/games/<game_id:uuid>/moves", name="play_engine_game_move")
@openapi.operation("playEngineGameMove")
@openapi.tag("engine games")
@openapi.body(_media(EngineGameMoveCreate), required=True)
@openapi.response(200, _media(EngineGameRead), "User and engine move applied")
async def play_engine_game_move(request: Request, game_id: UUID) -> HTTPResponse:
    body = parse_body(request, EngineGameMoveCreate)
    database, settings = _context(request)
    try:
        payload = await play_game_move(database, settings, game_id, body)
    except LookupError as error:
        raise ApiError(404, "not_found", str(error)) from error
    except ValueError as error:
        if str(error) == "stale_version":
            raise ApiError(409, "stale_version", str(error)) from error
        raise ApiError(422, "illegal_move", str(error)) from error
    except EngineError as error:
        raise _engine_api_error(error) from error
    return _json(payload)


@engine_blueprint.post("/engine/games/<game_id:uuid>/review", name="review_engine_game")
@openapi.operation("reviewEngineGame")
@openapi.tag("engine games")
@openapi.response(200, _media(EngineGameReviewRead), "Engine game review")
async def review_engine_game(request: Request, game_id: UUID) -> HTTPResponse:
    database, settings = _context(request)
    try:
        async with database.session() as session, session.begin():
            payload = await EngineService(session, settings).review_game(game_id)
    except LookupError as error:
        raise ApiError(404, "not_found", str(error)) from error
    except EngineError as error:
        raise _engine_api_error(error) from error
    return _json(payload)


@engine_blueprint.post(
    "/engine/games/<game_id:uuid>/review/course-draft", name="save_review_course_draft"
)
@openapi.operation("saveEngineReviewCourseDraft")
@openapi.tag("engine games")
@openapi.body(_media(SaveReviewDraftRequest), required=True)
@openapi.response(201, _media(SaveReviewDraftRead), "Traditional course draft")
async def save_review_course_draft(request: Request, game_id: UUID) -> HTTPResponse:
    body = parse_body(request, SaveReviewDraftRequest)
    database, settings = _context(request)
    try:
        async with database.session() as session, session.begin():
            payload = await EngineService(session, settings).save_review_draft(
                game_id, title=body.title, finding_plies=body.finding_plies
            )
    except LookupError as error:
        raise ApiError(404, "not_found", str(error)) from error
    except ValueError as error:
        raise ApiError(422, "validation_error", str(error)) from error
    return _json(payload, status=201)
