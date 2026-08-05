from chess_workbench.api.app import create_app
from chess_workbench.config import Settings


def run(settings: Settings) -> None:
    """Run Sanic with a process mode compatible with the debug reloader."""

    app = create_app(settings)
    app.run(
        host=settings.host,
        port=settings.port,
        debug=settings.debug,
        auto_reload=settings.debug,
        single_process=not settings.debug,
    )


def main() -> None:
    run(Settings())


if __name__ == "__main__":  # pragma: no cover - exercised by the HTTP smoke test
    main()
