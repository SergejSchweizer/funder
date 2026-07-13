"""Documentation refresh reporting."""

from __future__ import annotations

import argparse
from pathlib import Path

from founder.table_io import JsonRow, write_json

TRACKED_DOCS: tuple[str, ...] = (
    "README.md",
    "ARCHITECTURE.md",
    "RISKS.md",
    "DECISIONS.md",
    "BACKLOG.md",
    "AGENTS.md",
    "docs/lake_contracts.md",
    "docs/search_fetch_workflow.md",
)


def doc_review_line(path: Path) -> str:
    if not path.exists():
        return "missing"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Last reviewed:"):
            return line
    return "Last reviewed: missing"


def build_docs_refresh_report(root: Path) -> JsonRow:
    docs = {
        doc: {"exists": (root / doc).exists(), "review": doc_review_line(root / doc)}
        for doc in TRACKED_DOCS
    }
    missing_review_count = sum(
        1 for item in docs.values() if str(item["review"]).endswith("missing")
    )
    return {"tracked_docs": docs, "missing_review_count": missing_review_count}


def write_docs_refresh_report(root: Path, output: Path) -> JsonRow:
    report = build_docs_refresh_report(root)
    write_json(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Founder documentation facts.")
    parser.add_argument("--root", default=".", help="Repository root to inspect.")
    parser.add_argument(
        "--output",
        default="docs/docs_refresh_report.json",
        help="Report path to write, relative to the current directory unless absolute.",
    )
    args = parser.parse_args()
    write_docs_refresh_report(Path(args.root), Path(args.output))
