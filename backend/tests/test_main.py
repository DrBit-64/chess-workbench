from unittest.mock import patch

from chess_workbench import __main__ as entrypoint
from chess_workbench.config import Settings


def test_run_uses_single_process_without_reloader() -> None:
    settings = Settings(debug=False)

    with patch.object(entrypoint, "create_app") as create_app:
        entrypoint.run(settings)

    create_app.assert_called_once_with(settings)
    create_app.return_value.run.assert_called_once_with(
        host=settings.host,
        port=settings.port,
        debug=False,
        auto_reload=False,
        single_process=True,
    )


def test_run_uses_worker_manager_with_debug_reloader() -> None:
    settings = Settings(debug=True)

    with patch.object(entrypoint, "create_app") as create_app:
        entrypoint.run(settings)

    create_app.assert_called_once_with(settings)
    create_app.return_value.run.assert_called_once_with(
        host=settings.host,
        port=settings.port,
        debug=True,
        auto_reload=True,
        single_process=False,
    )


def test_main_loads_settings_and_runs() -> None:
    settings = Settings(port=9124)

    with (
        patch.object(entrypoint, "Settings", return_value=settings) as settings_factory,
        patch.object(entrypoint, "run") as run,
    ):
        entrypoint.main()

    settings_factory.assert_called_once_with()
    run.assert_called_once_with(settings)
