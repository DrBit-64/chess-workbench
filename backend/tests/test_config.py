from pathlib import Path

import pytest
from chess_workbench.config import Settings
from pydantic import ValidationError


def test_settings_are_validated_and_frozen(tmp_path: Path) -> None:
    settings = Settings(
        port=9123,
        debug=False,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'settings.db'}",
    )

    assert settings.port == 9123
    assert settings.debug is False

    with pytest.raises(ValidationError):
        settings.port = 8001


def test_invalid_port_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(port=70000)


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///./data/database.db",
        "mysql+pymysql://user:password@localhost/chess",
        "not a database url",
    ],
)
def test_sync_or_invalid_database_urls_are_rejected(database_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=database_url)


def test_async_mysql_driver_is_accepted() -> None:
    settings = Settings(database_url="mysql+asyncmy://user:password@localhost/chess")

    assert settings.database_url.startswith("mysql+asyncmy://")
