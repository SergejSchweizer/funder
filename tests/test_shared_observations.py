from __future__ import annotations

import pytest

from founder.shared_observations import (
    MarketObservation,
    SharedMarketObservationStore,
    SharedObservationCatalog,
    SharedObservationStoreError,
)


def _observation(
    *,
    business_key: str = "2026-01-01",
    close: float = 100.0,
) -> MarketObservation:
    return MarketObservation(
        provider="eodhd",
        dataset_type="quotes",
        listing_identity="XETRA:ABC:IE0000000001",
        business_key=business_key,
        payload={"date": business_key, "close": close, "volume": 10},
    )


def test_shared_observation_ids_are_content_addressed_and_revision_aware() -> None:
    original = _observation(close=100.0)
    corrected = _observation(close=101.0)

    assert original.observation_id() != corrected.observation_id()
    assert original.business_key == corrected.business_key
    assert original.payload_hash() != corrected.payload_hash()


def test_publish_segment_writes_atomic_parquet_and_deduplicates_identical_rows(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    catalog = SharedObservationCatalog()
    store = SharedMarketObservationStore(root=tmp_path, catalog=catalog)

    manifest = store.publish_segment(
        provider="eodhd",
        dataset_type="quotes",
        observations=[_observation(), _observation()],
    )
    second = store.publish_segment(
        provider="eodhd",
        dataset_type="quotes",
        observations=[_observation()],
    )

    assert second == manifest
    assert manifest.row_count == 1
    assert catalog.object_count() == 1
    rows = store.read_segment(manifest)
    assert rows[0]["close"] == 100.0
    assert "user_id" not in rows[0]
    assert "credential_id" not in rows[0]


def test_overlaps_appends_and_corrections_publish_distinct_canonical_segments(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    catalog = SharedObservationCatalog()
    store = SharedMarketObservationStore(root=tmp_path, catalog=catalog)

    first = store.publish_segment(
        provider="eodhd",
        dataset_type="quotes",
        observations=[_observation(business_key="2026-01-01", close=100.0)],
    )
    appended = store.publish_segment(
        provider="eodhd",
        dataset_type="quotes",
        observations=[
            _observation(business_key="2026-01-01", close=100.0),
            _observation(business_key="2026-01-02", close=102.0),
        ],
    )
    corrected = store.publish_segment(
        provider="eodhd",
        dataset_type="quotes",
        observations=[_observation(business_key="2026-01-01", close=101.0)],
    )

    assert first.segment_hash != appended.segment_hash
    assert first.segment_hash != corrected.segment_hash
    assert catalog.object_count() == 3


def test_shared_store_rejects_forbidden_authorization_fields_and_corruption(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    store = SharedMarketObservationStore(root=tmp_path, catalog=SharedObservationCatalog())

    with pytest.raises(SharedObservationStoreError, match="forbidden"):
        store.publish_segment(
            provider="eodhd",
            dataset_type="quotes",
            observations=[
                MarketObservation(
                    provider="eodhd",
                    dataset_type="quotes",
                    listing_identity="XETRA:ABC:IE0000000001",
                    business_key="2026-01-01",
                    payload={"date": "2026-01-01", "close": 100.0, "user_id": "user-1"},
                )
            ],
        )

    manifest = store.publish_segment(
        provider="eodhd",
        dataset_type="quotes",
        observations=[_observation()],
    )
    segment_path = tmp_path / manifest.storage_uri
    segment_path.write_text("not parquet", encoding="utf-8")
    with pytest.raises(SharedObservationStoreError, match="cannot be read|hash mismatch"):
        store.read_segment(manifest)
