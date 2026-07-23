"""Pure-Python single-linkage hierarchical clustering for True HRP (PR61).

Implements the actual mathematics behind the "Mandatory Amendments To PR61"
in `docs/backlog/00-critical-correctness-priority-queue.md`: correlation
distance, an explicit hierarchical clustering/linkage method, a deterministic
quasi-diagonal asset order derived from the linkage tree, and recursive
bisection along that order using inverse-variance intra-cluster weights
(Lopez de Prado's standard Hierarchical Risk Parity construction).

Per the "Architecture Ownership" principle, this real implementation lives in
a `portfolio_parts` module rather than being dynamically re-imported from the
`camovar.portfolio` facade. The repository has no numerical runtime
dependency (pyarrow only); this module hand-implements clustering rather than
depending on scipy, matching the precedent set by `camovar.risk_model`'s
Jacobi eigenvalue solver and `camovar.portfolio_parts.solvers`'s projected
gradient descent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

LINKAGE_METHOD = "single"
TIE_BREAKING_POLICY = "lowest_cluster_id_pair_first"
ALGORITHM_VERSION = 1


@dataclass(frozen=True)
class LinkageStep:
    """One merge step of the dendrogram, in scipy-`linkage`-like form."""

    left: int
    right: int
    distance: float
    size: int


def correlation_distance_matrix(covariance: Sequence[Sequence[float]]) -> list[list[float]]:
    """Return the standard HRP correlation-distance matrix: `sqrt(0.5*(1-corr))`.

    This maps correlation in `[-1, 1]` to a proper metric distance in
    `[0, 1]`: identical assets (`corr=1`) have distance 0, and perfectly
    anti-correlated assets (`corr=-1`) have the maximum distance of 1.
    """
    n = len(covariance)
    correlation = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            denominator = sqrt(covariance[i][i] * covariance[j][j])
            value = 1.0 if denominator == 0 else covariance[i][j] / denominator
            correlation[i][j] = max(-1.0, min(1.0, value))
    return [[sqrt(max(0.0, 0.5 * (1.0 - correlation[i][j]))) for j in range(n)] for i in range(n)]


def single_linkage(distance_matrix: Sequence[Sequence[float]]) -> tuple[LinkageStep, ...]:
    """Agglomerative single-linkage clustering over a distance matrix.

    Returns `n - 1` merge steps for `n` leaves (leaf ids `0..n-1`; each merge
    creates a new cluster id `n, n+1, ...`, in scipy `linkage`-like form).
    Ties are broken deterministically by the lowest `(left, right)` cluster
    id pair, so results depend only on the input distance matrix and
    canonical leaf order, never on iteration or dict ordering.
    """
    n = len(distance_matrix)
    if n <= 1:
        return ()
    active: list[int] = list(range(n))
    distance: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            distance[(i, j)] = distance_matrix[i][j]
    sizes: dict[int, int] = dict.fromkeys(range(n), 1)
    steps: list[LinkageStep] = []
    next_id = n
    while len(active) > 1:
        best_key: tuple[int, int] | None = None
        best_distance = 0.0
        for a_index in range(len(active)):
            for b_index in range(a_index + 1, len(active)):
                left, right = active[a_index], active[b_index]
                key: tuple[int, int] = (left, right) if left < right else (right, left)
                value = distance[key]
                if (
                    best_key is None
                    or value < best_distance - 1e-15
                    or (abs(value - best_distance) <= 1e-15 and key < best_key)
                ):
                    best_key = key
                    best_distance = value
        if best_key is None:
            raise RuntimeError("single_linkage: no candidate pair found with >= 2 active clusters")
        left, right = best_key
        new_id = next_id
        next_id += 1
        steps.append(
            LinkageStep(
                left=left, right=right, distance=best_distance, size=sizes[left] + sizes[right]
            )
        )
        sizes[new_id] = sizes[left] + sizes[right]
        remaining: list[int] = [cluster for cluster in active if cluster not in (left, right)]
        for other in remaining:
            key_left: tuple[int, int] = (left, other) if left < other else (other, left)
            key_right: tuple[int, int] = (right, other) if right < other else (other, right)
            new_key: tuple[int, int] = (new_id, other) if new_id < other else (other, new_id)
            distance[new_key] = min(distance[key_left], distance[key_right])
        active = [*remaining, new_id]
    return tuple(steps)


def quasi_diagonal_order(linkage: Sequence[LinkageStep], leaf_count: int) -> tuple[int, ...]:
    """Return the deterministic HRP quasi-diagonal leaf order from `linkage`.

    Recursively expands the final (root) cluster into its ordered leaves by
    always visiting the `left` child before the `right` child, so correlated
    assets that merged early end up adjacent in the returned order.
    """
    if leaf_count <= 1:
        return tuple(range(leaf_count))
    if not linkage:
        return tuple(range(leaf_count))
    steps_by_id = {leaf_count + index: step for index, step in enumerate(linkage)}

    def expand(cluster_id: int) -> list[int]:
        if cluster_id < leaf_count:
            return [cluster_id]
        step = steps_by_id[cluster_id]
        return expand(step.left) + expand(step.right)

    root_id = leaf_count + len(linkage) - 1
    return tuple(expand(root_id))


def inverse_variance_weights(
    cluster: Sequence[int], covariance: Sequence[Sequence[float]]
) -> list[float]:
    """Intra-cluster weights inversely proportional to each asset's variance."""
    inverse = [1.0 / covariance[i][i] if covariance[i][i] > 0 else 0.0 for i in cluster]
    total = sum(inverse)
    if total <= 0:
        return [1.0 / len(cluster)] * len(cluster)
    return [value / total for value in inverse]


def cluster_variance(cluster: Sequence[int], covariance: Sequence[Sequence[float]]) -> float:
    """Inverse-variance-weighted portfolio variance of a cluster (Lopez de Prado)."""
    if not cluster:
        return 0.0
    weights = inverse_variance_weights(cluster, covariance)
    return sum(
        weights[i] * weights[j] * covariance[cluster[i]][cluster[j]]
        for i in range(len(cluster))
        for j in range(len(cluster))
    )


@dataclass(frozen=True)
class BisectionSplit:
    """One recursive-bisection split, used both for allocation and diagnostics."""

    cluster_id: str
    left_members: tuple[int, ...]
    right_members: tuple[int, ...]
    left_variance: float
    right_variance: float
    left_allocation: float
    right_allocation: float


def recursive_bisection(
    order: Sequence[int], covariance: Sequence[Sequence[float]]
) -> tuple[dict[int, float], tuple[BisectionSplit, ...]]:
    """Standard HRP recursive bisection over a quasi-diagonalized leaf order.

    At each step, a contiguous cluster is split into two contiguous halves by
    count (not by re-deriving the exact linkage bifurcation point -- this
    count-based split over the quasi-diagonal order is the standard Lopez de
    Prado HRP construction), and capital is allocated between the halves in
    inverse proportion to their inverse-variance-weighted cluster variance.
    """
    weights = {leaf: 1.0 for leaf in order}
    splits: list[BisectionSplit] = []

    def recurse(cluster: tuple[int, ...], path: str) -> None:
        if len(cluster) <= 1:
            return
        midpoint = len(cluster) // 2
        left, right = cluster[:midpoint], cluster[midpoint:]
        left_variance = cluster_variance(left, covariance)
        right_variance = cluster_variance(right, covariance)
        total = left_variance + right_variance
        left_allocation = 0.5 if total == 0 else right_variance / total
        right_allocation = 1.0 - left_allocation
        for leaf in left:
            weights[leaf] *= left_allocation
        for leaf in right:
            weights[leaf] *= right_allocation
        splits.append(
            BisectionSplit(
                cluster_id=path,
                left_members=left,
                right_members=right,
                left_variance=left_variance,
                right_variance=right_variance,
                left_allocation=left_allocation,
                right_allocation=right_allocation,
            )
        )
        recurse(left, f"{path}L")
        recurse(right, f"{path}R")

    recurse(tuple(order), "root")
    return weights, tuple(splits)


__all__ = [
    "ALGORITHM_VERSION",
    "LINKAGE_METHOD",
    "TIE_BREAKING_POLICY",
    "BisectionSplit",
    "LinkageStep",
    "cluster_variance",
    "correlation_distance_matrix",
    "inverse_variance_weights",
    "quasi_diagonal_order",
    "recursive_bisection",
    "single_linkage",
]
