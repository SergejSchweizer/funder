"""Tests for PR66's explainable recommendation report."""

import pytest

from camovar.recommendation import (
    BEST_DEFENSIVE,
    BEST_DIVERSIFIED,
    BEST_ENSEMBLE,
    BEST_INCOME,
    BEST_TOTAL_RETURN,
    NO_GUARANTEE_DISCLAIMER,
    build_candidate_report,
    build_recommendation_report,
    render_recommendation_markdown,
)


def _profile_candidate(
    profile_name: str,
    candidate_id: str,
    *,
    status: str = "feasible",
    weights: dict[str, float] | None = None,
    portfolio_variance: float | None = 0.01,
    requires_income_data: bool = False,
    production_eligible: bool = True,
    reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "profile_candidate_id": candidate_id,
        "profile_name": profile_name,
        "status": status,
        "reasons": reasons or [],
        "weights": weights if weights is not None else {"IE1": 0.4, "IE2": 0.6},
        "constraint_violations": [],
        "portfolio_variance": portfolio_variance,
        "requires_income_data": requires_income_data,
        "production_eligible": production_eligible,
    }


def test_build_candidate_report_marks_income_and_cost_quality_unavailable() -> None:
    report = build_candidate_report(
        _profile_candidate("income", "income-1", requires_income_data=True)
    )

    assert report.income_quality == "unavailable"
    assert report.cost_quality == "unavailable"
    assert "income_quality_unavailable_pending_after_tax_cashflow_stack" in report.disadvantages
    assert "cost_quality_unavailable_pending_broker_cost_engine" in report.disadvantages


def test_build_candidate_report_marks_infeasible_candidate_excluded() -> None:
    report = build_candidate_report(
        _profile_candidate(
            "defensive", "defensive-1", status="infeasible", weights={}, reasons=["blocked"]
        )
    )

    assert report.included is False
    assert report.exclusion_reasons == ("blocked",)
    assert "candidate_infeasible" in report.disadvantages


def test_build_candidate_report_computes_turnover_and_concentration() -> None:
    report = build_candidate_report(
        _profile_candidate("balanced", "balanced-1", weights={"IE1": 0.7, "IE2": 0.3}),
        current_weights={"IE1": 0.5, "IE2": 0.5},
    )

    assert report.concentration == pytest.approx(0.7)
    assert report.turnover_from_current == pytest.approx(0.2)


def test_build_candidate_report_propagates_scorecard_rank_and_sensitivity() -> None:
    report = build_candidate_report(
        _profile_candidate("balanced", "balanced-1"),
        scorecard_row={"status": "scored", "rank": 1},
        sensitivity_summary={"worst_max_drawdown": -0.2, "worst_cvar": 0.15},
    )

    assert report.scorecard_rank == 1
    assert report.sensitivity_worst_drawdown == -0.2
    assert report.sensitivity_worst_cvar == 0.15


def test_build_candidate_report_flags_non_scored_scorecard_status() -> None:
    report = build_candidate_report(
        _profile_candidate("balanced", "balanced-1"),
        scorecard_row={"status": "blocked", "rank": None},
    )

    assert "scorecard_status_not_scored" in report.disadvantages


def test_build_recommendation_report_requires_at_least_one_candidate() -> None:
    with pytest.raises(ValueError, match="at least one candidate report"):
        build_recommendation_report(evaluation_id="eval-1", candidate_reports=[])


def test_build_recommendation_report_selects_best_candidates_per_slot() -> None:
    defensive = build_candidate_report(
        _profile_candidate("defensive", "defensive-1", portfolio_variance=0.02)
    )
    balanced = build_candidate_report(
        _profile_candidate("balanced", "balanced-1", portfolio_variance=0.01),
        scorecard_row={"status": "scored", "rank": 1},
    )
    income = build_candidate_report(
        _profile_candidate("income", "income-1", requires_income_data=True, portfolio_variance=0.03)
    )
    growth = build_candidate_report(
        _profile_candidate("growth", "growth-1", portfolio_variance=0.05),
        scorecard_row={"status": "scored", "rank": 2},
    )

    report = build_recommendation_report(
        evaluation_id="eval-1", candidate_reports=[defensive, balanced, income, growth]
    )

    assert report["comparisons"][BEST_DEFENSIVE] == "defensive-1"
    assert report["comparisons"][BEST_ENSEMBLE] == "balanced-1"
    assert report["comparisons"][BEST_INCOME] == "income-1"
    assert report["comparisons"][BEST_TOTAL_RETURN] == "balanced-1"
    assert report["comparisons"][BEST_DIVERSIFIED] == "balanced-1"
    assert report["disclaimer"] == NO_GUARANTEE_DISCLAIMER
    assert report["requires_user_approval"] is True
    assert "do not guarantee" in report["disclaimer"].lower()


def test_build_recommendation_report_excludes_infeasible_candidates_with_reasons() -> None:
    good = build_candidate_report(_profile_candidate("balanced", "balanced-1"))
    bad = build_candidate_report(
        _profile_candidate(
            "growth", "growth-1", status="infeasible", weights={}, reasons=["no_history"]
        )
    )

    report = build_recommendation_report(evaluation_id="eval-1", candidate_reports=[good, bad])

    assert len(report["excluded_candidates"]) == 1
    assert report["excluded_candidates"][0]["candidate_id"] == "growth-1"
    assert report["excluded_candidates"][0]["reasons"] == ["no_history"]
    assert report["comparisons"][BEST_TOTAL_RETURN] is None


def test_build_recommendation_report_is_deterministic() -> None:
    candidates = [
        build_candidate_report(_profile_candidate("balanced", "balanced-1")),
        build_candidate_report(_profile_candidate("defensive", "defensive-1")),
    ]

    first = build_recommendation_report(evaluation_id="eval-1", candidate_reports=candidates)
    second = build_recommendation_report(evaluation_id="eval-1", candidate_reports=candidates)

    assert first["recommendation_id"] == second["recommendation_id"]
    assert first == second


def test_build_recommendation_report_records_current_position_comparison_flag() -> None:
    candidates = [build_candidate_report(_profile_candidate("balanced", "balanced-1"))]

    without_current = build_recommendation_report(
        evaluation_id="eval-1", candidate_reports=candidates
    )
    with_current = build_recommendation_report(
        evaluation_id="eval-1", candidate_reports=candidates, current_weights={"IE1": 1.0}
    )

    assert without_current["has_current_position_comparison"] is False
    assert with_current["has_current_position_comparison"] is True
    assert with_current["recommendation_id"] != without_current["recommendation_id"]


def test_render_recommendation_markdown_is_html_safe_and_deterministic() -> None:
    malicious = build_candidate_report(
        _profile_candidate(
            "balanced",
            "balanced-1",
            status="infeasible",
            weights={},
            reasons=["<script>alert(1)</script>"],
        )
    )
    report = build_recommendation_report(evaluation_id="eval-1", candidate_reports=[malicious])

    markdown = render_recommendation_markdown(report)

    assert "<script>" not in markdown
    assert "&lt;script&gt;" in markdown
    assert "requires explicit user approval" in markdown
    assert markdown == render_recommendation_markdown(report)
