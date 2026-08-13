import os
from pathlib import Path
from typing import Any, cast

import pytest
from chess_workbench.config import SecretFileError, Settings, load_deepseek_api_key
from pydantic import SecretStr, ValidationError


@pytest.fixture(autouse=True)
def ignore_repository_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Configuration unit tests must never consume a developer's local secrets."""

    monkeypatch.chdir(tmp_path)


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


# ---------------------------------------------------------------------------
# Stage 8C runtime settings
# ---------------------------------------------------------------------------


def test_ccef_runtime_settings_defaults_and_field_types() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///./data/database/settings.db")

    assert settings.deepseek_api_key is None
    assert settings.deepseek_api_key_file is None
    assert settings.ccef_provider_timeout_seconds == 600.0
    assert settings.ccef_max_output_tokens == 128_000
    assert settings.ccef_max_prompt_chars == 2_000_000
    assert isinstance(settings.ccef_provider_timeout_seconds, float)
    assert isinstance(settings.ccef_max_output_tokens, int)
    assert isinstance(settings.ccef_max_prompt_chars, int)


def test_ccef_runtime_settings_load_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret_file = tmp_path / "deepseek-api-key"
    secret_file.write_text("sk-test-secret\n", encoding="utf-8")
    secret_file.chmod(0o600)
    monkeypatch.setenv("CHESS_WORKBENCH_DEEPSEEK_API_KEY_FILE", str(secret_file))
    monkeypatch.setenv("CHESS_WORKBENCH_CCEF_PROVIDER_TIMEOUT_SECONDS", "30.5")
    monkeypatch.setenv("CHESS_WORKBENCH_CCEF_MAX_OUTPUT_TOKENS", "64000")
    monkeypatch.setenv("CHESS_WORKBENCH_CCEF_MAX_PROMPT_CHARS", "1500000")

    settings = Settings(database_url="sqlite+aiosqlite:///./data/database/settings.db")

    assert settings.deepseek_api_key is None
    assert settings.deepseek_api_key_file == secret_file
    loaded = load_deepseek_api_key(settings)
    assert loaded is not None
    assert loaded.get_secret_value() == "sk-test-secret"
    assert settings.ccef_provider_timeout_seconds == 30.5
    assert settings.ccef_max_output_tokens == 64_000
    assert settings.ccef_max_prompt_chars == 1_500_000


def test_external_secret_is_not_retained_in_settings_and_is_available_to_trusted_code(
    tmp_path: Path,
) -> None:
    secret = "sk-very-secret-value"
    secret_file = tmp_path / "deepseek-api-key"
    secret_file.write_text(f"{secret}\n", encoding="utf-8")
    secret_file.chmod(0o600)
    settings = Settings(
        database_url="sqlite+aiosqlite:///./data/database/settings.db",
        deepseek_api_key_file=secret_file,
    )

    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert secret not in settings.model_dump_json()
    key = load_deepseek_api_key(settings)
    assert key is not None
    assert key.get_secret_value() == secret


def test_legacy_inline_secret_is_rejected_without_disclosure() -> None:
    secret = "sk-must-not-appear-in-validation"
    with pytest.raises(ValidationError, match="use deepseek_api_key_file") as caught:
        Settings(
            database_url="sqlite+aiosqlite:///./data/database/settings.db",
            deepseek_api_key=SecretStr(secret),
        )
    assert secret not in str(caught.value)


@pytest.mark.parametrize("contents", [b"", b"   ", b"first\nsecond", b"\xff"])
def test_secret_file_rejects_invalid_content(tmp_path: Path, contents: bytes) -> None:
    secret_file = tmp_path / "deepseek-api-key"
    secret_file.write_bytes(contents)
    secret_file.chmod(0o600)
    settings = Settings(
        database_url="sqlite+aiosqlite:///./data/database/settings.db",
        deepseek_api_key_file=secret_file,
    )

    with pytest.raises(SecretFileError) as caught:
        load_deepseek_api_key(settings)
    assert str(secret_file) not in str(caught.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_secret_file_rejects_group_or_other_access(tmp_path: Path) -> None:
    secret_file = tmp_path / "deepseek-api-key"
    secret_file.write_text("sk-test", encoding="utf-8")
    secret_file.chmod(0o640)
    settings = Settings(
        database_url="sqlite+aiosqlite:///./data/database/settings.db",
        deepseek_api_key_file=secret_file,
    )

    with pytest.raises(SecretFileError, match="permissions"):
        load_deepseek_api_key(settings)


def test_timeout_rejects_non_finite_and_out_of_range_values() -> None:
    for value in (float("nan"), float("inf"), float("-inf"), 0.5, 1800.1):
        with pytest.raises(ValidationError):
            Settings(
                database_url="sqlite+aiosqlite:///./data/database/settings.db",
                ccef_provider_timeout_seconds=value,
            )


@pytest.mark.parametrize(
    "field, bad",
    [
        ("ccef_max_output_tokens", True),
        ("ccef_max_output_tokens", "64000"),
        ("ccef_max_output_tokens", 0),
        ("ccef_max_output_tokens", 384_001),
        ("ccef_max_prompt_chars", True),
        ("ccef_max_prompt_chars", "1500000"),
        ("ccef_max_prompt_chars", 0),
        ("ccef_max_prompt_chars", 2_000_001),
    ],
)
def test_integer_limits_reject_bool_coerced_string_and_out_of_range(
    field: str, bad: object
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="sqlite+aiosqlite:///./data/database/settings.db",
            **cast(Any, {field: bad}),
        )


def test_existing_database_and_frozen_behavior_remains_green(tmp_path: Path) -> None:
    settings = Settings(
        port=8123,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'settings.db'}",
        ccef_max_output_tokens=64_000,
    )
    assert settings.port == 8123
    assert settings.ccef_max_output_tokens == 64_000
    with pytest.raises(ValidationError):
        settings.ccef_max_output_tokens = 128_000


@pytest.mark.parametrize(
    "field, value, expected",
    [
        ("port", "8123", 8123),
        ("debug", "false", False),
        ("debug", "true", True),
        ("source_storage_root", "/tmp/chess-workbench", Path("/tmp/chess-workbench")),
        ("pdf_max_bytes", "1048576", 1048576),
        ("paddle_ocr_runner_path", "/tmp/paddle/runner", Path("/tmp/paddle/runner")),
        ("stockfish_path", "/tmp/stockfish", Path("/tmp/stockfish")),
        ("syzygy_path", "/tmp/syzygy", Path("/tmp/syzygy")),
        ("engine_max_threads", "4", 4),
        ("engine_max_hash_mb", "1024", 1024),
        ("engine_max_time_ms", "30000", 30000),
        ("engine_worker_enabled", "false", False),
        ("engine_worker_poll_ms", "250", 250),
    ],
)
def test_preexisting_scalar_path_fields_accept_programmatic_strings_as_before(
    field: str, value: str, expected: object
) -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///./data/database/settings.db",
        **cast(Any, {field: value}),
    )
    actual = getattr(settings, field)
    assert actual == expected
    assert type(actual) is type(expected)
