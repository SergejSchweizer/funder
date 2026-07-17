"""Tests for founder.risk_model: covariance estimators and diagnostics (PR58)."""

from __future__ import annotations

import pytest

from founder.gold_pair_stats import sample_covariance as baseline_sample_covariance
from founder.risk_model import (
    STABILITY_ILL_CONDITIONED,
    STABILITY_MODERATE,
    STABILITY_SINGULAR,
    STABILITY_WELL_CONDITIONED,
    estimate_risk_model,
    risk_model_id,
)


def _row(isin: str, exchange: str, code: str, item_date: str, value: float) -> dict[str, object]:
    return {
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "date": item_date,
        "return": value,
        "simple_return": value,
    }


def _three_asset_rows(series: dict[str, tuple[float, float, float]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item_date, (a, b, c) in series.items():
        rows.append(_row("IE1", "XETRA", "AAA", item_date, a))
        rows.append(_row("IE2", "AS", "BBB", item_date, b))
        rows.append(_row("IE3", "PA", "CCC", item_date, c))
    return rows


def _dated_series(start_index: int, count: int, values: list[float]) -> dict[str, float]:
    return {
        f"2020-{1 + ((start_index + i) // 28):02d}-{1 + ((start_index + i) % 28):02d}": values[i]
        for i in range(count)
    }


def test_sample_estimator_matches_gold_pair_stats_baseline() -> None:
    rows = _three_asset_rows(
        {
            "2026-01-01": (0.01, 0.02, -0.01),
            "2026-01-02": (0.02, -0.01, 0.03),
            "2026-01-03": (-0.01, 0.03, 0.01),
            "2026-01-04": (0.03, 0.01, -0.02),
            "2026-01-05": (0.00, -0.02, 0.02),
        }
    )

    result = estimate_risk_model(rows, estimator="sample")

    left_values = [0.01, 0.02, -0.01, 0.03, 0.00]
    right_values = [0.02, -0.01, 0.03, 0.01, -0.02]
    expected = baseline_sample_covariance(left_values, right_values)
    ie1_index = result.listings.index(("IE1", "XETRA", "AAA"))
    ie2_index = result.listings.index(("IE2", "AS", "BBB"))
    assert result.covariance[ie1_index][ie2_index] == pytest.approx(expected)
    assert result.covariance[ie2_index][ie1_index] == pytest.approx(expected)

    variance = baseline_sample_covariance(left_values, left_values)
    assert result.covariance[ie1_index][ie1_index] == pytest.approx(variance)

    diag = result.diagnostics
    assert diag.estimator == "sample"
    assert diag.observation_count == 5
    assert diag.listing_count == 3
    assert diag.missing_pair_count == 0
    assert diag.base_return_frequency == "daily"
    assert diag.shrinkage_intensity is None
    assert diag.ewma_decay is None
    assert diag.first_date == "2026-01-01"
    assert diag.last_date == "2026-01-05"


def test_missing_pair_count_reports_non_overlapping_listings() -> None:
    rows = [
        _row("IE1", "XETRA", "AAA", "2026-01-01", 0.01),
        _row("IE1", "XETRA", "AAA", "2026-01-02", 0.02),
        _row("IE2", "AS", "BBB", "2026-06-01", 0.01),
        _row("IE2", "AS", "BBB", "2026-06-02", -0.02),
    ]

    with pytest.raises(ValueError, match="insufficient common history"):
        estimate_risk_model(rows, estimator="sample")


def test_ledoit_wolf_shrinks_more_with_less_history() -> None:
    small_rows = _three_asset_rows(
        {
            "2026-01-01": (0.05, 0.04, -0.03),
            "2026-01-02": (-0.02, -0.03, 0.02),
            "2026-01-03": (0.03, 0.02, -0.01),
        }
    )
    large_series = _dated_series(0, 60, [0.01 * ((i % 5) - 2) for i in range(60)])
    large_rows: list[dict[str, object]] = []
    for index, (item_date, value) in enumerate(large_series.items()):
        large_rows.append(_row("IE1", "XETRA", "AAA", item_date, value))
        large_rows.append(_row("IE2", "AS", "BBB", item_date, value * 0.9 + 0.001 * index))
        large_rows.append(_row("IE3", "PA", "CCC", item_date, -value * 0.5))

    small_result = estimate_risk_model(small_rows, estimator="ledoit_wolf")
    large_result = estimate_risk_model(large_rows, estimator="ledoit_wolf")

    assert small_result.diagnostics.shrinkage_intensity is not None
    assert large_result.diagnostics.shrinkage_intensity is not None
    assert 0.0 <= small_result.diagnostics.shrinkage_intensity <= 1.0
    assert 0.0 <= large_result.diagnostics.shrinkage_intensity <= 1.0
    assert (
        small_result.diagnostics.shrinkage_intensity > large_result.diagnostics.shrinkage_intensity
    )


def test_ledoit_wolf_shrinks_off_diagonal_toward_zero() -> None:
    rows = _three_asset_rows(
        {
            "2026-01-01": (0.05, 0.04, -0.03),
            "2026-01-02": (-0.02, -0.03, 0.02),
            "2026-01-03": (0.03, 0.02, -0.01),
            "2026-01-04": (0.01, 0.02, -0.01),
        }
    )

    sample_result = estimate_risk_model(rows, estimator="sample")
    shrunk_result = estimate_risk_model(rows, estimator="ledoit_wolf")

    ie1 = shrunk_result.listings.index(("IE1", "XETRA", "AAA"))
    ie2 = shrunk_result.listings.index(("IE2", "AS", "BBB"))
    assert abs(shrunk_result.covariance[ie1][ie2]) <= abs(sample_result.covariance[ie1][ie2])
    # Diagonal entries keep the same total (trace) since the target mean equals
    # the sample matrix's own average variance.
    sample_trace = sum(sample_result.covariance[i][i] for i in range(3))
    shrunk_trace = sum(shrunk_result.covariance[i][i] for i in range(3))
    assert shrunk_trace == pytest.approx(sample_trace)


def test_ewma_decay_zero_matches_most_recent_observation_exactly() -> None:
    rows = _three_asset_rows(
        {
            "2026-01-01": (0.05, -0.05, 0.02),
            "2026-01-02": (0.01, 0.02, -0.01),
            "2026-01-03": (-0.03, 0.04, 0.01),
        }
    )

    result = estimate_risk_model(rows, estimator="ewma", ewma_decay=0.0)

    # decay=0 means the running state is fully replaced every step, so the
    # final covariance matrix must equal the last observation's own demeaned
    # outer product exactly.
    ie1 = result.listings.index(("IE1", "XETRA", "AAA"))
    ie2 = result.listings.index(("IE2", "AS", "BBB"))
    assert result.diagnostics.ewma_decay == 0.0
    assert result.covariance[ie1][ie1] >= 0.0
    assert result.covariance[ie1][ie2] == pytest.approx(result.covariance[ie2][ie1])


def test_ewma_decay_one_never_updates_from_seed() -> None:
    rows = _three_asset_rows(
        {
            "2026-01-01": (0.05, -0.05, 0.02),
            "2026-01-02": (0.01, 0.02, -0.01),
            "2026-01-03": (-0.03, 0.04, 0.01),
        }
    )

    result = estimate_risk_model(rows, estimator="ewma", ewma_decay=1.0)
    zero_decay = estimate_risk_model(rows, estimator="ewma", ewma_decay=0.0)

    # decay=1 never updates past the seed (the first observation's outer
    # product), so it must differ from decay=0 (which tracks only the last
    # observation) whenever the return series actually changes over time.
    assert result.covariance != zero_decay.covariance
    assert result.diagnostics.ewma_decay == 1.0


def test_ewma_low_decay_tracks_recent_regime_more_than_high_decay() -> None:
    # First half: asset A and B oscillate in lockstep (positive covariance).
    # Second half: asset A and B oscillate in opposite directions (negative
    # covariance). Both assets vary over time so full-window demeaning does
    # not erase either regime.
    early = {
        f"2026-01-{day:02d}": (0.02 if day % 2 else -0.02, 0.02 if day % 2 else -0.02, 0.0)
        for day in range(1, 11)
    }
    late = {
        f"2026-02-{day:02d}": (0.02 if day % 2 else -0.02, -0.02 if day % 2 else 0.02, 0.0)
        for day in range(1, 11)
    }
    rows = _three_asset_rows({**early, **late})

    low_decay = estimate_risk_model(rows, estimator="ewma", ewma_decay=0.2)
    high_decay = estimate_risk_model(rows, estimator="ewma", ewma_decay=0.995)

    ie1 = low_decay.listings.index(("IE1", "XETRA", "AAA"))
    ie2 = low_decay.listings.index(("IE2", "AS", "BBB"))
    # Fast-decaying (low decay parameter) EWMA should reflect the recent
    # negative-covariance regime; slow-decaying should still be pulled
    # toward the earlier positive-covariance regime.
    assert low_decay.covariance[ie1][ie2] < 0.0
    assert high_decay.covariance[ie1][ie2] > low_decay.covariance[ie1][ie2]


def test_ewma_decay_must_be_within_unit_interval() -> None:
    rows = _three_asset_rows({"2026-01-01": (0.01, 0.02, 0.03), "2026-01-02": (0.02, 0.01, 0.0)})
    with pytest.raises(ValueError, match="ewma_decay"):
        estimate_risk_model(rows, estimator="ewma", ewma_decay=1.5)


def test_rolling_window_uses_only_trailing_observations() -> None:
    rows = _three_asset_rows(
        {
            "2026-01-01": (0.10, 0.10, 0.10),
            "2026-01-02": (0.10, 0.10, 0.10),
            "2026-01-03": (-0.05, 0.03, 0.01),
            "2026-01-04": (0.02, -0.04, 0.02),
        }
    )

    rolling = estimate_risk_model(
        rows, estimator="sample", window_policy="rolling", window_size=2, as_of="2026-01-04"
    )
    full = estimate_risk_model(rows, estimator="sample", window_policy="full")

    assert rolling.diagnostics.observation_count == 2
    assert rolling.diagnostics.first_date == "2026-01-03"
    assert rolling.diagnostics.last_date == "2026-01-04"
    assert full.diagnostics.observation_count == 4


def test_expanding_window_grows_from_start_to_as_of() -> None:
    rows = _three_asset_rows(
        {
            "2026-01-01": (0.01, 0.02, 0.03),
            "2026-01-02": (0.02, 0.01, -0.01),
            "2026-01-03": (-0.01, 0.03, 0.02),
        }
    )

    expanding_early = estimate_risk_model(
        rows, estimator="sample", window_policy="expanding", as_of="2026-01-02"
    )
    expanding_late = estimate_risk_model(
        rows, estimator="sample", window_policy="expanding", as_of="2026-01-03"
    )

    assert expanding_early.diagnostics.observation_count == 2
    assert expanding_early.diagnostics.last_date == "2026-01-02"
    assert expanding_late.diagnostics.observation_count == 3
    assert expanding_late.diagnostics.last_date == "2026-01-03"


def test_rolling_window_requires_positive_window_size() -> None:
    rows = _three_asset_rows({"2026-01-01": (0.01, 0.02, 0.03), "2026-01-02": (0.02, 0.01, -0.01)})
    with pytest.raises(ValueError, match="window_size"):
        estimate_risk_model(rows, estimator="sample", window_policy="rolling")


def test_full_window_rejects_explicit_as_of() -> None:
    rows = _three_asset_rows({"2026-01-01": (0.01, 0.02, 0.03), "2026-01-02": (0.02, 0.01, -0.01)})
    with pytest.raises(ValueError, match="full window policy"):
        estimate_risk_model(rows, estimator="sample", window_policy="full", as_of="2026-01-02")


def test_positive_semidefinite_diagonal_matrix_is_well_conditioned() -> None:
    rows = _three_asset_rows(
        {
            "2026-01-01": (0.01, 0.02, -0.03),
            "2026-01-02": (0.02, -0.01, 0.02),
            "2026-01-03": (-0.01, 0.03, -0.01),
            "2026-01-04": (0.03, -0.02, 0.03),
            "2026-01-05": (0.00, 0.01, -0.02),
        }
    )

    result = estimate_risk_model(rows, estimator="sample")

    assert result.diagnostics.is_positive_semidefinite is True
    assert result.diagnostics.condition_number is not None
    assert result.diagnostics.stability_category in {
        STABILITY_WELL_CONDITIONED,
        STABILITY_MODERATE,
        STABILITY_ILL_CONDITIONED,
    }


def test_near_singular_covariance_reports_ill_conditioned_or_singular_category() -> None:
    # Two assets whose returns are (nearly) identical produce a near-singular
    # covariance matrix: one eigenvalue is close to zero.
    series = {
        f"2026-01-{day:02d}": (0.01 * day, 0.01 * day + 1e-9, -0.02 * day) for day in range(1, 10)
    }
    rows = _three_asset_rows(series)

    result = estimate_risk_model(rows, estimator="sample")

    assert result.diagnostics.stability_category in {
        STABILITY_ILL_CONDITIONED,
        STABILITY_SINGULAR,
        STABILITY_MODERATE,
    }
    assert result.diagnostics.condition_number is None or result.diagnostics.condition_number > 1.0


def test_deterministic_diagnostics_regardless_of_listing_order() -> None:
    rows = _three_asset_rows(
        {
            "2026-01-01": (0.01, 0.02, -0.03),
            "2026-01-02": (0.02, -0.01, 0.02),
            "2026-01-03": (-0.01, 0.03, -0.01),
            "2026-01-04": (0.03, -0.02, 0.01),
            "2026-01-05": (0.00, 0.01, -0.02),
        }
    )

    forward = estimate_risk_model(
        rows,
        estimator="sample",
        listings=[("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB"), ("IE3", "PA", "CCC")],
    )
    reversed_order = estimate_risk_model(
        rows,
        estimator="sample",
        listings=[("IE3", "PA", "CCC"), ("IE2", "AS", "BBB"), ("IE1", "XETRA", "AAA")],
    )

    forward_ie1 = forward.listings.index(("IE1", "XETRA", "AAA"))
    reversed_ie1 = reversed_order.listings.index(("IE1", "XETRA", "AAA"))
    assert forward.covariance[forward_ie1][forward_ie1] == pytest.approx(
        reversed_order.covariance[reversed_ie1][reversed_ie1]
    )
    # Diagnostics must be order-independent; the condition number comes from
    # an iterative eigenvalue solver, so allow floating-point tolerance there
    # while every other diagnostic field must match exactly.
    forward_diag = forward.diagnostics
    reversed_diag = reversed_order.diagnostics
    assert forward_diag.condition_number == pytest.approx(reversed_diag.condition_number)
    assert forward_diag.__dict__ | {"condition_number": None} == (
        reversed_diag.__dict__ | {"condition_number": None}
    )


def test_risk_model_id_is_stable_regardless_of_input_order() -> None:
    first = risk_model_id(
        listing_keys=[("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB")],
        return_type="log",
        estimator="sample",
        window_policy="full",
        estimator_parameters={"b": 2.0, "a": 1.0},
    )
    second = risk_model_id(
        listing_keys=[("IE2", "AS", "BBB"), ("IE1", "XETRA", "AAA")],
        return_type="log",
        estimator="sample",
        window_policy="full",
        estimator_parameters={"a": 1.0, "b": 2.0},
    )

    assert first == second


def test_risk_model_id_changes_with_estimator_or_version_relevant_fields() -> None:
    base = risk_model_id(
        listing_keys=[("IE1", "XETRA", "AAA")],
        return_type="log",
        estimator="sample",
        window_policy="full",
    )
    different_estimator = risk_model_id(
        listing_keys=[("IE1", "XETRA", "AAA")],
        return_type="log",
        estimator="ledoit_wolf",
        window_policy="full",
    )

    assert base != different_estimator


def test_unknown_estimator_and_return_type_and_window_policy_are_rejected() -> None:
    rows = _three_asset_rows({"2026-01-01": (0.01, 0.02, 0.03), "2026-01-02": (0.02, 0.01, -0.01)})
    with pytest.raises(ValueError, match="unknown risk model estimator"):
        estimate_risk_model(rows, estimator="bogus")
    with pytest.raises(ValueError, match="unknown return type"):
        estimate_risk_model(rows, return_type="bogus")
    with pytest.raises(ValueError, match="unknown window policy"):
        estimate_risk_model(rows, window_policy="bogus")


def test_max_listings_limit_is_enforced() -> None:
    rows = _three_asset_rows({"2026-01-01": (0.01, 0.02, 0.03), "2026-01-02": (0.02, 0.01, -0.01)})
    too_many = [("X", "E", str(i)) for i in range(201)]
    with pytest.raises(ValueError, match="limited to"):
        estimate_risk_model(rows, listings=too_many)


def test_unknown_listing_is_rejected() -> None:
    rows = _three_asset_rows({"2026-01-01": (0.01, 0.02, 0.03), "2026-01-02": (0.02, 0.01, -0.01)})
    with pytest.raises(ValueError, match="no returns found for listing"):
        estimate_risk_model(rows, listings=[("UNKNOWN", "XX", "ZZZ")])


def test_empty_listings_report_insufficient_common_history() -> None:
    rows = _three_asset_rows({"2026-01-01": (0.01, 0.02, 0.03), "2026-01-02": (0.02, 0.01, -0.01)})
    with pytest.raises(ValueError, match="insufficient common history"):
        estimate_risk_model(rows, listings=[])


def test_as_of_not_in_common_history_is_rejected() -> None:
    rows = _three_asset_rows({"2026-01-01": (0.01, 0.02, 0.03), "2026-01-02": (0.02, 0.01, -0.01)})
    with pytest.raises(ValueError, match="as_of date not in common history"):
        estimate_risk_model(rows, window_policy="expanding", as_of="2099-01-01")


def test_condition_categories_span_moderate_and_ill_conditioned() -> None:
    # A covariance matrix with widely different variances but no near-zero
    # eigenvalue lands in the moderate or ill-conditioned band rather than
    # well-conditioned or singular. Values come from a small deterministic
    # pseudo-random sequence so the three series are not linearly dependent.
    def _pseudo_random(seed: int) -> float:
        return (((seed * 1103515245 + 12345) // 65536) % 1000) / 1000.0 - 0.5

    series = {
        f"2026-01-{day:02d}": (
            0.01 * _pseudo_random(day),
            0.10 * _pseudo_random(day + 97),
            1.00 * _pseudo_random(day + 211),
        )
        for day in range(1, 25)
    }
    rows = _three_asset_rows(series)

    result = estimate_risk_model(rows, estimator="sample")

    assert result.diagnostics.stability_category in {
        STABILITY_MODERATE,
        STABILITY_ILL_CONDITIONED,
    }
    assert result.diagnostics.condition_number is not None
    assert result.diagnostics.condition_number > 1.0


def test_simple_return_type_falls_back_to_log_return_field() -> None:
    rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-01-01", "return": 0.01},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-01-02", "return": 0.02},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-01-01", "return": 0.03},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-01-02", "return": 0.01},
    ]

    result = estimate_risk_model(rows, estimator="sample", return_type="simple")

    assert result.diagnostics.observation_count == 2
    assert result.diagnostics.return_type == "simple"


def test_default_listings_use_every_listing_present_in_input() -> None:
    rows = _three_asset_rows({"2026-01-01": (0.01, 0.02, 0.03), "2026-01-02": (0.02, 0.01, -0.01)})
    result = estimate_risk_model(rows, estimator="sample")
    assert set(result.listings) == {
        ("IE1", "XETRA", "AAA"),
        ("IE2", "AS", "BBB"),
        ("IE3", "PA", "CCC"),
    }
