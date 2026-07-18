"""Tests for PR64's walk-forward model comparison scorecard."""

import random

import pytest

from founder.calculation_status import UNAVAILABLE
from founder.portfolio import PortfolioConstraints
from founder.scorecard import (
    RANKING_METRIC,
    ScorecardCandidate,
    _rank_candidates,
    build_model_comparison_scorecard,
)


def _matrix_row(isin: str, exchange: str, code: str, date: str, value: float) -> dict[str, object]:
    return {
        "evaluation_id": "eval-1",
        "date": date,
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "return": value,
        "simple_return": value,
    }


def _return_rows(seed: int = 7, count: int = 120) -> list[dict[str, object]]:
    random.seed(seed)
    rows: list[dict[str, object]] = []
    for day in range(count):
        date = f"2020-{1 + day // 28:02d}-{1 + day % 28:02d}"
        risky = random.gauss(0.004, 0.02)
        if random.random() < 0.05:
            risky += 0.25
        safe = random.gauss(0.001, 0.003)
        rows.append(_matrix_row("IE1", "XETRA", "AAA", date, risky))
        rows.append(_matrix_row("IE2", "AS", "BBB", date, safe))
    return rows


def test_scorecard_candidate_rejects_empty_id() -> None:
    with pytest.raises(ValueError, match="candidate_id"):
        ScorecardCandidate("", "equal_weight", PortfolioConstraints(max_weight=1.0))


def test_build_model_comparison_scorecard_requires_at_least_one_candidate() -> None:
    with pytest.raises(ValueError, match="at least one candidate"):
        build_model_comparison_scorecard(
            _return_rows(),
            run_id="wf",
            evaluation_id="eval-1",
            candidates=[],
            train_window=20,
            test_window=10,
        )


def test_ranking_prefers_higher_median_sharpe_over_higher_raw_return() -> None:
    """The scorecard must never crown the candidate with the best raw/single-split
    return; it must rank by median out-of-sample Sharpe across completed splits.
    """
    high_return_low_sharpe = {
        "candidate_id": "spiky",
        "objective": "equal_weight",
        "status": "scored",
        "median_out_of_sample_return": 0.50,
        "median_sharpe_ratio": 0.2,
    }
    modest_return_high_sharpe = {
        "candidate_id": "steady",
        "objective": "minimum_variance",
        "status": "scored",
        "median_out_of_sample_return": 0.05,
        "median_sharpe_ratio": 3.0,
    }

    ranked = _rank_candidates([high_return_low_sharpe, modest_return_high_sharpe])

    assert RANKING_METRIC == "median_sharpe_ratio"
    assert ranked[0]["candidate_id"] == "steady"
    assert ranked[0]["rank"] == 1
    assert ranked[1]["candidate_id"] == "spiky"
    assert ranked[1]["rank"] == 2


def test_rank_candidates_breaks_ties_deterministically_by_candidate_id() -> None:
    tied_a = {
        "candidate_id": "bbb",
        "objective": "equal_weight",
        "status": "scored",
        "median_sharpe_ratio": 1.0,
    }
    tied_b = {
        "candidate_id": "aaa",
        "objective": "minimum_variance",
        "status": "scored",
        "median_sharpe_ratio": 1.0,
    }

    ranked = _rank_candidates([tied_a, tied_b])

    assert [row["candidate_id"] for row in ranked] == ["aaa", "bbb"]


def test_build_model_comparison_scorecard_scores_and_ranks_two_objectives() -> None:
    rows = _return_rows()
    candidates = [
        ScorecardCandidate("growth", "equal_weight", PortfolioConstraints(max_weight=1.0)),
        ScorecardCandidate("defensive", "minimum_variance", PortfolioConstraints(max_weight=1.0)),
    ]

    scorecard = build_model_comparison_scorecard(
        rows,
        run_id="wf",
        evaluation_id="eval-1",
        candidates=candidates,
        train_window=20,
        test_window=10,
        mode="rolling",
        grid_step=0.01,
        profile="development",
    )

    assert {row["candidate_id"] for row in scorecard} == {"growth", "defensive"}
    ranks = sorted(row["rank"] for row in scorecard)
    assert ranks == [1, 2]
    for row in scorecard:
        assert row["status"] == "scored"
        assert row["completed_splits"] > 0
        assert row["income_quality"] == UNAVAILABLE
        assert 0.0 <= row["median_concentration"] <= 1.0
        assert row["median_weight_variance"] >= 0.0
        assert row["cvar"] >= row["var"]


def test_build_model_comparison_scorecard_is_deterministic() -> None:
    rows = _return_rows()
    candidates = [
        ScorecardCandidate("growth", "equal_weight", PortfolioConstraints(max_weight=1.0)),
        ScorecardCandidate("defensive", "minimum_variance", PortfolioConstraints(max_weight=1.0)),
    ]

    first = build_model_comparison_scorecard(
        rows,
        run_id="wf",
        evaluation_id="eval-1",
        candidates=candidates,
        train_window=20,
        test_window=10,
        profile="development",
    )
    second = build_model_comparison_scorecard(
        rows,
        run_id="wf",
        evaluation_id="eval-1",
        candidates=candidates,
        train_window=20,
        test_window=10,
        profile="development",
    )

    assert first == second
    assert first[0]["model_comparison_id"] == second[0]["model_comparison_id"]


def test_build_model_comparison_scorecard_reports_blocked_candidate_without_crashing() -> None:
    rows = _return_rows()
    candidates = [
        ScorecardCandidate("growth", "equal_weight", PortfolioConstraints(max_weight=1.0)),
        ScorecardCandidate(
            "unknown_objective", "not_a_real_objective", PortfolioConstraints(max_weight=1.0)
        ),
    ]

    scorecard = build_model_comparison_scorecard(
        rows,
        run_id="wf",
        evaluation_id="eval-1",
        candidates=candidates,
        train_window=20,
        test_window=10,
        profile="development",
    )

    by_id = {row["candidate_id"]: row for row in scorecard}
    assert by_id["growth"]["status"] == "scored"
    assert by_id["growth"]["rank"] is not None
    assert by_id["unknown_objective"]["status"] == "blocked"
    assert by_id["unknown_objective"]["rank"] is None
    assert by_id["unknown_objective"]["reasons"]
