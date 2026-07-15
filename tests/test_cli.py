import json
from pathlib import Path

import pytest

from founder.cli import main
from founder.paths import LakePaths
from founder.table_io import read_json, read_rows, write_rows


def _quote(isin: str, exchange: str, code: str, date: str, close: float) -> dict[str, object]:
    return {
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "date": date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "adjusted_close": close,
        "volume": 100,
        "currency": "EUR",
    }


def test_cli_prints_project_name(capsys: pytest.CaptureFixture[str]) -> None:
    main([])

    output = capsys.readouterr()
    assert output.out == "founder\n"


def test_cli_runs_search_module(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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

    output = capsys.readouterr()
    payload = json.loads(output.out)
    paths = LakePaths(root=root)
    assert payload["canonical_rows"] == 1
    assert read_json(paths.current_universe())["search_run_id"] == "search-cli"


def test_cli_runs_univariate_and_bivariate_statistics_modules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "lake"
    paths = LakePaths(root=root)
    write_rows(
        paths.silver_quote_file("XETRA", "IE1"),
        [
            _quote("IE1", "XETRA", "AAA", "2026-01-01", 100.0),
            _quote("IE1", "XETRA", "AAA", "2026-01-02", 110.0),
            _quote("IE1", "XETRA", "AAA", "2026-01-03", 120.0),
        ],
    )
    write_rows(
        paths.silver_quote_file("AS", "IE2"),
        [
            _quote("IE2", "AS", "BBB", "2026-01-01", 120.0),
            _quote("IE2", "AS", "BBB", "2026-01-02", 110.0),
            _quote("IE2", "AS", "BBB", "2026-01-03", 100.0),
        ],
    )

    main(["univariate-statistics", "--root", str(root)])
    univariate_output = capsys.readouterr()
    assert json.loads(univariate_output.out)["univariate_statistics_rows"] == 2
    assert len(read_rows(paths.gold_univariate_statistics("XETRA", "IE1"))) == 1

    main(["bivariate-statistics", "--root", str(root)])
    bivariate_output = capsys.readouterr()
    assert json.loads(bivariate_output.out)["bivariate_statistics_rows"] == 1
    assert (
        len(
            read_rows(
                paths.gold_bivariate_statistics_pair(
                    "XETRA",
                    "IE1",
                    "AAA",
                    "AS",
                    "IE2",
                    "BBB",
                )
            )
        )
        == 1
    )
