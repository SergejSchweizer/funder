from pathlib import Path

import pytest

from founder.evaluation import (
    ANNUAL_TRADING_DAYS,
    build_asset_metrics,
    build_drawdowns,
    build_portfolio_metrics,
    build_portfolio_returns,
    build_return_matrix,
    equal_weight_portfolio,
    read_gold_returns,
    validate_portfolio_weights,
    write_evaluation_outputs,
    write_portfolio_evaluation,
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


def test_portfolio_returns_align_weights_and_cumulative_wealth() -> None:
    matrix = build_return_matrix(
        [
            _return_row("IE1", "XETRA", "AAA", "2026-07-11", 0.02),
            _return_row("IE1", "XETRA", "AAA", "2026-07-12", -0.10),
            _return_row("IE2", "AS", "BBB", "2026-07-11", 0.04),
            _return_row("IE2", "AS", "BBB", "2026-07-12", 0.00),
            _return_row("IE2", "AS", "BBB", "2026-07-13", 0.10),
        ],
        "eval-1",
    )

    rows = build_portfolio_returns(
        matrix,
        evaluation_id="eval-1",
        portfolio_id="balanced",
        weights={"IE1": 0.25, "IE2": 0.75},
    )

    assert [row["date"] for row in rows] == ["2026-07-11", "2026-07-12"]
    assert rows[0]["return"] == pytest.approx(0.035)
    assert rows[0]["cumulative_wealth"] == pytest.approx(1.035)
    assert rows[1]["return"] == pytest.approx(-0.025)
    assert rows[1]["cumulative_wealth"] == pytest.approx(1.035 * 0.975)


def test_portfolio_weights_are_cash_free_and_match_matrix_isins() -> None:
    matrix = build_return_matrix(
        [
            _return_row("IE1", "XETRA", "AAA", "2026-07-11", 0.01),
            _return_row("IE2", "AS", "BBB", "2026-07-11", 0.02),
        ],
        "eval-1",
    )

    assert equal_weight_portfolio(matrix) == {"IE1": 0.5, "IE2": 0.5}
    with pytest.raises(ValueError, match="sum to 1"):
        validate_portfolio_weights(matrix, {"IE1": 0.5, "IE2": 0.4})
    with pytest.raises(ValueError, match="missing ISINs: IE2"):
        validate_portfolio_weights(matrix, {"IE1": 1.0})
    with pytest.raises(ValueError, match="unknown ISINs: IE3"):
        validate_portfolio_weights(matrix, {"IE1": 0.5, "IE2": 0.5, "IE3": 0.0})


def test_drawdowns_track_recovery_and_metrics() -> None:
    portfolio_returns = [
        {
            "evaluation_id": "eval-1",
            "portfolio_id": "balanced",
            "date": "2026-07-11",
            "return": 0.10,
            "cumulative_wealth": 1.10,
        },
        {
            "evaluation_id": "eval-1",
            "portfolio_id": "balanced",
            "date": "2026-07-12",
            "return": -0.20,
            "cumulative_wealth": 0.88,
        },
        {
            "evaluation_id": "eval-1",
            "portfolio_id": "balanced",
            "date": "2026-07-13",
            "return": 0.25,
            "cumulative_wealth": 1.10,
        },
        {
            "evaluation_id": "eval-1",
            "portfolio_id": "balanced",
            "date": "2026-07-14",
            "return": 0.01,
            "cumulative_wealth": 1.111,
        },
    ]

    drawdowns = build_drawdowns(portfolio_returns)
    metrics = build_portfolio_metrics(portfolio_returns, drawdowns, objective="manual")

    assert drawdowns[1]["drawdown"] == pytest.approx(-0.20)
    assert drawdowns[1]["drawdown_duration"] == 1
    assert drawdowns[2]["drawdown"] == 0.0
    assert drawdowns[2]["recovery_duration"] == 1
    assert drawdowns[2]["is_recovered"] is True
    assert metrics[0]["objective"] == "manual"
    assert metrics[0]["max_drawdown"] == pytest.approx(-0.20)
    assert metrics[0]["calmar_ratio"] > 0.0
    assert metrics[0]["ulcer_index"] > 0.0


def test_write_portfolio_evaluation_is_idempotent(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    write_rows(
        paths.gold_returns("XETRA", "IE1"),
        [
            _return_row("IE1", "XETRA", "AAA", "2026-07-11", 0.02),
            _return_row("IE1", "XETRA", "AAA", "2026-07-12", -0.01),
        ],
    )
    write_rows(
        paths.gold_returns("AS", "IE2"),
        [
            _return_row("IE2", "AS", "BBB", "2026-07-11", 0.00),
            _return_row("IE2", "AS", "BBB", "2026-07-12", 0.03),
        ],
    )

    first = write_portfolio_evaluation(
        paths,
        evaluation_id="eval-1",
        portfolio_id="equal-weight",
    )
    write_portfolio_evaluation(
        paths,
        evaluation_id="eval-1",
        portfolio_id="manual",
        weights={"IE1": 0.25, "IE2": 0.75},
    )
    second = write_portfolio_evaluation(
        paths,
        evaluation_id="eval-1",
        portfolio_id="equal-weight",
    )

    assert first == second
    assert [row["portfolio_id"] for row in read_rows(paths.gold_portfolio_returns("eval-1"))] == [
        "equal-weight",
        "equal-weight",
        "manual",
        "manual",
    ]
    assert read_rows(paths.gold_drawdowns("eval-1", "equal-weight")) == first[1]
    assert [row["portfolio_id"] for row in read_rows(paths.gold_portfolio_metrics("eval-1"))] == [
        "equal-weight",
        "manual",
    ]
