import urllib.error
from email.message import Message
from io import BytesIO

import pytest

from camovar.config import EodhdConfig
from camovar.http import EodhdClient, EodhdHttpError


class JsonResponse:
    def __enter__(self) -> JsonResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"ok": true}'


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
    client = EodhdClient(
        EodhdConfig(api_token="secret-token", base_url="https://invalid.local"),
        sleeper=lambda _: None,
    )

    with pytest.raises(EodhdHttpError) as error:
        client.get_json("/x")

    assert "secret-token" not in str(error.value)


def test_get_json_returns_decoded_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def ok_urlopen(url: str, timeout: float) -> JsonResponse:
        return JsonResponse()

    monkeypatch.setattr("urllib.request.urlopen", ok_urlopen)
    client = EodhdClient(EodhdConfig(api_token="secret-token"))

    assert client.get_json("/x") == {"ok": True}


def test_get_json_does_not_retry_client_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fail_urlopen(url: str, timeout: float) -> None:
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(url, 404, "not found", Message(), BytesIO())

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    client = EodhdClient(
        EodhdConfig(api_token="secret-token", max_retries=2), sleeper=lambda _: None
    )

    with pytest.raises(EodhdHttpError):
        client.get_json("/x")

    assert calls == 1


def test_get_json_retries_rate_limit_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def urlopen(url: str, timeout: float) -> JsonResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            headers = Message()
            headers["Retry-After"] = "2.5"
            raise urllib.error.HTTPError(url, 429, "too many requests", headers, BytesIO())
        return JsonResponse()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = EodhdClient(
        EodhdConfig(api_token="secret-token", max_retries=1, min_request_interval_seconds=0),
        sleeper=sleeps.append,
    )

    assert client.get_json("/x") == {"ok": True}
    assert calls == 2
    assert sleeps == [2.5]


def test_get_json_spaces_successive_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 10.0
    sleeps: list[float] = []

    def clock() -> float:
        return now

    def sleeper(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    def urlopen(url: str, timeout: float) -> JsonResponse:
        return JsonResponse()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = EodhdClient(
        EodhdConfig(api_token="secret-token", min_request_interval_seconds=0.25),
        clock=clock,
        sleeper=sleeper,
    )

    client.get_json("/first")
    client.get_json("/second")

    assert sleeps == [0.25]
