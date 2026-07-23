"""Tests for instrument-level rebalancing drift and cost basis (PR57)."""

from __future__ import annotations

from pathlib import Path

import pytest

from camovar.evaluation import build_rebalance_events, write_rebalance_simulation
from camovar.paths import LakePaths
from camovar.table_io import read_rows, write_rows


def _matrix_row(
    isin: str, exchange: str, code: str, item_date: str, simple_return: float
) -> dict[str, object]:
    return {
        "evaluation_id": "eval-1",
        "date": item_date,
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "return": simple_return,
        "simple_return": simple_return,
    }


def _two_asset_matrix(returns: dict[str, tuple[float, float]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item_date, (ie1_return, ie2_return) in returns.items():
        rows.append(_matrix_row("IE1", "XETRA", "AAA", item_date, ie1_return))
        rows.append(_matrix_row("IE2", "AS", "BBB", item_date, ie2_return))
    return rows


def test_rebalance_matches_one_period_manual_spreadsheet_fixture() -> None:
    """Hand-computed two-day, two-asset fixture with no transaction costs."""
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.10, -0.02),
            "2026-01-02": (0.05, 0.00),
        }
    )

    events, weights = build_rebalance_events(
        matrix,
        run_id="rebalance-1",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="monthly",
        transaction_cost_rate=0.0,
    )

    assert len(events) == 2
    day1, day2 = events

    # Day 1 is always a rebalance day (no prior period recorded yet).
    assert day1["is_rebalance"] is True
    assert day1["pre_trade_value"] == pytest.approx(1.04)
    assert day1["turnover"] == pytest.approx(0.028846153846, rel=1e-9)
    assert day1["transaction_cost"] == 0.0
    assert day1["post_cost_return"] == pytest.approx(0.04)
    assert day1["portfolio_value"] == pytest.approx(1.04)
    assert day1["cash_remainder"] == pytest.approx(0.0, abs=1e-12)

    # Day 2 stays within the same month: no scheduled rebalance, instruments
    # simply drift from their own returns starting from day 1's rebalanced values.
    assert day2["is_rebalance"] is False
    assert day2["pre_trade_value"] == pytest.approx(1.066)
    assert day2["turnover"] == 0.0
    assert day2["transaction_cost"] == 0.0
    assert day2["post_cost_return"] == pytest.approx(0.025)
    assert day2["portfolio_value"] == pytest.approx(1.066)

    day1_weights = {row["isin"]: row for row in weights if row["date"] == "2026-01-01"}
    assert day1_weights["IE1"]["pre_trade_value"] == pytest.approx(0.55)
    assert day1_weights["IE1"]["pre_trade_weight"] == pytest.approx(0.528846153846, rel=1e-9)
    assert day1_weights["IE1"]["target_value"] == pytest.approx(0.52)
    assert day1_weights["IE1"]["trade_value"] == pytest.approx(-0.03)
    assert day1_weights["IE2"]["pre_trade_value"] == pytest.approx(0.49)
    assert day1_weights["IE2"]["target_value"] == pytest.approx(0.52)
    assert day1_weights["IE2"]["trade_value"] == pytest.approx(0.03)

    day2_weights = {row["isin"]: row for row in weights if row["date"] == "2026-01-02"}
    assert day2_weights["IE1"]["pre_trade_value"] == pytest.approx(0.546)
    assert day2_weights["IE1"]["trade_value"] == 0.0
    assert day2_weights["IE2"]["pre_trade_value"] == pytest.approx(0.52)
    assert day2_weights["IE2"]["trade_value"] == 0.0


def test_rebalance_persists_rows_matching_manual_fixture(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.10, -0.02),
            "2026-01-02": (0.05, 0.00),
        }
    )
    write_rows(paths.gold_return_matrix("eval-1"), matrix)

    events, weights = write_rebalance_simulation(
        paths,
        evaluation_id="eval-1",
        run_id="rebalance-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="monthly",
        transaction_cost_rate=0.0,
    )

    assert read_rows(paths.gold_rebalance_events("rebalance-1")) == events
    assert read_rows(paths.gold_rebalance_weights("rebalance-1")) == weights
    assert events[0]["portfolio_value"] == pytest.approx(1.04)
    assert events[1]["portfolio_value"] == pytest.approx(1.066)


def test_each_instrument_drifts_from_its_own_return_not_the_portfolio_return() -> None:
    """The core PR57 bug fix: instrument weights must diverge based on their own return."""
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.20, -0.20),  # first day: always rebalanced back to target
            "2026-01-02": (0.20, -0.20),  # second day: no scheduled rebalance, must drift
        }
    )

    _events, weights = build_rebalance_events(
        matrix,
        run_id="rebalance-1",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="monthly",
        transaction_cost_rate=0.0,
    )

    day2 = {row["isin"]: row for row in weights if row["date"] == "2026-01-02"}
    # IE1 gained 20% and IE2 lost 20% on day 2, so IE1's weight must rise and
    # IE2's must fall -- they cannot both move by the same blended amount.
    assert day2["IE1"]["pre_trade_weight"] > 0.5
    assert day2["IE2"]["pre_trade_weight"] < 0.5
    assert day2["IE1"]["pre_trade_weight"] != day2["IE2"]["pre_trade_weight"]


def test_no_trade_period_keeps_zero_turnover_and_trade_value() -> None:
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.0, 0.0),
            "2026-01-02": (0.03, -0.01),
            "2026-01-03": (0.01, 0.02),
        }
    )

    events, weights = build_rebalance_events(
        matrix,
        run_id="rebalance-1",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="monthly",
    )

    no_trade_days = [row for row in events if not row["is_rebalance"]]
    assert no_trade_days
    assert all(row["turnover"] == 0.0 for row in no_trade_days)
    assert all(row["transaction_cost"] == 0.0 for row in no_trade_days)
    no_trade_dates = {row["date"] for row in no_trade_days}
    assert all(row["trade_value"] == 0.0 for row in weights if row["date"] in no_trade_dates)


def test_threshold_schedule_triggers_only_past_drift_threshold() -> None:
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.0, 0.0),
            "2026-01-02": (0.30, -0.30),
        }
    )

    tight_events, _ = build_rebalance_events(
        matrix,
        run_id="rebalance-1",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="threshold",
        drift_threshold=0.05,
    )
    loose_events, _ = build_rebalance_events(
        matrix,
        run_id="rebalance-2",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="threshold",
        drift_threshold=0.90,
    )

    assert tight_events[1]["is_rebalance"] is True
    assert loose_events[1]["is_rebalance"] is False


def test_transaction_cost_reduces_post_cost_return_and_portfolio_value() -> None:
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.10, -0.02),
        }
    )

    free_events, _ = build_rebalance_events(
        matrix,
        run_id="rebalance-1",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="monthly",
        transaction_cost_rate=0.0,
    )
    costly_events, _ = build_rebalance_events(
        matrix,
        run_id="rebalance-2",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="monthly",
        transaction_cost_rate=0.01,
    )

    assert costly_events[0]["transaction_cost"] > 0.0
    assert costly_events[0]["transaction_cost"] == pytest.approx(
        costly_events[0]["turnover"] * 0.01 * costly_events[0]["pre_trade_value"]
    )
    assert costly_events[0]["portfolio_value"] < free_events[0]["portfolio_value"]
    assert costly_events[0]["post_cost_return"] < free_events[0]["post_cost_return"]


def test_changing_target_weights_produce_different_target_values() -> None:
    matrix = _two_asset_matrix({"2026-01-01": (0.10, -0.02)})

    _events_a, weights_a = build_rebalance_events(
        matrix,
        run_id="rebalance-a",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="monthly",
    )
    _events_b, weights_b = build_rebalance_events(
        matrix,
        run_id="rebalance-b",
        evaluation_id="eval-1",
        portfolio_id="tilted",
        target_weights={"IE1": 0.8, "IE2": 0.2},
        schedule="monthly",
    )

    ie1_a = next(row for row in weights_a if row["isin"] == "IE1")
    ie1_b = next(row for row in weights_b if row["isin"] == "IE1")
    assert ie1_a["target_weight"] == 0.5
    assert ie1_b["target_weight"] == 0.8
    assert ie1_a["target_value"] != ie1_b["target_value"]


def test_fully_invested_target_weights_leave_no_cash_remainder() -> None:
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.10, -0.02),
            "2026-01-02": (0.01, 0.01),
        }
    )

    events, _weights = build_rebalance_events(
        matrix,
        run_id="rebalance-1",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="monthly",
        transaction_cost_rate=0.01,
    )

    assert all(row["cash_remainder"] == pytest.approx(0.0, abs=1e-9) for row in events)


def test_build_rebalance_events_rejects_unknown_schedule() -> None:
    with pytest.raises(ValueError, match="unknown rebalance schedule"):
        build_rebalance_events(
            [],
            run_id="r",
            evaluation_id="e",
            portfolio_id="p",
            target_weights={"IE1": 1.0},
            schedule="weekly",
        )


def test_build_rebalance_events_defaults_to_equal_weight_target() -> None:
    matrix = _two_asset_matrix({"2026-01-01": (0.10, -0.02)})

    events, weights = build_rebalance_events(
        matrix,
        run_id="rebalance-1",
        evaluation_id="eval-1",
        portfolio_id="balanced",
        schedule="monthly",
    )

    assert events[0]["is_rebalance"] is True
    assert {row["target_weight"] for row in weights} == {0.5}
