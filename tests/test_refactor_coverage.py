from datetime import date
from pathlib import Path

import pytest

import founder.architecture_checks as architecture_checks
import founder.table_io as table_io
from founder.architecture_checks import check_architecture
from founder.cli import build_parser
from founder.contract_versioning import (
    ContractChangeKind,
    ContractVersion,
    canonical_json,
    classify_contract_change,
    stable_contract_id,
)
from founder.gold import build_correlation_edges, write_correlation_edges
from founder.gold_pair_stats import (
    OnlineCorrelation,
    bucket_correlation_edges,
    index_returns,
    iter_pair_statistics,
)
from founder.paths import LakePaths
from founder.run_locks import layer_run_lock
from founder.silver import build_silver_quotes, read_bronze_quote_rows, write_silver_quotes
from founder.table_io import read_json, read_rows, write_rows
from founder.univariate_statistics import build_quote_returns, build_univariate_statistics
from founder.workflows import generated_run_id, run_search_workflow


def _silver_quote(
    isin: str, exchange: str, code: str, date: str, close: float
) -> dict[str, object]:
    return {
        "run_id": "bronze-1",
        "isin": isin,
        "code": code,
        "exchange": exchange,
        "date": date,
        "close": close,
        "adjusted_close": close,
        "run_date": "2026-01-01",
    }


def test_contract_versioning_is_deterministic_and_validated() -> None:
    version = ContractVersion("statistics.univariate", 1)

    assert version.qualified_name == "statistics.univariate@v1"
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert stable_contract_id("contract", {"b": 2, "a": 1}) == stable_contract_id(
        "contract", {"a": 1, "b": 2}
    )
    assert (
        classify_contract_change(
            fields_removed_or_renamed=False, field_types_changed=False, fields_added=True
        )
        is ContractChangeKind.ADDITIVE
    )
    assert (
        classify_contract_change(fields_removed_or_renamed=True, field_types_changed=False)
        is ContractChangeKind.BREAKING
    )
    with pytest.raises(ValueError, match="contract name"):
        ContractVersion("", 1)
    with pytest.raises(ValueError, match="at least 1"):
        ContractVersion("statistics.univariate", 0)


def test_layer_run_lock_writes_metadata_and_rejects_contention(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")

    with layer_run_lock(paths, "gold") as lock_path:
        assert "pid=" in lock_path.read_text(encoding="utf-8")
        with (
            pytest.raises(RuntimeError, match="gold run already active"),
            layer_run_lock(paths, "gold"),
        ):
            pass


def test_silver_reads_bronze_partitions_and_writes_listing_files(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    bronze_path = paths.bronze_quote_file("XETRA", 2026, "IE1")
    write_rows(
        bronze_path,
        [
            _silver_quote("IE1", "XETRA", "AAA", "2026-01-02", 110.0),
            _silver_quote("IE1", "XETRA", "AAA", "2026-01-01", 100.0),
        ],
    )

    assert len(read_bronze_quote_rows(paths)) == 2
    written = write_silver_quotes(paths, read_bronze_quote_rows(paths), concurrency=1)
    rebuilt = build_silver_quotes(paths, concurrency=1)

    assert written == [{"exchange": "XETRA", "isin": "IE1", "rows": 2}]
    assert [row["date"] for row in rebuilt] == ["2026-01-01", "2026-01-02"]


def test_workflow_search_supports_csv_and_rejects_invalid_json(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    csv_path = tmp_path / "candidates.csv"
    csv_path.write_text(
        "Code,Exchange,Type,Country,Currency,Isin,Name\nAAA,XETRA,ETF,DE,EUR,IE1,Alpha UCITS ETF\n",
        encoding="utf-8",
    )

    summary = run_search_workflow(
        root=root,
        input_path=csv_path,
        query="UCITS",
        run_date=date(2026, 1, 1),
    )

    assert summary["search_run_id"] == "search-ucits-20260101"
    assert generated_run_id("manual", run_date=date(2026, 1, 1)) == "manual-20260101"

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text('{"responses": [1]}', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON objects"):
        run_search_workflow(root=root, input_path=invalid_path, query="UCITS")

    invalid_path.write_text('{"unexpected": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON list"):
        run_search_workflow(root=root, input_path=invalid_path, query="UCITS")


def test_univariate_statistics_cover_invalid_prices_and_single_quote() -> None:
    invalid_returns = build_quote_returns(
        [
            _silver_quote("IE1", "XETRA", "AAA", "2026-01-01", 0.0),
            _silver_quote("IE1", "XETRA", "AAA", "2026-01-02", 100.0),
        ]
    )
    single = build_univariate_statistics([_silver_quote("IE2", "AS", "BBB", "2026-01-01", 100.0)])

    assert invalid_returns[0]["return"] == 0.0
    assert single[0]["availability_reason"] == "insufficient_returns"
    assert single[0]["annualized_geometric_return"] == 0.0
    assert single[0]["var"] == 0.0
    assert single[0]["positive_day_ratio"] == 0.0


def test_univariate_statistics_cover_drawdown_and_flat_trend_branches() -> None:
    zero_price = build_univariate_statistics(
        [
            _silver_quote("IE1", "XETRA", "AAA", "2026-01-01", 0.0),
            _silver_quote("IE1", "XETRA", "AAA", "2026-01-02", 0.0),
        ]
    )
    flat_trend = build_univariate_statistics(
        [
            _silver_quote("IE2", "AS", "BBB", "2026-01-01", 100.0),
            _silver_quote("IE2", "AS", "BBB", "2026-01-02", 100.0),
            _silver_quote("IE2", "AS", "BBB", "2026-01-03", 100.0),
        ]
    )

    assert zero_price[0]["max_drawdown"] == 0.0
    assert flat_trend[0]["trend_r_squared"] == 0.0


def test_architecture_checks_report_boundary_violations(tmp_path: Path) -> None:
    root = tmp_path / "founder"
    (root / "evaluation_parts").mkdir(parents=True)
    (root / "portfolio_parts").mkdir()
    (root / "evaluation.py").write_text("import founder.search\n", encoding="utf-8")
    (root / "silver.py").write_text("from founder.bronze import _private\n", encoding="utf-8")
    (root / "paths.py").write_text("import founder.gold\n", encoding="utf-8")
    (root / "evaluation_parts" / "bad.py").write_text(
        "import founder.evaluation\nimport founder.search\n", encoding="utf-8"
    )
    (root / "bad_cli.py").write_text("import founder.cli\n", encoding="utf-8")
    (root / "portfolio_parts" / "bad.py").write_text("import founder.portfolio\n", encoding="utf-8")
    (root / "portfolio_parts" / "constraints.py").write_text(
        "import founder.paths\n", encoding="utf-8"
    )

    violations = check_architecture(root)

    assert any("must not import founder.evaluation facade" in violation for violation in violations)
    assert any("must not import founder.portfolio facade" in violation for violation in violations)
    assert any("imports ingestion modules" in violation for violation in violations)
    assert any("imports private Bronze helpers" in violation for violation in violations)
    assert any("shared module imports layer modules" in violation for violation in violations)
    assert any("core math imports lake IO modules" in violation for violation in violations)
    assert any("must not import founder.cli" in violation for violation in violations)


def test_architecture_main_reports_violations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(architecture_checks, "check_architecture", lambda: ["boom"])

    assert architecture_checks.main() == 1
    assert "boom" in capsys.readouterr().err


def test_table_io_rejects_non_object_json_rows(tmp_path: Path) -> None:
    object_path = tmp_path / "object.json"
    object_path.write_text("[1]", encoding="utf-8")
    line_path = tmp_path / "rows.jsonl"
    line_path.write_text("1\n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="expected JSON object"):
        read_json(object_path)
    with pytest.raises(ValueError, match="expected JSON object row"):
        read_rows(line_path)


def test_table_io_skips_blank_json_lines_and_rejects_non_object_parquet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeTable:
        def to_pylist(self) -> list[object]:
            return [1]

    class FakeParquet:
        def read_table(self, source: Path) -> FakeTable:
            return FakeTable()

        def write_table(self, table: object, where: Path) -> None:
            return None

    jsonl_path = tmp_path / "rows.jsonl"
    jsonl_path.write_text('\n{"a": 1}\n', encoding="utf-8")
    parquet_path = tmp_path / "rows.parquet"
    parquet_path.write_text("not parquet", encoding="utf-8")
    monkeypatch.setattr(table_io, "_PARQUET", FakeParquet())

    assert read_rows(jsonl_path) == [{"a": 1}]
    with pytest.raises(ValueError, match="expected Parquet object row"):
        read_rows(parquet_path)


def test_gold_and_pair_statistics_reject_invalid_configuration(tmp_path: Path) -> None:
    return_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-01-01", "return": 0.01},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-01-02", "return": 0.02},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-01-01", "return": 0.03},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-01-02", "return": 0.04},
    ]

    with pytest.raises(ValueError, match="unsupported correlation edge metric"):
        build_correlation_edges(return_rows, version="v1", metric="kendall")
    with pytest.raises(ValueError, match="min_abs_correlation"):
        build_correlation_edges(return_rows, version="v1", min_abs_correlation=2.0)
    with pytest.raises(ValueError, match="top_k_per_left"):
        build_correlation_edges(return_rows, version="v1", top_k_per_left=0)
    with pytest.raises(ValueError, match="bucket_count"):
        write_correlation_edges(
            LakePaths(root=tmp_path / "lake"), return_rows, version="v1", bucket_count=0
        )
    with pytest.raises(ValueError, match="bucket_count"):
        bucket_correlation_edges([], 0)

    pair_stats = list(iter_pair_statistics(index_returns(return_rows), include_self=True))
    empty_correlation = OnlineCorrelation()

    assert pair_stats[0].pearson == 1.0
    assert empty_correlation.value() == 0.0
    assert empty_correlation.sample_covariance() == 0.0
    assert build_parser().parse_args(
        ["search", "UCITS", "--run-date", "2026-01-01"]
    ).run_date == date(2026, 1, 1)
