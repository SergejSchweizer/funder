"""Tests for PR71's multivariate income/recommendation outputs."""

from pathlib import Path
from random import Random

import pytest

from camovar.calculation_status import UNAVAILABLE
from camovar.multivariate_statistics import (
    MultivariateRecommendationConfig,
    ProductionMultivariateConfig,
    write_multivariate_recommendation,
)
from camovar.paths import LakePaths
from camovar.portfolio import PortfolioConstraints
from camovar.table_io import write_rows

_OBSERVATION_COUNT = 260


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


def _config() -> MultivariateRecommendationConfig:
    return MultivariateRecommendationConfig(
        production_config=ProductionMultivariateConfig(
            evaluation_id="prod-eval", constraints=PortfolioConstraints(max_weight=0.4)
        )
    )


def test_write_multivariate_recommendation_produces_a_full_report(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)

    report = write_multivariate_recommendation(paths, selected_rows, config=_config())

    assert report["requires_user_approval"] is True
    assert len(report["candidates"]) == 4
    assert not report["excluded_candidates"]
    for candidate in report["candidates"]:
        assert candidate["income_quality"] in {UNAVAILABLE, "not_applicable"}
        assert candidate["cost_quality"] == UNAVAILABLE


def test_write_multivariate_recommendation_scores_growth_via_scorecard(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)

    report = write_multivariate_recommendation(paths, selected_rows, config=_config())

    growth = next(c for c in report["candidates"] if c["profile_name"] == "growth")
    defensive = next(c for c in report["candidates"] if c["profile_name"] == "defensive")
    assert growth["scorecard_rank"] == 1
    assert defensive["scorecard_rank"] is None


def test_write_multivariate_recommendation_reports_sensitivity_for_every_candidate(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)

    report = write_multivariate_recommendation(paths, selected_rows, config=_config())

    for candidate in report["candidates"]:
        assert candidate["sensitivity_worst_drawdown"] is not None
        assert candidate["sensitivity_worst_cvar"] is not None


def test_write_multivariate_recommendation_is_deterministic(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = _config()

    first = write_multivariate_recommendation(paths, selected_rows, config=config)
    second = write_multivariate_recommendation(paths, selected_rows, config=config)

    assert first["recommendation_id"] == second["recommendation_id"]
    assert first == second


def test_write_multivariate_recommendation_includes_current_position_comparison(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = MultivariateRecommendationConfig(
        production_config=ProductionMultivariateConfig(
            evaluation_id="prod-eval", constraints=PortfolioConstraints(max_weight=0.4)
        ),
        current_weights={isin: 0.2 for isin, _, _ in _FIVE_LISTINGS},
    )

    report = write_multivariate_recommendation(paths, selected_rows, config=config)

    assert report["has_current_position_comparison"] is True
    for candidate in report["candidates"]:
        assert candidate["turnover_from_current"] is not None


def test_write_multivariate_recommendation_propagates_production_gate_failures(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS, day_count=10)

    with pytest.raises(ValueError, match="production_data_quality_gate_failed"):
        write_multivariate_recommendation(paths, selected_rows, config=_config())


def test_write_multivariate_recommendation_disclaimer_has_no_guarantee_language(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)

    report = write_multivariate_recommendation(paths, selected_rows, config=_config())

    assert "do not guarantee" in report["disclaimer"].lower()
