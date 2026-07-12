import urllib.error

import pytest

from funder.config import EodhdConfig
from funder.http import EodhdClient, EodhdHttpError


def test_build_url_adds_token_and_sanitized_url_redacts_it() -> None:
    client = EodhdClient(EodhdConfig(api_token="secret-token"))

    url = client.build_url("/search/UCITS ETF", {"fmt": "json", "limit": 500})
    sanitized = client.sanitized_url("/search/UCITS ETF", {"fmt": "json", "limit": 500})

    assert "api_token=secret-token" in url
    assert "secret-token" not in sanitized
    assert "api_token=%3Credacted%3E" not in sanitized
    assert "api_token=<redacted>" in sanitized


def test_get_json_error_message_redacts_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_urlopen(url: str, timeout: float) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    client = EodhdClient(EodhdConfig(api_token="secret-token", base_url="https://invalid.local"))

    with pytest.raises(EodhdHttpError) as error:
        client.get_json("/x")

    assert "secret-token" not in str(error.value)
