import json
from pathlib import Path

import pytest

from founder.cli import main
from founder.paths import LakePaths
from founder.table_io import read_json, read_rows, write_json, write_rows


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


def _dividend(isin: str, exchange: str, code: str, date: str, value: float) -> dict[str, object]:
    return {
        "run_id": "bronze-1",
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "date": date,
        "value": value,
        "unadjustedValue": value,
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
        paths.bronze_dataset_file("dividends", "XETRA", 2026, "IE1"),
        [_dividend("IE1", "XETRA", "AAA", "2026-02-15", 1.0)],
    )
    write_rows(
        paths.bronze_dataset_file("dividends", "AS", 2026, "IE2"),
        [_dividend("IE2", "AS", "BBB", "2026-02-15", 1.0)],
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
    write_rows(
        paths.metadata_filter_isins("older-ie2"),
        [
            {
                "selection_id": "older-ie2",
                "isin": "IE2",
                "exchange": "AS",
                "code": "BBB",
                "name": "",
                "source_module": "metadata_filter",
            }
        ],
    )
    write_json(
        paths.metadata_filter_manifest("older-ie2"),
        {
            "selection_id": "older-ie2",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    )
    write_json(
        paths.metadata_filter_manifest("selected-ie1"),
        {
            "selection_id": "selected-ie1",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
    )

    main(["univariate-statistics", "--root", str(root)])
    univariate_output = capsys.readouterr()
    univariate_payload = json.loads(univariate_output.out)
    assert univariate_payload["selection_id"] == "selected-ie1"
    assert univariate_payload["selected_listing_count"] == 1
    assert univariate_payload["quote_rows"] == 3
    assert univariate_payload["dividend_rows"] == 1
    assert univariate_payload["univariate_statistics_rows"] == 1
    gold_rows = read_rows(paths.gold_univariate_statistics("XETRA", "IE1"))
    assert len(gold_rows) == 1
    assert gold_rows[0]["distribution_frequency"] == "unknown"
    assert gold_rows[0]["last_distribution_date"] == "2026-02-15"
    assert read_rows(paths.gold_univariate_statistics("AS", "IE2")) == []

    main(["bivariate-statistics", "--root", str(root), "--selection-id", "selected-ie1"])
    bivariate_output = capsys.readouterr()
    bivariate_payload = json.loads(bivariate_output.out)
    assert bivariate_payload["selection_id"] == "selected-ie1"
    assert bivariate_payload["bivariate_statistics_rows"] == 0
    assert (
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
        == []
    )


def test_cli_univariate_statistics_requires_metadata_selection(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="run metadata-filter first"):
        main(["univariate-statistics", "--root", str(tmp_path / "lake")])


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
        paths.univariate_filter_isins("two-listings"),
        [
            {
                "selection_id": "two-listings",
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "",
                "source_module": "univariate_filter",
            },
            {
                "selection_id": "two-listings",
                "isin": "IE2",
                "exchange": "AS",
                "code": "BBB",
                "name": "",
                "source_module": "univariate_filter",
            },
        ],
    )
    write_json(
        paths.current_univariate_filter_selection(),
        {"selection_id": "two-listings"},
    )

    main(["bivariate-statistics", "--root", str(root)])

    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["selection_id"] == "two-listings"
    assert payload["quote_rows"] == 6
    assert payload["bivariate_statistics_rows"] == 1


def test_cli_bivariate_statistics_requires_univariate_selection(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="run univariate-filter first"):
        main(["bivariate-statistics", "--root", str(tmp_path / "lake")])


def test_cli_bivariate_statistics_uses_latest_univariate_manifest_without_pointer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "lake"
    paths = LakePaths(root=root)
    for isin, exchange, code, base in (
        ("IE1", "XETRA", "AAA", 100.0),
        ("IE2", "AS", "BBB", 120.0),
    ):
        write_rows(
            paths.silver_quote_file(exchange, isin),
            [
                _quote(isin, exchange, code, "2026-01-01", base),
                _quote(isin, exchange, code, "2026-01-02", base + 1.0),
            ],
        )
    write_rows(
        paths.univariate_filter_isins("latest-two"),
        [
            {
                "selection_id": "latest-two",
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "",
                "source_module": "univariate_filter",
            },
            {
                "selection_id": "latest-two",
                "isin": "IE2",
                "exchange": "AS",
                "code": "BBB",
                "name": "",
                "source_module": "univariate_filter",
            },
        ],
    )
    write_json(
        paths.univariate_filter_manifest("latest-two"),
        {"selection_id": "latest-two", "created_at": "2026-01-02T00:00:00+00:00"},
    )

    main(["bivariate-statistics", "--root", str(root), "--concurrency", "1"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["selection_id"] == "latest-two"
    assert payload["bivariate_statistics_rows"] == 1


def test_cli_bivariate_statistics_accepts_explicit_metadata_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "lake"
    paths = LakePaths(root=root)
    for isin, exchange, code, base in (
        ("IE1", "XETRA", "AAA", 100.0),
        ("IE2", "AS", "BBB", 120.0),
    ):
        write_rows(
            paths.silver_quote_file(exchange, isin),
            [
                _quote(isin, exchange, code, "2026-01-01", base),
                _quote(isin, exchange, code, "2026-01-02", base + 1.0),
            ],
        )
    write_rows(
        paths.metadata_filter_isins("metadata-two"),
        [
            {
                "selection_id": "metadata-two",
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "",
                "source_module": "metadata_filter",
            },
            {
                "selection_id": "metadata-two",
                "isin": "IE2",
                "exchange": "AS",
                "code": "BBB",
                "name": "",
                "source_module": "metadata_filter",
            },
        ],
    )

    main(["bivariate-statistics", "--root", str(root), "--selection-id", "metadata-two"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["selection_id"] == "metadata-two"
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
    assert (
        read_json(paths.current_metadata_filter_selection())["selection_id"]
        == metadata_payload["selection_id"]
    )

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
    assert (
        read_json(paths.current_univariate_filter_selection())["selection_id"]
        == univariate_payload["selection_id"]
    )


def test_cli_metadata_filter_requires_a_filter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--where or --name-contains"):
        main(["metadata-filter", "--root", str(tmp_path / "lake")])
