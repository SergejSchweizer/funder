"""Small EODHD HTTP client used by Search and Fetch."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from funder.config import EodhdConfig


class EodhdHttpError(RuntimeError):
    """Raised after an EODHD request cannot be completed."""


class EodhdClient:
    """HTTP client that keeps API-token handling in one place."""

    def __init__(self, config: EodhdConfig) -> None:
        self._config = config

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
                with urllib.request.urlopen(url, timeout=self._config.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code < 500 or attempt >= self._config.max_retries:
                    break
            except urllib.error.URLError as error:
                last_error = error
                if attempt >= self._config.max_retries:
                    break
            if attempt < self._config.max_retries:
                time.sleep(0.25 * (attempt + 1))

        safe_url = self.sanitized_url(path, params)
        raise EodhdHttpError(f"EODHD request failed for {safe_url}") from last_error
