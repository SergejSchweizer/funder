"""Risk-model covariance estimators and structured diagnostics.

`founder.risk_model` is a pure-computation module: it accepts aligned Gold
return rows and produces dense covariance matrices plus diagnostics for
downstream optimizers (PR59+). It intentionally does not read or write the
lake and does not depend on `founder.evaluation` or `founder.portfolio`, so
those modules can depend on it without creating a cycle.

Three estimators are supported:

- `sample`: the classic unbiased sample covariance (denominator `T - 1`),
  numerically consistent with `founder.gold_pair_stats.sample_covariance`.
- `ledoit_wolf`: Ledoit-Wolf shrinkage toward a scaled-identity target
  (shrinkage intensity chosen analytically from the data, not a fixed
  constant), which is well-conditioned even for small samples.
- `ewma`: an exponentially weighted moving average covariance (RiskMetrics
  style), which weights recent observations more than older ones.

All three read from the same aligned return matrix: a `window_policy` of
`full`, `rolling`, or `expanding` selects which dates within the assets'
common history are used before the estimator runs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any

from founder.contract_versioning import stable_contract_id

ListingKey = tuple[str, str, str]
ReturnsByListing = dict[ListingKey, dict[str, float]]

ALGORITHM_VERSION = 1
BASE_RETURN_FREQUENCY = "daily"
MISSING_OBSERVATION_POLICY = "pairwise_common_date_intersection"
MIN_OBSERVATIONS = 2
MAX_LISTINGS = 200

DEFAULT_EWMA_DECAY = 0.94

ESTIMATORS = ("sample", "ledoit_wolf", "ewma")
WINDOW_POLICIES = ("full", "rolling", "expanding")
RETURN_TYPES = ("log", "simple")

STABILITY_WELL_CONDITIONED = "well_conditioned"
STABILITY_MODERATE = "moderate"
STABILITY_ILL_CONDITIONED = "ill_conditioned"
STABILITY_SINGULAR = "singular"

CONDITION_MODERATE_THRESHOLD = 1_000.0
CONDITION_ILL_THRESHOLD = 1_000_000.0


@dataclass(frozen=True)
class RiskModelDiagnostics:
    estimator: str
    window_policy: str
    return_type: str
    base_return_frequency: str
    first_date: str
    last_date: str
    observation_count: int
    listing_count: int
    missing_pair_count: int
    is_positive_semidefinite: bool
    condition_number: float | None
    stability_category: str
    shrinkage_intensity: float | None
    ewma_decay: float | None
    missing_observation_policy: str
    algorithm_version: int


@dataclass(frozen=True)
class RiskModelResult:
    listings: tuple[ListingKey, ...]
    covariance: tuple[tuple[float, ...], ...]
    diagnostics: RiskModelDiagnostics


def estimate_risk_model(
    return_rows: Sequence[Mapping[str, Any]],
    *,
    listings: Sequence[ListingKey] | None = None,
    estimator: str = "sample",
    window_policy: str = "full",
    window_size: int | None = None,
    as_of: str | None = None,
    return_type: str = "log",
    ewma_decay: float = DEFAULT_EWMA_DECAY,
) -> RiskModelResult:
    """Estimate a dense covariance matrix and diagnostics for `listings`.

    `return_rows` must contain `isin`/`exchange`/`code`/`date` plus a `return`
    (log return) field and, optionally, a `simple_return` field. When
    `listings` is omitted, every listing present in `return_rows` is used.
    """
    if estimator not in ESTIMATORS:
        raise ValueError(f"unknown risk model estimator: {estimator}")
    if return_type not in RETURN_TYPES:
        raise ValueError(f"unknown return type: {return_type}")
    if not 0.0 <= ewma_decay <= 1.0:
        raise ValueError("ewma_decay must be in [0, 1]")

    field = "return" if return_type == "log" else "simple_return"
    returns_by_listing = _index_returns_by_listing(return_rows, field)
    resolved_listings = (
        tuple(listings) if listings is not None else tuple(sorted(returns_by_listing))
    )
    if len(resolved_listings) > MAX_LISTINGS:
        raise ValueError(
            f"risk model estimation is limited to {MAX_LISTINGS} listings, "
            f"got {len(resolved_listings)}"
        )
    for listing in resolved_listings:
        if listing not in returns_by_listing:
            raise ValueError(f"no returns found for listing: {listing}")

    missing_pair_count = _count_missing_pairs(returns_by_listing, resolved_listings)
    raw_common_dates = _common_dates(returns_by_listing, resolved_listings)
    windowed_dates = _apply_window(
        raw_common_dates,
        window_policy=window_policy,
        window_size=window_size,
        as_of=as_of,
    )
    if len(windowed_dates) < MIN_OBSERVATIONS:
        raise ValueError(
            "insufficient common history: need at least "
            f"{MIN_OBSERVATIONS} shared observations, found {len(windowed_dates)}"
        )

    demeaned = _demeaned_matrix(returns_by_listing, resolved_listings, windowed_dates)
    sample_matrix = _sample_covariance_from_demeaned(demeaned)

    shrinkage_intensity: float | None = None
    ewma_decay_used: float | None = None
    if estimator == "sample":
        matrix = sample_matrix
    elif estimator == "ledoit_wolf":
        matrix, shrinkage_intensity = _ledoit_wolf_shrinkage(demeaned, sample_matrix)
    else:
        matrix = _ewma_covariance(demeaned, ewma_decay)
        ewma_decay_used = ewma_decay

    eigenvalues = _jacobi_eigenvalues(matrix)
    is_psd = _is_positive_semidefinite(eigenvalues)
    condition_number, stability_category = _condition_diagnostics(eigenvalues, is_psd)

    diagnostics = RiskModelDiagnostics(
        estimator=estimator,
        window_policy=window_policy,
        return_type=return_type,
        base_return_frequency=BASE_RETURN_FREQUENCY,
        first_date=windowed_dates[0],
        last_date=windowed_dates[-1],
        observation_count=len(windowed_dates),
        listing_count=len(resolved_listings),
        missing_pair_count=missing_pair_count,
        is_positive_semidefinite=is_psd,
        condition_number=condition_number,
        stability_category=stability_category,
        shrinkage_intensity=shrinkage_intensity,
        ewma_decay=ewma_decay_used,
        missing_observation_policy=MISSING_OBSERVATION_POLICY,
        algorithm_version=ALGORITHM_VERSION,
    )
    return RiskModelResult(
        listings=resolved_listings,
        covariance=tuple(tuple(row) for row in matrix),
        diagnostics=diagnostics,
    )


def risk_model_id(
    *,
    listing_keys: Sequence[ListingKey],
    return_type: str,
    estimator: str,
    window_policy: str,
    estimator_parameters: Mapping[str, float] | None = None,
    calendar_id: str = "",
    membership_id: str = "",
) -> str:
    """Return a deterministic id for a risk-model artifact.

    The id depends only on pinned identities and versioned settings, matching
    the Determinism policy for this PR series: worker order, dict order, and
    filesystem discovery order cannot affect it.
    """
    payload: dict[str, Any] = {
        "algorithm_version": ALGORITHM_VERSION,
        "calendar_id": calendar_id,
        "estimator": estimator,
        "estimator_parameters": dict(sorted((estimator_parameters or {}).items())),
        "listing_keys": [list(key) for key in sorted(listing_keys)],
        "membership_id": membership_id,
        "return_type": return_type,
        "window_policy": window_policy,
    }
    return stable_contract_id("risk_model", payload)


def _index_returns_by_listing(
    return_rows: Sequence[Mapping[str, Any]], field: str
) -> ReturnsByListing:
    indexed: ReturnsByListing = {}
    for row in return_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        value = float(row[field]) if field in row else float(row["return"])
        indexed.setdefault(key, {})[str(row["date"])] = value
    return indexed


def _common_dates(
    returns_by_listing: ReturnsByListing, listings: Sequence[ListingKey]
) -> tuple[str, ...]:
    if not listings:
        return ()
    common = set(returns_by_listing[listings[0]])
    for listing in listings[1:]:
        common &= set(returns_by_listing[listing])
    return tuple(sorted(common))


def _count_missing_pairs(
    returns_by_listing: ReturnsByListing, listings: Sequence[ListingKey]
) -> int:
    missing = 0
    for i in range(len(listings)):
        left_dates = set(returns_by_listing[listings[i]])
        for j in range(i + 1, len(listings)):
            right_dates = set(returns_by_listing[listings[j]])
            if len(left_dates & right_dates) < MIN_OBSERVATIONS:
                missing += 1
    return missing


def _apply_window(
    dates: tuple[str, ...],
    *,
    window_policy: str,
    window_size: int | None,
    as_of: str | None,
) -> tuple[str, ...]:
    if window_policy not in WINDOW_POLICIES:
        raise ValueError(f"unknown window policy: {window_policy}")
    if not dates:
        return dates
    end_index = len(dates) - 1
    if as_of is not None:
        if window_policy == "full":
            raise ValueError("as_of is not supported for the full window policy")
        if as_of not in dates:
            raise ValueError(f"as_of date not in common history: {as_of}")
        end_index = dates.index(as_of)
    if window_policy == "full":
        return dates
    if window_policy == "expanding":
        return dates[: end_index + 1]
    if window_size is None or window_size < 1:
        raise ValueError("rolling window policy requires a positive window_size")
    start_index = max(0, end_index - window_size + 1)
    return dates[start_index : end_index + 1]


def _demeaned_matrix(
    returns_by_listing: ReturnsByListing,
    listings: Sequence[ListingKey],
    dates: Sequence[str],
) -> list[list[float]]:
    series: list[list[float]] = []
    means: list[float] = []
    for listing in listings:
        values = [returns_by_listing[listing][date] for date in dates]
        series.append(values)
        means.append(sum(values) / len(values) if values else 0.0)
    listing_count = len(listings)
    return [[series[i][t] - means[i] for i in range(listing_count)] for t in range(len(dates))]


def _sample_covariance_from_demeaned(demeaned: Sequence[Sequence[float]]) -> list[list[float]]:
    observation_count = len(demeaned)
    listing_count = len(demeaned[0]) if observation_count else 0
    denominator = max(observation_count - 1, 1)
    matrix = [[0.0] * listing_count for _ in range(listing_count)]
    for i in range(listing_count):
        for j in range(i, listing_count):
            value = sum(demeaned[t][i] * demeaned[t][j] for t in range(observation_count))
            value /= denominator
            matrix[i][j] = value
            matrix[j][i] = value
    return matrix


def _ledoit_wolf_shrinkage(
    demeaned: Sequence[Sequence[float]], sample_matrix: Sequence[Sequence[float]]
) -> tuple[list[list[float]], float]:
    """Shrink `sample_matrix` toward a scaled-identity target (Ledoit-Wolf, 2004)."""
    listing_count = len(sample_matrix)
    observation_count = len(demeaned)
    if listing_count == 0:
        return [], 0.0
    mu = sum(sample_matrix[i][i] for i in range(listing_count)) / listing_count
    target = [[mu if i == j else 0.0 for j in range(listing_count)] for i in range(listing_count)]
    delta = (
        sum(
            (sample_matrix[i][j] - target[i][j]) ** 2
            for i in range(listing_count)
            for j in range(listing_count)
        )
        / listing_count
    )
    if delta <= 0.0 or observation_count < 2:
        return [list(row) for row in sample_matrix], 0.0
    beta_sum = 0.0
    for t in range(observation_count):
        row = demeaned[t]
        for i in range(listing_count):
            xi = row[i]
            for j in range(listing_count):
                diff = xi * row[j] - sample_matrix[i][j]
                beta_sum += diff * diff
    beta_hat = (beta_sum / (observation_count * observation_count)) / listing_count
    shrinkage = max(0.0, min(1.0, min(beta_hat, delta) / delta))
    shrunk = [
        [
            shrinkage * target[i][j] + (1.0 - shrinkage) * sample_matrix[i][j]
            for j in range(listing_count)
        ]
        for i in range(listing_count)
    ]
    return shrunk, shrinkage


def _ewma_covariance(demeaned: Sequence[Sequence[float]], decay: float) -> list[list[float]]:
    observation_count = len(demeaned)
    listing_count = len(demeaned[0]) if observation_count else 0
    if observation_count == 0 or listing_count == 0:
        return [[0.0] * listing_count for _ in range(listing_count)]
    first = demeaned[0]
    sigma = [[first[i] * first[j] for j in range(listing_count)] for i in range(listing_count)]
    for t in range(1, observation_count):
        row = demeaned[t]
        for i in range(listing_count):
            xi = row[i]
            for j in range(listing_count):
                sigma[i][j] = decay * sigma[i][j] + (1.0 - decay) * (xi * row[j])
    return sigma


def _jacobi_eigenvalues(
    matrix: Sequence[Sequence[float]], *, max_sweeps: int = 200, tolerance: float = 1e-14
) -> list[float]:
    """Return the eigenvalues of a symmetric matrix via the classical Jacobi method."""
    n = len(matrix)
    if n == 0:
        return []
    a = [list(row) for row in matrix]
    if n == 1:
        return [a[0][0]]
    total_norm = sum(a[i][j] * a[i][j] for i in range(n) for j in range(n))
    threshold = tolerance * max(total_norm, 1.0)
    for _sweep in range(max_sweeps):
        off_diagonal = sum(a[i][j] * a[i][j] for i in range(n) for j in range(n) if i != j)
        if off_diagonal < threshold:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                apq = a[p][q]
                if abs(apq) < 1e-15:
                    continue
                app = a[p][p]
                aqq = a[q][q]
                theta = (aqq - app) / (2.0 * apq)
                sign = 1.0 if theta >= 0 else -1.0
                t = sign / (abs(theta) + sqrt(theta * theta + 1.0))
                c = 1.0 / sqrt(t * t + 1.0)
                s = t * c
                a[p][p] = c * c * app - 2.0 * s * c * apq + s * s * aqq
                a[q][q] = s * s * app + 2.0 * s * c * apq + c * c * aqq
                a[p][q] = 0.0
                a[q][p] = 0.0
                for i in range(n):
                    if i != p and i != q:
                        aip = a[i][p]
                        aiq = a[i][q]
                        a[i][p] = c * aip - s * aiq
                        a[p][i] = a[i][p]
                        a[i][q] = s * aip + c * aiq
                        a[q][i] = a[i][q]
    return [a[i][i] for i in range(n)]


def _is_positive_semidefinite(eigenvalues: Sequence[float], *, tolerance: float = 1e-8) -> bool:
    if not eigenvalues:
        return True
    scale = max(abs(value) for value in eigenvalues) or 1.0
    return all(value >= -tolerance * scale for value in eigenvalues)


def _condition_diagnostics(eigenvalues: Sequence[float], is_psd: bool) -> tuple[float | None, str]:
    if not eigenvalues:
        return None, STABILITY_SINGULAR
    magnitudes = [abs(value) for value in eigenvalues]
    largest = max(magnitudes)
    smallest = min(magnitudes)
    if not is_psd or largest == 0.0 or smallest <= largest * 1e-6:
        return None, STABILITY_SINGULAR
    condition_number = largest / smallest
    if condition_number <= CONDITION_MODERATE_THRESHOLD:
        category = STABILITY_WELL_CONDITIONED
    elif condition_number <= CONDITION_ILL_THRESHOLD:
        category = STABILITY_MODERATE
    else:
        category = STABILITY_ILL_CONDITIONED
    return condition_number, category


__all__ = [
    "ALGORITHM_VERSION",
    "BASE_RETURN_FREQUENCY",
    "DEFAULT_EWMA_DECAY",
    "MIN_OBSERVATIONS",
    "MISSING_OBSERVATION_POLICY",
    "RiskModelDiagnostics",
    "RiskModelResult",
    "estimate_risk_model",
    "risk_model_id",
]
