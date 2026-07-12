"""Configuration loading for Funder."""

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


@dataclass(frozen=True)
class EodhdConfig:
    """EODHD API configuration."""

    api_token: str = field(repr=False)
    base_url: str = "https://eodhd.com/api"
    timeout_seconds: float = 30.0
    max_retries: int = 2

    def __post_init__(self) -> None:
        if not self.api_token:
            raise MissingConfigError("EODHD_API_TOKEN is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")


def load_eodhd_config(
    *,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = Path(".env.local"),
) -> EodhdConfig:
    """Load EODHD configuration from process env, optionally falling back to a file."""
    source = dict(os.environ if env is None else env)
    if env_file is not None:
        file_values = read_env_file(env_file)
        source = {**file_values, **source}

    token = source.get("EODHD_API_TOKEN", "")
    return EodhdConfig(api_token=token)
