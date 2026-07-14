"""Uniform Founder logging configuration and retention."""

from __future__ import annotations

import logging as py_logging
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import gmtime

LOG_DIR = Path(".logs")
LOG_FORMAT = "%(asctime)sZ %(levelname)s %(name)s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
LOG_KEEP_DAYS = 7
ZIP_KEEP_DAYS = 30


class UtcFormatter(py_logging.Formatter):
    """Logging formatter that renders timestamps in UTC."""

    converter = gmtime


def get_logger(name: str) -> py_logging.Logger:
    """Return a Founder namespaced logger for a module."""
    return py_logging.getLogger(name if name.startswith("founder") else f"founder.{name}")


def setup_logging(
    *, debug: bool = False, log_dir: Path = LOG_DIR, now: datetime | None = None
) -> py_logging.Logger:
    """Configure uniform Founder file logging and enforce retention.

    Logs are written to `.logs/founder-YYYY-MM-DD.log`. Plain log files older
    than seven days are zipped, and zipped logs older than thirty days are
    deleted. `debug=True` raises Founder loggers to DEBUG while keeping the same
    file format.
    """
    checked_at = now or datetime.now(UTC)
    log_dir.mkdir(parents=True, exist_ok=True)
    rotate_logs(log_dir=log_dir, now=checked_at)

    logger = py_logging.getLogger("founder")
    logger.setLevel(py_logging.DEBUG if debug else py_logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        if getattr(handler, "_founder_file_handler", False):
            logger.removeHandler(handler)
            handler.close()

    handler = py_logging.FileHandler(
        log_dir / f"founder-{checked_at.date().isoformat()}.log", encoding="utf-8"
    )
    handler.setLevel(py_logging.DEBUG if debug else py_logging.INFO)
    handler.setFormatter(UtcFormatter(LOG_FORMAT, LOG_DATE_FORMAT))
    handler._founder_file_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.info("logging configured debug=%s log_dir=%s", debug, log_dir)
    return logger


def rotate_logs(*, log_dir: Path = LOG_DIR, now: datetime | None = None) -> None:
    """Zip old plain logs and delete expired zip archives."""
    checked_at = now or datetime.now(UTC)
    for log_path in log_dir.glob("founder-*.log"):
        log_date = _dated_log_file(log_path, ".log")
        if log_date is None or checked_at.date() - log_date <= timedelta(days=LOG_KEEP_DAYS):
            continue
        zip_path = log_path.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(log_path, arcname=log_path.name)
        log_path.unlink()

    for zip_path in log_dir.glob("founder-*.zip"):
        zip_date = _dated_log_file(zip_path, ".zip")
        if zip_date is not None and checked_at.date() - zip_date > timedelta(days=ZIP_KEEP_DAYS):
            zip_path.unlink()


def _dated_log_file(path: Path, suffix: str) -> date | None:
    if path.suffix != suffix:
        return None
    stem = path.stem
    prefix = "founder-"
    if not stem.startswith(prefix):
        return None
    try:
        return datetime.fromisoformat(stem.removeprefix(prefix)).date()
    except ValueError:
        return None
