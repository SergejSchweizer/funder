import logging
import zipfile
from datetime import UTC, datetime

from camovar.logging import get_logger, log_event, rotate_logs, setup_logging


def test_setup_logging_writes_uniform_debug_log(tmp_path) -> None:  # type: ignore[no-untyped-def]
    log_dir = tmp_path / ".logs"
    logger = setup_logging(debug=True, log_dir=log_dir, now=datetime(2026, 7, 12, tzinfo=UTC))
    module_logger = get_logger("camovar.test")

    assert logger.level == logging.DEBUG
    log_event(module_logger, logging.DEBUG, module="test", event="debug", fields={"detail": "yes"})
    log_event(module_logger, logging.INFO, module="test", event="hello")

    log_path = log_dir / "camovar-2026-07-12.log"
    content = log_path.read_text(encoding="utf-8")
    assert "2026-" in content
    assert " INFO camovar module=logging event=configured debug=true log_dir=" in content
    assert " DEBUG camovar.test module=test event=debug detail=yes" in content
    assert " INFO camovar.test module=test event=hello" in content


def test_rotate_logs_zips_after_seven_days_and_deletes_after_month(tmp_path) -> None:  # type: ignore[no-untyped-def]
    log_dir = tmp_path / ".logs"
    log_dir.mkdir()
    old_log = log_dir / "camovar-2026-07-01.log"
    recent_log = log_dir / "camovar-2026-07-10.log"
    expired_zip = log_dir / "camovar-2026-06-01.zip"
    old_log.write_text("old log\n", encoding="utf-8")
    recent_log.write_text("recent log\n", encoding="utf-8")
    with zipfile.ZipFile(expired_zip, "w") as archive:
        archive.writestr("camovar-2026-06-01.log", "expired\n")

    rotate_logs(log_dir=log_dir, now=datetime(2026, 7, 12, tzinfo=UTC))

    zipped = log_dir / "camovar-2026-07-01.zip"
    assert not old_log.exists()
    assert recent_log.exists()
    assert zipped.exists()
    assert not expired_zip.exists()
    with zipfile.ZipFile(zipped) as archive:
        assert archive.read("camovar-2026-07-01.log") == b"old log\n"
