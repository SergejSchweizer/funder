"""Explainable recommendation report (PR66).

Compares already-computed profile candidates (`camovar.profiles.evaluate_profile_candidate`
output) and produces a single, deterministic, structured recommendation
report: best Defensive, Balanced (ensemble), Income, Growth (total-return),
most-diversified, and current-portfolio comparison, with human-readable
assumptions, inclusion/exclusion reasons, target weights, drawdown, tail
risk, concentration, turnover, data-quality warnings, model disadvantages,
and production-candidate status.

This module never invents a justification for excluding an instrument or a
data-quality warning: those must be supplied by the caller from an upstream
gate (universe review, return-quality, risk-model diagnostics) and are only
propagated here, never fabricated.

Income quality and broker-cost quality always report `unavailable` pending
the after-tax cash-flow stack (PR62E) and the broker/venue cost engine
(PR62D); this report never invents an income or cost figure.

No result may claim a guaranteed return. `requires_user_approval` is always
`True`: this module produces decision support, not an execution instruction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from camovar.calculation_status import UNAVAILABLE
from camovar.contract_versioning import stable_contract_id
from camovar.table_io import JsonRow

RECOMMENDATION_TEMPLATE_VERSION = 1

NO_GUARANTEE_DISCLAIMER = (
    "This report is decision support only. Past performance and scenario "
    "results do not guarantee future returns. No output in this report is "
    "investment advice or a guaranteed outcome."
)

BEST_DEFENSIVE = "best_defensive"
BEST_DIVERSIFIED = "best_diversified"
BEST_INCOME = "best_income"
BEST_TOTAL_RETURN = "best_total_return"
BEST_ENSEMBLE = "best_ensemble"
COMPARISON_SLOTS = (
    BEST_DEFENSIVE,
    BEST_DIVERSIFIED,
    BEST_INCOME,
    BEST_TOTAL_RETURN,
    BEST_ENSEMBLE,
)


def _turnover(current: Mapping[str, float], candidate: Mapping[str, float]) -> float:
    isins = set(current) | set(candidate)
    return sum(abs(current.get(isin, 0.0) - candidate.get(isin, 0.0)) for isin in isins) / 2.0


def _concentration(weights: Mapping[str, float]) -> float:
    return max(weights.values()) if weights else 0.0


@dataclass(frozen=True)
class CandidateReport:
    """One profile candidate's full explanation for the recommendation report."""

    candidate_id: str
    profile_name: str
    included: bool
    exclusion_reasons: tuple[str, ...]
    weights: Mapping[str, float]
    constraint_violations: tuple[str, ...]
    portfolio_variance: float | None
    max_drawdown: float | None
    var: float | None
    cvar: float | None
    concentration: float | None
    turnover_from_current: float | None
    income_quality: str
    cost_quality: str
    data_quality_warnings: tuple[str, ...]
    disadvantages: tuple[str, ...]
    production_eligible: bool
    scorecard_rank: int | None = None
    sensitivity_worst_drawdown: float | None = None
    sensitivity_worst_cvar: float | None = None

    def as_dict(self) -> JsonRow:
        return {
            "candidate_id": self.candidate_id,
            "profile_name": self.profile_name,
            "included": self.included,
            "exclusion_reasons": list(self.exclusion_reasons),
            "weights": dict(self.weights),
            "constraint_violations": list(self.constraint_violations),
            "portfolio_variance": self.portfolio_variance,
            "max_drawdown": self.max_drawdown,
            "var": self.var,
            "cvar": self.cvar,
            "concentration": self.concentration,
            "turnover_from_current": self.turnover_from_current,
            "income_quality": self.income_quality,
            "cost_quality": self.cost_quality,
            "data_quality_warnings": list(self.data_quality_warnings),
            "disadvantages": list(self.disadvantages),
            "production_eligible": self.production_eligible,
            "scorecard_rank": self.scorecard_rank,
            "sensitivity_worst_drawdown": self.sensitivity_worst_drawdown,
            "sensitivity_worst_cvar": self.sensitivity_worst_cvar,
        }


def build_candidate_report(
    profile_candidate: Mapping[str, Any],
    *,
    scorecard_row: Mapping[str, Any] | None = None,
    sensitivity_summary: Mapping[str, Any] | None = None,
    current_weights: Mapping[str, float] | None = None,
    data_quality_warnings: Sequence[str] = (),
) -> CandidateReport:
    """Build one candidate's explanation from `camovar.profiles.evaluate_profile_candidate`
    output plus optional `camovar.scorecard`/`camovar.stress` traceability and an
    optional current-portfolio comparison. Never recomputes weights or
    optimizer diagnostics; only explains what upstream modules already produced.
    """
    status = str(profile_candidate.get("status", "infeasible"))
    included = status == "feasible"
    exclusion_reasons = tuple(profile_candidate.get("reasons", [])) if not included else ()
    weights = dict(profile_candidate.get("weights") or {})
    disadvantages: list[str] = []
    if not included:
        disadvantages.append("candidate_infeasible")
    violations = tuple(profile_candidate.get("constraint_violations", []))
    if violations:
        disadvantages.append("constraint_violations_present")
    requires_income_data = bool(profile_candidate.get("requires_income_data", False))
    income_quality = UNAVAILABLE if requires_income_data else "not_applicable"
    if requires_income_data:
        disadvantages.append("income_quality_unavailable_pending_after_tax_cashflow_stack")
    cost_quality = UNAVAILABLE
    disadvantages.append("cost_quality_unavailable_pending_broker_cost_engine")

    turnover_from_current = (
        _turnover(current_weights, weights) if current_weights is not None and weights else None
    )
    concentration = _concentration(weights) if weights else None

    scorecard_rank = None
    if scorecard_row is not None:
        scorecard_rank = scorecard_row.get("rank")
        if scorecard_row.get("status") != "scored":
            disadvantages.append("scorecard_status_not_scored")

    sensitivity_worst_drawdown = None
    sensitivity_worst_cvar = None
    if sensitivity_summary is not None:
        sensitivity_worst_drawdown = sensitivity_summary.get("worst_max_drawdown")
        sensitivity_worst_cvar = sensitivity_summary.get("worst_cvar")

    return CandidateReport(
        candidate_id=str(profile_candidate.get("profile_candidate_id", "")),
        profile_name=str(profile_candidate.get("profile_name", "")),
        included=included,
        exclusion_reasons=exclusion_reasons,
        weights=weights,
        constraint_violations=violations,
        portfolio_variance=profile_candidate.get("portfolio_variance"),
        max_drawdown=None,
        var=None,
        cvar=None,
        concentration=concentration,
        turnover_from_current=turnover_from_current,
        income_quality=income_quality,
        cost_quality=cost_quality,
        data_quality_warnings=tuple(data_quality_warnings),
        disadvantages=tuple(disadvantages),
        production_eligible=bool(profile_candidate.get("production_eligible", False)),
        scorecard_rank=scorecard_rank,
        sensitivity_worst_drawdown=sensitivity_worst_drawdown,
        sensitivity_worst_cvar=sensitivity_worst_cvar,
    )


def _select_best(candidates: Sequence[CandidateReport], *, profile_name: str) -> str | None:
    matches = [c for c in candidates if c.profile_name == profile_name and c.included]
    if not matches:
        return None
    return sorted(matches, key=lambda c: c.candidate_id)[0].candidate_id


def _select_best_diversified(candidates: Sequence[CandidateReport]) -> str | None:
    matches = [c for c in candidates if c.included and c.portfolio_variance is not None]
    if not matches:
        return None
    return sorted(matches, key=lambda c: (c.portfolio_variance, c.candidate_id))[0].candidate_id


def _select_best_total_return(candidates: Sequence[CandidateReport]) -> str | None:
    matches = [c for c in candidates if c.included and c.scorecard_rank is not None]
    if not matches:
        return None
    return sorted(matches, key=lambda c: (c.scorecard_rank, c.candidate_id))[0].candidate_id


def build_recommendation_report(
    *,
    evaluation_id: str,
    candidate_reports: Sequence[CandidateReport],
    current_weights: Mapping[str, float] | None = None,
    report_template_version: int = RECOMMENDATION_TEMPLATE_VERSION,
) -> JsonRow:
    """Compare candidate reports and produce the final structured recommendation.

    Deterministic: depends only on the supplied candidate reports (already
    themselves deterministic ids from upstream modules), the optional
    current-position snapshot, and the report template version.
    """
    if not candidate_reports:
        raise ValueError("at least one candidate report is required")
    ordered = sorted(candidate_reports, key=lambda c: c.candidate_id)
    comparisons = {
        BEST_DEFENSIVE: _select_best(ordered, profile_name="defensive"),
        BEST_ENSEMBLE: _select_best(ordered, profile_name="balanced"),
        BEST_INCOME: _select_best(ordered, profile_name="income"),
        BEST_DIVERSIFIED: _select_best_diversified(ordered),
        BEST_TOTAL_RETURN: _select_best_total_return(ordered),
    }
    excluded = [
        {
            "candidate_id": c.candidate_id,
            "profile_name": c.profile_name,
            "reasons": list(c.exclusion_reasons),
        }
        for c in ordered
        if not c.included
    ]
    recommendation_id = stable_contract_id(
        "recommendation",
        {
            "evaluation_id": evaluation_id,
            "report_template_version": report_template_version,
            "candidate_ids": [c.candidate_id for c in ordered],
            "current_weights": dict(sorted((current_weights or {}).items())),
        },
    )
    return {
        "recommendation_id": recommendation_id,
        "evaluation_id": evaluation_id,
        "report_template_version": report_template_version,
        "disclaimer": NO_GUARANTEE_DISCLAIMER,
        "requires_user_approval": True,
        "comparisons": comparisons,
        "candidates": [c.as_dict() for c in ordered],
        "excluded_candidates": excluded,
        "has_current_position_comparison": current_weights is not None,
    }


def _escape_markdown(text: str) -> str:
    """Escape characters that are unsafe to interpolate raw into Markdown/HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|")


def render_recommendation_markdown(report: Mapping[str, Any]) -> str:
    """Render a deterministic, HTML-safe Markdown summary of a recommendation report."""
    lines = [
        f"# Recommendation {_escape_markdown(str(report['recommendation_id']))}",
        "",
        _escape_markdown(str(report["disclaimer"])),
        "",
        "**This report requires explicit user approval before any trade preparation.**",
        "",
        "## Comparisons",
    ]
    for slot in COMPARISON_SLOTS:
        value = report["comparisons"].get(slot)
        label = _escape_markdown(str(value)) if value else "unavailable"
        lines.append(f"- {slot}: {label}")
    lines.append("")
    lines.append("## Candidates")
    for candidate in sorted(report["candidates"], key=lambda c: str(c["candidate_id"])):
        lines.append(
            f"- {_escape_markdown(str(candidate['profile_name']))} "
            f"({_escape_markdown(str(candidate['candidate_id']))}): "
            f"included={candidate['included']}, "
            f"production_eligible={candidate['production_eligible']}"
        )
        for disadvantage in candidate["disadvantages"]:
            lines.append(f"  - disadvantage: {_escape_markdown(str(disadvantage))}")
    if report["excluded_candidates"]:
        lines.append("")
        lines.append("## Excluded Candidates")
        for excluded in report["excluded_candidates"]:
            reasons = ", ".join(_escape_markdown(str(reason)) for reason in excluded["reasons"])
            profile_name = _escape_markdown(str(excluded["profile_name"]))
            lines.append(f"- {profile_name}: {reasons or 'no reason recorded'}")
    return "\n".join(lines)


__all__ = [
    "BEST_DEFENSIVE",
    "BEST_DIVERSIFIED",
    "BEST_ENSEMBLE",
    "BEST_INCOME",
    "BEST_TOTAL_RETURN",
    "COMPARISON_SLOTS",
    "NO_GUARANTEE_DISCLAIMER",
    "RECOMMENDATION_TEMPLATE_VERSION",
    "CandidateReport",
    "build_candidate_report",
    "build_recommendation_report",
    "render_recommendation_markdown",
]
