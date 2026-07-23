from pathlib import Path

from camovar.table_io import read_rows, write_rows


def test_write_rows_writes_real_parquet(tmp_path: Path) -> None:
    path = tmp_path / "rows.parquet"
    rows = [{"isin": "IE1", "close": 10.5}, {"isin": "IE2", "close": 11.0}]

    write_rows(path, rows)

    content = path.read_bytes()
    assert content[:4] == b"PAR1"
    assert content[-4:] == b"PAR1"
    assert read_rows(path) == rows


def test_write_rows_keeps_json_lines_for_non_parquet_paths(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    rows = [{"isin": "IE1", "close": 10.5}]

    write_rows(path, rows)

    assert path.read_text(encoding="utf-8") == '{"close": 10.5, "isin": "IE1"}\n'
    assert read_rows(path) == rows
