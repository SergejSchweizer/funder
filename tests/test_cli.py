import pytest

from founder.cli import main


def test_cli_prints_project_name(capsys: pytest.CaptureFixture[str]) -> None:
    main([])

    output = capsys.readouterr()
    assert output.out == "founder\n"


def test_cli_runs_dry_run(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:  # type: ignore[no-untyped-def]
    main(["dry-run", "--root", str(tmp_path / "lake")])

    output = capsys.readouterr()
    assert '"canonical_rows": 2' in output.out
