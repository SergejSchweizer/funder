"""Configuration loading for Camovar."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType


class MissingConfigError(RuntimeError):
    """Raised when required local configuration is missing."""


def read_env_file(path: Path) -> Mapping[str, str]:
    """Read a simple KEY=VALUE environment file without mutating the process env."""
    if not path.exists():
        return MappingProxyType({})

    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return MappingProxyType(values)


def read_secret_config(path: Path) -> Mapping[str, str]:
    """Read a small local secret config file without requiring YAML dependencies."""
    if not path.exists():
        return MappingProxyType({})

    values: dict[str, str] = {}
    parent_key = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip() or ":" not in line_without_comment:
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip())
        key, value = line_without_comment.strip().split(":", 1)
        key = key.strip()
        cleaned_value = value.strip().strip('"').strip("'")
        if indent == 0 and cleaned_value == "":
            parent_key = key
            continue
        if cleaned_value == "":
            continue
        normalized_key = key.upper()
        is_eodhd_token = parent_key.casefold() == "eodhd" and normalized_key in {
            "API_KEY",
            "API_TOKEN",
            "TOKEN",
        }
        if is_eodhd_token or normalized_key in {"EODHD_API_TOKEN", "API_KEY", "API_TOKEN"}:
            values["EODHD_API_TOKEN"] = cleaned_value
        elif normalized_key.startswith("EODHD_"):
            values[normalized_key] = cleaned_value
    return MappingProxyType(values)


@dataclass(frozen=True)
class EodhdConfig:
    """EODHD API configuration."""

    api_token: str = field(repr=False)
    base_url: str = "https://eodhd.com/api"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    min_request_interval_seconds: float = 0.25
    retry_backoff_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.api_token:
            raise MissingConfigError("EODHD_API_TOKEN is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds cannot be negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")


def _float_setting(source: Mapping[str, str], key: str, default: float) -> float:
    value = source.get(key)
    return default if value is None or value.strip() == "" else float(value)


def _int_setting(source: Mapping[str, str], key: str, default: int) -> int:
    value = source.get(key)
    return default if value is None or value.strip() == "" else int(value)


def load_eodhd_config(
    *,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = Path(".env.local"),
    secret_config: Path | None = Path(".secrets/eodhd.yaml"),
) -> EodhdConfig:
    """Load EODHD configuration from local files and process env."""
    source = dict(os.environ if env is None else env)
    if env_file is not None:
        file_values = read_env_file(env_file)
        source = {**file_values, **source}
    if secret_config is not None:
        secret_values = read_secret_config(secret_config)
        source = {**source, **secret_values}

    token = source.get("EODHD_API_TOKEN", "")
    return EodhdConfig(
        api_token=token,
        base_url=source.get("EODHD_BASE_URL", EodhdConfig.base_url),
        timeout_seconds=_float_setting(source, "EODHD_TIMEOUT_SECONDS", 30.0),
        max_retries=_int_setting(source, "EODHD_MAX_RETRIES", 2),
        min_request_interval_seconds=_float_setting(
            source,
            "EODHD_MIN_REQUEST_INTERVAL_SECONDS",
            0.25,
        ),
        retry_backoff_seconds=_float_setting(source, "EODHD_RETRY_BACKOFF_SECONDS", 0.5),
    )
