"""Walk-forward model comparison scorecard (PR64).

Runs `founder.evaluation.build_walk_forward_backtest` across multiple
candidate objectives on the same aligned return matrix and the same pinned
windows/rebalance policy/costs, then produces one common, deterministically
ranked scorecard row per candidate: out-of-sample return, volatility,
Sharpe, Sortino, historical CVaR, whole-period drawdown and recovery
duration, concentration, weight stability, and robustness across splits.

Ranking never uses a single split's return, an in-sample return, or the
single best split as the sole criterion (see
docs/backlog/00-critical-correctness-priority-queue.md's stop-the-line
policy and BACKLOG.md's PR64 acceptance criteria): candidates are ranked by
the median out-of-sample Sharpe ratio across completed splits, with a
deterministic candidate-id tie-break.

Income quality requires the after-tax cash-flow stack (PR62E, still open)
and is always reported as `unavailable`, never computed from an invented
income figure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

from founder.calculation_status import UNAVAILABLE
from founder.contract_versioning import stable_contract_id
from founder.evaluation import (
    WALK_FORWARD_DEVELOPMENT_PROFILE,
    build_drawdowns,
    build_walk_forward_backtest,
)
from founder.portfolio import PortfolioConstraints
from founder.portfolio_parts.cvar import historical_var_and_cvar
from founder.table_io import JsonRow

SCORECARD_VERSION = 1
RANKING_METRIC = "median_sharpe_ratio"


@dataclass(frozen=True)
class ScorecardCandidate:
    """One objective/constraints combination to compare on identical windows."""

    candidate_id: str
    objective: str
    constraints: PortfolioConstraints

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id is required")


def _concentration(weight_rows: Sequence[Mapping[str, Any]]) -> float:
    by_split: dict[str, float] = {}
    for row in weight_rows:
        split_id = str(row["split_id"])
        by_split[split_id] = max(by_split.get(split_id, 0.0), float(row["weight"]))
    return median(by_split.values()) if by_split else 0.0


def _weight_variance(weight_rows: Sequence[Mapping[str, Any]]) -> float:
    by_isin: dict[str, list[float]] = {}
    for row in weight_rows:
        by_isin.setdefault(str(row["isin"]), []).append(float(row["weight"]))
    variances: list[float] = []
    for values in by_isin.values():
        if len(values) < 2:
            continue
        asset_mean = sum(values) / len(values)
        variances.append(sum((value - asset_mean) ** 2 for value in values) / (len(values) - 1))
    return median(variances) if variances else 0.0


def _stitched_drawdown(
    metrics: Sequence[Mapping[str, Any]], *, evaluation_id: str, candidate_id: str
) -> tuple[float, int]:
    """Whole-period max drawdown and recovery duration over the concatenated
    out-of-sample split returns, treating each split as one compounding period.
    """
    ordered = sorted(metrics, key=lambda row: str(row["split_id"]))
    cumulative_wealth = 1.0
    portfolio_returns: list[JsonRow] = []
    for row in ordered:
        cumulative_wealth *= 1.0 + float(row["post_cost_return"])
        portfolio_returns.append(
            {
                "evaluation_id": evaluation_id,
                "portfolio_id": candidate_id,
                "date": str(row["split_id"]),
                "return": float(row["post_cost_return"]),
                "cumulative_wealth": cumulative_wealth,
            }
        )
    if not portfolio_returns:
        return 0.0, 0
    drawdown_rows = build_drawdowns(portfolio_returns)
    max_drawdown = min((float(row["drawdown"]) for row in drawdown_rows), default=0.0)
    max_recovery_duration = max((int(row["recovery_duration"]) for row in drawdown_rows), default=0)
    return max_drawdown, max_recovery_duration


def _score_candidate(
    candidate: ScorecardCandidate,
    metrics: Sequence[JsonRow],
    weight_rows: Sequence[JsonRow],
    *,
    evaluation_id: str,
    confidence_level: float,
) -> JsonRow:
    if not metrics:
        return {
            "candidate_id": candidate.candidate_id,
            "objective": candidate.objective,
            "status": "blocked",
            "reasons": ["no_completed_out_of_sample_splits"],
            "completed_splits": 0,
        }
    realized_returns = [float(row["realized_return"]) for row in metrics]
    sharpe_ratios = [float(row["sharpe_ratio"]) for row in metrics]
    sortino_ratios = [float(row["sortino_ratio"]) for row in metrics]
    turnovers = [float(row["turnover"]) for row in metrics]
    losses = [-value for value in realized_returns]
    var, cvar, tail_count = historical_var_and_cvar(losses, confidence_level)
    whole_period_max_drawdown, recovery_duration = _stitched_drawdown(
        metrics, evaluation_id=evaluation_id, candidate_id=candidate.candidate_id
    )
    return {
        "candidate_id": candidate.candidate_id,
        "objective": candidate.objective,
        "status": "scored",
        "reasons": [],
        "completed_splits": len(metrics),
        "median_out_of_sample_return": median(realized_returns),
        "adverse_out_of_sample_return": min(realized_returns),
        "median_sharpe_ratio": median(sharpe_ratios),
        "median_sortino_ratio": median(sortino_ratios),
        "confidence_level": confidence_level,
        "var": var,
        "cvar": cvar,
        "tail_observation_count": tail_count,
        "whole_period_max_drawdown": whole_period_max_drawdown,
        "recovery_duration_splits": recovery_duration,
        "median_turnover": median(turnovers),
        "median_concentration": _concentration(weight_rows),
        "median_weight_variance": _weight_variance(weight_rows),
        "income_quality": UNAVAILABLE,
        "production_eligible": bool(metrics[-1].get("production_eligible", False)),
        "availability_reason": str(metrics[-1].get("availability_reason", "")),
    }


def _rank_candidates(rows: Sequence[JsonRow]) -> list[JsonRow]:
    scored = [row for row in rows if row["status"] == "scored"]
    blocked = [row for row in rows if row["status"] != "scored"]
    ordered = sorted(
        scored,
        key=lambda row: (-float(row[RANKING_METRIC]), str(row["candidate_id"])),
    )
    ranked: list[JsonRow] = []
    for index, row in enumerate(ordered, start=1):
        ranked.append({**row, "rank": index, "ranking_metric": RANKING_METRIC})
    for row in blocked:
        ranked.append({**row, "rank": None, "ranking_metric": RANKING_METRIC})
    return ranked


def build_model_comparison_scorecard(
    matrix_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    evaluation_id: str,
    candidates: Sequence[ScorecardCandidate],
    train_window: int,
    test_window: int,
    mode: str = "rolling",
    grid_step: float = 0.1,
    profile: str = WALK_FORWARD_DEVELOPMENT_PROFILE,
    transaction_cost_rate: float = 0.0,
    confidence_level: float = 0.95,
) -> list[JsonRow]:
    """Run every candidate on identical windows/rebalance policy/costs and
    return one deterministically ranked scorecard row per candidate.

    A candidate whose walk-forward request is infeasible (e.g. insufficient
    training history for the chosen profile) is reported with
    `status="blocked"` rather than raising, so one bad candidate never
    prevents scoring the rest.
    """
    if not candidates:
        raise ValueError("at least one candidate is required")
    rows: list[JsonRow] = []
    for candidate in candidates:
        try:
            metrics, weight_rows = build_walk_forward_backtest(
                matrix_rows,
                run_id=f"{run_id}-{candidate.candidate_id}",
                evaluation_id=evaluation_id,
                objective=candidate.objective,
                constraints=candidate.constraints,
                train_window=train_window,
                test_window=test_window,
                mode=mode,
                grid_step=grid_step,
                profile=profile,
                transaction_cost_rate=transaction_cost_rate,
            )
        except ValueError as error:
            rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "objective": candidate.objective,
                    "status": "blocked",
                    "reasons": [str(error)],
                    "completed_splits": 0,
                }
            )
            continue
        rows.append(
            _score_candidate(
                candidate,
                metrics,
                weight_rows,
                evaluation_id=evaluation_id,
                confidence_level=confidence_level,
            )
        )
    ranked = _rank_candidates(rows)
    model_comparison_id = stable_contract_id(
        "model_comparison",
        {
            "scorecard_version": SCORECARD_VERSION,
            "candidate_ids": [candidate.candidate_id for candidate in candidates],
            "objectives": [candidate.objective for candidate in candidates],
            "train_window": train_window,
            "test_window": test_window,
            "mode": mode,
            "grid_step": grid_step,
            "profile": profile,
            "transaction_cost_rate": transaction_cost_rate,
        },
    )
    return [
        {**row, "model_comparison_id": model_comparison_id, "scorecard_version": SCORECARD_VERSION}
        for row in ranked
    ]


__all__ = [
    "RANKING_METRIC",
    "SCORECARD_VERSION",
    "ScorecardCandidate",
    "build_model_comparison_scorecard",
]
