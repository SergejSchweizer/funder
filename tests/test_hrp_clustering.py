"""Tests for founder.portfolio_parts.clustering: pure-Python single-linkage
hierarchical clustering and recursive bisection for True HRP (PR61).
"""

from math import sqrt

import pytest

from founder.portfolio_parts.clustering import (
    LinkageStep,
    cluster_variance,
    correlation_distance_matrix,
    inverse_variance_weights,
    quasi_diagonal_order,
    recursive_bisection,
    single_linkage,
)


def test_correlation_distance_matrix_matches_hand_computed_formula() -> None:
    # corr(A,B) = 0.9 -> distance = sqrt(0.5*(1-0.9)) = sqrt(0.05)
    covariance = [[0.01, 0.009], [0.009, 0.01]]

    distance = correlation_distance_matrix(covariance)

    assert distance[0][1] == pytest.approx(sqrt(0.05))
    assert distance[1][0] == pytest.approx(sqrt(0.05))
    assert distance[0][0] == pytest.approx(0.0)
    assert distance[1][1] == pytest.approx(0.0)


def test_correlation_distance_matrix_handles_zero_variance_as_perfect_correlation() -> None:
    # A zero-variance asset produces a zero denominator; treated as corr=1
    # (distance 0) rather than raising or dividing by zero.
    covariance = [[0.0, 0.0], [0.0, 0.01]]

    distance = correlation_distance_matrix(covariance)

    assert distance[0][1] == pytest.approx(0.0)


def test_single_linkage_merges_closest_pair_first_with_deterministic_tie_break() -> None:
    # A/C are correlated (0.9); B/D are correlated (0.9); A/B/C/D otherwise
    # uncorrelated. distance(A,C) == distance(B,D); the lower pair id (0,2)
    # must win the tie deterministically.
    d = sqrt(0.05)
    far = sqrt(0.5)
    distance_matrix = [
        [0.0, far, d, far],
        [far, 0.0, far, d],
        [d, far, 0.0, far],
        [far, d, far, 0.0],
    ]

    linkage = single_linkage(distance_matrix)

    assert len(linkage) == 3
    assert linkage[0] == LinkageStep(left=0, right=2, distance=pytest.approx(d), size=2)
    assert linkage[1] == LinkageStep(left=1, right=3, distance=pytest.approx(d), size=2)
    assert linkage[2].size == 4


def test_single_linkage_of_empty_or_singleton_returns_no_steps() -> None:
    assert single_linkage([]) == ()
    assert single_linkage([[0.0]]) == ()


def test_quasi_diagonal_order_places_correlated_pairs_adjacent() -> None:
    # A/C and B/D are the correlated pairs, but the canonical index order is
    # A,B,C,D (0,1,2,3) -- the naive baseline would never reorder these.
    d = sqrt(0.05)
    far = sqrt(0.5)
    distance_matrix = [
        [0.0, far, d, far],
        [far, 0.0, far, d],
        [d, far, 0.0, far],
        [far, d, far, 0.0],
    ]
    linkage = single_linkage(distance_matrix)

    order = quasi_diagonal_order(linkage, 4)

    assert order == (0, 2, 1, 3)
    # Every correlated pair is now index-adjacent in the returned order.
    assert order.index(0) + 1 == order.index(2) or order.index(2) + 1 == order.index(0)
    assert order.index(1) + 1 == order.index(3) or order.index(3) + 1 == order.index(1)


def test_quasi_diagonal_order_handles_single_leaf() -> None:
    assert quasi_diagonal_order((), 1) == (0,)


def test_inverse_variance_weights_are_proportional_to_inverse_variance() -> None:
    covariance = [[0.01, 0.0], [0.0, 0.04]]

    weights = inverse_variance_weights([0, 1], covariance)

    expected = [(1 / 0.01) / (1 / 0.01 + 1 / 0.04), (1 / 0.04) / (1 / 0.01 + 1 / 0.04)]
    assert weights == pytest.approx(expected)


def test_inverse_variance_weights_fall_back_to_equal_weight_when_all_zero() -> None:
    covariance = [[0.0, 0.0], [0.0, 0.0]]

    weights = inverse_variance_weights([0, 1], covariance)

    assert weights == pytest.approx([0.5, 0.5])


def test_cluster_variance_uses_inverse_variance_weighting() -> None:
    covariance = [[0.01, 0.0], [0.0, 0.04]]
    weights = inverse_variance_weights([0, 1], covariance)
    expected = (
        weights[0] * weights[0] * covariance[0][0]
        + 2 * weights[0] * weights[1] * covariance[0][1]
        + weights[1] * weights[1] * covariance[1][1]
    )

    assert cluster_variance([0, 1], covariance) == pytest.approx(expected)


def test_cluster_variance_of_empty_cluster_is_zero() -> None:
    assert cluster_variance([], [[0.01]]) == 0.0


def test_recursive_bisection_weights_sum_to_one_for_symmetric_fixture() -> None:
    covariance = [
        [0.01, 0.009, 0.0, 0.0],
        [0.009, 0.01, 0.0, 0.0],
        [0.0, 0.0, 0.01, 0.009],
        [0.0, 0.0, 0.009, 0.01],
    ]
    order = (0, 2, 1, 3)

    weights, splits = recursive_bisection(order, covariance)

    assert sum(weights.values()) == pytest.approx(1.0)
    assert (
        weights[0]
        == pytest.approx(weights[1])
        == pytest.approx(weights[2])
        == pytest.approx(weights[3])
    )
    assert len(splits) == 3  # root split + two sub-splits for 4 leaves


def test_recursive_bisection_allocates_more_to_lower_variance_cluster() -> None:
    # Asset 0 has much lower variance than asset 1: minimum-variance-style
    # allocation should favor the lower-variance singleton cluster.
    covariance = [[0.01, 0.0], [0.0, 0.09]]
    order = (0, 1)

    weights, splits = recursive_bisection(order, covariance)

    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights[0] > weights[1]
    assert len(splits) == 1
    assert splits[0].left_members == (0,)
    assert splits[0].right_members == (1,)
    assert splits[0].left_allocation == pytest.approx(0.09 / (0.01 + 0.09))


def test_recursive_bisection_single_leaf_gets_full_allocation() -> None:
    weights, splits = recursive_bisection((0,), [[0.01]])

    assert weights == {0: 1.0}
    assert splits == ()


def test_clustering_is_deterministic_across_repeated_calls() -> None:
    covariance = [
        [0.01, 0.009, 0.0, 0.001],
        [0.009, 0.01, 0.0, 0.0],
        [0.0, 0.0, 0.01, 0.009],
        [0.001, 0.0, 0.009, 0.01],
    ]
    distance = correlation_distance_matrix(covariance)

    first_linkage = single_linkage(distance)
    second_linkage = single_linkage(distance)
    first_order = quasi_diagonal_order(first_linkage, 4)
    second_order = quasi_diagonal_order(second_linkage, 4)

    assert first_linkage == second_linkage
    assert first_order == second_order
