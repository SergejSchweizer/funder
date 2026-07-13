"""Small EODHD HTTP client used by Search and Fetch."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from email.message import Message
from typing import Any

from founder.config import EodhdConfig


class EodhdHttpError(RuntimeError):
    """Raised after an EODHD request cannot be completed."""


class EodhdClient:
    """HTTP client that keeps API-token handling in one place."""

    def __init__(
        self,
        config: EodhdConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: float | None = None
        self._request_lock = threading.Lock()

    def build_url(self, path: str, params: Mapping[str, str | int | float] | None = None) -> str:
        cleaned_path = path if path.startswith("/") else f"/{path}"
        query_params: dict[str, str | int | float] = {"api_token": self._config.api_token}
        if params is not None:
            query_params.update(params)
        query = urllib.parse.urlencode(query_params)
        return f"{self._config.base_url}{cleaned_path}?{query}"

    def sanitized_url(
        self,
        path: str,
        params: Mapping[str, str | int | float] | None = None,
    ) -> str:
        return self.build_url(path, params).replace(self._config.api_token, "<redacted>")

    def get_json(self, path: str, params: Mapping[str, str | int | float] | None = None) -> Any:
        url = self.build_url(path, params)
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                with self._open(url) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                last_error = error
                if (
                    not self._should_retry_http_error(error.code)
                    or attempt >= self._config.max_retries
                ):
                    break
                self._sleep_before_retry(attempt, error.headers)
            except urllib.error.URLError as error:
                last_error = error
                if attempt >= self._config.max_retries:
                    break
                self._sleep_before_retry(attempt, None)

        safe_url = self.sanitized_url(path, params)
        raise EodhdHttpError(f"EODHD request failed for {safe_url}") from last_error

    def _open(self, url: str) -> Any:
        with self._request_lock:
            self._sleep_until_request_allowed()
            self._last_request_at = self._clock()
        return urllib.request.urlopen(url, timeout=self._config.timeout_seconds)

    def _sleep_until_request_allowed(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        delay = self._config.min_request_interval_seconds - elapsed
        if delay > 0:
            self._sleeper(delay)

    @staticmethod
    def _should_retry_http_error(status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    def _sleep_before_retry(self, attempt: int, headers: Message | None) -> None:
        retry_after = self._retry_after_seconds(headers)
        delay = (
            retry_after
            if retry_after is not None
            else self._config.retry_backoff_seconds * (attempt + 1)
        )
        if delay > 0:
            self._sleeper(delay)

    @staticmethod
    def _retry_after_seconds(headers: Message | None) -> float | None:
        if headers is None:
            return None
        value = headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None
