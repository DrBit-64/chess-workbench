from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from chess_workbench import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "database" / "chess-workbench.db"
DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
DEFAULT_SOURCE_STORAGE_ROOT = PROJECT_ROOT / "data"
SUPPORTED_DATABASE_DRIVERS = frozenset({"mysql+asyncmy", "sqlite+aiosqlite"})


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
    source_storage_root: Path = DEFAULT_SOURCE_STORAGE_ROOT
    stockfish_path: Path = PROJECT_ROOT / "data" / "engines" / "stockfish-18" / "stockfish"
    syzygy_path: Path = PROJECT_ROOT / "data" / "tablebases" / "syzygy"
    engine_max_threads: int = Field(default=4, ge=1, le=64)
    engine_max_hash_mb: int = Field(default=1024, ge=16, le=65_536)
    engine_max_time_ms: int = Field(default=30_000, ge=100, le=600_000)
    engine_worker_enabled: bool = True
    engine_worker_poll_ms: int = Field(default=250, ge=50, le=10_000)

    @field_validator("database_url")
    @classmethod
    def database_driver_must_be_async(cls, value: str) -> str:
        try:
            driver_name = make_url(value).drivername
        except Exception as error:
            raise ValueError("database_url must be a valid SQLAlchemy URL") from error

        if driver_name not in SUPPORTED_DATABASE_DRIVERS:
            supported = ", ".join(sorted(SUPPORTED_DATABASE_DRIVERS))
            raise ValueError(f"database_url driver must be one of: {supported}")
        return value
