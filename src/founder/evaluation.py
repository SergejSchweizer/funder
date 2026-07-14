"""Gold evaluation datasets built from Gold return inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from math import sqrt
from typing import Any

from founder.gold import covariance
from founder.paths import LakePaths
from founder.portfolio import PortfolioConstraints, optimize_portfolio
from founder.table_io import JsonRow, read_rows, write_rows

ANNUAL_TRADING_DAYS = 252


def read_gold_returns(paths: LakePaths) -> list[JsonRow]:
    rows: list[JsonRow] = []
    for path in sorted((paths.gold / "returns").glob("*/*.parquet")):
        rows.extend(read_rows(path))
    return rows


def build_return_matrix(
    return_rows: Sequence[Mapping[str, Any]], evaluation_id: str
) -> list[JsonRow]:
    by_listing: dict[tuple[str, str, str], dict[str, float]] = {}
    for row in return_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, {})[str(row["date"])] = float(row["return"])
    if not by_listing:
        return []

    date_sets: list[set[str]] = [set(rows) for rows in by_listing.values()]
    common_dates = date_sets[0].copy()
    for dates in date_sets[1:]:
        common_dates.intersection_update(dates)
    matrix: list[JsonRow] = []
    for date in sorted(common_dates):
        for isin, exchange, code in sorted(by_listing):
            matrix.append(
                {
                    "evaluation_id": evaluation_id,
                    "date": date,
                    "isin": isin,
                    "exchange": exchange,
                    "code": code,
                    "return": by_listing[(isin, exchange, code)][date],
                }
            )
    return matrix


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


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
    matrix_rows: Sequence[Mapping[str, Any]], evaluation_id: str
) -> list[JsonRow]:
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
        metrics.append(
            {
                "evaluation_id": evaluation_id,
                "isin": isin,
                "exchange": exchange,
                "code": code,
                "observation_count": len(returns),
                "first_return_date": str(ordered[0]["date"]) if ordered else "",
                "last_return_date": str(ordered[-1]["date"]) if ordered else "",
                "mean_return": mean_return,
                "annualized_return": annualized_return,
                "annualized_volatility": annualized_volatility,
                "downside_deviation": downside_deviation,
                "sharpe_ratio": _ratio(annualized_return, annualized_volatility),
                "sortino_ratio": _ratio(annualized_return, downside_deviation),
            }
        )
    return metrics


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
            float(row["return"]) * validated_weights[str(row["isin"])] for row in by_date[item_date]
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
    paths: LakePaths, *, evaluation_id: str = "default"
) -> tuple[list[JsonRow], list[JsonRow]]:
    matrix = build_return_matrix(read_gold_returns(paths), evaluation_id)
    metrics = build_asset_metrics(matrix, evaluation_id)
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
) -> tuple[list[JsonRow], list[JsonRow]]:
    dates = sorted({str(row["date"]) for row in matrix_rows})
    if train_window < 1 or test_window < 1:
        raise ValueError("train_window and test_window must be positive")
    if mode not in {"rolling", "expanding"}:
        raise ValueError("mode must be rolling or expanding")
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
        split_id = f"split-{split_index:03d}"
        portfolio_returns = build_portfolio_returns(
            test_rows,
            evaluation_id=evaluation_id,
            portfolio_id=split_id,
            weights=weights,
        )
        drawdowns = build_drawdowns(portfolio_returns)
        returns = [float(row["return"]) for row in portfolio_returns]
        volatility = sqrt(covariance(returns, returns)) if len(returns) >= 2 else 0.0
        realized_return = sum(returns)
        turnover = _turnover(previous_weights, weights)
        metrics.append(
            {
                "run_id": run_id,
                "evaluation_id": evaluation_id,
                "split_id": split_id,
                "objective": objective,
                "train_start_date": train_dates[0],
                "train_end_date": train_dates[-1],
                "test_start_date": test_dates[0],
                "test_end_date": test_dates[-1],
                "realized_return": realized_return,
                "realized_volatility": volatility,
                "sharpe_ratio": _ratio(realized_return, volatility),
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
    target_weights: Mapping[str, float],
    schedule: str,
    transaction_cost_rate: float = 0.0,
    drift_threshold: float | None = None,
) -> list[JsonRow]:
    if schedule not in {"monthly", "quarterly", "annual", "threshold"}:
        raise ValueError("unknown rebalance schedule")
    rows_by_date = _rows_by_date(matrix_rows)
    weights = dict(target_weights)
    current_weights = dict(weights)
    value = 1.0
    events: list[JsonRow] = []
    last_period = ""
    for item_date in sorted(rows_by_date):
        period = _rebalance_period(item_date, schedule)
        daily_return = sum(
            current_weights[str(row["isin"])] * float(row["return"])
            for row in rows_by_date[item_date]
        )
        drift = sum(abs(current_weights[isin] - weights[isin]) for isin in weights) / 2
        scheduled = period != last_period
        threshold_hit = (
            schedule == "threshold" and drift_threshold is not None and drift >= drift_threshold
        )
        is_rebalance = scheduled or threshold_hit
        turnover = _turnover(current_weights, weights) if is_rebalance else 0.0
        cost = turnover * transaction_cost_rate
        post_cost_return = daily_return - cost
        value *= 1.0 + post_cost_return
        if is_rebalance:
            current_weights = dict(weights)
            last_period = period
        else:
            total = sum(current_weights[isin] * (1.0 + daily_return) for isin in current_weights)
            if total:
                current_weights = {
                    isin: current_weights[isin] * (1.0 + daily_return) / total
                    for isin in current_weights
                }
        events.append(
            {
                "run_id": run_id,
                "evaluation_id": evaluation_id,
                "portfolio_id": portfolio_id,
                "date": item_date,
                "schedule": schedule,
                "turnover": turnover,
                "transaction_cost": cost,
                "post_cost_return": post_cost_return,
                "portfolio_value": value,
                "is_rebalance": is_rebalance,
            }
        )
    return events


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
) -> list[JsonRow]:
    matrix = _read_or_build_matrix(paths, evaluation_id)
    weights = equal_weight_portfolio(matrix) if target_weights is None else dict(target_weights)
    events = build_rebalance_events(
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
    return events


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
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    returns = [
        float(row["return"])
        for row in build_portfolio_returns(
            matrix_rows,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
            weights=weights,
        )
    ]
    losses = sorted([-item for item in returns])
    if not losses:
        return []
    threshold_index = min(len(losses) - 1, int(confidence_level * len(losses)))
    var = losses[threshold_index]
    tail = [loss for loss in losses if loss >= var]
    cvar = sum(tail) / len(tail)
    return [
        {
            "run_id": run_id,
            "evaluation_id": evaluation_id,
            "portfolio_id": portfolio_id,
            "confidence_level": confidence_level,
            "var": var,
            "cvar": cvar,
            "tail_observation_count": len(tail),
            "scenario_count": len(losses),
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
    variance = 0.0
    for left, left_weight in zip(listings, weights, strict=True):
        for right, right_weight in zip(listings, weights, strict=True):
            variance += left_weight * right_weight * covariances.get((left, right), 0.0)
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
