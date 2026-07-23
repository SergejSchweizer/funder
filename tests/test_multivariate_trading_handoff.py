"""Tests for PR72's multivariate trading and monitoring handoff."""

import csv
from pathlib import Path
from random import Random

import pytest

from camovar.multivariate_statistics import (
    MultivariateRecommendationConfig,
    ProductionMultivariateConfig,
    TradingHandoffConfig,
    write_multivariate_trading_handoff,
)
from camovar.paths import LakePaths
from camovar.portfolio import PortfolioConstraints
from camovar.table_io import write_rows

_OBSERVATION_COUNT = 260


def _quote(
    isin: str, exchange: str, code: str, date: str, close: float, currency: str = "EUR"
) -> dict[str, object]:
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
        "currency": currency,
    }


def _quote_series(
    isin: str, exchange: str, code: str, *, seed: int, day_count: int = _OBSERVATION_COUNT
) -> list[dict[str, object]]:
    rng = Random(seed)
    rows = []
    close = 100.0
    for day in range(day_count):
        year = 2020 + day // 365
        remainder = day % 365
        month = 1 + remainder // 28
        day_of_month = 1 + remainder % 28
        date = f"{year:04d}-{month:02d}-{day_of_month:02d}"
        close *= 1.0 + rng.gauss(0.0004, 0.01)
        rows.append(_quote(isin, exchange, code, date, close))
    return rows


def _write_selection(
    paths: LakePaths, listings: list[tuple[str, str, str]], *, day_count: int = _OBSERVATION_COUNT
) -> list[dict[str, object]]:
    selected_rows: list[dict[str, object]] = []
    for index, (isin, exchange, code) in enumerate(listings):
        rows = _quote_series(isin, exchange, code, seed=100 + index, day_count=day_count)
        write_rows(paths.silver_quote_file(exchange, isin), rows)
        selected_rows.append({"isin": isin, "exchange": exchange, "code": code})
    return selected_rows


_FIVE_LISTINGS = [
    ("IE1", "XETRA", "AAA"),
    ("IE2", "AS", "BBB"),
    ("IE3", "PA", "CCC"),
    ("IE4", "MU", "DDD"),
    ("IE5", "LSE", "EEE"),
]


def _recommendation_config() -> MultivariateRecommendationConfig:
    return MultivariateRecommendationConfig(
        production_config=ProductionMultivariateConfig(
            evaluation_id="prod-eval", constraints=PortfolioConstraints(max_weight=0.4)
        )
    )


def test_write_multivariate_trading_handoff_rejects_unapproved_recommendation_by_default(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = TradingHandoffConfig(recommendation_config=_recommendation_config())

    with pytest.raises(ValueError, match="recommendation_not_approved"):
        write_multivariate_trading_handoff(paths, selected_rows, config=config)


def test_write_multivariate_trading_handoff_rejects_unknown_comparison_slot(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = TradingHandoffConfig(
        recommendation_config=_recommendation_config(),
        approved_comparison_slot="not_a_real_slot",
    )

    with pytest.raises(ValueError, match="recommendation_not_approved"):
        write_multivariate_trading_handoff(paths, selected_rows, config=config)


def test_write_multivariate_trading_handoff_succeeds_with_approved_slot(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = TradingHandoffConfig(
        recommendation_config=_recommendation_config(),
        approved_comparison_slot="best_ensemble",
    )

    handoff = write_multivariate_trading_handoff(paths, selected_rows, config=config)

    assert handoff["approved_comparison_slot"] == "best_ensemble"
    assert handoff["target_weights"]
    assert handoff["transition_rows"] is None
    assert handoff["flatex_export_path"] is None
    assert handoff["monitoring_statuses"]["distribution_cut_status"] == "unavailable"
    assert handoff["monitoring_statuses"]["nav_erosion_status"] == "unavailable"


def test_write_multivariate_trading_handoff_includes_current_position_transition(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = TradingHandoffConfig(
        recommendation_config=_recommendation_config(),
        approved_comparison_slot="best_ensemble",
        current_weights={isin: 0.2 for isin, _, _ in _FIVE_LISTINGS},
    )

    handoff = write_multivariate_trading_handoff(paths, selected_rows, config=config)

    assert handoff["transition_rows"] is not None
    assert len(handoff["transition_rows"]) == 5
    for row in handoff["transition_rows"]:
        assert row["delta"] == pytest.approx(row["target_weight"] - row["current_weight"])


def test_write_multivariate_trading_handoff_writes_deterministic_flatex_export(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    prices = {isin: 100.0 for isin, _, _ in _FIVE_LISTINGS}
    config = TradingHandoffConfig(
        recommendation_config=_recommendation_config(),
        approved_comparison_slot="best_ensemble",
        current_prices=prices,
        portfolio_value=10_000.0,
    )

    handoff = write_multivariate_trading_handoff(paths, selected_rows, config=config)

    assert handoff["flatex_export_path"] is not None
    export_path = Path(handoff["flatex_export_path"])
    assert export_path.exists()
    assert handoff["flatex_order_count"] > 0
    expected_path = paths.trading_flatex_export("prod-eval", handoff["approved_candidate_id"])
    assert export_path == expected_path


def test_write_multivariate_trading_handoff_is_deterministic(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = TradingHandoffConfig(
        recommendation_config=_recommendation_config(),
        approved_comparison_slot="best_ensemble",
        current_weights={isin: 0.2 for isin, _, _ in _FIVE_LISTINGS},
    )

    first = write_multivariate_trading_handoff(paths, selected_rows, config=config)
    second = write_multivariate_trading_handoff(paths, selected_rows, config=config)

    assert first["handoff_id"] == second["handoff_id"]
    assert first == second


def test_write_multivariate_trading_handoff_detects_drift_over_threshold(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = TradingHandoffConfig(
        recommendation_config=_recommendation_config(),
        approved_comparison_slot="best_ensemble",
        current_weights={"IE1": 1.0},
        drift_threshold=0.01,
    )

    handoff = write_multivariate_trading_handoff(paths, selected_rows, config=config)

    assert handoff["monitoring_statuses"]["drift_status"] == "drift_detected"


def test_write_multivariate_trading_handoff_reports_within_tolerance_without_current_weights(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = TradingHandoffConfig(
        recommendation_config=_recommendation_config(),
        approved_comparison_slot="best_ensemble",
    )

    handoff = write_multivariate_trading_handoff(paths, selected_rows, config=config)

    assert handoff["monitoring_statuses"]["drift_status"] == "within_tolerance"


def test_write_multivariate_trading_handoff_does_not_write_duplicate_flatex_rows_on_rerun(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    prices = {isin: 100.0 for isin, _, _ in _FIVE_LISTINGS}
    config = TradingHandoffConfig(
        recommendation_config=_recommendation_config(),
        approved_comparison_slot="best_ensemble",
        current_prices=prices,
        portfolio_value=10_000.0,
    )

    write_multivariate_trading_handoff(paths, selected_rows, config=config)
    handoff = write_multivariate_trading_handoff(paths, selected_rows, config=config)

    export_path = Path(handoff["flatex_export_path"])
    with export_path.open(newline="", encoding="utf-8") as handle:
        line_count = sum(1 for _ in csv.reader(handle)) - 1  # minus header
    assert line_count == 5
