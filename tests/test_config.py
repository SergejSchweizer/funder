from pathlib import Path

import pytest

from funder.config import MissingConfigError, load_eodhd_config, read_env_file


def test_load_eodhd_config_requires_token() -> None:
    with pytest.raises(MissingConfigError, match="EODHD_API_TOKEN"):
        load_eodhd_config(env={}, env_file=None)


def test_load_eodhd_config_prefers_env_over_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("EODHD_API_TOKEN=file-token\n")

    config = load_eodhd_config(env={"EODHD_API_TOKEN": "env-token"}, env_file=env_file)

    assert config.api_token == "env-token"
    assert "env-token" not in repr(config)


def test_read_env_file_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("# comment\n\nEODHD_API_TOKEN='abc'\nBROKEN\n")

    values = read_env_file(env_file)

    assert values == {"EODHD_API_TOKEN": "abc"}
