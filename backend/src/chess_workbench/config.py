import os
import stat
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from chess_workbench import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "database" / "chess-workbench.db"
DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
DEFAULT_SOURCE_STORAGE_ROOT = PROJECT_ROOT / "data"
DEFAULT_PDF_MAX_BYTES = 256 * 1024 * 1024
SUPPORTED_DATABASE_DRIVERS = frozenset({"mysql+asyncmy", "sqlite+aiosqlite"})
MAX_SECRET_FILE_BYTES = 4096


class SecretFileError(ValueError):
    """A sanitized failure while loading a server-owned secret file."""


def load_deepseek_api_key(settings: "Settings") -> SecretStr | None:
    """Load the optional DeepSeek key without retaining plaintext in configuration."""

    path = settings.deepseek_api_key_file
    if path is None:
        return None
    try:
        with path.open("rb") as secret_file:
            file_stat = os.fstat(secret_file.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise SecretFileError("DeepSeek API key file is not a regular file")
            if os.name == "posix" and stat.S_IMODE(file_stat.st_mode) & 0o077:
                raise SecretFileError("DeepSeek API key file permissions are too broad")
            raw = secret_file.read(MAX_SECRET_FILE_BYTES + 1)
    except SecretFileError:
        raise
    except OSError:
        raise SecretFileError("DeepSeek API key file is unavailable") from None
    if len(raw) > MAX_SECRET_FILE_BYTES:
        raise SecretFileError("DeepSeek API key file is too large")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SecretFileError("DeepSeek API key file is not valid UTF-8") from None
    if value.endswith("\n"):
        value = value[:-1]
        if value.endswith("\r"):
            value = value[:-1]
    if not value or value != value.strip() or "\n" in value or "\r" in value:
        raise SecretFileError("DeepSeek API key file does not contain one valid secret")
    return SecretStr(value)


class Settings(BaseSettings):
    """Validated process configuration loaded from CHESS_WORKBENCH_* variables."""

    model_config = SettingsConfigDict(
        env_prefix="CHESS_WORKBENCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        # Strict validation with pydantic-settings env coercion: environment
        # strings are coerced to the declared scalar type before strict field
        # validation, so strict int/float/bool fields still load from env.
        strict=True,
    )

    # Pre-existing settings keep their former non-strict behavior with
    # explicit field-level strict=False: the model-level strict=True below
    # only enables pydantic-settings environment-string coercion, so env
    # values still load for the strict Stage 8C fields while programmatic
    # init of every legacy field normalizes exactly as before.
    service_name: str = Field(default="chess-workbench-api", strict=False)
    version: str = Field(default=__version__, strict=False)
    host: str = Field(default="127.0.0.1", strict=False)
    port: int = Field(default=8000, ge=1, le=65535, strict=False)
    debug: bool = Field(default=False, strict=False)
    database_url: str = Field(default=DEFAULT_DATABASE_URL, strict=False)
    source_storage_root: Path = Field(default=DEFAULT_SOURCE_STORAGE_ROOT, strict=False)
    pdf_max_bytes: int = Field(default=DEFAULT_PDF_MAX_BYTES, ge=1, le=2_147_483_647, strict=False)
    paddle_ocr_runner_path: Path | None = Field(default=None, strict=False)
    stockfish_path: Path = Field(
        default=PROJECT_ROOT / "data" / "engines" / "stockfish-18" / "stockfish",
        strict=False,
    )
    syzygy_path: Path = Field(default=PROJECT_ROOT / "data" / "tablebases" / "syzygy", strict=False)
    engine_max_threads: int = Field(default=4, ge=1, le=64, strict=False)
    engine_max_hash_mb: int = Field(default=1024, ge=16, le=65_536, strict=False)
    engine_max_time_ms: int = Field(default=30_000, ge=100, le=600_000, strict=False)
    engine_worker_enabled: bool = Field(default=True, strict=False)
    engine_worker_poll_ms: int = Field(default=250, ge=50, le=10_000, strict=False)

    # Stage 8C secrets are file-only. The legacy inline field is retained only
    # to reject old .env configuration with a clear, masked validation error.
    deepseek_api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    deepseek_api_key_file: Path | None = Field(default=None, repr=False, strict=False)
    ccef_provider_timeout_seconds: float = Field(
        default=600.0, ge=1.0, le=1800.0, allow_inf_nan=False, strict=True
    )
    ccef_max_output_tokens: int = Field(default=128_000, ge=1, le=384_000, strict=True)
    ccef_max_prompt_chars: int = Field(default=2_000_000, ge=1, le=2_000_000, strict=True)

    @field_validator("deepseek_api_key")
    @classmethod
    def deepseek_api_key_not_blank(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("deepseek_api_key must not be empty or whitespace-only")
        return value

    @model_validator(mode="after")
    def deepseek_api_key_must_use_external_file(self) -> "Settings":
        if self.deepseek_api_key is not None:
            raise ValueError("inline deepseek_api_key is not supported; use deepseek_api_key_file")
        return self

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
