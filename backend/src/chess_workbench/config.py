from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from chess_workbench import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "database" / "chess-workbench.db"
DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"


class Settings(BaseSettings):
    """Validated process configuration loaded from CHESS_WORKBENCH_* variables."""

    model_config = SettingsConfigDict(
        env_prefix="CHESS_WORKBENCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    service_name: str = "chess-workbench-api"
    version: str = __version__
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = False
    database_url: str = DEFAULT_DATABASE_URL
