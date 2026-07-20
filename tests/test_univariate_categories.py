from __future__ import annotations

from founder.schemas import required_fields
from founder.univariate_categories import (
    UNIVARIATE_PORTFOLIO_CATEGORIES,
    categorized_univariate_fields,
    category_for_univariate_field,
)


def test_univariate_portfolio_categories_cover_schema_fields_exactly_once() -> None:
    categorized = categorized_univariate_fields()

    assert categorized
    assert len(categorized) == len(set(categorized))
    assert set(categorized) == set(required_fields("univariate_statistics"))


def test_univariate_portfolio_categories_are_decision_oriented() -> None:
    categories = {category.key: category for category in UNIVARIATE_PORTFOLIO_CATEGORIES}

    assert categories["return_level"].label == "Return Level"
    assert "annualized_geometric_return" in categories["return_level"].fields
    assert "expected_shortfall" in categories["tail_risk"].fields
    assert "distribution_frequency" in categories["income_distribution"].fields
    assert "production_eligible" in categories["data_quality_readiness"].fields
    assert category_for_univariate_field("sharpe_ratio") == categories["risk_adjusted_performance"]
    assert category_for_univariate_field("not_a_univariate_field") is None
