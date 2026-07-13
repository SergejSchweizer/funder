import csv

import pytest

from founder.docs_refresh import (
    build_docs_refresh_report,
    doc_review_line,
    main,
    write_docs_refresh_report,
)
from founder.portfolio import (
    PortfolioConstraints,
    equal_weight_seed,
    minimum_variance_two_asset_weight,
    validate_weights,
)
from founder.trading import prepare_flatex_orders, write_flatex_orders
from founder.universe_review import currency_exposure, missing_isin_rows, review_universe


def test_portfolio_constraints_validate_seed_and_two_asset_weights() -> None:
    constraints = PortfolioConstraints(max_weight=0.6)
    weights = equal_weight_seed(["IE3", "IE1", "IE2", "IE4", "IE5"], constraints)

    assert list(weights) == ["IE1", "IE2", "IE3", "IE4", "IE5"]
    assert sum(weights.values()) == pytest.approx(1.0)

    two_asset = minimum_variance_two_asset_weight(
        left_variance=0.04,
        right_variance=0.09,
        covariance=0.01,
        constraints=PortfolioConstraints(max_weight=0.8),
    )
    assert two_asset == {
        "left": pytest.approx(0.7272727272727273),
        "right": pytest.approx(0.2727272727272727),
    }

    with pytest.raises(ValueError, match="weights must sum to 1"):
        validate_weights({"IE1": 0.5, "IE2": 0.4}, constraints)


def test_portfolio_constraints_reject_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="min_weight cannot be negative"):
        PortfolioConstraints(min_weight=-0.1)
    with pytest.raises(ValueError, match="max_weight must be positive"):
        PortfolioConstraints(max_weight=0.0)
    with pytest.raises(ValueError, match="min_weight cannot exceed max_weight"):
        PortfolioConstraints(min_weight=0.3, max_weight=0.2)
    with pytest.raises(ValueError, match="min_quote_coverage must be in"):
        PortfolioConstraints(min_quote_coverage=0.0)

    with pytest.raises(ValueError, match="weights are required"):
        validate_weights({}, PortfolioConstraints())
    with pytest.raises(ValueError, match="negative weight"):
        validate_weights({"IE1": -0.1, "IE2": 1.1}, PortfolioConstraints(max_weight=2.0))
    with pytest.raises(ValueError, match="weight below minimum"):
        validate_weights(
            {"IE1": 0.1, "IE2": 0.9}, PortfolioConstraints(min_weight=0.2, max_weight=1.0)
        )
    with pytest.raises(ValueError, match="weight above maximum"):
        validate_weights({"IE1": 0.1, "IE2": 0.9}, PortfolioConstraints(max_weight=0.8))
    with pytest.raises(ValueError, match="at least one ISIN"):
        equal_weight_seed([], PortfolioConstraints())

    equal_split = minimum_variance_two_asset_weight(
        left_variance=0.01,
        right_variance=0.01,
        covariance=0.01,
        constraints=PortfolioConstraints(max_weight=0.8),
    )
    assert equal_split == {"left": 0.5, "right": 0.5}


def test_flatex_orders_are_deterministic_and_exportable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    orders = prepare_flatex_orders(
        [
            {
                "isin": "IE1",
                "code": "AAA",
                "exchange": "XETRA",
                "currency": "EUR",
                "weight": 0.5,
                "price": 33.0,
            },
            {
                "isin": "IE2",
                "code": "BBB",
                "exchange": "AS",
                "currency": "EUR",
                "weight": 0.2,
                "price": 1_000.0,
            },
        ],
        portfolio_value=1_000.0,
        cash_buffer=0.01,
    )

    assert orders[0]["quantity"] == 15
    assert orders[0]["estimated_value"] == 495.0
    assert orders[1]["side"] == "SKIP"

    path = tmp_path / "flatex_orders.csv"
    write_flatex_orders(path, orders)

    with path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows[0]["broker"] == "Flatex"
    assert rows[0]["isin"] == "IE1"


def test_flatex_orders_reject_invalid_inputs() -> None:
    target = {
        "isin": "IE1",
        "code": "AAA",
        "exchange": "XETRA",
        "currency": "EUR",
        "weight": 0.5,
        "price": 33.0,
    }
    with pytest.raises(ValueError, match="portfolio_value must be positive"):
        prepare_flatex_orders([target], portfolio_value=0)
    with pytest.raises(ValueError, match="cash_buffer must be"):
        prepare_flatex_orders([target], portfolio_value=100, cash_buffer=1)
    with pytest.raises(ValueError, match="price must be positive"):
        prepare_flatex_orders([{**target, "price": 0}], portfolio_value=100)


def test_universe_review_flags_missing_isins_currency_and_survivorship() -> None:
    candidates = [
        {"isin": "IE1", "currency": "EUR", "status": "active"},
        {"isin": "IE2", "currency": "USD", "status": "active"},
        {"isin": "", "currency": "GBP", "status": "active"},
    ]
    weights = {"IE1": 0.7, "IE2": 0.3}

    assert len(missing_isin_rows(candidates)) == 1
    assert currency_exposure(candidates, weights) == {"EUR": 0.7, "GBP": 0.0, "USD": 0.3}
    report = review_universe(candidates, weights)
    assert report["missing_isin_rows"] == 1
    assert len(report["warnings"]) == 2


def test_docs_refresh_report_tracks_review_lines(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "docs").mkdir()
    for name in (
        "README.md",
        "ARCHITECTURE.md",
        "RISKS.md",
        "DECISIONS.md",
        "BACKLOG.md",
        "AGENTS.md",
        "docs/lake_contracts.md",
        "docs/search_bronze_workflow.md",
    ):
        (tmp_path / name).write_text("# Doc\n\nLast reviewed: 2026-07-12\n", encoding="utf-8")
    (tmp_path / "RISKS.md").write_text("# Risks\n", encoding="utf-8")

    report = build_docs_refresh_report(tmp_path)
    assert report["missing_review_count"] == 1
    assert report["tracked_docs"]["README.md"]["exists"] is True

    output = tmp_path / "docs" / "docs_refresh_report.json"
    written = write_docs_refresh_report(tmp_path, output)
    assert written == report
    assert output.exists()


def test_docs_refresh_handles_missing_docs_and_cli(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert doc_review_line(tmp_path / "missing.md") == "missing"

    output = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "founder-docs-refresh",
            "--root",
            str(tmp_path),
            "--output",
            str(output),
        ],
    )
    main()

    assert output.exists()
    assert build_docs_refresh_report(tmp_path)["missing_review_count"] == 8
