"""Tests for the PR61 True HRP replacement in camovar.portfolio."""

from pathlib import Path

import pytest

from camovar.paths import LakePaths
from camovar.portfolio import (
    HIERARCHICAL_RISK_PARITY_BASELINE_OBJECTIVE,
    HIERARCHICAL_RISK_PARITY_OBJECTIVE,
    PortfolioConstraints,
    build_hrp_cluster_rows,
    build_hrp_linkage_rows,
    hierarchical_risk_parity_baseline_weights,
    hierarchical_risk_parity_weights,
    write_hierarchical_risk_parity,
    write_hierarchical_risk_parity_baseline,
)
from camovar.table_io import read_rows, write_rows

# A/C are correlated (0.9); B/D are correlated (0.9); canonical ISIN order is
# A,B,C,D, so the naive baseline never puts a correlated pair adjacent, but
# true HRP's quasi-diagonal reordering must.
_LISTINGS = [
    {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},  # A
    {"isin": "IE2", "exchange": "AS", "code": "BBB"},  # B
    {"isin": "IE3", "exchange": "PA", "code": "CCC"},  # C
    {"isin": "IE4", "exchange": "MU", "code": "DDD"},  # D
]


def _covariance_row(left: dict[str, str], right: dict[str, str], value: float) -> dict[str, object]:
    return {
        "left_isin": left["isin"],
        "left_exchange": left["exchange"],
        "left_code": left["code"],
        "right_isin": right["isin"],
        "right_exchange": right["exchange"],
        "right_code": right["code"],
        "covariance": value,
    }


def _covariance_rows() -> list[dict[str, object]]:
    a, b, c, d = _LISTINGS
    # Asymmetric variances so baseline (canonical A,B|C,D split) and true HRP
    # (correlation-clustered A,C|B,D split) produce genuinely different
    # weights, not just a different (but numerically coincidental) order.
    variance = {"IE1": 0.01, "IE2": 0.04, "IE3": 0.09, "IE4": 0.16}
    ac = 0.9 * (variance["IE1"] * variance["IE3"]) ** 0.5  # corr(A,C) = 0.9
    bd = 0.9 * (variance["IE2"] * variance["IE4"]) ** 0.5  # corr(B,D) = 0.9
    rows = []
    listings = [a, b, c, d]
    values = {
        ("IE1", "IE1"): variance["IE1"],
        ("IE2", "IE2"): variance["IE2"],
        ("IE3", "IE3"): variance["IE3"],
        ("IE4", "IE4"): variance["IE4"],
        ("IE1", "IE3"): ac,
        ("IE3", "IE1"): ac,
        ("IE2", "IE4"): bd,
        ("IE4", "IE2"): bd,
    }
    for left in listings:
        for right in listings:
            key = (left["isin"], right["isin"])
            rows.append(_covariance_row(left, right, values.get(key, 0.0)))
    return rows


def test_true_hrp_reorders_correlated_pairs_adjacent_in_cluster_rows() -> None:
    rows = build_hrp_cluster_rows(
        _LISTINGS, _covariance_rows(), evaluation_id="eval-1", portfolio_id="hrp"
    )

    ordered_isins = rows[0]["ordered_isins"].split(",")
    assert ordered_isins == ["IE1", "IE3", "IE2", "IE4"]


def test_true_hrp_cluster_rows_expose_linkage_diagnostics() -> None:
    rows = build_hrp_cluster_rows(
        _LISTINGS, _covariance_rows(), evaluation_id="eval-1", portfolio_id="hrp"
    )

    for row in rows:
        assert row["linkage_method"] == "single"
        assert row["tie_breaking_policy"]
        assert row["algorithm_version"] == 1
        assert "cluster_variance" in row
        assert "allocation" in row


def test_true_hrp_linkage_rows_persist_dendrogram() -> None:
    rows = build_hrp_linkage_rows(
        _LISTINGS, _covariance_rows(), evaluation_id="eval-1", portfolio_id="hrp"
    )

    assert len(rows) == 3  # 4 leaves -> 3 merges
    assert rows[0]["step_index"] == 1
    assert rows[-1]["size"] == 4
    assert {rows[0]["left_cluster_id"], rows[0]["right_cluster_id"]} == {"IE1", "IE3"}
    assert rows[1]["step_index"] == 2
    assert {rows[1]["left_cluster_id"], rows[1]["right_cluster_id"]} == {"IE2", "IE4"}
    for row in rows:
        assert row["linkage_method"] == "single"
        assert row["algorithm_version"] == 1


def test_true_hrp_weights_sum_to_one_and_respect_constraints() -> None:
    constraints = PortfolioConstraints(max_weight=0.4)

    weights = hierarchical_risk_parity_weights(_LISTINGS, _covariance_rows(), constraints)

    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(value <= 0.4 + 1e-9 for value in weights.values())


def test_true_hrp_is_deterministic_across_repeated_calls() -> None:
    constraints = PortfolioConstraints(max_weight=1.0)

    first = hierarchical_risk_parity_weights(_LISTINGS, _covariance_rows(), constraints)
    second = hierarchical_risk_parity_weights(_LISTINGS, _covariance_rows(), constraints)

    assert first == second


def test_baseline_hrp_uses_canonical_order_not_clustering() -> None:
    constraints = PortfolioConstraints(max_weight=1.0)

    baseline_weights = hierarchical_risk_parity_baseline_weights(
        _LISTINGS, _covariance_rows(), constraints
    )
    true_weights = hierarchical_risk_parity_weights(_LISTINGS, _covariance_rows(), constraints)

    assert sum(baseline_weights.values()) == pytest.approx(1.0)
    # The baseline (naive midpoint split on canonical order) and true HRP
    # (correlation-clustered order) must generally disagree for this fixture,
    # since the baseline never discovers the A/C, B/D correlation structure.
    assert baseline_weights != true_weights


def test_write_hierarchical_risk_parity_persists_weights_clusters_and_linkage(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    write_rows(
        paths.gold_return_matrix("eval-1"),
        [
            {
                "evaluation_id": "eval-1",
                "date": "2026-07-11",
                "isin": row["isin"],
                "exchange": row["exchange"],
                "code": row["code"],
                "return": 0.01,
            }
            for row in _LISTINGS
        ],
    )
    for left in _LISTINGS:
        write_rows(
            paths.gold_covariance(left["exchange"], left["isin"]),
            [row for row in _covariance_rows() if row["left_isin"] == left["isin"]],
        )
    constraints = PortfolioConstraints(max_weight=1.0)

    weight_rows, cluster_rows, linkage_rows = write_hierarchical_risk_parity(
        paths, evaluation_id="eval-1", portfolio_id="hrp", constraints=constraints
    )

    assert len(weight_rows) == 4
    assert all(row["objective"] == HIERARCHICAL_RISK_PARITY_OBJECTIVE for row in weight_rows)
    assert read_rows(
        paths.gold_optimized_weights(HIERARCHICAL_RISK_PARITY_OBJECTIVE, "eval-1")
    ) == (weight_rows)
    assert read_rows(paths.gold_hrp_clusters("eval-1")) == cluster_rows
    assert read_rows(paths.gold_hrp_linkage("eval-1")) == linkage_rows
    assert len(linkage_rows) == 3


def test_write_hierarchical_risk_parity_baseline_uses_distinct_objective_and_path(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    write_rows(
        paths.gold_return_matrix("eval-1"),
        [
            {
                "evaluation_id": "eval-1",
                "date": "2026-07-11",
                "isin": row["isin"],
                "exchange": row["exchange"],
                "code": row["code"],
                "return": 0.01,
            }
            for row in _LISTINGS
        ],
    )
    for left in _LISTINGS:
        write_rows(
            paths.gold_covariance(left["exchange"], left["isin"]),
            [row for row in _covariance_rows() if row["left_isin"] == left["isin"]],
        )
    constraints = PortfolioConstraints(max_weight=1.0)

    weight_rows = write_hierarchical_risk_parity_baseline(
        paths, evaluation_id="eval-1", portfolio_id="hrp-baseline", constraints=constraints
    )

    assert all(
        row["objective"] == HIERARCHICAL_RISK_PARITY_BASELINE_OBJECTIVE for row in weight_rows
    )
    assert (
        read_rows(
            paths.gold_optimized_weights(HIERARCHICAL_RISK_PARITY_BASELINE_OBJECTIVE, "eval-1")
        )
        == weight_rows
    )
    # The true-HRP path must never receive baseline output.
    assert (
        read_rows(paths.gold_optimized_weights(HIERARCHICAL_RISK_PARITY_OBJECTIVE, "eval-1")) == []
    )
