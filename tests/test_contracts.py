from datetime import UTC, datetime

import pytest

from founder.contracts import BronzeError, BronzeRun, CanonicalUniverseRow, SearchCandidate


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
