from __future__ import annotations

from dataclasses import dataclass

from sanic import Sanic
from sanic.config import Config
from sanic_ext import Extend

from chess_workbench.api.health import health_blueprint
from chess_workbench.config import Settings
from chess_workbench.store.database import Database


@dataclass
class AppContext:
    settings: Settings
    database: Database


ChessWorkbenchApp = Sanic[Config, AppContext]


def create_app(settings: Settings | None = None) -> ChessWorkbenchApp:
    """Build an isolated application instance for production or tests."""

    resolved_settings = settings or Settings()
    app = Sanic(
        resolved_settings.service_name,
        ctx=AppContext(
            settings=resolved_settings,
            database=Database(resolved_settings.database_url),
        ),
        configure_logging=not resolved_settings.debug,
    )

    app.config.OAS_AUTODOC = False
    Extend(app)
    app.ext.openapi.describe(
        "ChessWorkbench API",
        version=resolved_settings.version,
        description="Authoritative HTTP API for ChessWorkbench.",
    )

    app.blueprint(health_blueprint)

    @app.after_server_stop
    async def close_database(stopping_app: ChessWorkbenchApp) -> None:
        await stopping_app.ctx.database.close()

    return app
