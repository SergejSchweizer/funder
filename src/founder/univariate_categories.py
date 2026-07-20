"""Portfolio-construction categories for univariate statistic fields."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnivariateStatisticCategory:
    """Named field group used to present univariate metrics for portfolio work."""

    key: str
    label: str
    purpose: str
    fields: tuple[str, ...]


UNIVARIATE_PORTFOLIO_CATEGORIES: tuple[UnivariateStatisticCategory, ...] = (
    UnivariateStatisticCategory(
        key="instrument_identity",
        label="Instrument Identity",
        purpose="Identify the listing before deduplication, broker mapping, and portfolio display.",
        fields=("isin", "exchange", "code"),
    ),
    UnivariateStatisticCategory(
        key="history_coverage",
        label="History Coverage",
        purpose="Decide whether a listing has enough aligned history for portfolio inputs.",
        fields=(
            "first_quote_date",
            "last_quote_date",
            "quote_observation_count",
            "first_return_date",
            "last_return_date",
            "return_observation_count",
            "meets_min_history_252",
            "meets_min_history_504",
            "meets_min_history_756",
        ),
    ),
    UnivariateStatisticCategory(
        key="return_level",
        label="Return Level",
        purpose="Rank and sanity-check absolute performance without treating it as a forecast.",
        fields=(
            "start_adjusted_close",
            "end_adjusted_close",
            "total_return",
            "cagr",
            "cumulative_log_return",
            "annualized_return",
            "annualized_log_return",
            "annualized_simple_return",
            "annualized_geometric_return",
        ),
    ),
    UnivariateStatisticCategory(
        key="return_distribution",
        label="Return Distribution",
        purpose="Inspect day-to-day return shape before risk and allocation decisions.",
        fields=(
            "mean_log_return",
            "median_log_return",
            "min_log_return",
            "max_log_return",
            "mean_simple_return",
            "median_simple_return",
            "min_simple_return",
            "max_simple_return",
            "positive_day_ratio",
        ),
    ),
    UnivariateStatisticCategory(
        key="volatility_and_downside",
        label="Volatility And Downside Risk",
        purpose="Screen unstable instruments before covariance, risk-parity, and frontier work.",
        fields=(
            "daily_log_return_std",
            "daily_simple_return_std",
            "annualized_volatility",
            "realized_variance",
            "realized_volatility",
            "downside_deviation",
        ),
    ),
    UnivariateStatisticCategory(
        key="risk_adjusted_performance",
        label="Risk-Adjusted Performance",
        purpose="Compare return per unit of broad or downside risk.",
        fields=("sharpe_ratio", "sortino_ratio"),
    ),
    UnivariateStatisticCategory(
        key="tail_risk",
        label="Tail Risk",
        purpose="Filter instruments with unacceptable historical loss tails.",
        fields=("confidence_level", "var", "expected_shortfall", "tail_observation_count"),
    ),
    UnivariateStatisticCategory(
        key="drawdown_and_trend",
        label="Drawdown And Trend",
        purpose="Assess NAV erosion, recovery risk, and trend quality before portfolio inclusion.",
        fields=("max_drawdown", "log_price_slope", "trend_r_squared"),
    ),
    UnivariateStatisticCategory(
        key="income_distribution",
        label="Income Distribution",
        purpose="Support income portfolios and distinguish distributing from accumulating funds.",
        fields=(
            "distribution_frequency",
            "distribution_events_per_year",
            "last_distribution_date",
            "distribution_observation_count",
        ),
    ),
    UnivariateStatisticCategory(
        key="data_quality_readiness",
        label="Data Quality And Production Readiness",
        purpose="Exclude unreliable listings before portfolio optimization.",
        fields=(
            "availability_reason",
            "quarantined_price_count",
            "non_positive_price_detected",
            "duplicate_date_detected",
            "stale_price_detected",
            "unexplained_gap_detected",
            "production_eligible",
            "data_quality_reason",
        ),
    ),
)


def categorized_univariate_fields() -> tuple[str, ...]:
    """Return every categorized univariate field in portfolio presentation order."""

    return tuple(field for category in UNIVARIATE_PORTFOLIO_CATEGORIES for field in category.fields)


def category_for_univariate_field(field: str) -> UnivariateStatisticCategory | None:
    """Return the portfolio category for one univariate field."""

    for category in UNIVARIATE_PORTFOLIO_CATEGORIES:
        if field in category.fields:
            return category
    return None


__all__ = [
    "UNIVARIATE_PORTFOLIO_CATEGORIES",
    "UnivariateStatisticCategory",
    "categorized_univariate_fields",
    "category_for_univariate_field",
]
