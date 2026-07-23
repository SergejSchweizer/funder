from pathlib import Path

import pytest

from camovar.config import (
    EodhdConfig,
    MissingConfigError,
    load_eodhd_config,
    read_env_file,
    read_secret_config,
)


def test_load_eodhd_config_requires_token() -> None:
    with pytest.raises(MissingConfigError, match="EODHD_API_TOKEN"):
        load_eodhd_config(env={}, env_file=None, secret_config=None)


def test_load_eodhd_config_prefers_env_over_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("EODHD_API_TOKEN=file-token\n")

    config = load_eodhd_config(
        env={"EODHD_API_TOKEN": "env-token"},
        env_file=env_file,
        secret_config=None,
    )

    assert config.api_token == "env-token"
    assert "env-token" not in repr(config)


def test_load_eodhd_config_prefers_secret_config_over_env(tmp_path: Path) -> None:
    secret_config = tmp_path / "eodhd.yaml"
    secret_config.write_text("eodhd:\n  api_key: secret-token\n", encoding="utf-8")

    config = load_eodhd_config(
        env={"EODHD_API_TOKEN": "env-token"},
        env_file=None,
        secret_config=secret_config,
    )

    assert config.api_token == "secret-token"


def test_load_eodhd_config_reads_http_rate_limit_settings() -> None:
    config = load_eodhd_config(
        env={
            "EODHD_API_TOKEN": "token",
            "EODHD_BASE_URL": "https://example.test/api",
            "EODHD_TIMEOUT_SECONDS": "12.5",
            "EODHD_MAX_RETRIES": "4",
            "EODHD_MIN_REQUEST_INTERVAL_SECONDS": "1.25",
            "EODHD_RETRY_BACKOFF_SECONDS": "2.5",
        },
        env_file=None,
        secret_config=None,
    )

    assert config.base_url == "https://example.test/api"
    assert config.timeout_seconds == 12.5
    assert config.max_retries == 4
    assert config.min_request_interval_seconds == 1.25
    assert config.retry_backoff_seconds == 2.5


def test_eodhd_config_rejects_invalid_retry_settings() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        EodhdConfig(api_token="token", timeout_seconds=0)

    with pytest.raises(ValueError, match="max_retries"):
        EodhdConfig(api_token="token", max_retries=-1)

    with pytest.raises(ValueError, match="min_request_interval_seconds"):
        EodhdConfig(api_token="token", min_request_interval_seconds=-1)

    with pytest.raises(ValueError, match="retry_backoff_seconds"):
        EodhdConfig(api_token="token", retry_backoff_seconds=-1)


def test_read_env_file_returns_empty_mapping_for_missing_file(tmp_path: Path) -> None:
    assert read_env_file(tmp_path / ".env.local") == {}


def test_read_env_file_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("# comment\n\nEODHD_API_TOKEN='abc'\nBROKEN\n")

    values = read_env_file(env_file)

    assert values == {"EODHD_API_TOKEN": "abc"}


def test_read_secret_config_accepts_flat_api_key(tmp_path: Path) -> None:
    secret_config = tmp_path / "eodhd.yaml"
    secret_config.write_text("api_key: 'abc'\n", encoding="utf-8")

    assert read_secret_config(secret_config) == {"EODHD_API_TOKEN": "abc"}
