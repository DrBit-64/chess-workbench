from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from sanic import Request, Sanic
from sanic.config import Config
from sanic.response import HTTPResponse
from sanic_ext import Extend

from chess_workbench.api.content import content_blueprint
from chess_workbench.api.engine import engine_blueprint
from chess_workbench.api.errors import ApiError, handle_api_error
from chess_workbench.api.graph import graph_blueprint
from chess_workbench.api.health import health_blueprint
from chess_workbench.api.pdf import pdf_blueprint
from chess_workbench.api.pgn import pgn_blueprint
from chess_workbench.config import Settings
from chess_workbench.services import ServiceError
from chess_workbench.services.engine import process_analysis_job
from chess_workbench.services.pdf_extraction import process_pdf_extraction_job
from chess_workbench.services.worker import JobHandler, SqlWorker
from chess_workbench.store.database import Database


@dataclass
class AppContext:
    settings: Settings
    database: Database
    pgn_import_lock: asyncio.Lock
    pdf_persistence_lock: asyncio.Lock
    worker_task: asyncio.Task[None] | None = None


ChessWorkbenchApp = Sanic[Config, AppContext]


def create_app(settings: Settings | None = None) -> ChessWorkbenchApp:
    """Build an isolated application instance for production or tests."""

    resolved_settings = settings or Settings()
    app = Sanic(
        resolved_settings.service_name,
        ctx=AppContext(
            settings=resolved_settings,
            database=Database(resolved_settings.database_url),
            pgn_import_lock=asyncio.Lock(),
            pdf_persistence_lock=asyncio.Lock(),
        ),
        configure_logging=not resolved_settings.debug,
    )

    # Sanic must permit the bounded PDF plus finite multipart framing overhead.
    # Keep a larger framework default intact when pdf_max_bytes is configured down.
    app.config.REQUEST_MAX_SIZE = max(
        int(app.config.REQUEST_MAX_SIZE),
        resolved_settings.pdf_max_bytes + 1024 * 1024,
    )

    app.config.OAS_AUTODOC = False
    Extend(app)
    app.ext.openapi.describe(
        "ChessWorkbench API",
        version=resolved_settings.version,
        description="Authoritative HTTP API for ChessWorkbench.",
    )

    app.exception(ApiError)(handle_api_error)

    @app.exception(ServiceError)
    async def handle_service_error(request: Request, error: ServiceError) -> HTTPResponse:
        return await handle_api_error(
            request,
            ApiError(error.status, error.code, error.message, error.details),
        )

    app.blueprint(health_blueprint)
    app.blueprint(graph_blueprint)
    app.blueprint(content_blueprint)
    app.blueprint(pgn_blueprint)
    app.blueprint(pdf_blueprint)
    app.blueprint(engine_blueprint)

    @app.before_server_start
    async def start_worker(starting_app: ChessWorkbenchApp) -> None:
        if starting_app.ctx.settings.engine_worker_enabled:
            handlers: dict[str, JobHandler] = {"pdf_extraction": process_pdf_extraction_job}
            if starting_app.ctx.settings.stockfish_path.is_file():
                handlers["engine_analysis"] = process_analysis_job
            worker = SqlWorker(
                starting_app.ctx.database,
                starting_app.ctx.settings,
                worker_id=f"api-{id(starting_app)}",
                handlers=handlers,
            )
            starting_app.ctx.worker_task = asyncio.create_task(worker.run_forever())

    @app.after_server_stop
    async def close_database(stopping_app: ChessWorkbenchApp) -> None:
        if stopping_app.ctx.worker_task is not None:
            stopping_app.ctx.worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stopping_app.ctx.worker_task
        await stopping_app.ctx.database.close()

    return app
