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
    write_rows(
        paths.metadata_filter_isins("selected-ie1"),
        [
            {
                "selection_id": "selected-ie1",
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "",
                "source_module": "metadata_filter",
            }
        ],
    )

    main(["univariate-statistics", "--root", str(root), "--selection-id", "selected-ie1"])
    univariate_output = capsys.readouterr()
    univariate_payload = json.loads(univariate_output.out)
    assert univariate_payload["selection_id"] == "selected-ie1"
    assert univariate_payload["selected_listing_count"] == 1
    assert univariate_payload["quote_rows"] == 3
    assert univariate_payload["univariate_statistics_rows"] == 1
    assert len(read_rows(paths.gold_univariate_statistics("XETRA", "IE1"))) == 1
    assert read_rows(paths.gold_univariate_statistics("AS", "IE2")) == []

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


def test_cli_restricts_bivariate_statistics_to_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "lake"
    paths = LakePaths(root=root)
    for isin, exchange, code, base in (
        ("IE1", "XETRA", "AAA", 100.0),
        ("IE2", "AS", "BBB", 120.0),
        ("IE3", "PA", "CCC", 90.0),
    ):
        write_rows(
            paths.silver_quote_file(exchange, isin),
            [
                _quote(isin, exchange, code, "2026-01-01", base),
                _quote(isin, exchange, code, "2026-01-02", base + 1.0),
                _quote(isin, exchange, code, "2026-01-03", base + 2.0),
            ],
        )
    write_rows(
        paths.metadata_filter_isins("two-listings"),
        [
            {
                "selection_id": "two-listings",
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "",
                "source_module": "metadata_filter",
            },
            {
                "selection_id": "two-listings",
                "isin": "IE2",
                "exchange": "AS",
                "code": "BBB",
                "name": "",
                "source_module": "metadata_filter",
            },
        ],
    )

    main(["bivariate-statistics", "--root", str(root), "--selection-id", "two-listings"])

    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["quote_rows"] == 6
    assert payload["bivariate_statistics_rows"] == 1


def test_cli_runs_metadata_and_univariate_filter_modules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "lake"
    paths = LakePaths(root=root)
    write_rows(
        paths.all_isins(),
        [
            {
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "Example UCITS ETF",
                "instrument_type": "ETF",
                "country": "DE",
                "currency": "EUR",
                "source_exchange": "XETRA",
                "fetched_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "isin": "IE2",
                "exchange": "US",
                "code": "BBB",
                "name": "Other Fund",
                "instrument_type": "FUND",
                "country": "US",
                "currency": "USD",
                "source_exchange": "US",
                "fetched_at": "2026-01-01T00:00:00+00:00",
            },
        ],
    )

    main(
        [
            "metadata-filter",
            "--root",
            str(root),
            "--where",
            "instrument_type=ETF",
            "--name-contains",
            "UCITS ETF",
            "--selection-name",
            "ucits-etf",
        ]
    )
    metadata_output = capsys.readouterr()
    metadata_payload = json.loads(metadata_output.out)
    assert metadata_payload["selected_rows"] == 1
    assert len(read_rows(paths.metadata_filter_isins(metadata_payload["selection_id"]))) == 1

    write_rows(
        paths.gold_univariate_statistics("XETRA", "IE1"),
        [
            {
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "Example UCITS ETF",
                "sharpe_ratio": 1.5,
            }
        ],
    )

    main(
        [
            "univariate-filter",
            "--root",
            str(root),
            "--where",
            "sharpe_ratio>1.0",
            "--selection-name",
            "high-sharpe",
        ]
    )
    univariate_output = capsys.readouterr()
    univariate_payload = json.loads(univariate_output.out)
    assert univariate_payload["selected_rows"] == 1
    assert len(read_rows(paths.univariate_filter_isins(univariate_payload["selection_id"]))) == 1


def test_cli_metadata_filter_requires_a_filter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--where or --name-contains"):
        main(["metadata-filter", "--root", str(tmp_path / "lake")])
