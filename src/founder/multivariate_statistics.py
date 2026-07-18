"""Multivariate portfolio statistics for selected ISIN listings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from founder.contract_versioning import stable_contract_id
from founder.evaluation import (
    build_asset_metrics,
    build_return_matrix,
    equal_weight_portfolio,
    write_efficient_frontier,
    write_portfolio_evaluation,
    write_rebalance_simulation,
    write_tail_risk_evaluation,
    write_walk_forward_backtest,
)
from founder.gold import write_gold_inputs
from founder.paths import LakePaths
from founder.portfolio import (
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
from founder.profiles import (
    PROFILE_NAMES,
    balanced_profile,
    defensive_profile,
    evaluate_profile_candidate,
    growth_profile,
    income_profile,
    write_profile_candidate,
)
from founder.recommendation import (
    CandidateReport,
    build_candidate_report,
    build_recommendation_report,
)
from founder.return_quality import evaluate_quote_quality
from founder.risk_model import estimate_risk_model
from founder.scorecard import ScorecardCandidate, build_model_comparison_scorecard
from founder.silver import read_silver_quotes
from founder.stress import (
    block_bootstrap_scenarios,
    build_sensitivity_summary,
    historical_stress_scenario,
)
from founder.table_io import JsonRow, read_rows, write_rows

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
    concurrency: int = 2


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
    returns, _correlations, _covariances, _features = write_gold_inputs(
        paths,
        quotes,
        concurrency=resolved_config.concurrency,
    )
    matrix = build_return_matrix(returns, resolved_config.evaluation_id)
    asset_metrics = build_asset_metrics(
        matrix,
        resolved_config.evaluation_id,
        confidence_level=resolved_config.confidence_level,
    )
    write_rows(paths.gold_return_matrix(resolved_config.evaluation_id), matrix)
    write_rows(paths.gold_asset_metrics(resolved_config.evaluation_id), asset_metrics)

    if not matrix:
        return {
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
    return {
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
    concurrency: int = 2


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
# founder.scorecard's walk-forward comparison (optimize_portfolio's
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
    `founder.recommendation` into one deterministic report.

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


__all__ = [
    "DEFAULT_OBJECTIVES",
    "MultivariateRecommendationConfig",
    "MultivariateStatisticsConfig",
    "ProductionMultivariateConfig",
    "write_multivariate_recommendation",
    "write_multivariate_statistics",
    "write_production_multivariate_statistics",
]
