"""Selection statistics views (PR74).

Materializes which cached univariate/bivariate rows belong to a Metadata
Filter or Univariate Filter selection, without recomputing statistics.
Trusts the PR73 generic Gold cache: a row is considered available if it is
present in the canonical Gold cache path for that listing/pair. Missing
rows are reported deterministically rather than silently recomputed or
substituted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from camovar.contract_versioning import stable_contract_id
from camovar.gold_pair_stats import DEFAULT_BUCKET_COUNT
from camovar.paths import LakePaths
from camovar.table_io import JsonRow, read_rows, write_json

STATISTICS_VIEW_VERSION = 1
DEFAULT_BIVARIATE_VERSION = "current"

ListingKey = tuple[str, str, str]


def _listing_keys(rows: Sequence[Mapping[str, Any]]) -> list[ListingKey]:
    return sorted({(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in rows})


def _pair_key(left: ListingKey, right: ListingKey) -> str:
    # Must match camovar.bivariate_statistics._pair_key's format exactly
    # (exchange__isin__code, joined by "___") so cache lookups hit the same
    # pair_key values written by write_bivariate_statistics.
    def _listing_key(listing: ListingKey) -> str:
        isin, exchange, code = listing
        return f"{exchange}__{isin}__{code}"

    return f"{_listing_key(left)}___{_listing_key(right)}"


def _bivariate_pair_index(
    paths: LakePaths, *, version: str, bucket_count: int
) -> dict[str, JsonRow]:
    index: dict[str, JsonRow] = {}
    for bucket in range(bucket_count):
        for row in read_rows(paths.gold_bivariate_statistics_bucket(version, bucket)):
            index[str(row["pair_key"])] = row
    return index


def build_selection_statistics_view(
    paths: LakePaths,
    *,
    selection_id: str,
    source_module: str,
    listing_rows: Sequence[Mapping[str, Any]],
    skip_same_isin: bool = True,
    bivariate_version: str = DEFAULT_BIVARIATE_VERSION,
    bivariate_bucket_count: int = DEFAULT_BUCKET_COUNT,
) -> JsonRow:
    """Report which univariate/bivariate cache rows exist for a selection.

    Never recomputes a missing row; `missing_univariate_listings`/
    `missing_bivariate_pairs` name exactly what is absent so a caller can
    decide whether to trigger `write_univariate_statistics`/
    `write_bivariate_statistics` before retrying.
    """
    listings = _listing_keys(listing_rows)
    present_univariate: list[JsonRow] = []
    missing_univariate: list[JsonRow] = []
    for isin, exchange, code in listings:
        cached = read_rows(paths.gold_univariate_statistics(exchange, isin))
        if len(cached) == 1 and str(cached[0].get("code")) == code:
            present_univariate.append({"isin": isin, "exchange": exchange, "code": code})
        else:
            missing_univariate.append({"isin": isin, "exchange": exchange, "code": code})

    pair_index = _bivariate_pair_index(
        paths, version=bivariate_version, bucket_count=bivariate_bucket_count
    )
    present_pairs: list[JsonRow] = []
    missing_pairs: list[JsonRow] = []
    for i in range(len(listings)):
        for j in range(i + 1, len(listings)):
            left, right = listings[i], listings[j]
            if skip_same_isin and left[0] == right[0]:
                continue
            pair_row = {
                "left_isin": left[0],
                "left_exchange": left[1],
                "left_code": left[2],
                "right_isin": right[0],
                "right_exchange": right[1],
                "right_code": right[2],
            }
            if _pair_key(left, right) in pair_index:
                present_pairs.append(pair_row)
            else:
                missing_pairs.append(pair_row)

    view_id = stable_contract_id(
        "statistics_selection_view",
        {
            "selection_id": selection_id,
            "source_module": source_module,
            "listing_keys": [list(key) for key in listings],
            "statistic_version": STATISTICS_VIEW_VERSION,
            "bivariate_version": bivariate_version,
            "skip_same_isin": skip_same_isin,
        },
    )
    return {
        "view_id": view_id,
        "selection_id": selection_id,
        "source_module": source_module,
        "statistic_version": STATISTICS_VIEW_VERSION,
        "bivariate_version": bivariate_version,
        "listing_count": len(listings),
        "univariate_status": "complete" if not missing_univariate else "missing_rows",
        "present_univariate_count": len(present_univariate),
        "missing_univariate_listings": missing_univariate,
        "bivariate_status": "complete" if not missing_pairs else "missing_rows",
        "present_bivariate_pair_count": len(present_pairs),
        "missing_bivariate_pairs": missing_pairs,
    }


def write_selection_statistics_view(
    paths: LakePaths,
    *,
    selection_id: str,
    source_module: str,
    listing_rows: Sequence[Mapping[str, Any]],
    skip_same_isin: bool = True,
    bivariate_version: str = DEFAULT_BIVARIATE_VERSION,
    bivariate_bucket_count: int = DEFAULT_BUCKET_COUNT,
) -> JsonRow:
    """Build and persist a selection statistics view. Idempotent: rebuilding
    an unchanged selection produces a byte-equivalent view and never rewrites
    canonical univariate/bivariate statistic rows.
    """
    view = build_selection_statistics_view(
        paths,
        selection_id=selection_id,
        source_module=source_module,
        listing_rows=listing_rows,
        skip_same_isin=skip_same_isin,
        bivariate_version=bivariate_version,
        bivariate_bucket_count=bivariate_bucket_count,
    )
    write_json(paths.selection_statistics_view(source_module, selection_id), view)
    return view


def read_selection_statistics(
    paths: LakePaths,
    *,
    selection_id: str,
    source_module: str,
    listing_rows: Sequence[Mapping[str, Any]],
    skip_same_isin: bool = True,
    bivariate_version: str = DEFAULT_BIVARIATE_VERSION,
    bivariate_bucket_count: int = DEFAULT_BUCKET_COUNT,
) -> tuple[list[JsonRow], list[JsonRow], JsonRow]:
    """Load a selection's univariate and bivariate rows from the generic Gold
    cache without recomputing anything.

    Raises `ValueError` naming the missing listings/pairs when any referenced
    cache row is absent, rather than silently recomputing or returning a
    partial result.
    """
    view = write_selection_statistics_view(
        paths,
        selection_id=selection_id,
        source_module=source_module,
        listing_rows=listing_rows,
        skip_same_isin=skip_same_isin,
        bivariate_version=bivariate_version,
        bivariate_bucket_count=bivariate_bucket_count,
    )
    if view["univariate_status"] != "complete" or view["bivariate_status"] != "complete":
        raise ValueError(
            f"selection statistics incomplete for {selection_id!r}: "
            f"missing_univariate_listings={view['missing_univariate_listings']}, "
            f"missing_bivariate_pairs={view['missing_bivariate_pairs']}"
        )

    listings = _listing_keys(listing_rows)
    univariate_rows = [
        read_rows(paths.gold_univariate_statistics(exchange, isin))[0]
        for isin, exchange, _code in listings
    ]
    pair_index = _bivariate_pair_index(
        paths, version=bivariate_version, bucket_count=bivariate_bucket_count
    )
    bivariate_rows: list[JsonRow] = []
    for i in range(len(listings)):
        for j in range(i + 1, len(listings)):
            left, right = listings[i], listings[j]
            if skip_same_isin and left[0] == right[0]:
                continue
            bivariate_rows.append(pair_index[_pair_key(left, right)])
    return univariate_rows, bivariate_rows, view


__all__ = [
    "DEFAULT_BIVARIATE_VERSION",
    "STATISTICS_VIEW_VERSION",
    "build_selection_statistics_view",
    "read_selection_statistics",
    "write_selection_statistics_view",
]
