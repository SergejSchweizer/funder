"""Tests for PR70's multivariate production portfolio adapter."""

from pathlib import Path
from random import Random

import pytest

from camovar.multivariate_statistics import (
    ProductionMultivariateConfig,
    write_production_multivariate_statistics,
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
_TWO_LISTINGS = [("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB")]


def test_write_production_multivariate_statistics_succeeds_with_valid_data(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = ProductionMultivariateConfig(
        evaluation_id="prod-eval", constraints=PortfolioConstraints(max_weight=0.4)
    )

    summary = write_production_multivariate_statistics(paths, selected_rows, config=config)

    assert summary["production_eligible"] is True
    assert summary["selected_listing_count"] == 5
    assert summary["risk_model_production_eligible"] is True
    assert set(summary["profile_candidate_ids"]) == {"defensive", "balanced", "income", "growth"}
    assert summary["weight_rows"] > 0


def test_write_production_multivariate_statistics_is_deterministic(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = ProductionMultivariateConfig(
        evaluation_id="prod-eval", constraints=PortfolioConstraints(max_weight=0.4)
    )

    first = write_production_multivariate_statistics(paths, selected_rows, config=config)
    second = write_production_multivariate_statistics(paths, selected_rows, config=config)

    assert first["production_adapter_id"] == second["production_adapter_id"]


def test_write_production_multivariate_statistics_rejects_insufficient_history(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _TWO_LISTINGS, day_count=10)
    config = ProductionMultivariateConfig(
        evaluation_id="prod-eval", constraints=PortfolioConstraints(max_weight=1.0)
    )

    with pytest.raises(ValueError, match="production_data_quality_gate_failed"):
        write_production_multivariate_statistics(paths, selected_rows, config=config)


def test_write_production_multivariate_statistics_rejects_invalid_prices(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _TWO_LISTINGS)
    # Corrupt one listing's Silver history with a non-positive price.
    rows = _quote_series("IE1", "XETRA", "AAA", seed=100)
    rows[5] = {**rows[5], "adjusted_close": -1.0}
    write_rows(paths.silver_quote_file("XETRA", "IE1"), rows)
    config = ProductionMultivariateConfig(
        evaluation_id="prod-eval", constraints=PortfolioConstraints(max_weight=1.0)
    )

    with pytest.raises(ValueError, match="production_data_quality_gate_failed"):
        write_production_multivariate_statistics(paths, selected_rows, config=config)


def test_write_production_multivariate_statistics_rejects_infeasible_constraints(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _TWO_LISTINGS)
    # Default max_weight=0.25 with only 2 listings cannot sum to 1 (2*0.25=0.5).
    config = ProductionMultivariateConfig(evaluation_id="prod-eval")

    with pytest.raises(ValueError):
        write_production_multivariate_statistics(paths, selected_rows, config=config)


def test_write_production_multivariate_statistics_rejects_unknown_profile_name(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = ProductionMultivariateConfig(
        evaluation_id="prod-eval",
        constraints=PortfolioConstraints(max_weight=0.4),
        profile_names=("aggressive",),
    )

    with pytest.raises(ValueError, match="unknown profile_names"):
        write_production_multivariate_statistics(paths, selected_rows, config=config)


def test_write_production_multivariate_statistics_rejects_missing_risk_model_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = ProductionMultivariateConfig(
        evaluation_id="prod-eval", constraints=PortfolioConstraints(max_weight=0.4)
    )

    import camovar.multivariate_statistics as module
    from camovar.risk_model import RiskModelDiagnostics, RiskModelResult

    real_estimate_risk_model = module.estimate_risk_model

    def _fake_estimate_risk_model(*args: object, **kwargs: object) -> RiskModelResult:
        real_result = real_estimate_risk_model(*args, **kwargs)  # type: ignore[arg-type]
        blocked_diagnostics = RiskModelDiagnostics(
            **{
                **real_result.diagnostics.__dict__,
                "production_eligible": False,
                "availability_reasons": ("forced_unavailable_for_test",),
            }
        )
        return RiskModelResult(
            listings=real_result.listings,
            covariance=real_result.covariance,
            diagnostics=blocked_diagnostics,
        )

    monkeypatch.setattr(module, "estimate_risk_model", _fake_estimate_risk_model)

    with pytest.raises(ValueError, match="risk_model_not_production_eligible"):
        write_production_multivariate_statistics(paths, selected_rows, config=config)


def test_write_production_multivariate_statistics_rejects_missing_baseline_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _write_selection(paths, _FIVE_LISTINGS)
    config = ProductionMultivariateConfig(
        evaluation_id="prod-eval", constraints=PortfolioConstraints(max_weight=0.4)
    )

    import camovar.multivariate_statistics as module

    real_evaluate = module.evaluate_profile_candidate

    def _fake_evaluate(*args: object, **kwargs: object) -> dict[str, object]:
        candidate = dict(real_evaluate(*args, **kwargs))  # type: ignore[arg-type]
        candidate["baseline_comparison"] = {}
        return candidate

    monkeypatch.setattr(module, "evaluate_profile_candidate", _fake_evaluate)

    with pytest.raises(ValueError, match="missing a baseline comparison"):
        write_production_multivariate_statistics(paths, selected_rows, config=config)
