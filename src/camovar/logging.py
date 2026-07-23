"""Uniform Camovar logging configuration and retention."""

from __future__ import annotations

import logging as py_logging
import zipfile
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import gmtime, struct_time
from typing import Any

LOG_DIR = Path(".logs")
LOG_FORMAT = "%(asctime)sZ %(levelname)s %(name)s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
LOG_KEEP_DAYS = 7
ZIP_KEEP_DAYS = 30


class UtcFormatter(py_logging.Formatter):
    """Logging formatter that renders timestamps in UTC."""

    def converter(self, timestamp: float | None = None) -> struct_time:
        return gmtime(timestamp)


def get_logger(name: str) -> py_logging.Logger:
    """Return a Camovar namespaced logger for a module."""
    return py_logging.getLogger(name if name.startswith("camovar") else f"camovar.{name}")


def log_event(
    logger: py_logging.Logger,
    level: int,
    *,
    module: str,
    event: str,
    fields: Mapping[str, Any] | None = None,
) -> None:
    """Write one uniformly shaped Camovar log message."""
    message = f"module={module} event={event}"
    if fields:
        message = f"{message} {_format_fields(fields)}"
    logger.log(level, message)


def setup_logging(
    *, debug: bool = False, log_dir: Path = LOG_DIR, now: datetime | None = None
) -> py_logging.Logger:
    """Configure uniform Camovar file logging and enforce retention.

    Logs are written to `.logs/camovar-YYYY-MM-DD.log`. Plain log files older
    than seven days are zipped, and zipped logs older than thirty days are
    deleted. `debug=True` raises Camovar loggers to DEBUG while keeping the same
    file format.
    """
    checked_at = now or datetime.now(UTC)
    log_dir.mkdir(parents=True, exist_ok=True)
    rotate_logs(log_dir=log_dir, now=checked_at)

    logger = py_logging.getLogger("camovar")
    logger.setLevel(py_logging.DEBUG if debug else py_logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        if getattr(handler, "_camovar_file_handler", False):
            logger.removeHandler(handler)
            handler.close()

    handler = py_logging.FileHandler(
        log_dir / f"camovar-{checked_at.date().isoformat()}.log", encoding="utf-8"
    )
    handler.setLevel(py_logging.DEBUG if debug else py_logging.INFO)
    handler.setFormatter(UtcFormatter(LOG_FORMAT, LOG_DATE_FORMAT))
    handler._camovar_file_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    log_event(
        logger,
        py_logging.INFO,
        module="logging",
        event="configured",
        fields={"debug": debug, "log_dir": log_dir},
    )
    return logger


def rotate_logs(*, log_dir: Path = LOG_DIR, now: datetime | None = None) -> None:
    """Zip old plain logs and delete expired zip archives."""
    checked_at = now or datetime.now(UTC)
    for log_path in log_dir.glob("camovar-*.log"):
        log_date = _dated_log_file(log_path, ".log")
        if log_date is None or checked_at.date() - log_date <= timedelta(days=LOG_KEEP_DAYS):
            continue
        zip_path = log_path.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(log_path, arcname=log_path.name)
        log_path.unlink()

    for zip_path in log_dir.glob("camovar-*.zip"):
        zip_date = _dated_log_file(zip_path, ".zip")
        if zip_date is not None and checked_at.date() - zip_date > timedelta(days=ZIP_KEEP_DAYS):
            zip_path.unlink()


def _dated_log_file(path: Path, suffix: str) -> date | None:
    if path.suffix != suffix:
        return None
    stem = path.stem
    prefix = "camovar-"
    if not stem.startswith(prefix):
        return None
    try:
        return datetime.fromisoformat(stem.removeprefix(prefix)).date()
    except ValueError:
        return None


def _format_fields(fields: Mapping[str, Any]) -> str:
    return " ".join(f"{key}={_format_value(value)}" for key, value in sorted(fields.items()))


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    if any(character.isspace() for character in text):
        return repr(text)
    return text
