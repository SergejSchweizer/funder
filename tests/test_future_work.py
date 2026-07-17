import csv
import json
from pathlib import Path

import pytest

from founder.docs_refresh import (
    build_docs_refresh_report,
    doc_review_line,
    main,
    write_docs_refresh_report,
)
from founder.paths import LakePaths
from founder.portfolio import (
    PortfolioConstraints,
    build_risk_contribution_rows,
    build_target_weight_rows,
    equal_weight_seed,
    minimum_variance_two_asset_weight,
    optimize_portfolio,
    validate_weights,
    write_optimized_weights,
)
from founder.table_io import read_rows, write_rows
from founder.trading import prepare_flatex_orders, write_flatex_orders
from founder.universe_review import currency_exposure, missing_isin_rows, review_universe


def _dense_covariance_rows(
    listings: list[dict[str, str]], *, diagonal: float = 0.01, off_diagonal: float = 0.0
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for left in listings:
        for right in listings:
            rows.append(
                {
                    "left_isin": left["isin"],
                    "left_exchange": left["exchange"],
                    "left_code": left["code"],
                    "right_isin": right["isin"],
                    "right_exchange": right["exchange"],
                    "right_code": right["code"],
                    "covariance": diagonal if left["isin"] == right["isin"] else off_diagonal,
                }
            )
    return rows


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


def test_portfolio_objectives_select_deterministic_weights() -> None:
    listings = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},
        {"isin": "IE2", "exchange": "AS", "code": "BBB"},
    ]
    covariance_rows = [
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.01,
        },
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.00,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.00,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.04,
        },
    ]
    expected_returns = {"IE1": 0.01, "IE2": 0.03}
    constraints = PortfolioConstraints(max_weight=0.8)

    assert optimize_portfolio(
        listings,
        covariance_rows,
        expected_returns,
        objective="equal_weight",
        constraints=constraints,
    ) == {"IE1": 0.5, "IE2": 0.5}
    assert optimize_portfolio(
        listings,
        covariance_rows,
        expected_returns,
        objective="minimum_variance",
        constraints=constraints,
        grid_step=0.1,
    ) == {"IE1": 0.8, "IE2": 0.2}
    assert optimize_portfolio(
        listings,
        covariance_rows,
        expected_returns,
        objective="maximum_sharpe",
        constraints=constraints,
        risk_free_rate=0.005,
        grid_step=0.1,
    ) == {"IE1": 0.4, "IE2": 0.6}
    assert optimize_portfolio(
        listings,
        covariance_rows,
        expected_returns,
        objective="target_return_minimum_variance",
        constraints=constraints,
        target_return=0.02,
        grid_step=0.1,
    ) == {"IE1": 0.5, "IE2": 0.5}


def test_portfolio_objectives_reject_infeasible_constraints() -> None:
    listings = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},
        {"isin": "IE2", "exchange": "AS", "code": "BBB"},
    ]
    covariance_rows = _dense_covariance_rows(listings)
    with pytest.raises(ValueError, match="no feasible weights"):
        optimize_portfolio(
            listings,
            covariance_rows,
            {"IE1": 0.01, "IE2": 0.02},
            objective="minimum_variance",
            constraints=PortfolioConstraints(max_weight=0.4),
            grid_step=0.1,
        )
    with pytest.raises(ValueError, match="target_return is required"):
        optimize_portfolio(
            listings,
            covariance_rows,
            {"IE1": 0.01, "IE2": 0.02},
            objective="target_return_minimum_variance",
            constraints=PortfolioConstraints(max_weight=1.0),
        )
    with pytest.raises(ValueError, match="satisfy target_return"):
        optimize_portfolio(
            listings,
            covariance_rows,
            {"IE1": 0.01, "IE2": 0.02},
            objective="target_return_minimum_variance",
            constraints=PortfolioConstraints(max_weight=1.0),
            target_return=0.03,
            grid_step=0.1,
        )


def test_portfolio_objectives_use_bounded_large_universe_fallback() -> None:
    listings = [
        {"isin": f"IE{index}", "exchange": "XETRA", "code": f"ETF{index}"} for index in range(1, 7)
    ]

    weights = optimize_portfolio(
        listings,
        _dense_covariance_rows(listings),
        {str(row["isin"]): 0.01 for row in listings},
        objective="minimum_variance",
        constraints=PortfolioConstraints(max_weight=0.5),
        grid_step=0.01,
    )

    assert set(weights) == {"IE1", "IE2", "IE3", "IE4", "IE5", "IE6"}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_optimized_weight_rows_and_gold_write_are_idempotent(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    matrix_rows = [
        {
            "evaluation_id": "eval-1",
            "date": "2026-07-11",
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "return": 0.01,
        },
        {
            "evaluation_id": "eval-1",
            "date": "2026-07-11",
            "isin": "IE2",
            "exchange": "AS",
            "code": "BBB",
            "return": 0.03,
        },
    ]
    covariance_rows = [
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.01,
        },
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.00,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.00,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.04,
        },
    ]
    write_rows(paths.gold_return_matrix("eval-1"), matrix_rows)
    write_rows(paths.gold_covariance("XETRA", "IE1"), covariance_rows[:2])
    write_rows(paths.gold_covariance("AS", "IE2"), covariance_rows[2:])
    constraints = PortfolioConstraints(max_weight=0.8)

    rows = build_target_weight_rows(
        [{"isin": "IE1", "exchange": "XETRA", "code": "AAA"}],
        {"IE1": 1.0},
        evaluation_id="eval-1",
        objective="equal_weight",
        portfolio_id="baseline",
        constraints=PortfolioConstraints(max_weight=1.0),
    )
    assert rows[0]["constraints"] == (
        '{"long_only": true, "max_weight": 1.0, "min_quote_coverage": 0.95, "min_weight": 0.0}'
    )

    first = write_optimized_weights(
        paths,
        evaluation_id="eval-1",
        objective="minimum_variance",
        portfolio_id="min-var",
        constraints=constraints,
        grid_step=0.1,
    )
    second = write_optimized_weights(
        paths,
        evaluation_id="eval-1",
        objective="minimum_variance",
        portfolio_id="min-var",
        constraints=constraints,
        grid_step=0.1,
    )

    assert first == second
    assert [row["weight"] for row in first] == [0.8, 0.2]
    assert read_rows(paths.gold_optimized_weights("minimum_variance", "eval-1")) == first


def test_risk_parity_selects_equal_risk_contribution_weights() -> None:
    listings = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},
        {"isin": "IE2", "exchange": "AS", "code": "BBB"},
    ]
    covariance_rows = [
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.01,
        },
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.0,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.0,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.04,
        },
    ]

    weights = optimize_portfolio(
        listings,
        covariance_rows,
        {},
        objective="risk_parity",
        constraints=PortfolioConstraints(max_weight=0.8),
        grid_step=0.01,
    )
    rows = build_risk_contribution_rows(
        listings,
        covariance_rows,
        weights,
        evaluation_id="eval-1",
        objective="risk_parity",
        portfolio_id="risk-parity",
        tolerance=1e-4,
    )

    assert weights == {"IE1": pytest.approx(0.67), "IE2": pytest.approx(0.33)}
    assert [row["percent_risk_contribution"] for row in rows] == [
        pytest.approx(0.5075183719615601),
        pytest.approx(0.49248162803843976),
    ]
    assert rows[0]["convergence_status"] == "not_converged"
    assert rows[0]["objective_residual"] == pytest.approx(rows[1]["objective_residual"])


def test_risk_parity_handles_correlated_assets_and_allocation_bounds() -> None:
    listings = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},
        {"isin": "IE2", "exchange": "AS", "code": "BBB"},
    ]
    covariance_rows = [
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.01,
        },
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.01,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.01,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.04,
        },
    ]

    weights = optimize_portfolio(
        listings,
        covariance_rows,
        {},
        objective="equal_risk_contribution",
        constraints=PortfolioConstraints(max_weight=0.6),
        grid_step=0.01,
    )

    assert weights == {"IE1": pytest.approx(0.6), "IE2": pytest.approx(0.4)}


def test_risk_parity_reports_zero_variance_non_convergence() -> None:
    listings = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},
        {"isin": "IE2", "exchange": "AS", "code": "BBB"},
    ]
    covariance_rows = [
        {
            "left_isin": left,
            "left_exchange": left_exchange,
            "left_code": left_code,
            "right_isin": right,
            "right_exchange": right_exchange,
            "right_code": right_code,
            "covariance": 0.0,
        }
        for left, left_exchange, left_code in [("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB")]
        for right, right_exchange, right_code in [("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB")]
    ]
    weights = optimize_portfolio(
        listings,
        covariance_rows,
        {},
        objective="risk_parity",
        constraints=PortfolioConstraints(max_weight=0.8),
        grid_step=0.1,
    )
    rows = build_risk_contribution_rows(
        listings,
        covariance_rows,
        weights,
        evaluation_id="eval-1",
        objective="risk_parity",
        portfolio_id="zero-var",
    )

    assert rows[0]["portfolio_variance"] == 0.0
    assert rows[0]["convergence_status"] == "not_converged"
    assert rows[0]["objective_residual"] == pytest.approx(0.5)


def test_risk_parity_gold_writes_are_idempotent(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    matrix_rows = [
        {
            "evaluation_id": "eval-1",
            "date": "2026-07-11",
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "return": 0.01,
        },
        {
            "evaluation_id": "eval-1",
            "date": "2026-07-11",
            "isin": "IE2",
            "exchange": "AS",
            "code": "BBB",
            "return": 0.03,
        },
    ]
    covariance_rows = [
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.01,
        },
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.0,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.0,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.04,
        },
    ]
    write_rows(paths.gold_return_matrix("eval-1"), matrix_rows)
    write_rows(paths.gold_covariance("XETRA", "IE1"), covariance_rows[:2])
    write_rows(paths.gold_covariance("AS", "IE2"), covariance_rows[2:])

    first = write_optimized_weights(
        paths,
        evaluation_id="eval-1",
        objective="risk_parity",
        portfolio_id="risk-parity",
        constraints=PortfolioConstraints(max_weight=0.8),
        grid_step=0.01,
        risk_budget_tolerance=1e-3,
    )
    second = write_optimized_weights(
        paths,
        evaluation_id="eval-1",
        objective="risk_parity",
        portfolio_id="risk-parity",
        constraints=PortfolioConstraints(max_weight=0.8),
        grid_step=0.01,
        risk_budget_tolerance=1e-3,
    )

    risk_rows = read_rows(paths.gold_risk_contributions("risk_parity", "eval-1"))
    diagnostics = json.loads(str(first[0]["diagnostics"]))
    assert first == second
    assert [row["weight"] for row in first] == [pytest.approx(0.67), pytest.approx(0.33)]
    assert read_rows(paths.gold_optimized_weights("risk_parity", "eval-1")) == first
    assert len(risk_rows) == 2
    assert risk_rows[0]["convergence_status"] == "converged"
    assert diagnostics["convergence_status"] == "converged"
    assert diagnostics["risk_parity_residual"] == pytest.approx(risk_rows[0]["objective_residual"])


def test_flatex_orders_are_deterministic_and_exportable(tmp_path: Path) -> None:
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


def test_docs_refresh_report_tracks_review_lines(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    for name in (
        "README.md",
        "ARCHITECTURE.md",
        "RISKS.md",
        "DECISIONS.md",
        "BACKLOG.md",
        "AGENTS.md",
        "docs/lake_contracts.md",
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


def test_docs_refresh_handles_missing_docs_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    assert build_docs_refresh_report(tmp_path)["missing_review_count"] == 7
