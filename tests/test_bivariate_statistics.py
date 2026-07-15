from pathlib import Path

import pytest

from founder.bivariate_statistics import build_bivariate_statistics, write_bivariate_statistics
from founder.paths import LakePaths
from founder.table_io import read_rows


def _return(isin: str, exchange: str, code: str, date: str, value: float) -> dict[str, object]:
    return {
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "date": date,
        "return": value,
    }


def test_bivariate_statistics_use_common_dates_and_pairwise_metrics(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    returns = [
        _return("IE1", "XETRA", "AAA", "2026-01-01", 0.01),
        _return("IE1", "XETRA", "AAA", "2026-01-02", 0.02),
        _return("IE1", "XETRA", "AAA", "2026-01-03", 0.03),
        _return("IE2", "AS", "BBB", "2026-01-01", 0.03),
        _return("IE2", "AS", "BBB", "2026-01-02", 0.02),
        _return("IE2", "AS", "BBB", "2026-01-03", 0.01),
        _return("IE3", "XETRA", "CCC", "2026-01-02", 0.10),
    ]

    statistics = build_bivariate_statistics(returns)
    written = write_bivariate_statistics(paths, returns)

    assert len(statistics) == 3
    row = statistics[0]
    assert row["left_isin"] == "IE1"
    assert row["right_isin"] == "IE2"
    assert row["left_listing_key"] == "XETRA__IE1__AAA"
    assert row["right_listing_key"] == "AS__IE2__BBB"
    assert row["pair_key"] == "XETRA__IE1__AAA___AS__IE2__BBB"
    assert row["date_start"] == "2026-01-01"
    assert row["date_end"] == "2026-01-03"
    assert row["n_observations"] == 3
    assert row["pearson_correlation"] == pytest.approx(-1.0)
    assert row["covariance"] == pytest.approx(-0.0001)
    assert row["left_variance"] == pytest.approx(0.0001)
    assert row["right_variance"] == pytest.approx(0.0001)
    assert row["left_beta_to_right"] == pytest.approx(-1.0)
    assert row["right_beta_to_left"] == pytest.approx(-1.0)
    assert "spearman_correlation" in row
    assert written == statistics
    assert read_rows(
        paths.gold_bivariate_statistics_pair("XETRA", "IE1", "AAA", "AS", "IE2", "BBB")
    ) == [row]


def test_bivariate_statistics_skip_same_isin_pairs_by_default() -> None:
    returns = [
        _return("IE1", "XETRA", "AAA", "2026-01-01", 0.01),
        _return("IE1", "AS", "BBB", "2026-01-01", 0.02),
    ]

    assert build_bivariate_statistics(returns) == []
    assert len(build_bivariate_statistics(returns, skip_same_isin=False)) == 1
