from __future__ import annotations

from pathlib import Path
from typing import Any

from founder.compose_web_watch import DEFAULT_COMMAND, snapshot_paths, watch_and_rebuild


def test_snapshot_paths_changes_when_watched_file_changes(tmp_path: Path) -> None:
    watched = tmp_path / "apps" / "web"
    watched.mkdir(parents=True)
    server = watched / "server.js"
    server.write_text("first", encoding="utf-8")

    first = snapshot_paths(tmp_path, ("apps/web",))
    server.write_text("second", encoding="utf-8")
    second = snapshot_paths(tmp_path, ("apps/web",))

    assert first.file_count == 1
    assert second.file_count == 1
    assert first.digest != second.digest


def test_snapshot_paths_ignores_cache_directories(tmp_path: Path) -> None:
    watched = tmp_path / "src"
    cache = watched / "__pycache__"
    cache.mkdir(parents=True)
    (watched / "module.py").write_text("value = 1", encoding="utf-8")
    (cache / "module.pyc").write_bytes(b"ignored")

    snapshot = snapshot_paths(tmp_path, ("src",))

    assert snapshot.file_count == 1


def test_once_dry_run_prints_compose_rebuild_command(tmp_path: Path, capsys: Any) -> None:
    result = watch_and_rebuild(
        root=tmp_path,
        relative_paths=("apps/web",),
        interval_seconds=0.01,
        dry_run=True,
        once=True,
    )
    captured = capsys.readouterr()

    assert result == 0
    assert " ".join(DEFAULT_COMMAND) in captured.out
    assert ".env.local" in captured.out
    assert "up --build -d web" in captured.out
