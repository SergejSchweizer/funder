from datetime import UTC, datetime

import pytest

from camovar.contracts import BronzeError, BronzeRun, CanonicalUniverseRow, SearchCandidate
from camovar.schemas import required_fields, validate_fields


def test_search_candidate_accepts_valid_timezone_aware_record() -> None:
    candidate = SearchCandidate(
        search_run_id="run",
        query="UCITS ETF",
        source_endpoint="search",
        code="CSPX",
        exchange="XETRA",
        instrument_type="ETF",
        country="Germany",
        currency="EUR",
        isin="IE00B5BMR087",
        name="iShares Core S&P 500 UCITS ETF",
        normalized_name="ishares core s&p 500 ucits etf",
        found_at=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert candidate.code == "CSPX"


def test_search_candidate_requires_timezone_aware_found_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SearchCandidate(
            search_run_id="run",
            query="UCITS ETF",
            source_endpoint="search",
            code="CSPX",
            exchange="XETRA",
            instrument_type="ETF",
            country="Germany",
            currency="EUR",
            isin="IE00B5BMR087",
            name="iShares Core S&P 500 UCITS ETF",
            normalized_name="ishares core s&p 500 ucits etf",
            found_at=datetime(2026, 7, 12),
        )


def test_canonical_universe_row_rejects_empty_isin() -> None:
    with pytest.raises(ValueError, match="isin"):
        CanonicalUniverseRow(
            search_run_id="run",
            isin="",
            code="CSPX",
            exchange="XETRA",
            instrument_type="ETF",
            country="Germany",
            currency="EUR",
            name="iShares Core S&P 500 UCITS ETF",
            normalized_name="ishares core s&p 500 ucits etf",
            selection_reason="preferred_xetra",
            selected_for_bronze=True,
        )


def test_canonical_universe_row_must_be_selected_for_bronze() -> None:
    with pytest.raises(ValueError, match="selected for bronze"):
        CanonicalUniverseRow(
            search_run_id="run",
            isin="IE00B5BMR087",
            code="CSPX",
            exchange="XETRA",
            instrument_type="ETF",
            country="Germany",
            currency="EUR",
            name="iShares Core S&P 500 UCITS ETF",
            normalized_name="ishares core s&p 500 ucits etf",
            selection_reason="preferred_xetra",
            selected_for_bronze=False,
        )


def test_bronze_run_and_error_contracts_accept_valid_records() -> None:
    run = BronzeRun(
        run_id="bronze-1",
        universe_search_run_id="search-1",
        started_at=datetime.now(UTC),
    )
    error = BronzeError(
        run_id=run.run_id,
        code="CSPX",
        exchange="XETRA",
        endpoint="eod",
        error_type="HTTPError",
        message="not found",
    )

    assert error.run_id == "bronze-1"


def test_bronze_run_start_uses_timezone_aware_started_at() -> None:
    run = BronzeRun.start("bronze-1", "search-1")

    assert run.started_at.tzinfo is not None


def test_gold_evaluation_schema_contracts_are_registered() -> None:
    assert required_fields("return_matrix") == (
        "evaluation_id",
        "date",
        "isin",
        "exchange",
        "code",
        "return",
        "simple_return",
    )
    assert "annualized_volatility" in required_fields("asset_metrics")
    assert "sharpe_ratio" in required_fields("asset_metrics")
    assert "sortino_ratio" in required_fields("asset_metrics")
    assert "cvar" in required_fields("asset_metrics")
    assert "input_snapshot_date" in required_fields("gold_runs")
    assert "drawdown_duration" in required_fields("drawdowns")
    assert "frontier_point_id" in required_fields("frontier_points")
    assert "weight" in required_fields("frontier_weights")
    assert "split_id" in required_fields("backtests")
    assert "post_cost_return" in required_fields("rebalance_events")
    assert "pre_trade_value" in required_fields("rebalance_events")
    assert "cash_remainder" in required_fields("rebalance_events")
    assert required_fields("rebalance_weights") == (
        "run_id",
        "evaluation_id",
        "portfolio_id",
        "isin",
        "exchange",
        "code",
        "date",
        "pre_trade_value",
        "pre_trade_weight",
        "target_weight",
        "target_value",
        "trade_value",
        "is_rebalance",
    )
    assert "cvar" in required_fields("tail_risk")
    assert "constraints" in required_fields("optimized_weights")
    assert "cluster_variance" in required_fields("hrp_clusters")
    assert "diversification_ratio" in required_fields("diversification_metrics")


def test_gold_evaluation_schema_validation_reports_missing_fields() -> None:
    with pytest.raises(ValueError, match="return_matrix row missing fields: return"):
        validate_fields(
            "return_matrix",
            {
                "evaluation_id": "eval-1",
                "date": "2026-07-13",
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "ETF1",
            },
        )
