from __future__ import annotations

from datetime import UTC, datetime

import pytest
from lifecycle_scenario import lifecycle_engine
from semantic_scenario import semantic_scenario

from intelligence.lifecycle.lifecycle_intelligence import LifecycleIntelligence
from semantic.semantic_engine import SemanticEngine


def test_lifecycle_analysis_enriches_eol_system_with_operational_context():
    analysis = lifecycle_engine().analyze()
    payroll = next(
        item
        for item in analysis["findings"]
        if item["resource"]["name"] == "vm-payroll-legacy"
    )

    assert payroll["lifecycle_status"] == "EOL"
    assert payroll["product"] == "Windows Server"
    assert payroll["version"] == "2012 R2"
    assert payroll["application"] == "Payroll"
    assert payroll["business_service"] == "Finance Operations"
    assert payroll["owner"] == "finance-platform@example.com"
    assert payroll["support_team"] == "Finance SRE"
    assert payroll["patch_compliance"] == 35
    assert payroll["risk_score"] >= 75
    assert payroll["business_impact"] == "Critical"
    assert payroll["modernization_recommendation"]["recommended_action"] == (
        "Upgrade to Windows Server 2025"
    )
    assert payroll["evidence"]
    assert payroll["risk_drivers"]
    assert 0 <= payroll["confidence"] <= 1
    assert payroll["advisory_only"] is True
    assert analysis["read_only"] is True


def test_unknown_operating_system_is_explicit_and_not_reported_supported():
    unknown = next(
        item
        for item in lifecycle_engine().analyze()["findings"]
        if item["resource"]["name"] == "arc-unknown"
    )

    assert unknown["lifecycle_status"] == "Unknown"
    assert unknown["confidence"] < 0.5
    assert "catalog_match_missing" in unknown["risk_drivers"]


def test_lifecycle_context_is_correlated_through_public_semantic_engine_apis():
    scenario = semantic_scenario()
    inventory = [dict(scenario["inventory"][0])]
    inventory[0].update(os_name="Windows Server", os_version="2012 R2", region="eastus")
    semantic = SemanticEngine.from_rows(**scenario)
    catalog = [
        {
            "product": "Windows Server",
            "version": "2012 R2",
            "release_date": "2013-11-25",
            "mainstream_support_end": "2018-10-09",
            "extended_support_end": "2023-10-10",
            "last_update_date": "2026-08-18",
            "recommended_upgrade_path": "Windows Server 2025",
            "source_url": "https://learn.microsoft.com/lifecycle/products/windows-server-2012-r2",
        }
    ]

    engine = LifecycleIntelligence.from_semantic_engine(
        semantic,
        inventory=inventory,
        catalog=catalog,
        history=[],
        patch_posture={inventory[0]["resource_id"]: {"compliance_score": 35}},
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    finding = engine.analyze()["findings"][0]

    assert finding["application"] == "Payments"
    assert finding["business_service"] == "Retail"
    assert finding["owner"] == "ops@example.com"
    assert finding["support_team"] == "SRE"
    assert finding["environment"] == "Production"
    assert finding["business_criticality"] == "Critical"
    assert finding["patch_compliance"] == 35


def test_unknown_semantic_patch_posture_adds_no_patch_noncompliance_risk():
    scenario = semantic_scenario()
    scenario["compliance"][0]["status"] = "unknown"
    inventory = [dict(scenario["inventory"][0])]
    inventory[0].update(os_name="Windows Server", os_version="2022")
    semantic = SemanticEngine.from_rows(**scenario)
    catalog = [
        {
            "product": "Windows Server",
            "version": "2022",
            "release_date": "2021-08-18",
            "mainstream_support_end": "2026-10-13",
            "extended_support_end": "2031-10-14",
            "last_update_date": "2026-08-18",
            "recommended_upgrade_path": "Windows Server 2025",
            "source_url": "https://learn.microsoft.com/lifecycle/products/windows-server-2022",
            "default_support_channel": "extended",
        }
    ]

    engine = LifecycleIntelligence.from_semantic_engine(
        semantic,
        inventory=inventory,
        catalog=catalog,
        history=[],
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    finding = engine.analyze()["findings"][0]

    assert finding["patch_compliance"] is None
    assert finding["risk_factors"]["patch_noncompliance"] == 0
    assert "patch_noncompliance" not in finding["risk_drivers"]


def test_snapshot_uses_catalog_default_support_channel_when_resource_omits_it():
    engine = LifecycleIntelligence(
        resources=[
            {
                "resource_key": "resource-1",
                "name": "server-1",
                "product": "Example OS",
                "version": "1",
            }
        ],
        catalog=[
            {
                "product": "Example OS",
                "version": "1",
                "release_date": "2020-01-01",
                "mainstream_support_end": "2025-01-01",
                "extended_support_end": "2030-01-01",
                "last_update_date": "2026-08-18",
                "recommended_upgrade_path": "Example OS 2",
                "source_url": "https://example.com/lifecycle",
                "default_support_channel": "extended",
            }
        ],
        history=[],
        freshness="2026-08-18T00:00:00Z",
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )

    finding = engine.analyze()["findings"][0]

    assert finding["support_channel"] == "extended"
    assert finding["lifecycle_status"] == "Supported"


def test_duplicate_history_observation_identity_is_rejected():
    observation = {
        "resource_key": "resource-1",
        "observed_at": "2026-08-17T00:00:00Z",
        "ingestion_run_id": "run-1",
        "lifecycle_status": "EOL",
        "risk_score": 90,
    }

    with pytest.raises(ValueError, match="Duplicate lifecycle history observation"):
        LifecycleIntelligence(
            resources=[],
            catalog=[],
            history=[observation, dict(observation)],
            freshness="2026-08-18T00:00:00Z",
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        )


@pytest.mark.parametrize("missing_field", ["resource_key", "ingestion_run_id"])
def test_history_observation_requires_canonical_identity(missing_field):
    observation = {
        "resource_key": "resource-1",
        "observed_at": "2026-08-17T00:00:00Z",
        "ingestion_run_id": "run-1",
        "lifecycle_status": "EOL",
        "risk_score": 90,
    }
    del observation[missing_field]

    with pytest.raises(ValueError, match="Lifecycle history requires"):
        LifecycleIntelligence(
            resources=[],
            catalog=[],
            history=[observation],
            freshness="2026-08-18T00:00:00Z",
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        )
