from pathlib import Path

import pytest

from founder.evaluation import (
    ANNUAL_TRADING_DAYS,
    build_asset_metrics,
    build_return_matrix,
    read_gold_returns,
    write_evaluation_outputs,
)
from founder.paths import LakePaths
from founder.table_io import read_rows, write_rows


def _return_row(
    isin: str, exchange: str, code: str, date: str, daily_return: float
) -> dict[str, object]:
    return {
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "date": date,
        "return": daily_return,
    }


def test_return_matrix_aligns_common_dates_and_sorts_rows() -> None:
    rows = [
        _return_row("IE2", "AS", "BBB", "2026-07-12", 0.03),
        _return_row("IE1", "XETRA", "AAA", "2026-07-11", 0.01),
        _return_row("IE1", "XETRA", "AAA", "2026-07-12", 0.02),
        _return_row("IE2", "AS", "BBB", "2026-07-11", -0.01),
        _return_row("IE2", "AS", "BBB", "2026-07-13", 0.04),
    ]

    matrix = build_return_matrix(rows, "eval-1")

    assert [(row["date"], row["isin"]) for row in matrix] == [
        ("2026-07-11", "IE1"),
        ("2026-07-11", "IE2"),
        ("2026-07-12", "IE1"),
        ("2026-07-12", "IE2"),
    ]
    assert {row["evaluation_id"] for row in matrix} == {"eval-1"}


def test_asset_metrics_handle_zero_variance_and_downside_returns() -> None:
    matrix = build_return_matrix(
        [
            _return_row("IE1", "XETRA", "AAA", "2026-07-11", 0.01),
            _return_row("IE1", "XETRA", "AAA", "2026-07-12", 0.01),
            _return_row("IE2", "AS", "BBB", "2026-07-11", -0.02),
            _return_row("IE2", "AS", "BBB", "2026-07-12", 0.04),
        ],
        "eval-1",
    )

    metrics = build_asset_metrics(matrix, "eval-1")

    assert metrics[0]["isin"] == "IE1"
    assert metrics[0]["observation_count"] == 2
    assert metrics[0]["first_return_date"] == "2026-07-11"
    assert metrics[0]["last_return_date"] == "2026-07-12"
    assert metrics[0]["mean_return"] == pytest.approx(0.01)
    assert metrics[0]["annualized_return"] == pytest.approx(0.01 * ANNUAL_TRADING_DAYS)
    assert metrics[0]["annualized_volatility"] == 0.0
    assert metrics[0]["sharpe_ratio"] == 0.0
    assert metrics[0]["sortino_ratio"] == 0.0
    assert metrics[1]["downside_deviation"] > 0.0
    assert metrics[1]["sortino_ratio"] > 0.0


def test_write_evaluation_outputs_is_idempotent(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    write_rows(
        paths.gold_returns("XETRA", "IE1"),
        [
            _return_row("IE1", "XETRA", "AAA", "2026-07-11", 0.01),
            _return_row("IE1", "XETRA", "AAA", "2026-07-12", 0.02),
        ],
    )
    write_rows(
        paths.gold_returns("AS", "IE2"),
        [
            _return_row("IE2", "AS", "BBB", "2026-07-11", -0.01),
            _return_row("IE2", "AS", "BBB", "2026-07-12", 0.03),
        ],
    )

    first = write_evaluation_outputs(paths, evaluation_id="eval-1")
    second = write_evaluation_outputs(paths, evaluation_id="eval-1")

    assert first == second
    assert read_gold_returns(paths) == [
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-11", "return": -0.01},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-12", "return": 0.03},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-11", "return": 0.01},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-12", "return": 0.02},
    ]
    assert read_rows(paths.gold_return_matrix("eval-1")) == first[0]
    assert read_rows(paths.gold_asset_metrics("eval-1")) == first[1]
