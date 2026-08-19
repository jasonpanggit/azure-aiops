from __future__ import annotations

from datetime import UTC, datetime

from intelligence.lifecycle.eol_catalog import EOLCatalog, LifecycleStatus


def test_catalog_classifies_configurable_lifecycle_thresholds():
    catalog = EOLCatalog.from_rows(
        [
            {
                "product": "Example OS",
                "version": "1",
                "release_date": "2020-01-01",
                "mainstream_support_end": "2028-02-18",
                "extended_support_end": "2030-01-01",
                "last_update_date": "2026-08-18",
                "recommended_upgrade_path": "Example OS 2",
                "source_url": "https://vendor.example/lifecycle",
            }
        ],
        approaching_months=24,
        near_months=12,
        critical_months=6,
    )

    now = datetime(2026, 8, 18, tzinfo=UTC)
    record = catalog.lookup("Example OS", "1")

    assert record is not None
    assert catalog.classify(record, now=now, support_channel="mainstream").status is LifecycleStatus.APPROACHING_EOL
    assert catalog.classify(record, now=now, support_channel="extended").status is LifecycleStatus.SUPPORTED


def test_catalog_updates_replace_matching_product_version_and_track_freshness():
    catalog = EOLCatalog.from_rows(
        [
            {
                "product": "Example OS",
                "version": "1",
                "release_date": "2020-01-01",
                "mainstream_support_end": "2027-01-01",
                "extended_support_end": "2028-01-01",
                "last_update_date": "2026-01-01",
                "recommended_upgrade_path": "Example OS 2",
                "source_url": "https://vendor.example/lifecycle",
            }
        ]
    )

    updated = catalog.update(
        [
            {
                "product": "Example OS",
                "version": "1",
                "release_date": "2020-01-01",
                "mainstream_support_end": "2027-06-01",
                "extended_support_end": "2028-06-01",
                "last_update_date": "2026-08-18",
                "recommended_upgrade_path": "Example OS 3",
                "source_url": "https://vendor.example/lifecycle-v2",
            }
        ]
    )

    assert updated.lookup("example os", "1").recommended_upgrade_path == "Example OS 3"
    assert updated.freshness == "2026-08-18"
    assert catalog.lookup("Example OS", "1").recommended_upgrade_path == "Example OS 2"


def test_catalog_unknown_product_is_explicit_not_supported():
    catalog = EOLCatalog.from_rows([])

    result = catalog.classify_product(
        "Unknown OS", "9", now=datetime(2026, 8, 18, tzinfo=UTC)
    )

    assert result.status is LifecycleStatus.UNKNOWN
    assert result.support_end is None
    assert result.confidence == 0.0


def test_default_catalog_covers_required_enterprise_technology_families():
    catalog = EOLCatalog.default()
    products = {row["product"] for row in catalog.rows()}

    assert {
        "Windows Server",
        "Ubuntu",
        "Red Hat Enterprise Linux",
        "Debian",
        "SQL Server",
        "Azure Stack HCI",
        "Azure Local",
        "Kubernetes",
    } <= products
    windows_2022 = catalog.lookup("Windows Server", "2022")
    assert windows_2022.default_support_channel == "extended"
    assert catalog.classify(
        windows_2022, now=datetime(2026, 8, 18, tzinfo=UTC)
    ).status is LifecycleStatus.SUPPORTED
