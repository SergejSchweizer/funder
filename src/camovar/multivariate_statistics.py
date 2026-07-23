"""Multivariate portfolio statistics for selected ISIN listings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from camovar.bivariate_statistics import write_bivariate_statistics
from camovar.calculation_status import UNAVAILABLE
from camovar.contract_versioning import stable_contract_id
from camovar.evaluation import (
    build_asset_metrics,
    build_return_matrix,
    equal_weight_portfolio,
    write_efficient_frontier,
    write_portfolio_evaluation,
    write_rebalance_simulation,
    write_tail_risk_evaluation,
    write_walk_forward_backtest,
)
from camovar.gold import build_returns, write_gold_inputs
from camovar.gold_pair_stats import DEFAULT_BUCKET_COUNT, sort_pair_rows
from camovar.paths import LakePaths
from camovar.portfolio import (
    PortfolioConstraints,
    covariance_map,
    listing_keys,
    listing_rows,
    read_covariances,
    require_complete_covariance,
    write_hierarchical_risk_parity,
    write_maximum_diversification,
    write_optimized_weights,
)
from camovar.profiles import (
    PROFILE_NAMES,
    balanced_profile,
    defensive_profile,
    evaluate_profile_candidate,
    growth_profile,
    income_profile,
    write_profile_candidate,
)
from camovar.recommendation import (
    CandidateReport,
    build_candidate_report,
    build_recommendation_report,
)
from camovar.return_quality import evaluate_quote_quality
from camovar.risk_model import estimate_risk_model
from camovar.scorecard import ScorecardCandidate, build_model_comparison_scorecard
from camovar.silver import read_silver_quotes
from camovar.statistics_views import DEFAULT_BIVARIATE_VERSION, read_selection_statistics
from camovar.stress import (
    block_bootstrap_scenarios,
    build_sensitivity_summary,
    historical_stress_scenario,
)
from camovar.table_io import JsonRow, read_json, read_rows, write_json, write_rows
from camovar.trading import prepare_flatex_orders, write_flatex_orders
from camovar.univariate_statistics import write_univariate_statistics

DEFAULT_OBJECTIVES: tuple[str, ...] = (
    "equal_weight",
    "minimum_variance",
    "maximum_sharpe",
    "risk_parity",
)


@dataclass(frozen=True)
class MultivariateStatisticsConfig:
    """Configuration for one multivariate statistics run."""

    evaluation_id: str = "multivariate-latest"
    portfolio_id_prefix: str = "multivariate"
    confidence_level: float = 0.95
    grid_step: float = 0.1
    train_window: int = 2
    test_window: int = 1
    walk_forward_profile: str = "development"
    rebalance_schedule: str = "monthly"
    transaction_cost_rate: float = 0.0
    drift_threshold: float | None = None
    constraints: PortfolioConstraints = PortfolioConstraints(max_weight=1.0)
    objectives: tuple[str, ...] = DEFAULT_OBJECTIVES
    frontier_target_returns: tuple[float, ...] = (-0.01, 0.0, 0.01)
    concurrency: int | None = None
    selection_id: str | None = None
    selection_source_module: str = "univariate_filter"
    use_selection_statistics_cache: bool = False
    bivariate_version: str = DEFAULT_BIVARIATE_VERSION
    bivariate_bucket_count: int = DEFAULT_BUCKET_COUNT


def write_multivariate_statistics(
    paths: LakePaths,
    selected_rows: Sequence[Mapping[str, Any]],
    *,
    config: MultivariateStatisticsConfig | None = None,
) -> dict[str, Any]:
    """Write portfolio analytics for the selected listings.

    The selected rows are expected to come from Univariate Filter membership.
    This function intentionally filters Silver quotes first, then builds all
    downstream Gold, Evaluation, and Portfolio artifacts from that pinned set.
    """
    resolved_config = config or MultivariateStatisticsConfig()
    quotes = _filter_quotes_to_selection(read_silver_quotes(paths), selected_rows)
    cache_summary: JsonRow = {"cache_status": "disabled"}
    if resolved_config.use_selection_statistics_cache:
        returns, cache_summary = _prepare_selection_cached_inputs(
            paths, selected_rows, quotes, resolved_config
        )
        portfolio_run_id = _portfolio_run_id(resolved_config, cache_summary)
        reused_summary = _read_reusable_portfolio_summary(paths, portfolio_run_id)
        if reused_summary is not None:
            return reused_summary
    else:
        returns, _correlations, _covariances, _features = write_gold_inputs(
            paths,
            quotes,
            concurrency=resolved_config.concurrency,
        )
        portfolio_run_id = ""
    matrix = build_return_matrix(returns, resolved_config.evaluation_id)
    asset_metrics = build_asset_metrics(
        matrix,
        resolved_config.evaluation_id,
        confidence_level=resolved_config.confidence_level,
    )
    write_rows(paths.gold_return_matrix(resolved_config.evaluation_id), matrix)
    write_rows(paths.gold_asset_metrics(resolved_config.evaluation_id), asset_metrics)

    if not matrix:
        summary = {
            "asset_metric_rows": len(asset_metrics),
            "backtest_rows": 0,
            "backtest_weight_rows": 0,
            "evaluation_id": resolved_config.evaluation_id,
            "frontier_points": 0,
            "frontier_weight_rows": 0,
            "hrp_cluster_rows": 0,
            "hrp_linkage_rows": 0,
            "matrix_rows": 0,
            "maximum_diversification_metric_rows": 0,
            "optimized_weight_rows": 0,
            "portfolio_count": 0,
            "quote_rows": len(quotes),
            "return_rows": len(returns),
            "selected_listing_count": len(
                {
                    (str(row["isin"]), str(row["exchange"]), str(row["code"]))
                    for row in selected_rows
                }
            ),
        }
        summary.update(cache_summary)
        if portfolio_run_id:
            _write_portfolio_cache_manifest(paths, portfolio_run_id, summary, resolved_config)
        return summary

    written_portfolios = 0
    equal_weight_id = _portfolio_id(resolved_config, "equal_weight")
    if matrix:
        equal_weights = equal_weight_portfolio(matrix)
        _write_portfolio_bundle(
            paths,
            evaluation_id=resolved_config.evaluation_id,
            portfolio_id=equal_weight_id,
            objective="equal_weight",
            weights=equal_weights,
            confidence_level=resolved_config.confidence_level,
            rebalance_schedule=resolved_config.rebalance_schedule,
            transaction_cost_rate=resolved_config.transaction_cost_rate,
            drift_threshold=resolved_config.drift_threshold,
        )
        written_portfolios += 1

    optimized_weight_rows: list[JsonRow] = []
    for objective in resolved_config.objectives:
        if objective == "equal_weight":
            continue
        rows = write_optimized_weights(
            paths,
            evaluation_id=resolved_config.evaluation_id,
            objective=objective,
            portfolio_id=_portfolio_id(resolved_config, objective),
            constraints=resolved_config.constraints,
            grid_step=resolved_config.grid_step,
        )
        optimized_weight_rows.extend(rows)
        _write_portfolio_bundle(
            paths,
            evaluation_id=resolved_config.evaluation_id,
            portfolio_id=_portfolio_id(resolved_config, objective),
            objective=objective,
            weights=_weights_from_rows(rows),
            confidence_level=resolved_config.confidence_level,
            rebalance_schedule=resolved_config.rebalance_schedule,
            transaction_cost_rate=resolved_config.transaction_cost_rate,
            drift_threshold=resolved_config.drift_threshold,
        )
        written_portfolios += 1

    hrp_weights, hrp_clusters, hrp_linkage = write_hierarchical_risk_parity(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        portfolio_id=_portfolio_id(resolved_config, "hierarchical_risk_parity"),
        constraints=resolved_config.constraints,
    )
    _write_portfolio_bundle(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        portfolio_id=_portfolio_id(resolved_config, "hierarchical_risk_parity"),
        objective="hierarchical_risk_parity",
        weights=_weights_from_rows(hrp_weights),
        confidence_level=resolved_config.confidence_level,
        rebalance_schedule=resolved_config.rebalance_schedule,
        transaction_cost_rate=resolved_config.transaction_cost_rate,
        drift_threshold=resolved_config.drift_threshold,
    )
    written_portfolios += 1

    max_div_weights, max_div_metrics = write_maximum_diversification(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        portfolio_id=_portfolio_id(resolved_config, "maximum_diversification"),
        constraints=resolved_config.constraints,
        grid_step=resolved_config.grid_step,
    )
    _write_portfolio_bundle(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        portfolio_id=_portfolio_id(resolved_config, "maximum_diversification"),
        objective="maximum_diversification",
        weights=_weights_from_rows(max_div_weights),
        confidence_level=resolved_config.confidence_level,
        rebalance_schedule=resolved_config.rebalance_schedule,
        transaction_cost_rate=resolved_config.transaction_cost_rate,
        drift_threshold=resolved_config.drift_threshold,
    )
    written_portfolios += 1

    frontier_points, frontier_weights = write_efficient_frontier(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        constraints=resolved_config.constraints,
        target_returns=resolved_config.frontier_target_returns,
        grid_step=resolved_config.grid_step,
    )
    backtests, backtest_weights = write_walk_forward_backtest(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        run_id=f"{resolved_config.evaluation_id}-walk-forward",
        objective="minimum_variance",
        constraints=resolved_config.constraints,
        train_window=resolved_config.train_window,
        test_window=resolved_config.test_window,
        grid_step=resolved_config.grid_step,
        profile=resolved_config.walk_forward_profile,
        transaction_cost_rate=resolved_config.transaction_cost_rate,
    )
    summary = {
        "asset_metric_rows": len(asset_metrics),
        "backtest_rows": len(backtests),
        "backtest_weight_rows": len(backtest_weights),
        "evaluation_id": resolved_config.evaluation_id,
        "frontier_points": len(frontier_points),
        "frontier_weight_rows": len(frontier_weights),
        "hrp_cluster_rows": len(hrp_clusters),
        "hrp_linkage_rows": len(hrp_linkage),
        "matrix_rows": len(matrix),
        "maximum_diversification_metric_rows": len(max_div_metrics),
        "optimized_weight_rows": len(optimized_weight_rows)
        + len(hrp_weights)
        + len(max_div_weights),
        "portfolio_count": written_portfolios,
        "quote_rows": len(quotes),
        "return_rows": len(returns),
        "selected_listing_count": len(
            {(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in selected_rows}
        ),
    }
    summary.update(cache_summary)
    if portfolio_run_id:
        _write_portfolio_cache_manifest(paths, portfolio_run_id, summary, resolved_config)
    return summary


def _prepare_selection_cached_inputs(
    paths: LakePaths,
    selected_rows: Sequence[Mapping[str, Any]],
    quotes: Sequence[Mapping[str, Any]],
    config: MultivariateStatisticsConfig,
) -> tuple[list[JsonRow], JsonRow]:
    if config.selection_id is None:
        raise ValueError("selection_id is required when use_selection_statistics_cache=True")

    _write_selected_returns_cache(paths, quotes)
    write_univariate_statistics(
        paths,
        quotes,
        confidence_level=config.confidence_level,
        concurrency=config.concurrency,
    )
    returns = _read_selected_returns(paths, selected_rows)
    write_bivariate_statistics(
        paths,
        returns,
        version=config.bivariate_version,
        bucket_count=config.bivariate_bucket_count,
        concurrency=config.concurrency,
    )
    univariate_rows, bivariate_rows, view = read_selection_statistics(
        paths,
        selection_id=config.selection_id,
        source_module=config.selection_source_module,
        listing_rows=selected_rows,
        bivariate_version=config.bivariate_version,
        bivariate_bucket_count=config.bivariate_bucket_count,
    )
    _write_selected_pair_inputs(paths, univariate_rows, bivariate_rows)
    return returns, {
        "cache_status": "prepared",
        "selection_statistics_view_id": view["view_id"],
        "selection_statistics_listing_count": view["listing_count"],
        "selection_statistics_pair_count": view["present_bivariate_pair_count"],
    }


def _write_selected_returns_cache(paths: LakePaths, quotes: Sequence[Mapping[str, Any]]) -> None:
    by_listing: dict[tuple[str, str, str], list[JsonRow]] = {}
    for row in build_returns(quotes):
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, []).append(dict(row))
    for isin, exchange, _code in sorted(by_listing):
        rows = by_listing[(isin, exchange, _code)]
        _write_rows_if_changed(paths.gold_returns(exchange, isin), rows)


def _read_selected_returns(
    paths: LakePaths, selected_rows: Sequence[Mapping[str, Any]]
) -> list[JsonRow]:
    rows: list[JsonRow] = []
    for isin, exchange, _code in _selected_listing_keys(selected_rows):
        rows.extend(read_rows(paths.gold_returns(exchange, isin)))
    selected = set(_selected_listing_keys(selected_rows))
    return [
        row
        for row in rows
        if (str(row["isin"]), str(row["exchange"]), str(row["code"])) in selected
    ]


def _write_selected_pair_inputs(
    paths: LakePaths,
    univariate_rows: Sequence[Mapping[str, Any]],
    bivariate_rows: Sequence[Mapping[str, Any]],
) -> None:
    covariances: list[JsonRow] = []
    correlations: list[JsonRow] = []
    for row in univariate_rows:
        listing = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        variance = float(row["daily_log_return_std"]) ** 2
        covariances.append(_pair_metric_row(listing, listing, "covariance", variance))
        correlations.append(_pair_metric_row(listing, listing, "correlation", 1.0))
    for row in bivariate_rows:
        left = (str(row["left_isin"]), str(row["left_exchange"]), str(row["left_code"]))
        right = (str(row["right_isin"]), str(row["right_exchange"]), str(row["right_code"]))
        covariance = float(row["covariance"])
        correlation = float(row["pearson_correlation"])
        covariances.extend(
            (
                _pair_metric_row(left, right, "covariance", covariance),
                _pair_metric_row(right, left, "covariance", covariance),
            )
        )
        correlations.extend(
            (
                _pair_metric_row(left, right, "correlation", correlation),
                _pair_metric_row(right, left, "correlation", correlation),
            )
        )

    for isin, exchange, _code in _selected_listing_keys(univariate_rows):
        _write_rows_if_changed(
            paths.gold_covariance(exchange, isin),
            [row for row in sort_pair_rows(covariances) if str(row["left_isin"]) == isin],
        )
        _write_rows_if_changed(
            paths.gold_correlation(exchange, isin),
            [row for row in sort_pair_rows(correlations) if str(row["left_isin"]) == isin],
        )


def _pair_metric_row(
    left: tuple[str, str, str], right: tuple[str, str, str], field: str, value: float
) -> JsonRow:
    return {
        "left_isin": left[0],
        "left_exchange": left[1],
        "left_code": left[2],
        "right_isin": right[0],
        "right_exchange": right[1],
        "right_code": right[2],
        field: value,
    }


def _selected_listing_keys(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    return sorted({(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in rows})


def _write_rows_if_changed(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    normalized = [dict(row) for row in rows]
    if read_rows(path) == normalized:
        return
    write_rows(path, normalized)


def _portfolio_run_id(
    config: MultivariateStatisticsConfig, cache_summary: Mapping[str, Any]
) -> str:
    return stable_contract_id(
        "multivariate_selection_portfolio_run",
        {
            "evaluation_id": config.evaluation_id,
            "portfolio_id_prefix": config.portfolio_id_prefix,
            "confidence_level": config.confidence_level,
            "grid_step": config.grid_step,
            "train_window": config.train_window,
            "test_window": config.test_window,
            "walk_forward_profile": config.walk_forward_profile,
            "rebalance_schedule": config.rebalance_schedule,
            "transaction_cost_rate": config.transaction_cost_rate,
            "drift_threshold": config.drift_threshold,
            "constraints": config.constraints.as_dict(),
            "objectives": config.objectives,
            "frontier_target_returns": config.frontier_target_returns,
            "selection_id": config.selection_id,
            "selection_source_module": config.selection_source_module,
            "selection_statistics_view_id": cache_summary.get("selection_statistics_view_id"),
            "bivariate_version": config.bivariate_version,
        },
    )


def _portfolio_cache_manifest_path(paths: LakePaths, portfolio_run_id: str) -> Path:
    return paths.job_manifest("multivariate-statistics-cache", portfolio_run_id)


def _read_reusable_portfolio_summary(paths: LakePaths, portfolio_run_id: str) -> JsonRow | None:
    manifest_path = _portfolio_cache_manifest_path(paths, portfolio_run_id)
    if not manifest_path.exists():
        return None
    manifest = read_json(manifest_path)
    summary_object: object = manifest.get("summary")
    artifact_path_objects: object = manifest.get("artifact_paths")
    if not isinstance(summary_object, dict) or not isinstance(artifact_path_objects, list):
        return None
    summary = cast(dict[str, Any], summary_object)
    artifact_paths = cast(list[object], artifact_path_objects)
    if not all(Path(str(path)).exists() for path in artifact_paths):
        return None
    reused = dict(summary)
    reused["cache_status"] = "portfolio_reused"
    reused["portfolio_run_id"] = portfolio_run_id
    return reused


def _write_portfolio_cache_manifest(
    paths: LakePaths,
    portfolio_run_id: str,
    summary: Mapping[str, Any],
    config: MultivariateStatisticsConfig,
) -> None:
    evaluation_id = str(summary["evaluation_id"])
    artifact_paths = [
        paths.gold_return_matrix(evaluation_id),
        paths.gold_asset_metrics(evaluation_id),
        paths.gold_portfolio_returns(evaluation_id),
        paths.gold_portfolio_metrics(evaluation_id),
        paths.gold_frontier_points(evaluation_id),
        paths.gold_frontier_weights(evaluation_id),
        paths.gold_backtests(f"{evaluation_id}-walk-forward"),
        paths.gold_backtest_weights(f"{evaluation_id}-walk-forward"),
        paths.gold_rebalance_events(f"{evaluation_id}-rebalance-{config.rebalance_schedule}"),
        paths.gold_rebalance_weights(f"{evaluation_id}-rebalance-{config.rebalance_schedule}"),
        paths.gold_tail_risk(f"{evaluation_id}-tail-risk"),
        paths.gold_hrp_clusters(evaluation_id),
        paths.gold_hrp_linkage(evaluation_id),
        paths.gold_diversification_metrics(evaluation_id),
    ]
    artifact_paths.extend(
        paths.gold_optimized_weights(objective, evaluation_id)
        for objective in (
            *tuple(item for item in config.objectives if item != "equal_weight"),
            "hierarchical_risk_parity",
            "maximum_diversification",
        )
    )
    payload = {
        "status": "completed",
        "portfolio_run_id": portfolio_run_id,
        "summary": {**dict(summary), "portfolio_run_id": portfolio_run_id},
        "artifact_paths": [str(path) for path in artifact_paths if path.exists()],
    }
    write_json(_portfolio_cache_manifest_path(paths, portfolio_run_id), payload)


def _write_portfolio_bundle(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    objective: str,
    weights: Mapping[str, float],
    confidence_level: float,
    rebalance_schedule: str,
    transaction_cost_rate: float,
    drift_threshold: float | None,
) -> None:
    write_portfolio_evaluation(
        paths,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
        weights=weights,
        objective=objective,
    )
    write_tail_risk_evaluation(
        paths,
        evaluation_id=evaluation_id,
        run_id=f"{evaluation_id}-tail-risk",
        portfolio_id=portfolio_id,
        weights=weights,
        confidence_level=confidence_level,
    )
    write_rebalance_simulation(
        paths,
        evaluation_id=evaluation_id,
        run_id=f"{evaluation_id}-rebalance-{rebalance_schedule}",
        portfolio_id=portfolio_id,
        target_weights=weights,
        schedule=rebalance_schedule,
        transaction_cost_rate=transaction_cost_rate,
        drift_threshold=drift_threshold,
    )


def _filter_quotes_to_selection(
    quotes: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
) -> list[JsonRow]:
    selected = {(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in selected_rows}
    return [
        dict(row)
        for row in quotes
        if (str(row["isin"]), str(row["exchange"]), str(row["code"])) in selected
    ]


def _portfolio_id(config: MultivariateStatisticsConfig, objective: str) -> str:
    return f"{config.portfolio_id_prefix}-{objective.replace('_', '-')}"


def _weights_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    return {str(row["isin"]): float(row["weight"]) for row in rows}


@dataclass(frozen=True)
class ProductionMultivariateConfig:
    """Configuration for one production-mode multivariate statistics run.

    Unlike `MultivariateStatisticsConfig` (deterministic baseline objectives),
    this config drives `write_production_multivariate_statistics`, which
    requires a passing production data-quality gate, production-eligible risk-
    model diagnostics, and feasible profile candidates with a baseline
    comparison before writing anything.
    """

    evaluation_id: str = "multivariate-production"
    portfolio_id_prefix: str = "multivariate-production"
    confidence_level: float = 0.95
    constraints: PortfolioConstraints = PortfolioConstraints(max_weight=0.25)
    risk_model_estimator: str = "ledoit_wolf"
    profile_names: tuple[str, ...] = PROFILE_NAMES
    concurrency: int | None = None


_PROFILE_BUILDERS: dict[str, Any] = {
    "defensive": defensive_profile,
    "balanced": balanced_profile,
    "income": income_profile,
    "growth": growth_profile,
}


def write_production_multivariate_statistics(
    paths: LakePaths,
    selected_rows: Sequence[Mapping[str, Any]],
    *,
    config: ProductionMultivariateConfig | None = None,
) -> JsonRow:
    """Write production-mode portfolio profile analytics for the selected listings.

    Refuses (raises `ValueError`) rather than silently falling back to a
    baseline when: any selected listing's quote history fails the production
    data-quality gate, there is insufficient aligned return history, the
    risk-model estimate is not production eligible, a requested profile
    candidate is infeasible, or a profile candidate is missing its baseline
    comparison. See BACKLOG.md's PR70 acceptance criteria.
    """
    resolved_config = config or ProductionMultivariateConfig()
    unknown_profiles = set(resolved_config.profile_names) - set(PROFILE_NAMES)
    if unknown_profiles:
        raise ValueError(f"unknown profile_names: {sorted(unknown_profiles)}")

    quotes = _filter_quotes_to_selection(read_silver_quotes(paths), selected_rows)
    quality_by_listing = _quote_quality_by_listing(quotes)
    failing_quality = sorted(
        f"{isin}/{exchange}/{code}:{quality['data_quality_reason']}"
        for (isin, exchange, code), quality in quality_by_listing.items()
        if not quality["production_eligible"]
    )
    if failing_quality:
        raise ValueError("production_data_quality_gate_failed: " + ", ".join(failing_quality))

    returns, _correlations, _covariances, _features = write_gold_inputs(
        paths, quotes, concurrency=resolved_config.concurrency
    )
    matrix = build_return_matrix(returns, resolved_config.evaluation_id)
    if not matrix:
        raise ValueError("insufficient_history: no aligned return matrix rows for the selection")
    write_rows(paths.gold_return_matrix(resolved_config.evaluation_id), matrix)

    listings = listing_rows(matrix)
    ordered = listing_keys(listings)
    covariance_rows = read_covariances(paths, listings)
    covariances = covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)

    risk_model = estimate_risk_model(
        matrix, listings=ordered, estimator=resolved_config.risk_model_estimator
    )
    if not risk_model.diagnostics.production_eligible:
        raise ValueError(
            "risk_model_not_production_eligible: "
            + ", ".join(risk_model.diagnostics.availability_reasons)
        )

    profile_candidates: dict[str, JsonRow] = {}
    written_weight_rows = 0
    for profile_name in resolved_config.profile_names:
        profile = _PROFILE_BUILDERS[profile_name](max_weight=resolved_config.constraints.max_weight)
        candidate = evaluate_profile_candidate(profile, listings, covariance_rows, matrix)
        if candidate["status"] != "feasible":
            raise ValueError(f"profile {profile_name!r} is infeasible: {candidate['reasons']}")
        if not candidate["baseline_comparison"]:
            raise ValueError(f"profile {profile_name!r} is missing a baseline comparison")
        profile_candidates[profile_name] = candidate
        weight_rows = write_profile_candidate(
            paths,
            evaluation_id=resolved_config.evaluation_id,
            portfolio_id=f"{resolved_config.portfolio_id_prefix}-{profile_name}",
            profile=profile,
        )
        written_weight_rows += len(weight_rows)

    production_adapter_id = stable_contract_id(
        "multivariate_production_adapter",
        {
            "selection_membership": sorted(str(isin) for isin, _, _ in ordered),
            "quality_policy": "return_quality.evaluate_quote_quality",
            "risk_model_id": risk_model.diagnostics.estimator,
            "risk_model_algorithm_version": risk_model.diagnostics.algorithm_version,
            "optimizer_ids": sorted(resolved_config.profile_names),
            "profile_version": [
                profile_candidates[name]["profile_version"] for name in sorted(profile_candidates)
            ],
            "constraint_version": resolved_config.constraints.as_dict(),
        },
    )

    return {
        "production_adapter_id": production_adapter_id,
        "evaluation_id": resolved_config.evaluation_id,
        "selected_listing_count": len(ordered),
        "matrix_rows": len(matrix),
        "risk_model_estimator": risk_model.diagnostics.estimator,
        "risk_model_production_eligible": risk_model.diagnostics.production_eligible,
        "profile_names": list(resolved_config.profile_names),
        "profile_candidate_ids": {
            name: candidate["profile_candidate_id"]
            for name, candidate in profile_candidates.items()
        },
        "weight_rows": written_weight_rows,
        "production_eligible": True,
    }


# Profiles whose single underlying objective is compatible with
# camovar.scorecard's walk-forward comparison (optimize_portfolio's
# GRID_OBJECTIVES/solver-backed objectives). Defensive (shrinkage Minimum
# Variance), Income (Minimum CVaR), and Balanced (a multi-objective
# ensemble) are not single walk-forward-compatible objectives today; their
# scorecard traceability is reported as unavailable (None) rather than
# fabricated or silently skipped.
_SCORECARD_COMPATIBLE_OBJECTIVES: dict[str, str] = {"growth": "equal_risk_contribution"}


@dataclass(frozen=True)
class MultivariateRecommendationConfig:
    """Configuration for one PR71 recommendation run over a production adapter result."""

    production_config: ProductionMultivariateConfig = ProductionMultivariateConfig()
    scorecard_train_window: int = 20
    scorecard_test_window: int = 10
    scorecard_mode: str = "rolling"
    scorecard_profile: str = "development"
    stress_window_length: int = 10
    stress_block_length: int = 5
    stress_scenario_count: int = 5
    stress_seed: int = 1
    current_weights: Mapping[str, float] | None = None


def write_multivariate_recommendation(
    paths: LakePaths,
    selected_rows: Sequence[Mapping[str, Any]],
    *,
    config: MultivariateRecommendationConfig | None = None,
) -> JsonRow:
    """Produce an explainable recommendation report for the selected membership.

    Runs the PR70 production adapter first (which enforces every production
    gate and writes profile weight rows), then adds PR64 walk-forward
    scorecard traceability (where a profile's objective is scorecard
    compatible) and PR65 stress/sensitivity summaries for every profile
    candidate, and finally compares candidates via PR66's
    `camovar.recommendation` into one deterministic report.

    Income quality, sustainable income, NAV erosion, and income efficiency
    always report `unavailable`: they require the after-tax cash-flow stack
    (PR62E), which remains open, and are never computed from an invented
    figure.
    """
    resolved_config = config or MultivariateRecommendationConfig()
    production_config = resolved_config.production_config
    write_production_multivariate_statistics(paths, selected_rows, config=production_config)

    matrix = read_rows(paths.gold_return_matrix(production_config.evaluation_id))
    listings = listing_rows(matrix)
    covariance_rows = read_covariances(paths, listings)

    candidate_reports: list[CandidateReport] = []
    for profile_name in production_config.profile_names:
        max_weight = production_config.constraints.max_weight
        profile = _PROFILE_BUILDERS[profile_name](max_weight=max_weight)
        candidate = evaluate_profile_candidate(profile, listings, covariance_rows, matrix)

        scorecard_row: JsonRow | None = None
        objective = _SCORECARD_COMPATIBLE_OBJECTIVES.get(profile_name)
        if objective is not None:
            scorecard_rows = build_model_comparison_scorecard(
                matrix,
                run_id=f"{production_config.evaluation_id}-scorecard",
                evaluation_id=production_config.evaluation_id,
                candidates=[ScorecardCandidate(profile_name, objective, profile.constraints)],
                train_window=resolved_config.scorecard_train_window,
                test_window=resolved_config.scorecard_test_window,
                mode=resolved_config.scorecard_mode,
                profile=resolved_config.scorecard_profile,
            )
            scorecard_row = scorecard_rows[0]

        sensitivity_summary: JsonRow | None = None
        if candidate["weights"]:
            scenario_results = [
                historical_stress_scenario(
                    matrix,
                    candidate["weights"],
                    candidate_id=profile_name,
                    window_length=resolved_config.stress_window_length,
                ),
                *block_bootstrap_scenarios(
                    matrix,
                    candidate["weights"],
                    candidate_id=profile_name,
                    block_length=resolved_config.stress_block_length,
                    scenario_count=resolved_config.stress_scenario_count,
                    seed=resolved_config.stress_seed,
                ),
            ]
            sensitivity_summary = build_sensitivity_summary(scenario_results)

        candidate_reports.append(
            build_candidate_report(
                candidate,
                scorecard_row=scorecard_row,
                sensitivity_summary=sensitivity_summary,
                current_weights=resolved_config.current_weights,
            )
        )

    return build_recommendation_report(
        evaluation_id=production_config.evaluation_id,
        candidate_reports=candidate_reports,
        current_weights=resolved_config.current_weights,
    )


def _quote_quality_by_listing(
    quotes: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], JsonRow]:
    by_listing: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in quotes:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, []).append(row)
    return {key: evaluate_quote_quality(rows) for key, rows in by_listing.items()}


@dataclass(frozen=True)
class TradingHandoffConfig:
    """Configuration for one PR72 trading/monitoring handoff.

    `approved_comparison_slot` (e.g. `"best_ensemble"`) must be explicitly
    supplied and resolve to an included candidate; by default (`None`) the
    handoff rejects trade preparation entirely -- this module never decides
    which candidate to trade on behalf of the user.
    """

    recommendation_config: MultivariateRecommendationConfig = MultivariateRecommendationConfig()
    approved_comparison_slot: str | None = None
    current_weights: Mapping[str, float] | None = None
    current_prices: Mapping[str, float] | None = None
    portfolio_value: float = 0.0
    cash_buffer: float = 0.0
    drift_threshold: float = 0.05
    monitoring_policy_id: str = "default-monitoring-v1"
    report_template_version: int = 1


def write_multivariate_trading_handoff(
    paths: LakePaths,
    selected_rows: Sequence[Mapping[str, Any]],
    *,
    config: TradingHandoffConfig | None = None,
) -> JsonRow:
    """Produce a trading/monitoring handoff for an approved recommendation slot.

    Rejects (raises `ValueError`) by default when no `approved_comparison_slot`
    is supplied or it has no included candidate -- this module never decides
    broker execution or infers approval. When approved, it includes
    current-versus-target weight differences (when `current_weights` is
    supplied), links a deterministic Flatex export path (when
    `current_prices` and a positive `portfolio_value` are supplied), and
    reports monitoring-ready drift/risk/stale-data statuses. Distribution-cut
    and NAV-erosion statuses always report `unavailable`: they require the
    after-tax cash-flow stack (PR62E), which remains open, and are never
    computed from an invented figure. Never alters current positions or
    decides broker execution.
    """
    resolved_config = config or TradingHandoffConfig()
    recommendation_config = resolved_config.recommendation_config
    recommendation = write_multivariate_recommendation(
        paths, selected_rows, config=recommendation_config
    )

    approved_candidate_id = (
        recommendation["comparisons"].get(resolved_config.approved_comparison_slot)
        if resolved_config.approved_comparison_slot is not None
        else None
    )
    if not approved_candidate_id:
        raise ValueError(
            "recommendation_not_approved: no approved_comparison_slot was supplied, or "
            f"{resolved_config.approved_comparison_slot!r} has no included candidate; "
            "trade preparation requires an explicit, approved recommendation slot"
        )
    approved = next(
        candidate
        for candidate in recommendation["candidates"]
        if candidate["candidate_id"] == approved_candidate_id
    )
    target_weights: dict[str, float] = dict(approved["weights"])

    transition_rows: list[JsonRow] | None = None
    if resolved_config.current_weights is not None:
        isins = set(resolved_config.current_weights) | set(target_weights)
        transition_rows = [
            {
                "isin": isin,
                "current_weight": resolved_config.current_weights.get(isin, 0.0),
                "target_weight": target_weights.get(isin, 0.0),
                "delta": target_weights.get(isin, 0.0)
                - resolved_config.current_weights.get(isin, 0.0),
            }
            for isin in sorted(isins)
        ]

    quotes = _filter_quotes_to_selection(read_silver_quotes(paths), selected_rows)
    quality_by_listing = _quote_quality_by_listing(quotes)
    stale_data_detected = any(
        quality["stale_price_detected"] for quality in quality_by_listing.values()
    )

    flatex_export_path = None
    flatex_order_count = 0
    if resolved_config.current_prices is not None and resolved_config.portfolio_value > 0:
        currency_by_isin = {str(row["isin"]): str(row["currency"]) for row in quotes}
        listing_meta = {str(row["isin"]): row for row in selected_rows}
        targets = [
            {
                "isin": isin,
                "code": listing_meta[isin]["code"],
                "exchange": listing_meta[isin]["exchange"],
                "currency": currency_by_isin.get(isin, ""),
                "weight": weight,
                "price": resolved_config.current_prices[isin],
            }
            for isin, weight in target_weights.items()
            if isin in resolved_config.current_prices and isin in listing_meta
        ]
        orders = prepare_flatex_orders(
            targets,
            portfolio_value=resolved_config.portfolio_value,
            cash_buffer=resolved_config.cash_buffer,
        )
        flatex_export_path = paths.trading_flatex_export(
            recommendation["evaluation_id"], approved_candidate_id
        )
        write_flatex_orders(flatex_export_path, orders)
        flatex_order_count = len(orders)

    approved_profile = _PROFILE_BUILDERS[approved["profile_name"]](
        max_weight=recommendation_config.production_config.constraints.max_weight
    )
    risk_limit_max_cvar = approved_profile.risk_limits.max_cvar
    sensitivity_worst_cvar = approved.get("sensitivity_worst_cvar")
    risk_limit_breach = (
        risk_limit_max_cvar is not None
        and sensitivity_worst_cvar is not None
        and sensitivity_worst_cvar > risk_limit_max_cvar
    )
    drift_detected = transition_rows is not None and any(
        abs(row["delta"]) > resolved_config.drift_threshold for row in transition_rows
    )

    handoff_id = stable_contract_id(
        "multivariate_trading_handoff",
        {
            "recommendation_id": recommendation["recommendation_id"],
            "approved_candidate_id": approved_candidate_id,
            "current_position_snapshot": dict(
                sorted((resolved_config.current_weights or {}).items())
            ),
            "transition_plan": transition_rows or [],
            "monitoring_policy_id": resolved_config.monitoring_policy_id,
            "report_template_version": resolved_config.report_template_version,
        },
    )

    return {
        "handoff_id": handoff_id,
        "recommendation_id": recommendation["recommendation_id"],
        "approved_comparison_slot": resolved_config.approved_comparison_slot,
        "approved_candidate_id": approved_candidate_id,
        "target_weights": target_weights,
        "transition_rows": transition_rows,
        "flatex_export_path": str(flatex_export_path) if flatex_export_path else None,
        "flatex_order_count": flatex_order_count,
        "monitoring_statuses": {
            "drift_status": "drift_detected" if drift_detected else "within_tolerance",
            "risk_status": "risk_limit_breach" if risk_limit_breach else "within_limits",
            "stale_data_status": "stale_data_detected" if stale_data_detected else "ok",
            "distribution_cut_status": UNAVAILABLE,
            "nav_erosion_status": UNAVAILABLE,
        },
        "monitoring_policy_id": resolved_config.monitoring_policy_id,
        "report_template_version": resolved_config.report_template_version,
    }


__all__ = [
    "DEFAULT_OBJECTIVES",
    "MultivariateRecommendationConfig",
    "MultivariateStatisticsConfig",
    "ProductionMultivariateConfig",
    "TradingHandoffConfig",
    "write_multivariate_recommendation",
    "write_multivariate_statistics",
    "write_multivariate_trading_handoff",
    "write_production_multivariate_statistics",
]
