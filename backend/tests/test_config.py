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
