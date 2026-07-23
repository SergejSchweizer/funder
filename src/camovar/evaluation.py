"""Gold evaluation datasets built from Gold return inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any

from camovar.gold import covariance
from camovar.paths import LakePaths
from camovar.portfolio import (
    PortfolioConstraints,
    optimize_portfolio,
    require_complete_covariance,
    resolve_actual_optimizer_method,
)
from camovar.return_quality import MIN_HISTORY_LONG, MIN_HISTORY_MEDIUM, MIN_HISTORY_SHORT
from camovar.table_io import JsonRow, read_rows, write_rows

ANNUAL_TRADING_DAYS = 252

WALK_FORWARD_DEVELOPMENT_PROFILE = "development"
WALK_FORWARD_PRODUCTION_PROFILE = "production"

PRODUCTION_MIN_TRAIN_OBSERVATIONS = 504
PRODUCTION_MIN_TEST_OBSERVATIONS = 21
PRODUCTION_MIN_COMPLETED_SPLITS = 2
PRODUCTION_MAX_WEIGHT = 0.25


@dataclass(frozen=True)
class WalkForwardProfile:
    """Named walk-forward policy: development fixtures vs. production defaults."""

    name: str
    min_train_observations: int
    min_test_observations: int
    min_completed_splits: int
    max_weight: float


WALK_FORWARD_PROFILES: dict[str, WalkForwardProfile] = {
    WALK_FORWARD_DEVELOPMENT_PROFILE: WalkForwardProfile(
        name=WALK_FORWARD_DEVELOPMENT_PROFILE,
        min_train_observations=1,
        min_test_observations=1,
        min_completed_splits=1,
        max_weight=1.0,
    ),
    WALK_FORWARD_PRODUCTION_PROFILE: WalkForwardProfile(
        name=WALK_FORWARD_PRODUCTION_PROFILE,
        min_train_observations=PRODUCTION_MIN_TRAIN_OBSERVATIONS,
        min_test_observations=PRODUCTION_MIN_TEST_OBSERVATIONS,
        min_completed_splits=PRODUCTION_MIN_COMPLETED_SPLITS,
        max_weight=PRODUCTION_MAX_WEIGHT,
    ),
}


def _compound_return(returns: Sequence[float]) -> float:
    """Geometrically compound a series of simple returns: `prod(1 + r) - 1`."""
    product = 1.0
    for value in returns:
        product *= 1.0 + value
    return product - 1.0


def read_gold_returns(paths: LakePaths) -> list[JsonRow]:
    rows: list[JsonRow] = []
    for path in sorted((paths.gold / "returns").glob("*/*.parquet")):
        rows.extend(read_rows(path))
    return rows


def build_return_matrix(
    return_rows: Sequence[Mapping[str, Any]], evaluation_id: str
) -> list[JsonRow]:
    by_listing: dict[tuple[str, str, str], dict[str, tuple[float, float]]] = {}
    for row in return_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        log_return = float(row["return"])
        simple_return = float(row["simple_return"]) if "simple_return" in row else log_return
        by_listing.setdefault(key, {})[str(row["date"])] = (log_return, simple_return)
    if not by_listing:
        return []

    date_sets: list[set[str]] = [set(rows) for rows in by_listing.values()]
    common_dates = date_sets[0].copy()
    for dates in date_sets[1:]:
        common_dates.intersection_update(dates)
    matrix: list[JsonRow] = []
    for date in sorted(common_dates):
        for isin, exchange, code in sorted(by_listing):
            log_return, simple_return = by_listing[(isin, exchange, code)][date]
            matrix.append(
                {
                    "evaluation_id": evaluation_id,
                    "date": date,
                    "isin": isin,
                    "exchange": exchange,
                    "code": code,
                    "return": log_return,
                    "simple_return": simple_return,
                }
            )
    return matrix


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _historical_tail_risk(
    returns: Sequence[float], confidence_level: float
) -> tuple[float, float, int]:
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    losses = sorted(-item for item in returns)
    if not losses:
        return 0.0, 0.0, 0
    threshold_index = min(len(losses) - 1, int(confidence_level * len(losses)))
    var = losses[threshold_index]
    tail = [loss for loss in losses if loss >= var]
    return var, sum(tail) / len(tail), len(tail)


def equal_weight_portfolio(matrix_rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    isins = sorted({str(row["isin"]) for row in matrix_rows})
    if not isins:
        raise ValueError("at least one return row is required")
    weight = 1.0 / len(isins)
    return {isin: weight for isin in isins}


def validate_portfolio_weights(
    matrix_rows: Sequence[Mapping[str, Any]], weights: Mapping[str, float]
) -> dict[str, float]:
    expected = {str(row["isin"]) for row in matrix_rows}
    cleaned = {str(isin): float(weight) for isin, weight in weights.items()}
    if not cleaned:
        raise ValueError("portfolio weights are required")
    missing = sorted(expected - set(cleaned))
    extra = sorted(set(cleaned) - expected)
    if missing:
        raise ValueError(f"portfolio weights missing ISINs: {', '.join(missing)}")
    if extra:
        raise ValueError(f"portfolio weights include unknown ISINs: {', '.join(extra)}")
    if any(weight < 0 for weight in cleaned.values()):
        raise ValueError("portfolio weights must be long-only")
    if abs(sum(cleaned.values()) - 1.0) > 1e-9:
        raise ValueError("portfolio weights must sum to 1")
    return {isin: cleaned[isin] for isin in sorted(cleaned)}


def build_asset_metrics(
    matrix_rows: Sequence[Mapping[str, Any]],
    evaluation_id: str,
    *,
    confidence_level: float = 0.95,
) -> list[JsonRow]:
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    by_listing: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in matrix_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, []).append(row)

    metrics: list[JsonRow] = []
    for isin, exchange, code in sorted(by_listing):
        ordered = sorted(by_listing[(isin, exchange, code)], key=lambda row: str(row["date"]))
        returns = [float(row["return"]) for row in ordered]
        mean_return = sum(returns) / len(returns) if returns else 0.0
        volatility = sqrt(covariance(returns, returns)) if len(returns) >= 2 else 0.0
        downside_returns = [min(0.0, item) for item in returns]
        downside_deviation = (
            sqrt(sum(item * item for item in downside_returns) / len(downside_returns))
            * sqrt(ANNUAL_TRADING_DAYS)
            if downside_returns
            else 0.0
        )
        annualized_return = mean_return * ANNUAL_TRADING_DAYS
        annualized_volatility = volatility * sqrt(ANNUAL_TRADING_DAYS)
        var, cvar, tail_observation_count = _historical_tail_risk(returns, confidence_level)
        observation_count = len(returns)
        metrics.append(
            {
                "evaluation_id": evaluation_id,
                "isin": isin,
                "exchange": exchange,
                "code": code,
                "observation_count": observation_count,
                "first_return_date": str(ordered[0]["date"]) if ordered else "",
                "last_return_date": str(ordered[-1]["date"]) if ordered else "",
                "mean_return": mean_return,
                "annualized_return": annualized_return,
                "annualized_volatility": annualized_volatility,
                "downside_deviation": downside_deviation,
                "sharpe_ratio": _ratio(annualized_return, annualized_volatility),
                "sortino_ratio": _ratio(annualized_return, downside_deviation),
                "confidence_level": confidence_level,
                "var": var,
                "cvar": cvar,
                "tail_observation_count": tail_observation_count,
                "meets_min_history_252": observation_count >= MIN_HISTORY_SHORT,
                "meets_min_history_504": observation_count >= MIN_HISTORY_MEDIUM,
                "meets_min_history_756": observation_count >= MIN_HISTORY_LONG,
                "production_eligible": observation_count >= MIN_HISTORY_SHORT,
            }
        )
    return metrics


def _asset_simple_return(row: Mapping[str, Any]) -> float:
    """Return the simple-return field for wealth compounding.

    Falls back to the `return` field for legacy matrix rows that only carry a
    log return, so existing callers built before Gold return rows carried an
    explicit `simple_return` keep their prior numeric behavior unchanged.
    """
    if "simple_return" in row:
        return float(row["simple_return"])
    return float(row["return"])


def build_portfolio_returns(
    matrix_rows: Sequence[Mapping[str, Any]],
    *,
    evaluation_id: str,
    portfolio_id: str,
    weights: Mapping[str, float],
) -> list[JsonRow]:
    validated_weights = validate_portfolio_weights(matrix_rows, weights)
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for row in matrix_rows:
        by_date.setdefault(str(row["date"]), []).append(row)

    cumulative_wealth = 1.0
    rows: list[JsonRow] = []
    for item_date in sorted(by_date):
        daily_return = sum(
            _asset_simple_return(row) * validated_weights[str(row["isin"])]
            for row in by_date[item_date]
        )
        cumulative_wealth *= 1.0 + daily_return
        rows.append(
            {
                "evaluation_id": evaluation_id,
                "portfolio_id": portfolio_id,
                "date": item_date,
                "return": daily_return,
                "cumulative_wealth": cumulative_wealth,
            }
        )
    return rows


def build_drawdowns(portfolio_returns: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    running_peak = 1.0
    drawdown_duration = 0
    rows: list[JsonRow] = []
    for row in sorted(portfolio_returns, key=lambda item: str(item["date"])):
        cumulative_wealth = float(row["cumulative_wealth"])
        recovered_duration = 0
        if cumulative_wealth >= running_peak:
            recovered_duration = drawdown_duration if drawdown_duration else 0
            running_peak = cumulative_wealth
            drawdown_duration = 0
        else:
            drawdown_duration += 1
        drawdown = 0.0 if running_peak == 0 else (cumulative_wealth / running_peak) - 1.0
        rows.append(
            {
                "evaluation_id": str(row["evaluation_id"]),
                "portfolio_id": str(row["portfolio_id"]),
                "date": str(row["date"]),
                "cumulative_wealth": cumulative_wealth,
                "running_peak": running_peak,
                "drawdown": drawdown,
                "drawdown_duration": drawdown_duration,
                "recovery_duration": recovered_duration,
                "is_recovered": recovered_duration > 0,
            }
        )
    return rows


def build_portfolio_metrics(
    portfolio_returns: Sequence[Mapping[str, Any]],
    drawdown_rows: Sequence[Mapping[str, Any]],
    *,
    objective: str = "explicit_weights",
) -> list[JsonRow]:
    if not portfolio_returns:
        return []
    ordered_returns = sorted(portfolio_returns, key=lambda row: str(row["date"]))
    returns = [float(row["return"]) for row in ordered_returns]
    mean_return = sum(returns) / len(returns)
    volatility = sqrt(covariance(returns, returns)) if len(returns) >= 2 else 0.0
    downside_returns = [min(0.0, item) for item in returns]
    downside_deviation = sqrt(sum(item * item for item in downside_returns) / len(returns)) * sqrt(
        ANNUAL_TRADING_DAYS
    )
    annualized_return = mean_return * ANNUAL_TRADING_DAYS
    annualized_volatility = volatility * sqrt(ANNUAL_TRADING_DAYS)
    max_drawdown = min((float(row["drawdown"]) for row in drawdown_rows), default=0.0)
    ulcer_index = sqrt(
        sum(float(row["drawdown"]) * float(row["drawdown"]) for row in drawdown_rows)
        / len(drawdown_rows)
    )
    first = ordered_returns[0]
    return [
        {
            "evaluation_id": str(first["evaluation_id"]),
            "portfolio_id": str(first["portfolio_id"]),
            "objective": objective,
            "annualized_return": annualized_return,
            "annualized_volatility": annualized_volatility,
            "sharpe_ratio": _ratio(annualized_return, annualized_volatility),
            "sortino_ratio": _ratio(annualized_return, downside_deviation),
            "max_drawdown": max_drawdown,
            "calmar_ratio": _ratio(annualized_return, abs(max_drawdown)),
            "ulcer_index": ulcer_index,
            "turnover": 0.0,
        }
    ]


def write_evaluation_outputs(
    paths: LakePaths,
    *,
    evaluation_id: str = "default",
    confidence_level: float = 0.95,
) -> tuple[list[JsonRow], list[JsonRow]]:
    matrix = build_return_matrix(read_gold_returns(paths), evaluation_id)
    metrics = build_asset_metrics(matrix, evaluation_id, confidence_level=confidence_level)
    write_rows(paths.gold_return_matrix(evaluation_id), matrix)
    write_rows(paths.gold_asset_metrics(evaluation_id), metrics)
    return matrix, metrics


def write_portfolio_evaluation(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    weights: Mapping[str, float] | None = None,
    objective: str = "explicit_weights",
) -> tuple[list[JsonRow], list[JsonRow], list[JsonRow]]:
    matrix = read_rows(paths.gold_return_matrix(evaluation_id))
    if not matrix:
        matrix, _ = write_evaluation_outputs(paths, evaluation_id=evaluation_id)
    portfolio_weights = equal_weight_portfolio(matrix) if weights is None else dict(weights)
    portfolio_returns = build_portfolio_returns(
        matrix,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
        weights=portfolio_weights,
    )
    drawdowns = build_drawdowns(portfolio_returns)
    metrics = build_portfolio_metrics(
        portfolio_returns,
        drawdowns,
        objective="equal_weight" if weights is None else objective,
    )
    existing_returns = [
        row
        for row in read_rows(paths.gold_portfolio_returns(evaluation_id))
        if str(row["portfolio_id"]) != portfolio_id
    ]
    existing_metrics = [
        row
        for row in read_rows(paths.gold_portfolio_metrics(evaluation_id))
        if str(row["portfolio_id"]) != portfolio_id
    ]
    write_rows(
        paths.gold_portfolio_returns(evaluation_id),
        sorted(
            [*existing_returns, *portfolio_returns],
            key=lambda row: (str(row["portfolio_id"]), str(row["date"])),
        ),
    )
    write_rows(paths.gold_drawdowns(evaluation_id, portfolio_id), drawdowns)
    write_rows(
        paths.gold_portfolio_metrics(evaluation_id),
        sorted([*existing_metrics, *metrics], key=lambda row: str(row["portfolio_id"])),
    )
    return portfolio_returns, drawdowns, metrics


def build_walk_forward_backtest(
    matrix_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    evaluation_id: str,
    objective: str,
    constraints: PortfolioConstraints,
    train_window: int,
    test_window: int,
    mode: str = "rolling",
    grid_step: float = 0.1,
    profile: str = WALK_FORWARD_DEVELOPMENT_PROFILE,
    transaction_cost_rate: float = 0.0,
) -> tuple[list[JsonRow], list[JsonRow]]:
    dates = sorted({str(row["date"]) for row in matrix_rows})
    if train_window < 1 or test_window < 1:
        raise ValueError("train_window and test_window must be positive")
    if mode not in {"rolling", "expanding"}:
        raise ValueError("mode must be rolling or expanding")
    if profile not in WALK_FORWARD_PROFILES:
        raise ValueError(f"unknown walk-forward profile: {profile}")
    profile_settings = WALK_FORWARD_PROFILES[profile]
    if train_window < profile_settings.min_train_observations:
        raise ValueError(
            f"{profile} profile requires train_window >= "
            f"{profile_settings.min_train_observations} observations, got {train_window}"
        )
    if test_window < profile_settings.min_test_observations:
        raise ValueError(
            f"{profile} profile requires test_window >= "
            f"{profile_settings.min_test_observations} observations, got {test_window}"
        )
    if constraints.max_weight > profile_settings.max_weight:
        raise ValueError(
            f"{profile} profile requires max_weight <= {profile_settings.max_weight}, "
            f"got {constraints.max_weight}"
        )
    metrics: list[JsonRow] = []
    weight_rows: list[JsonRow] = []
    previous_weights: dict[str, float] = {}
    split_index = 1
    start = train_window
    while start + test_window <= len(dates):
        train_dates = dates[:start] if mode == "expanding" else dates[start - train_window : start]
        test_dates = dates[start : start + test_window]
        train_rows = [row for row in matrix_rows if str(row["date"]) in set(train_dates)]
        test_rows = [row for row in matrix_rows if str(row["date"]) in set(test_dates)]
        listings = _listing_rows(train_rows)
        covariance_rows = _matrix_covariance_rows(train_rows)
        expected_returns = _expected_returns(train_rows)
        weights = optimize_portfolio(
            listings,
            covariance_rows,
            expected_returns,
            objective=objective,
            constraints=constraints,
            grid_step=grid_step,
        )
        actual_optimizer_method = resolve_actual_optimizer_method(
            objective, len(listings), grid_step
        )
        split_id = f"split-{split_index:03d}"
        portfolio_returns = build_portfolio_returns(
            test_rows,
            evaluation_id=evaluation_id,
            portfolio_id=split_id,
            weights=weights,
        )
        drawdowns = build_drawdowns(portfolio_returns)
        returns = [float(row["return"]) for row in portfolio_returns]
        daily_volatility = sqrt(covariance(returns, returns)) if len(returns) >= 2 else 0.0
        downside_returns = [min(0.0, value) for value in returns]
        downside_deviation = (
            sqrt(sum(value * value for value in downside_returns) / len(downside_returns))
            if downside_returns
            else 0.0
        )
        pre_cost_return = _compound_return(returns)
        turnover = _turnover(previous_weights, weights)
        transaction_cost = turnover * transaction_cost_rate
        post_cost_return = (1.0 - transaction_cost) * (1.0 + pre_cost_return) - 1.0
        periods_per_year = ANNUAL_TRADING_DAYS / len(test_dates)
        annualized_return = (1.0 + post_cost_return) ** periods_per_year - 1.0
        annualized_volatility = daily_volatility * sqrt(ANNUAL_TRADING_DAYS)
        annualized_downside_deviation = downside_deviation * sqrt(ANNUAL_TRADING_DAYS)
        metrics.append(
            {
                "run_id": run_id,
                "evaluation_id": evaluation_id,
                "split_id": split_id,
                "objective": objective,
                "actual_optimizer_method": actual_optimizer_method,
                "train_start_date": train_dates[0],
                "train_end_date": train_dates[-1],
                "test_start_date": test_dates[0],
                "test_end_date": test_dates[-1],
                "pre_cost_return": pre_cost_return,
                "transaction_cost": transaction_cost,
                "post_cost_return": post_cost_return,
                "realized_return": post_cost_return,
                "realized_volatility": annualized_volatility,
                "sharpe_ratio": _ratio(annualized_return, annualized_volatility),
                "sortino_ratio": _ratio(annualized_return, annualized_downside_deviation),
                "max_drawdown": min((float(row["drawdown"]) for row in drawdowns), default=0.0),
                "turnover": turnover,
            }
        )
        weight_rows.extend(
            {
                "run_id": run_id,
                "evaluation_id": evaluation_id,
                "split_id": split_id,
                "isin": str(row["isin"]),
                "exchange": str(row["exchange"]),
                "code": str(row["code"]),
                "weight": weights[str(row["isin"])],
            }
            for row in listings
        )
        previous_weights = weights
        split_index += 1
        start += test_window
    completed_splits = len(metrics)
    production_eligible = (
        profile == WALK_FORWARD_PRODUCTION_PROFILE
        and completed_splits >= profile_settings.min_completed_splits
    )
    if profile != WALK_FORWARD_PRODUCTION_PROFILE:
        availability_reason = "development_profile_baseline_only"
    elif production_eligible:
        availability_reason = "ok"
    else:
        availability_reason = "insufficient_completed_splits"
    for row in metrics:
        row["profile"] = profile
        row["production_eligible"] = production_eligible
        row["availability_reason"] = availability_reason
    return metrics, sorted(weight_rows, key=lambda row: (str(row["split_id"]), str(row["isin"])))


def write_walk_forward_backtest(
    paths: LakePaths,
    *,
    evaluation_id: str,
    run_id: str,
    objective: str,
    constraints: PortfolioConstraints,
    train_window: int,
    test_window: int,
    mode: str = "rolling",
    grid_step: float = 0.1,
    profile: str = WALK_FORWARD_DEVELOPMENT_PROFILE,
    transaction_cost_rate: float = 0.0,
) -> tuple[list[JsonRow], list[JsonRow]]:
    matrix = _read_or_build_matrix(paths, evaluation_id)
    metrics, weights = build_walk_forward_backtest(
        matrix,
        run_id=run_id,
        evaluation_id=evaluation_id,
        objective=objective,
        constraints=constraints,
        train_window=train_window,
        test_window=test_window,
        mode=mode,
        grid_step=grid_step,
        profile=profile,
        transaction_cost_rate=transaction_cost_rate,
    )
    write_rows(paths.gold_backtests(run_id), metrics)
    write_rows(paths.gold_backtest_weights(run_id), weights)
    return metrics, weights


def build_rebalance_events(
    matrix_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    evaluation_id: str,
    portfolio_id: str,
    target_weights: Mapping[str, float] | None = None,
    schedule: str = "monthly",
    transaction_cost_rate: float = 0.0,
    drift_threshold: float | None = None,
) -> tuple[list[JsonRow], list[JsonRow]]:
    """Simulate a rebalance schedule where each instrument drifts from its own return.

    Returns `(events, weights)`: `events` is one row per date with portfolio-level
    turnover, transaction cost, post-cost return, portfolio value, and cash
    remainder; `weights` is one row per date per instrument with pre-trade value,
    pre-trade weight, target value, and trade value.
    """
    if schedule not in {"monthly", "quarterly", "annual", "threshold"}:
        raise ValueError("unknown rebalance schedule")
    rows_by_date = _rows_by_date(matrix_rows)
    weights = (
        equal_weight_portfolio(matrix_rows) if target_weights is None else dict(target_weights)
    )
    isins = sorted(weights)
    current_values = {isin: weights[isin] for isin in isins}
    portfolio_value = sum(current_values.values())
    events: list[JsonRow] = []
    weight_rows: list[JsonRow] = []
    last_period = ""
    for item_date in sorted(rows_by_date):
        listing_by_isin = {str(row["isin"]): row for row in rows_by_date[item_date]}
        pre_trade_values = {
            isin: current_values[isin] * (1.0 + _asset_simple_return(listing_by_isin[isin]))
            if isin in listing_by_isin
            else current_values[isin]
            for isin in isins
        }
        pre_trade_total = sum(pre_trade_values.values())
        pre_trade_weights = (
            {isin: pre_trade_values[isin] / pre_trade_total for isin in isins}
            if pre_trade_total
            else dict.fromkeys(isins, 0.0)
        )
        period = _rebalance_period(item_date, schedule)
        drift = _turnover(pre_trade_weights, weights)
        scheduled = period != last_period
        threshold_hit = (
            schedule == "threshold" and drift_threshold is not None and drift >= drift_threshold
        )
        is_rebalance = scheduled or threshold_hit
        if is_rebalance:
            target_values = {isin: weights[isin] * pre_trade_total for isin in isins}
            trade_values = {isin: target_values[isin] - pre_trade_values[isin] for isin in isins}
            turnover = drift
            cost = turnover * transaction_cost_rate * pre_trade_total
            post_trade_total = pre_trade_total - cost
            scale = (post_trade_total / pre_trade_total) if pre_trade_total else 0.0
            current_values = {isin: target_values[isin] * scale for isin in isins}
            last_period = period
        else:
            turnover = 0.0
            cost = 0.0
            post_trade_total = pre_trade_total
            target_values = dict(pre_trade_values)
            trade_values = dict.fromkeys(isins, 0.0)
            current_values = dict(pre_trade_values)
        cash_remainder = post_trade_total - sum(current_values.values())
        post_cost_return = (post_trade_total / portfolio_value) - 1.0 if portfolio_value else 0.0
        portfolio_value = post_trade_total
        events.append(
            {
                "run_id": run_id,
                "evaluation_id": evaluation_id,
                "portfolio_id": portfolio_id,
                "date": item_date,
                "schedule": schedule,
                "pre_trade_value": pre_trade_total,
                "turnover": turnover,
                "transaction_cost": cost,
                "post_cost_return": post_cost_return,
                "portfolio_value": portfolio_value,
                "cash_remainder": cash_remainder,
                "is_rebalance": is_rebalance,
            }
        )
        for isin in isins:
            listing = listing_by_isin.get(isin)
            weight_rows.append(
                {
                    "run_id": run_id,
                    "evaluation_id": evaluation_id,
                    "portfolio_id": portfolio_id,
                    "isin": isin,
                    "exchange": str(listing["exchange"]) if listing else "",
                    "code": str(listing["code"]) if listing else "",
                    "date": item_date,
                    "pre_trade_value": pre_trade_values[isin],
                    "pre_trade_weight": pre_trade_weights[isin],
                    "target_weight": weights[isin],
                    "target_value": target_values[isin],
                    "trade_value": trade_values[isin],
                    "is_rebalance": is_rebalance,
                }
            )
    return events, weight_rows


def write_rebalance_simulation(
    paths: LakePaths,
    *,
    evaluation_id: str,
    run_id: str,
    portfolio_id: str,
    target_weights: Mapping[str, float] | None = None,
    schedule: str = "monthly",
    transaction_cost_rate: float = 0.0,
    drift_threshold: float | None = None,
) -> tuple[list[JsonRow], list[JsonRow]]:
    matrix = _read_or_build_matrix(paths, evaluation_id)
    weights = equal_weight_portfolio(matrix) if target_weights is None else dict(target_weights)
    events, weight_rows = build_rebalance_events(
        matrix,
        run_id=run_id,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
        target_weights=weights,
        schedule=schedule,
        transaction_cost_rate=transaction_cost_rate,
        drift_threshold=drift_threshold,
    )
    write_rows(paths.gold_rebalance_events(run_id), events)
    write_rows(paths.gold_rebalance_weights(run_id), weight_rows)
    return events, weight_rows


def build_efficient_frontier(
    matrix_rows: Sequence[Mapping[str, Any]],
    *,
    evaluation_id: str,
    constraints: PortfolioConstraints,
    target_returns: Sequence[float],
    risk_free_rate: float = 0.0,
    grid_step: float = 0.1,
) -> tuple[list[JsonRow], list[JsonRow]]:
    listings = _listing_rows(matrix_rows)
    covariance_rows = _matrix_covariance_rows(matrix_rows)
    expected_returns = _expected_returns(matrix_rows)
    covariance_map = _covariance_map(covariance_rows)
    points: list[JsonRow] = []
    weights_rows: list[JsonRow] = []
    for index, target in enumerate(target_returns, start=1):
        point_id = f"frontier-{index:03d}"
        try:
            weights = optimize_portfolio(
                listings,
                covariance_rows,
                expected_returns,
                objective="target_return_minimum_variance",
                constraints=constraints,
                target_return=target,
                grid_step=grid_step,
            )
            ordered = _listing_keys(listings)
            ordered_weights = tuple(weights[isin] for isin, _, _ in ordered)
            expected = sum(expected_returns.get(isin, 0.0) * weights[isin] for isin in weights)
            volatility = _portfolio_volatility(ordered, ordered_weights, covariance_map)
            feasible = True
        except ValueError:
            weights = {str(row["isin"]): 0.0 for row in listings}
            expected = 0.0
            volatility = 0.0
            feasible = False
        points.append(
            {
                "evaluation_id": evaluation_id,
                "frontier_point_id": point_id,
                "target_return": target,
                "expected_return": expected,
                "volatility": volatility,
                "sharpe_ratio": _ratio(expected - risk_free_rate, volatility),
                "is_feasible": feasible,
                "diagnostics": json.dumps({"grid_step": grid_step}, sort_keys=True),
            }
        )
        weights_rows.extend(
            {
                "evaluation_id": evaluation_id,
                "frontier_point_id": point_id,
                "isin": str(row["isin"]),
                "exchange": str(row["exchange"]),
                "code": str(row["code"]),
                "weight": weights[str(row["isin"])],
            }
            for row in listings
        )
    return points, sorted(
        weights_rows, key=lambda row: (str(row["frontier_point_id"]), str(row["isin"]))
    )


def write_efficient_frontier(
    paths: LakePaths,
    *,
    evaluation_id: str,
    constraints: PortfolioConstraints,
    target_returns: Sequence[float],
    risk_free_rate: float = 0.0,
    grid_step: float = 0.1,
) -> tuple[list[JsonRow], list[JsonRow]]:
    matrix = _read_or_build_matrix(paths, evaluation_id)
    points, weights = build_efficient_frontier(
        matrix,
        evaluation_id=evaluation_id,
        constraints=constraints,
        target_returns=target_returns,
        risk_free_rate=risk_free_rate,
        grid_step=grid_step,
    )
    write_rows(paths.gold_frontier_points(evaluation_id), points)
    write_rows(paths.gold_frontier_weights(evaluation_id), weights)
    return points, weights


def build_tail_risk_rows(
    matrix_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    evaluation_id: str,
    portfolio_id: str,
    weights: Mapping[str, float],
    confidence_level: float,
) -> list[JsonRow]:
    returns = [
        float(row["return"])
        for row in build_portfolio_returns(
            matrix_rows,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
            weights=weights,
        )
    ]
    var, cvar, tail_observation_count = _historical_tail_risk(returns, confidence_level)
    if not returns:
        return []
    return [
        {
            "run_id": run_id,
            "evaluation_id": evaluation_id,
            "portfolio_id": portfolio_id,
            "confidence_level": confidence_level,
            "var": var,
            "cvar": cvar,
            "tail_observation_count": tail_observation_count,
            "scenario_count": len(returns),
        }
    ]


def write_tail_risk_evaluation(
    paths: LakePaths,
    *,
    evaluation_id: str,
    run_id: str,
    portfolio_id: str,
    weights: Mapping[str, float] | None = None,
    confidence_level: float = 0.95,
) -> list[JsonRow]:
    matrix = _read_or_build_matrix(paths, evaluation_id)
    portfolio_weights = equal_weight_portfolio(matrix) if weights is None else dict(weights)
    rows = build_tail_risk_rows(
        matrix,
        run_id=run_id,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
        weights=portfolio_weights,
        confidence_level=confidence_level,
    )
    write_rows(paths.gold_tail_risk(run_id), rows)
    return rows


def _read_or_build_matrix(paths: LakePaths, evaluation_id: str) -> list[JsonRow]:
    matrix = read_rows(paths.gold_return_matrix(evaluation_id))
    if matrix:
        return matrix
    matrix, _ = write_evaluation_outputs(paths, evaluation_id=evaluation_id)
    return matrix


def _listing_keys(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    return sorted({(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in rows})


def _listing_rows(rows: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    return [
        {"isin": isin, "exchange": exchange, "code": code}
        for isin, exchange, code in _listing_keys(rows)
    ]


def _rows_by_date(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_date.setdefault(str(row["date"]), []).append(row)
    return by_date


def _expected_returns(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    by_isin: dict[str, list[float]] = {}
    for row in rows:
        by_isin.setdefault(str(row["isin"]), []).append(float(row["return"]))
    return {isin: sum(values) / len(values) for isin, values in by_isin.items()}


def _matrix_covariance_rows(rows: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    by_listing: dict[tuple[str, str, str], dict[str, float]] = {}
    for row in rows:
        by_listing.setdefault((str(row["isin"]), str(row["exchange"]), str(row["code"])), {})[
            str(row["date"])
        ] = float(row["return"])
    output: list[JsonRow] = []
    for left in sorted(by_listing):
        for right in sorted(by_listing):
            common_dates = sorted(set(by_listing[left]) & set(by_listing[right]))
            value = covariance(
                [by_listing[left][item] for item in common_dates],
                [by_listing[right][item] for item in common_dates],
            )
            output.append(
                {
                    "left_isin": left[0],
                    "left_exchange": left[1],
                    "left_code": left[2],
                    "right_isin": right[0],
                    "right_exchange": right[1],
                    "right_code": right[2],
                    "covariance": value,
                }
            )
    return output


def _covariance_map(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[tuple[str, str, str], tuple[str, str, str]], float]:
    return {
        (
            (str(row["left_isin"]), str(row["left_exchange"]), str(row["left_code"])),
            (str(row["right_isin"]), str(row["right_exchange"]), str(row["right_code"])),
        ): float(row["covariance"])
        for row in rows
    }


def _portfolio_volatility(
    listings: Sequence[tuple[str, str, str]],
    weights: Sequence[float],
    covariances: Mapping[tuple[tuple[str, str, str], tuple[str, str, str]], float],
) -> float:
    require_complete_covariance(listings, covariances)
    variance = 0.0
    for left, left_weight in zip(listings, weights, strict=True):
        for right, right_weight in zip(listings, weights, strict=True):
            variance += left_weight * right_weight * covariances[(left, right)]
    return sqrt(max(0.0, variance))


def _turnover(previous: Mapping[str, float], current: Mapping[str, float]) -> float:
    if not previous:
        return 0.0
    keys = set(previous) | set(current)
    return sum(abs(previous.get(key, 0.0) - current.get(key, 0.0)) for key in keys) / 2


def _rebalance_period(item_date: str, schedule: str) -> str:
    year, month, _ = item_date.split("-")
    if schedule == "annual":
        return year
    if schedule == "quarterly":
        quarter = ((int(month) - 1) // 3) + 1
        return f"{year}-Q{quarter}"
    return f"{year}-{month}"
