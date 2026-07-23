"""Versioned portfolio profile contracts and ensemble candidate construction (PR63).

Builds on already-merged production optimizers (True HRP, Equal Risk
Contribution, Minimum CVaR, and PR63's new shrinkage Minimum Variance) to
construct Defensive/Balanced/Income/Growth profile candidates with explicit
objective sets, constraints, risk limits, and production-eligibility rules.

Income-profile net-income and NAV-erosion limits require the after-tax
cash-flow stack (PR62A is merged; PR62B-PR62F remain open) and are reported
as `unavailable` rather than computed from invented income figures -- see
docs/backlog/eu-tax-cost-architecture.md and BACKLOG.md's PR62A-PR62F entries.

Group and issuer concentration limits are out of scope for this PR: no
group/issuer metadata is currently plumbed through the lake (see BACKLOG.md's
PR63 entry, "group and issuer limits when metadata is available").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from camovar.calculation_status import UNAVAILABLE
from camovar.contract_versioning import stable_contract_id
from camovar.paths import LakePaths
from camovar.portfolio import (
    PortfolioConstraints,
    build_target_weight_rows,
    constraint_violations,
    covariance_map,
    equal_weight_seed,
    hierarchical_risk_parity_weights,
    listing_keys,
    listing_rows,
    minimum_cvar_weights,
    optimize_portfolio,
    portfolio_variance,
    read_covariances,
    require_complete_covariance,
    shrinkage_minimum_variance_weights,
)
from camovar.portfolio_parts.solvers import inverse_volatility_weights, project_capped_simplex
from camovar.table_io import JsonRow, read_rows

PROFILE_CONTRACT_VERSION = 1

DEFENSIVE_PROFILE = "defensive"
BALANCED_PROFILE = "balanced"
INCOME_PROFILE = "income"
GROWTH_PROFILE = "growth"
PROFILE_NAMES = (DEFENSIVE_PROFILE, BALANCED_PROFILE, INCOME_PROFILE, GROWTH_PROFILE)

BALANCED_ENSEMBLE_OBJECTIVES = (
    "hierarchical_risk_parity",
    "equal_risk_contribution",
    "shrinkage_minimum_variance",
)
ENSEMBLE_OBJECTIVE = "balanced_ensemble"

# Objectives with a real production-eligible implementation today. Objectives
# needing a trusted expected-return model (maximum_sharpe) or group/issuer
# metadata remain out of scope until that supporting work lands.
PRODUCTION_ELIGIBLE_SINGLE_OBJECTIVES = frozenset(
    {
        "hierarchical_risk_parity",
        "equal_risk_contribution",
        "shrinkage_minimum_variance",
        "minimum_cvar",
    }
)


@dataclass(frozen=True)
class ProfileRiskLimits:
    """Risk limits for a profile. `None` means "no limit declared"."""

    max_drawdown: float | None = None
    max_cvar: float | None = None
    max_turnover: float | None = None
    # Require the after-tax cash-flow stack (PR62E); reported as `unavailable`
    # until then, never computed from invented income figures.
    min_net_income: float | None = None
    max_nav_erosion: float | None = None


@dataclass(frozen=True)
class ProfileContract:
    """A versioned profile definition: objectives, constraints, and risk limits."""

    name: str
    version: int
    objective_set: tuple[str, ...]
    constraints: PortfolioConstraints
    risk_limits: ProfileRiskLimits = field(default_factory=ProfileRiskLimits)
    requires_income_data: bool = False

    def __post_init__(self) -> None:
        if self.name not in PROFILE_NAMES:
            raise ValueError(f"name must be one of {PROFILE_NAMES}, got {self.name!r}")
        if not self.objective_set:
            raise ValueError("objective_set must be non-empty")


def defensive_profile(*, max_weight: float = 0.15) -> ProfileContract:
    """A capital-preservation-first profile: shrinkage Minimum Variance only."""
    return ProfileContract(
        name=DEFENSIVE_PROFILE,
        version=PROFILE_CONTRACT_VERSION,
        objective_set=("shrinkage_minimum_variance",),
        constraints=PortfolioConstraints(max_weight=max_weight),
        risk_limits=ProfileRiskLimits(max_drawdown=0.15, max_cvar=0.10, max_turnover=0.30),
    )


def balanced_profile(*, max_weight: float = 0.20) -> ProfileContract:
    """The initial Balanced ensemble: median of True HRP, ERC, and shrinkage Minimum Variance."""
    return ProfileContract(
        name=BALANCED_PROFILE,
        version=PROFILE_CONTRACT_VERSION,
        objective_set=BALANCED_ENSEMBLE_OBJECTIVES,
        constraints=PortfolioConstraints(max_weight=max_weight),
        risk_limits=ProfileRiskLimits(max_drawdown=0.25, max_cvar=0.15, max_turnover=0.40),
    )


def income_profile(*, max_weight: float = 0.20) -> ProfileContract:
    """An income-oriented profile: Minimum CVaR for tail-risk-aware capital preservation.

    `min_net_income` and `max_nav_erosion` require the after-tax cash-flow
    stack and are always reported as `unavailable` until PR62E lands.
    """
    return ProfileContract(
        name=INCOME_PROFILE,
        version=PROFILE_CONTRACT_VERSION,
        objective_set=("minimum_cvar",),
        constraints=PortfolioConstraints(max_weight=max_weight),
        risk_limits=ProfileRiskLimits(
            max_drawdown=0.20,
            max_cvar=0.12,
            max_turnover=0.30,
            min_net_income=None,
            max_nav_erosion=None,
        ),
        requires_income_data=True,
    )


def growth_profile(*, max_weight: float = 0.25) -> ProfileContract:
    """A return-seeking profile.

    Uses Equal Risk Contribution as its production-eligible objective today;
    a genuinely return-seeking objective (Maximum Sharpe) remains a grid-only
    comparison method until a trusted expected-return model is chosen and
    tested out of sample (see README.md's "Portfolio Objective" section).
    """
    return ProfileContract(
        name=GROWTH_PROFILE,
        version=PROFILE_CONTRACT_VERSION,
        objective_set=("equal_risk_contribution",),
        constraints=PortfolioConstraints(max_weight=max_weight),
        risk_limits=ProfileRiskLimits(max_drawdown=0.35, max_cvar=0.20, max_turnover=0.50),
    )


def build_balanced_ensemble_weights(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    return_rows: Sequence[Mapping[str, Any]],
    constraints: PortfolioConstraints,
) -> dict[str, float]:
    """Per-asset median of True HRP, Equal Risk Contribution, and shrinkage
    Minimum Variance weights, normalized to sum to one, then projected onto
    the profile's final long-only bounds.
    """
    ordered = listing_keys(listings)
    hrp_weights = hierarchical_risk_parity_weights(listings, covariance_rows, constraints)
    erc_weights = optimize_portfolio(
        listings,
        covariance_rows,
        {},
        objective="equal_risk_contribution",
        constraints=constraints,
        mode="production",
    )
    shrinkage_weights = shrinkage_minimum_variance_weights(listings, return_rows, constraints)

    raw_median = [
        median((hrp_weights[isin], erc_weights[isin], shrinkage_weights[isin]))
        for isin, _, _ in ordered
    ]
    total = sum(raw_median)
    if total <= 0:
        raise ValueError("balanced ensemble median weights summed to zero or less")
    normalized = [value / total for value in raw_median]
    projected = project_capped_simplex(
        normalized, min_weight=constraints.min_weight, max_weight=constraints.max_weight
    )
    return {ordered[index][0]: value for index, value in enumerate(projected)}


def _resolve_single_objective_weights(
    objective: str,
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    return_rows: Sequence[Mapping[str, Any]],
    constraints: PortfolioConstraints,
) -> dict[str, float]:
    if objective == "hierarchical_risk_parity":
        return hierarchical_risk_parity_weights(listings, covariance_rows, constraints)
    if objective == "shrinkage_minimum_variance":
        return shrinkage_minimum_variance_weights(listings, return_rows, constraints)
    if objective == "minimum_cvar":
        return minimum_cvar_weights(listings, return_rows, constraints)
    if objective == "equal_risk_contribution":
        return optimize_portfolio(
            listings,
            covariance_rows,
            {},
            objective="equal_risk_contribution",
            constraints=constraints,
            mode="production",
        )
    raise ValueError(f"objective {objective!r} is not production-eligible in this PR")


def evaluate_profile_candidate(
    profile: ProfileContract,
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    return_rows: Sequence[Mapping[str, Any]],
) -> JsonRow:
    """Compute a profile candidate's weights and structured diagnostics.

    Never raises for expected fail-closed conditions (insufficient history,
    solver non-convergence, incomplete covariance); those are reported as an
    explicit `infeasible`/`blocked` status with reasons instead, per the
    stop-the-line policy ("missing information must produce unavailable,
    blocked, or an explicit baseline status").
    """
    ordered = listing_keys(listings)
    isins = [isin for isin, _, _ in ordered]
    reasons: list[str] = []
    weights: dict[str, float] | None = None
    try:
        if profile.name == BALANCED_PROFILE:
            weights = build_balanced_ensemble_weights(
                listings, covariance_rows, return_rows, profile.constraints
            )
        else:
            unsupported = [
                objective
                for objective in profile.objective_set
                if objective not in PRODUCTION_ELIGIBLE_SINGLE_OBJECTIVES
            ]
            if unsupported:
                raise ValueError(f"objectives not yet production-eligible: {unsupported}")
            weights = _resolve_single_objective_weights(
                profile.objective_set[0],
                listings,
                covariance_rows,
                return_rows,
                profile.constraints,
            )
    except ValueError as error:
        reasons.append(str(error))

    covariances = covariance_map(covariance_rows)
    baselines: dict[str, float] = {}
    try:
        require_complete_covariance(ordered, covariances)
        equal_weights = equal_weight_seed(isins, profile.constraints)
        baselines["equal_weight_variance"] = portfolio_variance(
            ordered, tuple(equal_weights[isin] for isin in isins), covariances
        )
        inverse_vol = inverse_volatility_weights(
            ordered,
            covariances,
            min_weight=profile.constraints.min_weight,
            max_weight=profile.constraints.max_weight,
        )
        baselines["inverse_volatility_variance"] = portfolio_variance(
            ordered, inverse_vol, covariances
        )
    except ValueError as error:
        reasons.append(f"baseline_comparison_unavailable: {error}")

    violations = constraint_violations(weights, profile.constraints) if weights else []
    status = "feasible" if weights is not None and not violations else "infeasible"
    candidate_variance: float | None = None
    if weights is not None and not violations:
        try:
            candidate_variance = portfolio_variance(
                ordered, tuple(weights[isin] for isin in isins), covariances
            )
        except KeyError, ValueError:
            candidate_variance = None

    income_status = UNAVAILABLE if profile.requires_income_data else None
    candidate_id = stable_contract_id(
        f"profile_{profile.name}",
        {
            "profile_version": profile.version,
            "isins": sorted(isins),
            "objective_set": list(profile.objective_set),
            "constraints": profile.constraints.as_dict(),
        },
    )

    return {
        "profile_candidate_id": candidate_id,
        "profile_name": profile.name,
        "profile_version": profile.version,
        "objective_set": list(profile.objective_set),
        "status": status,
        "reasons": reasons,
        "weights": dict(weights) if weights is not None else {},
        "constraint_violations": violations,
        "portfolio_variance": candidate_variance,
        "baseline_comparison": baselines,
        "risk_limits": {
            "max_drawdown": profile.risk_limits.max_drawdown,
            "max_cvar": profile.risk_limits.max_cvar,
            "max_turnover": profile.risk_limits.max_turnover,
            "min_net_income": income_status or profile.risk_limits.min_net_income,
            "max_nav_erosion": income_status or profile.risk_limits.max_nav_erosion,
        },
        "requires_income_data": profile.requires_income_data,
    }


def write_profile_candidate(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    profile: ProfileContract,
) -> list[JsonRow]:
    """Evaluate and persist one profile candidate to the Gold weights dataset."""
    matrix_rows = read_rows(paths.gold_return_matrix(evaluation_id))
    listings = listing_rows(matrix_rows)
    covariance_rows = read_covariances(paths, listings)
    candidate = evaluate_profile_candidate(profile, listings, covariance_rows, matrix_rows)
    weights = candidate["weights"] or equal_weight_seed(
        [str(isin) for isin, _, _ in listing_keys(listings)], profile.constraints
    )
    objective_label = f"profile_{profile.name}"
    return build_target_weight_rows(
        listings,
        weights,
        evaluation_id=evaluation_id,
        objective=objective_label,
        portfolio_id=portfolio_id,
        constraints=profile.constraints,
        diagnostics=candidate,
    )


__all__ = [
    "BALANCED_ENSEMBLE_OBJECTIVES",
    "BALANCED_PROFILE",
    "DEFENSIVE_PROFILE",
    "ENSEMBLE_OBJECTIVE",
    "GROWTH_PROFILE",
    "INCOME_PROFILE",
    "PROFILE_CONTRACT_VERSION",
    "PROFILE_NAMES",
    "ProfileContract",
    "ProfileRiskLimits",
    "balanced_profile",
    "build_balanced_ensemble_weights",
    "defensive_profile",
    "evaluate_profile_candidate",
    "growth_profile",
    "income_profile",
    "write_profile_candidate",
]
