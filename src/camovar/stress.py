"""Stress, bootstrap, and sensitivity analysis (PR65).

Adds historical stress-period replay, correlation-convergence stress,
distribution-cut scenarios, block-bootstrap return scenarios, and
covariance/parameter perturbations for an already-computed candidate
portfolio (weights + the aligned return matrix they were built from).

Reuses existing tested infrastructure rather than a new simulation engine:
`camovar.evaluation.build_portfolio_returns`/`build_drawdowns` for
return-series-based scenarios (historical stress, distribution cut, block
bootstrap), and `camovar.portfolio_parts.cvar.historical_var_and_cvar` for
historical VaR/CVaR. Covariance-only scenarios (correlation convergence,
covariance perturbation) have no return series to replay, so they report a
standard parametric (Gaussian, zero-mean) VaR/CVaR estimate from the
stressed portfolio volatility instead, using a hand-implemented inverse
normal CDF (no scipy/numpy, matching this repository's established
pure-Python numerical style).

No hardcoded historical crash dates: the "historical stress period" is the
worst-drawdown window of the requested length *within the caller's own
supplied data*, detected deterministically -- never an invented or
externally-asserted date range.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import exp, log, pi, sqrt
from random import Random
from statistics import median
from typing import Any

from camovar.contract_versioning import stable_contract_id
from camovar.evaluation import build_drawdowns, build_portfolio_returns
from camovar.portfolio_parts.cvar import historical_var_and_cvar
from camovar.table_io import JsonRow

SCENARIO_VERSION = 1

HISTORICAL_STRESS_SCENARIO = "historical_stress_period"
CORRELATION_CONVERGENCE_SCENARIO = "correlation_convergence"
DISTRIBUTION_CUT_SCENARIO = "distribution_cut"
BLOCK_BOOTSTRAP_SCENARIO = "block_bootstrap"
COVARIANCE_PERTURBATION_SCENARIO = "covariance_perturbation"
SCENARIO_TYPES = (
    HISTORICAL_STRESS_SCENARIO,
    CORRELATION_CONVERGENCE_SCENARIO,
    DISTRIBUTION_CUT_SCENARIO,
    BLOCK_BOOTSTRAP_SCENARIO,
    COVARIANCE_PERTURBATION_SCENARIO,
)


@dataclass(frozen=True)
class ScenarioResult:
    """One scenario's outcome for one candidate portfolio."""

    scenario_id: str
    scenario_type: str
    candidate_id: str
    compounded_return: float
    max_drawdown: float
    confidence_level: float
    var: float
    cvar: float
    parameters: Mapping[str, Any]

    def as_dict(self) -> JsonRow:
        return {
            "scenario_id": self.scenario_id,
            "scenario_type": self.scenario_type,
            "candidate_id": self.candidate_id,
            "compounded_return": self.compounded_return,
            "max_drawdown": self.max_drawdown,
            "confidence_level": self.confidence_level,
            "var": self.var,
            "cvar": self.cvar,
            "parameters": dict(self.parameters),
            "scenario_version": SCENARIO_VERSION,
        }


def _inverse_normal_cdf(probability: float) -> float:
    """Peter Acklam's rational approximation of the standard normal quantile.

    Accurate to about 1.15e-9 absolute error, adequate for risk estimates;
    avoids a scipy/numpy dependency for the handful of quantiles this module
    needs.
    """
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be in (0, 1)")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    p_low = 0.02425
    p_high = 1 - p_low
    if probability < p_low:
        q = sqrt(-2 * log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if probability <= p_high:
        q = probability - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    q = sqrt(-2 * log(1 - probability))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )


def _normal_pdf(value: float) -> float:
    return exp(-0.5 * value * value) / sqrt(2 * pi)


def parametric_var_cvar(volatility: float, confidence_level: float) -> tuple[float, float]:
    """Standard zero-mean Gaussian parametric VaR/CVaR for a given volatility.

    `VaR = z * sigma`; `CVaR = sigma * phi(z) / (1 - confidence_level)`,
    where `z` is the `confidence_level` quantile of the standard normal and
    `phi` its density. Used only for covariance-only scenarios that have no
    return series to compute a historical VaR/CVaR from.
    """
    if volatility < 0:
        raise ValueError("volatility cannot be negative")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    if volatility == 0:
        return 0.0, 0.0
    z = _inverse_normal_cdf(confidence_level)
    var = z * volatility
    cvar = volatility * _normal_pdf(z) / (1 - confidence_level)
    return var, cvar


def _dense_portfolio_variance(
    weights: Sequence[float], covariance_matrix: Sequence[Sequence[float]]
) -> float:
    return sum(
        weights[i] * weights[j] * covariance_matrix[i][j]
        for i in range(len(weights))
        for j in range(len(weights))
    )


def _correlation_matrix(covariance_matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    n = len(covariance_matrix)
    correlation = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            denominator = sqrt(covariance_matrix[i][i] * covariance_matrix[j][j])
            value = 1.0 if denominator == 0 else covariance_matrix[i][j] / denominator
            correlation[i][j] = max(-1.0, min(1.0, value))
    return correlation


def _by_listing_returns(
    matrix_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    by_listing: dict[str, dict[str, float]] = {}
    for row in matrix_rows:
        isin = str(row["isin"])
        value = float(row["simple_return"]) if "simple_return" in row else float(row["return"])
        by_listing.setdefault(isin, {})[str(row["date"])] = value
    return by_listing


def _compounded_and_drawdown(
    matrix_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    evaluation_id: str,
    candidate_id: str,
    confidence_level: float,
) -> tuple[float, float, float, float]:
    """Shared aggregation for return-series-based scenarios: compounded return,
    whole-scenario max drawdown, and historical VaR/CVaR over the per-period
    portfolio returns.
    """
    portfolio_returns = build_portfolio_returns(
        matrix_rows, evaluation_id=evaluation_id, portfolio_id=candidate_id, weights=weights
    )
    if not portfolio_returns:
        return 0.0, 0.0, 0.0, 0.0
    drawdown_rows = build_drawdowns(portfolio_returns)
    compounded_return = float(portfolio_returns[-1]["cumulative_wealth"]) - 1.0
    max_drawdown = min((float(row["drawdown"]) for row in drawdown_rows), default=0.0)
    losses = [-float(row["return"]) for row in portfolio_returns]
    var, cvar, _tail_count = historical_var_and_cvar(losses, confidence_level)
    return compounded_return, max_drawdown, var, cvar


def detect_worst_drawdown_window(
    matrix_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    window_length: int,
    evaluation_id: str = "stress",
    candidate_id: str = "stress-candidate",
) -> tuple[str, str]:
    """Return the `(start_date, end_date)` of the worst-drawdown window of
    `window_length` observations within the supplied data, for the given
    weights. Deterministic and data-derived -- never an asserted date.
    """
    if window_length < 2:
        raise ValueError("window_length must be at least 2")
    portfolio_returns = build_portfolio_returns(
        matrix_rows, evaluation_id=evaluation_id, portfolio_id=candidate_id, weights=weights
    )
    dates = [str(row["date"]) for row in portfolio_returns]
    if len(dates) < window_length:
        raise ValueError(f"at least {window_length} observations are required, found {len(dates)}")
    returns = [float(row["return"]) for row in portfolio_returns]
    best_start = 0
    worst_wealth = None
    for start in range(0, len(returns) - window_length + 1):
        wealth = 1.0
        for value in returns[start : start + window_length]:
            wealth *= 1.0 + value
        if worst_wealth is None or wealth < worst_wealth:
            worst_wealth = wealth
            best_start = start
    return dates[best_start], dates[best_start + window_length - 1]


def historical_stress_scenario(
    matrix_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    candidate_id: str,
    window_length: int,
    confidence_level: float = 0.95,
    evaluation_id: str = "stress",
) -> ScenarioResult:
    """Replay the worst-drawdown window of `window_length` observations
    detected within the supplied data (see `detect_worst_drawdown_window`).
    """
    start_date, end_date = detect_worst_drawdown_window(
        matrix_rows,
        weights,
        window_length=window_length,
        evaluation_id=evaluation_id,
        candidate_id=candidate_id,
    )
    window_rows = [row for row in matrix_rows if start_date <= str(row["date"]) <= end_date]
    compounded_return, max_drawdown, var, cvar = _compounded_and_drawdown(
        window_rows,
        weights,
        evaluation_id=evaluation_id,
        candidate_id=candidate_id,
        confidence_level=confidence_level,
    )
    parameters = {
        "window_length": window_length,
        "start_date": start_date,
        "end_date": end_date,
    }
    scenario_id = stable_contract_id(
        HISTORICAL_STRESS_SCENARIO, {"candidate_id": candidate_id, **parameters}
    )
    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type=HISTORICAL_STRESS_SCENARIO,
        candidate_id=candidate_id,
        compounded_return=compounded_return,
        max_drawdown=max_drawdown,
        confidence_level=confidence_level,
        var=var,
        cvar=cvar,
        parameters=parameters,
    )


def distribution_cut_scenario(
    matrix_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    candidate_id: str,
    cut_isins: Sequence[str],
    cut_factor: float,
    confidence_level: float = 0.95,
    evaluation_id: str = "stress",
) -> ScenarioResult:
    """Apply a multiplicative shock (`cut_factor`, e.g. `-0.5` for a 50% cut)
    to the returns of `cut_isins` and replay the resulting shocked series.
    """
    if not -1.0 <= cut_factor <= 0.0:
        raise ValueError("cut_factor must be in [-1, 0] (a reduction, not a boost)")
    cut_set = set(cut_isins)
    shocked_rows = [
        {
            **row,
            "simple_return": (float(row.get("simple_return", row["return"])) * (1.0 + cut_factor)),
        }
        if str(row["isin"]) in cut_set
        else dict(row)
        for row in matrix_rows
    ]
    compounded_return, max_drawdown, var, cvar = _compounded_and_drawdown(
        shocked_rows,
        weights,
        evaluation_id=evaluation_id,
        candidate_id=candidate_id,
        confidence_level=confidence_level,
    )
    parameters = {"cut_isins": sorted(cut_set), "cut_factor": cut_factor}
    scenario_id = stable_contract_id(
        DISTRIBUTION_CUT_SCENARIO, {"candidate_id": candidate_id, **parameters}
    )
    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type=DISTRIBUTION_CUT_SCENARIO,
        candidate_id=candidate_id,
        compounded_return=compounded_return,
        max_drawdown=max_drawdown,
        confidence_level=confidence_level,
        var=var,
        cvar=cvar,
        parameters=parameters,
    )


def block_bootstrap_scenarios(
    matrix_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    candidate_id: str,
    block_length: int,
    scenario_count: int,
    seed: int,
    confidence_level: float = 0.95,
    evaluation_id: str = "stress",
) -> list[ScenarioResult]:
    """Resample historical returns in contiguous blocks (preserving serial
    correlation better than i.i.d. resampling) to generate `scenario_count`
    synthetic return paths, each seeded deterministically from `seed`.
    """
    if block_length < 1:
        raise ValueError("block_length must be at least 1")
    if scenario_count < 1:
        raise ValueError("scenario_count must be at least 1")
    by_listing = _by_listing_returns(matrix_rows)
    dates = sorted({str(row["date"]) for row in matrix_rows})
    if len(dates) < block_length:
        raise ValueError(f"at least {block_length} observations are required, found {len(dates)}")
    isins = sorted(by_listing)
    by_isin_meta = {
        str(row["isin"]): (str(row["exchange"]), str(row["code"])) for row in matrix_rows
    }

    results: list[ScenarioResult] = []
    for scenario_index in range(scenario_count):
        rng = Random(seed * 1_000_003 + scenario_index)
        resampled_dates: list[str] = []
        while len(resampled_dates) < len(dates):
            start = rng.randrange(0, len(dates) - block_length + 1)
            resampled_dates.extend(dates[start : start + block_length])
        resampled_dates = resampled_dates[: len(dates)]
        synthetic_rows: list[JsonRow] = [
            {
                "isin": isin,
                "exchange": by_isin_meta[isin][0],
                "code": by_isin_meta[isin][1],
                "date": f"scenario-{scenario_index:03d}-day-{position:04d}",
                "simple_return": by_listing[isin][original_date],
            }
            for position, original_date in enumerate(resampled_dates)
            for isin in isins
            if original_date in by_listing[isin]
        ]
        compounded_return, max_drawdown, var, cvar = _compounded_and_drawdown(
            synthetic_rows,
            weights,
            evaluation_id=evaluation_id,
            candidate_id=candidate_id,
            confidence_level=confidence_level,
        )
        parameters = {
            "block_length": block_length,
            "seed": seed,
            "scenario_index": scenario_index,
        }
        scenario_id = stable_contract_id(
            BLOCK_BOOTSTRAP_SCENARIO, {"candidate_id": candidate_id, **parameters}
        )
        results.append(
            ScenarioResult(
                scenario_id=scenario_id,
                scenario_type=BLOCK_BOOTSTRAP_SCENARIO,
                candidate_id=candidate_id,
                compounded_return=compounded_return,
                max_drawdown=max_drawdown,
                confidence_level=confidence_level,
                var=var,
                cvar=cvar,
                parameters=parameters,
            )
        )
    return results


def correlation_convergence_scenario(
    covariance_matrix: Sequence[Sequence[float]],
    weights: Sequence[float],
    *,
    candidate_id: str,
    convergence_factor: float,
    confidence_level: float = 0.95,
) -> ScenarioResult:
    """Blend every pairwise correlation toward 1 by `convergence_factor` in
    `[0, 1]` (representing the loss of diversification benefit often seen in
    a crisis), then report the stressed portfolio's parametric VaR/CVaR.

    Has no return series to replay, so `compounded_return` is always `0.0`;
    only the stressed risk (`var`/`cvar`) is meaningful for this scenario.
    """
    if not 0.0 <= convergence_factor <= 1.0:
        raise ValueError("convergence_factor must be in [0, 1]")
    n = len(covariance_matrix)
    correlation = _correlation_matrix(covariance_matrix)
    volatilities = [sqrt(max(0.0, covariance_matrix[i][i])) for i in range(n)]
    stressed_covariance = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                stressed_covariance[i][j] = covariance_matrix[i][i]
                continue
            stressed_correlation = correlation[i][j] * (1 - convergence_factor) + convergence_factor
            stressed_covariance[i][j] = stressed_correlation * volatilities[i] * volatilities[j]
    stressed_variance = _dense_portfolio_variance(weights, stressed_covariance)
    stressed_volatility = sqrt(max(0.0, stressed_variance))
    var, cvar = parametric_var_cvar(stressed_volatility, confidence_level)
    parameters = {"convergence_factor": convergence_factor}
    scenario_id = stable_contract_id(
        CORRELATION_CONVERGENCE_SCENARIO, {"candidate_id": candidate_id, **parameters}
    )
    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type=CORRELATION_CONVERGENCE_SCENARIO,
        candidate_id=candidate_id,
        compounded_return=0.0,
        max_drawdown=0.0,
        confidence_level=confidence_level,
        var=var,
        cvar=cvar,
        parameters=parameters,
    )


def covariance_perturbation_scenario(
    covariance_matrix: Sequence[Sequence[float]],
    weights: Sequence[float],
    *,
    candidate_id: str,
    perturbation_factor: float,
    confidence_level: float = 0.95,
) -> ScenarioResult:
    """Uniformly scale the whole covariance matrix by `(1 + perturbation_factor)`
    (a scalar multiple of a PSD matrix is still PSD) and report the stressed
    portfolio's parametric VaR/CVaR.
    """
    if perturbation_factor <= -1.0:
        raise ValueError("perturbation_factor must be greater than -1")
    scale = 1.0 + perturbation_factor
    stressed_variance = _dense_portfolio_variance(weights, covariance_matrix) * scale
    stressed_volatility = sqrt(max(0.0, stressed_variance))
    var, cvar = parametric_var_cvar(stressed_volatility, confidence_level)
    parameters = {"perturbation_factor": perturbation_factor}
    scenario_id = stable_contract_id(
        COVARIANCE_PERTURBATION_SCENARIO, {"candidate_id": candidate_id, **parameters}
    )
    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type=COVARIANCE_PERTURBATION_SCENARIO,
        candidate_id=candidate_id,
        compounded_return=0.0,
        max_drawdown=0.0,
        confidence_level=confidence_level,
        var=var,
        cvar=cvar,
        parameters=parameters,
    )


def build_sensitivity_summary(scenario_results: Sequence[ScenarioResult]) -> JsonRow:
    """Aggregate median and worst-case metrics across every scenario result
    for one candidate. Stable regardless of scenario evaluation order.
    """
    if not scenario_results:
        raise ValueError("at least one scenario result is required")
    candidate_ids = {result.candidate_id for result in scenario_results}
    if len(candidate_ids) != 1:
        raise ValueError("all scenario results must belong to the same candidate")
    returns = [result.compounded_return for result in scenario_results]
    drawdowns = [result.max_drawdown for result in scenario_results]
    cvars = [result.cvar for result in scenario_results]
    return {
        "candidate_id": next(iter(candidate_ids)),
        "scenario_count": len(scenario_results),
        "scenario_types": sorted({result.scenario_type for result in scenario_results}),
        "median_compounded_return": median(returns),
        "worst_compounded_return": min(returns),
        "median_max_drawdown": median(drawdowns),
        "worst_max_drawdown": min(drawdowns),
        "median_cvar": median(cvars),
        "worst_cvar": max(cvars),
        "scenario_version": SCENARIO_VERSION,
    }


__all__ = [
    "BLOCK_BOOTSTRAP_SCENARIO",
    "CORRELATION_CONVERGENCE_SCENARIO",
    "COVARIANCE_PERTURBATION_SCENARIO",
    "DISTRIBUTION_CUT_SCENARIO",
    "HISTORICAL_STRESS_SCENARIO",
    "SCENARIO_TYPES",
    "SCENARIO_VERSION",
    "ScenarioResult",
    "block_bootstrap_scenarios",
    "build_sensitivity_summary",
    "correlation_convergence_scenario",
    "covariance_perturbation_scenario",
    "detect_worst_drawdown_window",
    "distribution_cut_scenario",
    "historical_stress_scenario",
    "parametric_var_cvar",
]
