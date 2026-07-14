"""Process locks for lake layer commands."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from founder.paths import LakePaths

LayerName = Literal["bronze", "silver", "gold"]


def layer_lock_path(paths: LakePaths, layer: LayerName) -> Path:
    """Return the stable lock path for one lake layer command.

    Args:
        paths: Lake path contract for the target data root.
        layer: Lake layer name whose command should be serialized.

    Returns:
        Path to the lock file used by the layer command.
    """
    layer_root = {
        "bronze": paths.bronze,
        "silver": paths.silver,
        "gold": paths.gold,
    }[layer]
    return layer_root / "runs" / f"{layer}.lock"


@contextmanager
def layer_run_lock(paths: LakePaths, layer: LayerName) -> Generator[Path]:
    """Hold an exclusive non-blocking process lock for one lake layer.

    The lock is advisory and process-scoped through `fcntl`, so it prevents
    concurrent Founder commands on the same host without leaving a stale lock
    after process termination.

    Args:
        paths: Lake path contract for the target data root.
        layer: Lake layer name whose command should be serialized.

    Yields:
        Path to the held lock file.

    Raises:
        RuntimeError: If another process already holds the layer lock.
    """
    lock_path = layer_lock_path(paths, layer)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"{layer} run already active") from error
        lock_file.seek(0)
        lock_file.truncate()
        acquired_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        lock_file.write(f"pid={os.getpid()} acquired_at={acquired_at}\n")
        lock_file.flush()
        try:
            yield lock_path
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
