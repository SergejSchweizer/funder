"""Operational workflow functions behind the Founder CLI."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from founder.bronze import (
    ADDITIONAL_EODHD_DATASETS,
    bronze_run_lock,
    build_gap_bronze_plan,
    eodhd_quote_loader,
    eodhd_raw_data_loader,
    write_bronze_manifests,
    write_bronze_plan,
    write_quotes_to_bronze,
    write_raw_eodhd_datasets_to_bronze,
)
from founder.evaluation import (
    build_asset_metrics,
    write_efficient_frontier,
    write_evaluation_outputs,
    write_portfolio_evaluation,
    write_rebalance_simulation,
    write_tail_risk_evaluation,
    write_walk_forward_backtest,
)
from founder.gold import write_gold_inputs
from founder.http import EodhdClient
from founder.logging import get_logger
from founder.paths import LakePaths
from founder.portfolio import (
    PortfolioConstraints,
    write_hierarchical_risk_parity,
    write_maximum_diversification,
    write_optimized_weights,
)
from founder.run_locks import layer_run_lock
from founder.schemas import required_fields
from founder.search import (
    approve_universe,
    normalize_name,
    resolve_current_universe,
    write_canonical_universe,
    write_search_run,
)
from founder.silver import (
    build_silver_quote_rows,
    build_silver_quotes,
    read_bronze_quote_rows,
    read_silver_quotes,
)
from founder.table_io import read_rows, write_rows

LOGGER = get_logger(__name__)


ConfigLoader = Callable[[], Any]
ClientFactory = Callable[[Any], EodhdClient]


def _asset_metrics_are_current(rows: Sequence[Mapping[str, Any]], confidence_level: float) -> bool:
    required = required_fields("asset_metrics")
    return bool(rows) and all(
        all(field in row for field in required)
        and float(row["confidence_level"]) == confidence_level
        for row in rows
    )


def generated_run_id(prefix: str, value: str | None = None, run_date: date | None = None) -> str:
    parts = [prefix]
    if value:
        parts.append(_slug(value))
    parts.append((run_date or date.today()).isoformat().replace("-", ""))
    return "-".join(parts)


def run_search_workflow(
    *,
    root: Path,
    input_path: Path,
    query: str,
    search_run_id: str | None = None,
    run_date: date | None = None,
    approve: bool = True,
) -> dict[str, Any]:
    paths = LakePaths(root=root)
    resolved_run_date = run_date or date.today()
    resolved_search_run_id = search_run_id or generated_run_id("search", query, resolved_run_date)
    raw_candidates = _filter_candidates(_read_candidate_payload(input_path), query)
    LOGGER.info(
        "running search query=%s search_run_id=%s input=%s candidates=%s",
        query,
        resolved_search_run_id,
        input_path,
        len(raw_candidates),
    )
    candidates = write_search_run(
        raw_candidates,
        paths=paths,
        search_run_id=resolved_search_run_id,
        query=query,
        run_date=resolved_run_date,
        found_at=datetime.combine(resolved_run_date, datetime.min.time(), tzinfo=UTC),
    )
    canonical = write_canonical_universe(paths, resolved_search_run_id)
    summary: dict[str, Any] = {
        "candidate_rows": len(candidates),
        "canonical_rows": len(canonical),
        "query": query,
        "search_run_id": resolved_search_run_id,
    }
    if approve:
        summary["approved_universe"] = approve_universe(paths, resolved_search_run_id)
    LOGGER.info(
        "search complete search_run_id=%s canonical_rows=%s",
        resolved_search_run_id,
        len(canonical),
    )
    return summary


def run_search_sync_isins_workflow(
    *,
    root: Path,
    config_loader: ConfigLoader,
    client_factory: ClientFactory,
    search_run_id: str | None = None,
    run_date: date | None = None,
    approve: bool = True,
) -> dict[str, Any]:
    """Enumerate EODHD exchange symbol lists and write all rows with ISINs."""

    paths = LakePaths(root=root)
    resolved_run_date = run_date or date.today()
    resolved_search_run_id = search_run_id or generated_run_id(
        "sync-eodhd-isins", run_date=resolved_run_date
    )
    client = client_factory(config_loader())
    exchange_codes = _load_eodhd_exchange_codes(client)
    raw_candidates: list[dict[str, Any]] = []
    failed_exchanges: list[str] = []
    for exchange_code in exchange_codes:
        try:
            rows = _load_eodhd_symbol_list(client, exchange_code)
        except Exception as exc:
            LOGGER.warning(
                "EODHD symbol-list sync failed exchange=%s error=%s",
                exchange_code,
                exc,
            )
            failed_exchanges.append(exchange_code)
            continue
        raw_candidates.extend(row for row in rows if str(row.get("Isin", "")).strip())

    LOGGER.info(
        "running search ISIN sync search_run_id=%s exchanges=%s candidates=%s failed_exchanges=%s",
        resolved_search_run_id,
        len(exchange_codes),
        len(raw_candidates),
        len(failed_exchanges),
    )
    candidates = write_search_run(
        raw_candidates,
        paths=paths,
        search_run_id=resolved_search_run_id,
        query="ALL_EODHD_ISINS",
        run_date=resolved_run_date,
        found_at=datetime.combine(resolved_run_date, datetime.min.time(), tzinfo=UTC),
    )
    canonical = write_canonical_universe(paths, resolved_search_run_id)
    summary: dict[str, Any] = {
        "candidate_rows": len(candidates),
        "canonical_rows": len(canonical),
        "exchange_rows": len(exchange_codes),
        "failed_exchanges": failed_exchanges,
        "isin_rows_fetched": len(candidates),
        "query": "ALL_EODHD_ISINS",
        "search_run_id": resolved_search_run_id,
        "unique_isins_fetched": len(canonical),
    }
    if approve:
        summary["approved_universe"] = approve_universe(paths, resolved_search_run_id)
    LOGGER.info(
        "search ISIN sync complete search_run_id=%s canonical_rows=%s failed_exchanges=%s",
        resolved_search_run_id,
        len(canonical),
        len(failed_exchanges),
    )
    return summary


def run_bronze_workflow(
    *,
    root: Path,
    config_loader: ConfigLoader,
    client_factory: ClientFactory,
    run_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    run_date: date | None = None,
    mock: bool = False,
    concurrency: int = 2,
    limit: int | None = None,
    isin: str | None = None,
) -> dict[str, Any]:
    paths = LakePaths(root=root)
    resolved_run_date = run_date or date.today()
    resolved_end_date = end_date
    resolved_start_date = start_date
    gap_aware = resolved_start_date is None and not mock
    if gap_aware:
        resolved_end_date = resolved_end_date or resolved_run_date
    if mock:
        resolved_end_date = resolved_end_date or resolved_run_date
        resolved_start_date = resolved_start_date or (resolved_end_date - timedelta(days=30))
    resolved_run_id = run_id or generated_run_id("bronze", run_date=resolved_run_date)
    canonical_path = resolve_current_universe(paths)
    LOGGER.info("running bronze run_id=%s canonical_path=%s", resolved_run_id, canonical_path)
    with bronze_run_lock(paths, resolved_run_id):
        listing_plan = write_bronze_plan(
            paths,
            canonical_path,
            run_id=resolved_run_id,
            start_date=resolved_start_date,
            end_date=resolved_end_date,
            limit=limit,
            isin=isin,
            gap_aware=False,
        )
        quote_plan = listing_plan
        if gap_aware:
            quote_plan = build_gap_bronze_plan(
                listing_plan,
                read_silver_quotes(paths),
                end_date=resolved_end_date,
            )
            write_rows(paths.bronze_plan(resolved_run_id), quote_plan)
        summary: dict[str, Any] = {
            "concurrency": concurrency,
            "end_date": resolved_end_date.isoformat() if resolved_end_date is not None else None,
            "bronze_plan_rows": len(quote_plan),
            "gap_aware": gap_aware,
            "run_id": resolved_run_id,
            "start_date": resolved_start_date.isoformat()
            if resolved_start_date is not None
            else None,
        }
        if mock:
            if resolved_end_date is None:
                raise RuntimeError("mock bronze requires start and end dates")

            def mock_quotes_for_item(item: Mapping[str, Any]) -> list[dict[str, Any]]:
                item_start = (
                    date.fromisoformat(str(item.get("start_date", "")))
                    if item.get("start_date")
                    else resolved_start_date
                )
                item_end = (
                    date.fromisoformat(str(item.get("end_date", "")))
                    if item.get("end_date")
                    else resolved_end_date
                )
                if item_start is None:
                    raise RuntimeError("mock bronze requires start and end dates")
                return _mock_quote_rows(item_start, item_end)

            def mock_empty_dataset(_item: Mapping[str, Any]) -> list[dict[str, Any]]:
                return []

            _, quote_errors = write_quotes_to_bronze(
                paths,
                quote_plan,
                run_date=resolved_run_date,
                loader=mock_quotes_for_item,
                concurrency=concurrency,
            )
            raw_successes, raw_errors = write_raw_eodhd_datasets_to_bronze(
                paths,
                quote_plan,
                run_date=resolved_run_date,
                loaders={
                    strategy.name: mock_empty_dataset for strategy in ADDITIONAL_EODHD_DATASETS
                },
                concurrency=concurrency,
            )
        else:
            client = client_factory(config_loader())
            _, quote_errors = write_quotes_to_bronze(
                paths,
                quote_plan,
                run_date=resolved_run_date,
                loader=eodhd_quote_loader(client),
                concurrency=concurrency,
            )
            raw_successes, raw_errors = write_raw_eodhd_datasets_to_bronze(
                paths,
                quote_plan,
                run_date=resolved_run_date,
                loaders={
                    strategy.name: eodhd_raw_data_loader(client, strategy.endpoint)
                    for strategy in ADDITIONAL_EODHD_DATASETS
                },
                concurrency=concurrency,
            )
        bronze_quote_rows = read_bronze_quote_rows(paths)
        coverage_quote_rows = build_silver_quote_rows(bronze_quote_rows)
        coverage = write_bronze_manifests(
            paths,
            run_id=resolved_run_id,
            quote_rows=coverage_quote_rows,
            plan=listing_plan,
            as_of=resolved_end_date,
        )
        summary["bronze_quote_rows"] = len(bronze_quote_rows)
        summary["coverage_rows"] = len(coverage)
        summary["error_rows"] = len(quote_errors) + len(raw_errors)
        summary["raw_data_payloads"] = len(raw_successes)
    LOGGER.info("bronze complete run_id=%s plan_rows=%s", resolved_run_id, len(quote_plan))
    return summary


def run_silver_workflow(*, root: Path, concurrency: int = 2) -> dict[str, Any]:
    paths = LakePaths(root=root)
    LOGGER.info("running silver build root=%s concurrency=%s", root, concurrency)
    with layer_run_lock(paths, "silver"):
        quote_rows = build_silver_quotes(paths, concurrency=concurrency)
    LOGGER.info("silver build complete root=%s rows=%s", root, len(quote_rows))
    return {"concurrency": concurrency, "quote_rows": len(quote_rows)}


def run_gold_workflow(*, root: Path, concurrency: int = 2) -> dict[str, Any]:
    paths = LakePaths(root=root)
    LOGGER.info("running gold build root=%s concurrency=%s", root, concurrency)
    with layer_run_lock(paths, "gold"):
        quotes = read_silver_quotes(paths)
        returns, correlations, covariances, features = write_gold_inputs(
            paths, quotes, concurrency=concurrency
        )
    LOGGER.info(
        "gold build complete root=%s returns=%s features=%s", root, len(returns), len(features)
    )
    return {
        "concurrency": concurrency,
        "correlation_rows": len(correlations),
        "covariance_rows": len(covariances),
        "feature_rows": len(features),
        "return_rows": len(returns),
    }


def run_evaluate_workflow(
    *,
    root: Path,
    evaluation_id: str,
    portfolio_id: str,
    objective: str,
    optimize: bool = False,
    walk_forward: bool = False,
    rebalance: bool = False,
    frontier: bool = False,
    tail_risk: bool = False,
    run_id: str = "evaluation-run",
    train_window: int = 2,
    test_window: int = 1,
    schedule: str = "monthly",
    grid_step: float = 0.1,
    max_weight: float = 1.0,
    target_returns: Sequence[float] = (0.0, 0.01),
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    paths = LakePaths(root=root)
    constraints = PortfolioConstraints(max_weight=max_weight)
    matrix = read_rows(paths.gold_return_matrix(evaluation_id))
    if matrix:
        asset_metrics = read_rows(paths.gold_asset_metrics(evaluation_id))
        if not _asset_metrics_are_current(asset_metrics, confidence_level):
            asset_metrics = build_asset_metrics(
                matrix,
                evaluation_id,
                confidence_level=confidence_level,
            )
            write_rows(paths.gold_asset_metrics(evaluation_id), asset_metrics)
    else:
        matrix, asset_metrics = write_evaluation_outputs(
            paths,
            evaluation_id=evaluation_id,
            confidence_level=confidence_level,
        )
    if matrix:
        portfolio_returns, drawdowns, portfolio_metrics = write_portfolio_evaluation(
            paths,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
        )
    else:
        portfolio_returns = []
        drawdowns = []
        portfolio_metrics = []
    summary: dict[str, Any] = {
        "asset_metric_rows": len(asset_metrics),
        "drawdown_rows": len(drawdowns),
        "evaluation_id": evaluation_id,
        "portfolio_metric_rows": len(portfolio_metrics),
        "portfolio_return_rows": len(portfolio_returns),
        "return_matrix_rows": len(matrix),
    }
    if optimize:
        if objective == "hierarchical_risk_parity":
            weight_rows, cluster_rows = write_hierarchical_risk_parity(
                paths,
                evaluation_id=evaluation_id,
                portfolio_id=portfolio_id,
                constraints=constraints,
            )
            summary["cluster_rows"] = len(cluster_rows)
        elif objective == "maximum_diversification":
            weight_rows, metric_rows = write_maximum_diversification(
                paths,
                evaluation_id=evaluation_id,
                portfolio_id=portfolio_id,
                constraints=constraints,
                grid_step=grid_step,
            )
            summary["diversification_metric_rows"] = len(metric_rows)
        else:
            weight_rows = write_optimized_weights(
                paths,
                evaluation_id=evaluation_id,
                objective=objective,
                portfolio_id=portfolio_id,
                constraints=constraints,
                grid_step=grid_step,
            )
        summary["optimized_weight_rows"] = len(weight_rows)
    if walk_forward:
        backtests, backtest_weights = write_walk_forward_backtest(
            paths,
            evaluation_id=evaluation_id,
            run_id=run_id,
            objective=objective,
            constraints=constraints,
            train_window=train_window,
            test_window=test_window,
            grid_step=grid_step,
        )
        summary["backtest_rows"] = len(backtests)
        summary["backtest_weight_rows"] = len(backtest_weights)
    if rebalance:
        rebalance_events = write_rebalance_simulation(
            paths,
            evaluation_id=evaluation_id,
            run_id=run_id,
            portfolio_id=portfolio_id,
            schedule=schedule,
        )
        summary["rebalance_event_rows"] = len(rebalance_events)
    if frontier:
        frontier_points, frontier_weights = write_efficient_frontier(
            paths,
            evaluation_id=evaluation_id,
            constraints=constraints,
            target_returns=target_returns,
            grid_step=grid_step,
        )
        summary["frontier_point_rows"] = len(frontier_points)
        summary["frontier_weight_rows"] = len(frontier_weights)
    if tail_risk:
        tail_rows = write_tail_risk_evaluation(
            paths,
            evaluation_id=evaluation_id,
            run_id=run_id,
            portfolio_id=portfolio_id,
            confidence_level=confidence_level,
        )
        summary["tail_risk_rows"] = len(tail_rows)
    return summary


def run_refresh_workflow(
    *,
    root: Path,
    config_loader: ConfigLoader,
    client_factory: ClientFactory,
    run_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    run_date: date | None = None,
    mock: bool = False,
    concurrency: int = 2,
    limit: int | None = None,
    isin: str | None = None,
) -> dict[str, Any]:
    bronze_summary = run_bronze_workflow(
        root=root,
        config_loader=config_loader,
        client_factory=client_factory,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
        run_date=run_date,
        mock=mock,
        concurrency=concurrency,
        limit=limit,
        isin=isin,
    )
    silver_summary = run_silver_workflow(root=root, concurrency=concurrency)
    gold_summary = run_gold_workflow(root=root, concurrency=concurrency)
    return {"bronze": bronze_summary, "gold": gold_summary, "silver": silver_summary}


def _slug(value: str) -> str:
    slug = "-".join(normalize_name(value).replace("_", "-").split())
    return slug or "run"


def _read_candidate_payload(path: Path) -> list[dict[str, Any]]:
    if path.suffix.casefold() == ".csv":
        with path.open(encoding="utf-8", newline="") as csv_file:
            return [dict(row) for row in csv.DictReader(csv_file)]
    payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if isinstance(payload, dict):
        payload_by_name = cast(dict[str, object], payload)
        payload = payload_by_name.get("responses", payload_by_name.get("candidates"))
    if not isinstance(payload, list):
        raise ValueError("search input must be a JSON list or an object with responses/candidates")
    rows: list[dict[str, Any]] = []
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            raise ValueError("search input rows must be JSON objects")
        rows.append(cast(dict[str, Any], item))
    return rows


def _filter_candidates(rows: Sequence[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = normalize_name(query)
    return [
        row
        for row in rows
        if normalized_query in normalize_name(str(row.get("name", row.get("Name", ""))))
    ]


def _load_eodhd_exchange_codes(client: EodhdClient) -> list[str]:
    payload = client.get_json("/exchanges-list/", {"fmt": "json"})
    if not isinstance(payload, list):
        raise ValueError("EODHD exchanges-list response must be a list")
    codes: set[str] = set()
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            continue
        code = str(cast(dict[str, Any], item).get("Code", "")).strip().upper()
        if code:
            codes.add(code)
    if not codes:
        raise ValueError("EODHD exchanges-list response did not contain exchange codes")
    return sorted(codes)


def _load_eodhd_symbol_list(client: EodhdClient, exchange_code: str) -> list[dict[str, Any]]:
    payload = client.get_json(f"/exchange-symbol-list/{exchange_code}", {"fmt": "json"})
    if not isinstance(payload, list):
        raise ValueError(f"EODHD symbol-list response for {exchange_code} must be a list")
    rows: list[dict[str, Any]] = []
    for item in cast(list[object], payload):
        if isinstance(item, dict):
            rows.append(cast(dict[str, Any], item))
    return rows


def _mock_quote_rows(start_date: date, end_date: date) -> list[dict[str, Any]]:
    start_close = 100.0
    end_close = 101.0 if end_date != start_date else start_close
    return [
        {"date": start_date.isoformat(), "close": start_close, "adjusted_close": start_close},
        {"date": end_date.isoformat(), "close": end_close, "adjusted_close": end_close},
    ]
