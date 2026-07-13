from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from founder.cli import main
from founder.paths import LakePaths
from founder.table_io import read_json, read_rows


class FakeEodhdClient:
    requests: list[tuple[str, dict[str, str | int | float] | None]] = []

    def __init__(self, config: object) -> None:
        self.config = config

    def get_json(self, path: str, params: dict[str, str | int | float] | None = None) -> Any:
        self.requests.append((path, params))
        if path.startswith("/div/"):
            return [{"date": "2025-12-15", "value": 0.12}]
        if path.startswith("/splits/"):
            return []
        if params is not None and "from" in params and "to" in params:
            start = date.fromisoformat(str(params["from"]))
            end = date.fromisoformat(str(params["to"]))
            rows: list[dict[str, Any]] = []
            current = start
            while current <= end:
                if current.weekday() < 5:
                    rows.append(
                        {
                            "date": current.isoformat(),
                            "close": 10.0,
                            "adjusted_close": 10.0,
                        }
                    )
                current += timedelta(days=1)
            return rows
        return [
            {"date": "2020-01-02", "close": 10.0, "adjusted_close": 10.0},
            {"date": "2026-07-12", "close": 12.0, "adjusted_close": 12.0},
        ]


def test_cli_prints_project_name(capsys: pytest.CaptureFixture[str]) -> None:
    main([])

    output = capsys.readouterr()
    assert output.out == "founder\n"


def test_cli_runs_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["dry-run", "--root", str(tmp_path / "lake")])

    output = capsys.readouterr()
    assert '"canonical_rows": 2' in output.out


def test_cli_runs_search_and_fetch_modules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "lake"
    input_path = tmp_path / "candidates.json"
    input_path.write_text(
        """
        [
          {
            "Code": "EXAMPLE",
            "Exchange": "XETRA",
            "Type": "ETF",
            "Country": "DE",
            "Currency": "EUR",
            "Isin": "IE0000000001",
            "Name": "Example UCITS ETF"
                    },
                    {
                        "Code": "SECOND",
                        "Exchange": "XETRA",
                        "Type": "ETF",
                        "Country": "DE",
                        "Currency": "EUR",
                        "Isin": "IE0000000002",
                        "Name": "Second UCITS ETF"
          }
        ]
        """,
        encoding="utf-8",
    )

    main(
        [
            "search",
            "UCITS ETF",
            "--root",
            str(root),
            "--input",
            str(input_path),
            "--search-run-id",
            "search-cli",
            "--debug",
        ]
    )
    search_output = capsys.readouterr()
    assert '"canonical_rows": 2' in search_output.out

    main(
        [
            "fetch",
            "--root",
            str(root),
            "--mock",
            "--limit",
            "1",
            "--debug",
        ]
    )
    fetch_output = capsys.readouterr()
    assert '"fetch_plan_rows": 1' in fetch_output.out
    assert '"quote_rows": 2' in fetch_output.out
    assert '"return_rows": 1' in fetch_output.out

    paths = LakePaths(root=root)
    assert read_json(paths.current_universe())["search_run_id"] == "search-cli"
    assert len(read_rows(paths.coverage())) == 1
    assert len(read_rows(paths.gold_returns("XETRA", "IE0000000001"))) == 1
    assert len(read_rows(paths.gold_correlation("XETRA", "IE0000000001"))) == 1
    assert len(read_rows(paths.gold_covariance("XETRA", "IE0000000001"))) == 1
    log_path = next((tmp_path / ".logs").glob("founder-*.log"))
    assert " DEBUG founder.cli parsed cli args" in log_path.read_text(encoding="utf-8")


def test_cli_fetch_can_select_one_isin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "lake"
    input_path = tmp_path / "candidates.json"
    input_path.write_text(
        """
        [
          {
            "Code": "EXAMPLE",
            "Exchange": "XETRA",
            "Type": "ETF",
            "Country": "DE",
            "Currency": "EUR",
            "Isin": "IE0000000001",
            "Name": "Example UCITS ETF"
          },
          {
            "Code": "SECOND",
            "Exchange": "XETRA",
            "Type": "ETF",
            "Country": "DE",
            "Currency": "EUR",
            "Isin": "IE0000000002",
            "Name": "Second UCITS ETF"
          }
        ]
        """,
        encoding="utf-8",
    )

    main(
        [
            "search",
            "UCITS ETF",
            "--root",
            str(root),
            "--input",
            str(input_path),
            "--search-run-id",
            "search-cli",
        ]
    )
    capsys.readouterr()

    main(
        [
            "fetch",
            "--root",
            str(root),
            "--mock",
            "--isin",
            "IE0000000002",
            "--run-date",
            "2026-07-12",
        ]
    )

    fetch_output = capsys.readouterr()
    assert '"fetch_plan_rows": 1' in fetch_output.out
    assert read_rows(LakePaths(root=root).fetch_plan("fetch-20260712"))[0]["isin"] == "IE0000000002"


def test_cli_fetch_limit_and_isin_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        main(["fetch", "--limit", "1", "--isin", "IE0000000001"])


def test_cli_fetch_live_defaults_to_gap_aware_full_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("founder.cli.load_eodhd_config", lambda: object())
    FakeEodhdClient.requests = []
    monkeypatch.setattr("founder.cli.EodhdClient", FakeEodhdClient)
    root = tmp_path / "lake"
    input_path = tmp_path / "candidates.json"
    input_path.write_text(
        """
        [
          {
            "Code": "EXAMPLE",
            "Exchange": "XETRA",
            "Type": "ETF",
            "Country": "DE",
            "Currency": "EUR",
            "Isin": "IE0000000001",
            "Name": "Example UCITS ETF"
          }
        ]
        """,
        encoding="utf-8",
    )

    main(
        [
            "search",
            "UCITS ETF",
            "--root",
            str(root),
            "--input",
            str(input_path),
            "--search-run-id",
            "search-cli",
        ]
    )
    capsys.readouterr()

    main(
        [
            "fetch",
            "--root",
            str(root),
            "--run-id",
            "fetch-live",
            "--run-date",
            "2026-07-12",
        ]
    )

    fetch_output = capsys.readouterr()
    assert '"fetch_plan_rows": 1' in fetch_output.out
    assert '"gap_aware": true' in fetch_output.out
    assert '"quote_rows": 2' in fetch_output.out
    assert '"return_rows": 1' in fetch_output.out
    assert '"raw_data_payloads": 2' in fetch_output.out
    assert FakeEodhdClient.requests == [
        ("/eod/EXAMPLE.XETRA", {"fmt": "json", "to": "2026-07-12"}),
        ("/div/EXAMPLE.XETRA", {"fmt": "json", "to": "2026-07-12"}),
        ("/splits/EXAMPLE.XETRA", {"fmt": "json", "to": "2026-07-12"}),
    ]
    paths = LakePaths(root=root)
    plan_row = read_rows(paths.fetch_plan("fetch-live"))[0]
    assert plan_row["start_date"] == ""
    assert plan_row["end_date"] == "2026-07-12"
    assert plan_row["window_reason"] == "full_history"
    assert len(read_rows(paths.coverage())) == 1
    assert len(read_rows(paths.gold_returns("XETRA", "IE0000000001"))) == 1
    assert len(read_rows(paths.gold_correlation("XETRA", "IE0000000001"))) == 1
    assert len(read_rows(paths.gold_covariance("XETRA", "IE0000000001"))) == 1
    dividends_path = paths.bronze_dataset_file("dividends", "XETRA", 2025, "IE0000000001")
    assert read_rows(dividends_path) == [
        {
            "date": "2025-12-15",
            "value": 0.12,
            "run_id": "fetch-live",
            "isin": "IE0000000001",
            "code": "EXAMPLE",
            "exchange": "XETRA",
            "symbol": "EXAMPLE.XETRA",
            "run_date": "2026-07-12",
        }
    ]
    assert not paths.bronze_dataset_file("splits", "XETRA", 2026, "IE0000000001").exists()


def test_cli_fetch_manual_start_date_bypasses_gap_aware_planning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("founder.cli.load_eodhd_config", lambda: object())
    FakeEodhdClient.requests = []
    monkeypatch.setattr("founder.cli.EodhdClient", FakeEodhdClient)
    root = tmp_path / "lake"
    input_path = tmp_path / "candidates.json"
    input_path.write_text(
        """
        [
          {
            "Code": "EXAMPLE",
            "Exchange": "XETRA",
            "Type": "ETF",
            "Country": "DE",
            "Currency": "EUR",
            "Isin": "IE0000000001",
            "Name": "Example UCITS ETF"
          }
        ]
        """,
        encoding="utf-8",
    )

    main(
        [
            "search",
            "UCITS ETF",
            "--root",
            str(root),
            "--input",
            str(input_path),
            "--search-run-id",
            "search-cli",
        ]
    )
    capsys.readouterr()
    main(
        [
            "fetch",
            "--root",
            str(root),
            "--run-id",
            "fetch-current-day",
            "--start-date",
            "2026-07-12",
            "--end-date",
            "2026-07-12",
        ]
    )
    capsys.readouterr()

    FakeEodhdClient.requests = []
    main(
        [
            "fetch",
            "--root",
            str(root),
            "--run-id",
            "fetch-manual",
            "--start-date",
            "2026-07-01",
            "--end-date",
            "2026-07-13",
        ]
    )

    fetch_output = capsys.readouterr()
    assert '"gap_aware": false' in fetch_output.out
    assert FakeEodhdClient.requests == [
        ("/eod/EXAMPLE.XETRA", {"fmt": "json", "from": "2026-07-01", "to": "2026-07-13"}),
        ("/div/EXAMPLE.XETRA", {"fmt": "json", "from": "2026-07-01", "to": "2026-07-13"}),
        ("/splits/EXAMPLE.XETRA", {"fmt": "json", "from": "2026-07-01", "to": "2026-07-13"}),
    ]


def test_cli_fetch_defaults_to_gap_aware_windows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("founder.cli.load_eodhd_config", lambda: object())
    FakeEodhdClient.requests = []
    monkeypatch.setattr("founder.cli.EodhdClient", FakeEodhdClient)
    root = tmp_path / "lake"
    input_path = tmp_path / "candidates.json"
    input_path.write_text(
        """
        [
          {
            "Code": "EXAMPLE",
            "Exchange": "XETRA",
            "Type": "ETF",
            "Country": "DE",
            "Currency": "EUR",
            "Isin": "IE0000000001",
            "Name": "Example UCITS ETF"
          }
        ]
        """,
        encoding="utf-8",
    )

    main(
        [
            "search",
            "UCITS ETF",
            "--root",
            str(root),
            "--input",
            str(input_path),
            "--search-run-id",
            "search-cli",
        ]
    )
    capsys.readouterr()
    main(["fetch", "--root", str(root), "--run-id", "fetch-full"])
    capsys.readouterr()

    FakeEodhdClient.requests = []
    main(
        [
            "fetch",
            "--root",
            str(root),
            "--run-id",
            "fetch-gap-aware",
            "--run-date",
            "2026-07-13",
        ]
    )

    fetch_output = capsys.readouterr()
    assert '"gap_aware": true' in fetch_output.out
    assert FakeEodhdClient.requests == [
        ("/eod/EXAMPLE.XETRA", {"fmt": "json", "from": "2020-01-03", "to": "2026-07-13"}),
        ("/div/EXAMPLE.XETRA", {"fmt": "json", "from": "2020-01-03", "to": "2026-07-13"}),
        ("/splits/EXAMPLE.XETRA", {"fmt": "json", "from": "2020-01-03", "to": "2026-07-13"}),
    ]
    plan_rows = read_rows(LakePaths(root=root).fetch_plan("fetch-gap-aware"))
    assert [row["window_reason"] for row in plan_rows] == ["gap_backfill"]
    assert [(row["start_date"], row["end_date"]) for row in plan_rows] == [
        ("2020-01-03", "2026-07-13"),
    ]
    gap_rows = read_rows(LakePaths(root=root).quote_gaps())
    assert gap_rows == []


def test_cli_fetch_skips_non_quote_data_when_quote_plan_is_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("founder.cli.load_eodhd_config", lambda: object())
    FakeEodhdClient.requests = []
    monkeypatch.setattr("founder.cli.EodhdClient", FakeEodhdClient)
    root = tmp_path / "lake"
    input_path = tmp_path / "candidates.json"
    input_path.write_text(
        """
        [
          {
            "Code": "EXAMPLE",
            "Exchange": "XETRA",
            "Type": "ETF",
            "Country": "DE",
            "Currency": "EUR",
            "Isin": "IE0000000001",
            "Name": "Example UCITS ETF"
          }
        ]
        """,
        encoding="utf-8",
    )

    main(
        [
            "search",
            "UCITS ETF",
            "--root",
            str(root),
            "--input",
            str(input_path),
            "--search-run-id",
            "search-cli",
        ]
    )
    capsys.readouterr()
    main(
        [
            "fetch",
            "--root",
            str(root),
            "--run-id",
            "fetch-current-day",
            "--start-date",
            "2026-07-10",
            "--end-date",
            "2026-07-10",
        ]
    )
    capsys.readouterr()

    FakeEodhdClient.requests = []
    main(
        [
            "fetch",
            "--root",
            str(root),
            "--run-id",
            "fetch-no-quote-gaps",
            "--run-date",
            "2026-07-10",
        ]
    )

    fetch_output = capsys.readouterr()
    assert '"fetch_plan_rows": 0' in fetch_output.out
    assert '"raw_data_payloads": 0' in fetch_output.out
    assert FakeEodhdClient.requests == []


def test_cli_fetch_rejects_removed_incremental_flag() -> None:
    with pytest.raises(SystemExit):
        main(["fetch", "--incremental"])
