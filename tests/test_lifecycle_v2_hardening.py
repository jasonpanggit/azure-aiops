from __future__ import annotations

import base64
import json
import math
import re
from datetime import UTC, datetime

import pytest
from lifecycle_scenario import lifecycle_engine

from fabric.config import FabricRuntimeConfig
from intelligence.lifecycle.eol_catalog import EOLCatalog
from intelligence.lifecycle.lifecycle_context_builder import (
    LifecycleContextBuilder,
    public_subscription_label,
)
from intelligence.lifecycle.lifecycle_intelligence import LifecycleIntelligence
from intelligence.lifecycle.lifecycle_risk_engine import LifecycleRiskEngine
from intelligence.lifecycle.lifecycle_trend_engine import LifecycleTrendEngine
from intelligence.lifecycle.modernization_engine import ModernizationEngine


def test_direct_lifecycle_bounds_reject_boolean_fractional_zero_and_negative():
    common = {
        "resources": [],
        "catalog": [],
        "history": [],
        "freshness": "2026-08-18T00:00:00Z",
        "now": lambda: datetime(2026, 8, 18, tzinfo=UTC),
    }
    for name, value in (
        ("max_resources", True),
        ("max_history_rows", 0),
        ("max_catalog_rows", -1),
        ("max_resources", 1.5),
    ):
        with pytest.raises((TypeError, ValueError)):
            LifecycleIntelligence(**common, **{name: value})

    with pytest.raises((TypeError, ValueError)):
        EOLCatalog.from_rows([], approaching_months=24.5)


def test_semantic_inventory_bound_is_checked_before_context_calls():
    class Semantic:
        freshness = "2026-08-18T00:00:00Z"

        def __init__(self):
            self.calls = 0

        def get_resource_context(self, *_args, **_kwargs):
            self.calls += 1
            return {"sections": {}}

    semantic = Semantic()
    inventory = [
        {"resource_id": f"resource-{index}", "name": f"Resource {index}"}
        for index in range(2)
    ]
    with pytest.raises(ValueError, match="bound"):
        LifecycleIntelligence.from_semantic_engine(
            semantic,
            inventory=inventory,
            catalog=[],
            history=[],
            max_resources=1,
        )
    assert semantic.calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("ownership_coverage", "false"),
        ("internet_exposed", "false"),
        ("patch_compliance_score", True),
        ("patch_compliance_score", 1.5),
    ],
)
def test_context_boolean_and_score_types_fail_closed(field, value):
    resource = {"resource_key": "resource-1", "name": "server", field: value}
    with pytest.raises((TypeError, ValueError)):
        LifecycleContextBuilder([resource])


def test_risk_and_modernization_direct_apis_reject_boolean_scores():
    with pytest.raises((TypeError, ValueError)):
        LifecycleRiskEngine().calculate(
            context={"patch_compliance": True},
            classification={"status": "Supported"},
        )
    with pytest.raises((TypeError, ValueError)):
        ModernizationEngine().recommend(
            context={},
            classification={"status": "Supported", "confidence": 1.0},
            risk={"score": True, "factors": {}, "risk_drivers": []},
            upgrade_path="Example OS 2",
        )


def test_unknown_history_risk_does_not_become_zero_risk():
    trends = LifecycleTrendEngine().calculate(
        [
            {
                "resource_key": "resource-1",
                "observed_at": "2026-08-17T00:00:00Z",
                "ingestion_run_id": "run-1",
                "risk_score": None,
                "lifecycle_status": "Unknown",
            }
        ],
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )
    assert trends["30_day"]["risk_score_change"] is None
    assert trends["30_day"]["trend"] == "Unknown"


def test_catalog_rows_fail_closed_on_malformed_types():
    with pytest.raises(TypeError):
        EOLCatalog.from_rows("not-a-list")
    with pytest.raises(TypeError):
        EOLCatalog.from_rows(["not-a-mapping"])


def test_all_guid_shaped_subscription_identifiers_are_aliased():
    raw = "00000000-0000-0000-0000-000000000000"
    label = public_subscription_label(raw)
    assert label != raw
    assert label.startswith("Subscription ")


@pytest.mark.parametrize(
    "lifecycle_config",
    [
        "true",
        "{enabled: 'yes'}",
        "{approaching_months: 24.5}",
        "{near_months: true}",
        "{critical_months: 0}",
    ],
)
def test_lifecycle_runtime_configuration_fails_closed(tmp_path, lifecycle_config):
    path = tmp_path / "fabric.yaml"
    path.write_text(
        "fabric:\n"
        "  auth: {mode: managed_identity}\n"
        "  workspace_name: Operations\n"
        "  lakehouse_name: Inventory\n"
        "  source_data_root: ./source\n"
        f"  lifecycle: {lifecycle_config}\n"
    )
    with pytest.raises((TypeError, ValueError)):
        FabricRuntimeConfig.load(path)


@pytest.mark.parametrize(
    "identifier",
    [
        base64.b64encode(b"5ef7423a-80d9-4c44-ae0f-058600202e4a").decode(),
        b"5ef7423a-80d9-4c44-ae0f-058600202e4a".hex(),
        "%2Fsubscriptions%2F5ef7423a-80d9-4c44-ae0f-058600202e4a",
    ],
)
def test_encoded_subscription_identifiers_are_aliased(identifier):
    assert public_subscription_label(identifier) != identifier


def test_zero_x_prefixed_hex_identifier_is_redacted_from_public_output():
    arm_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    engine = LifecycleIntelligence(
        resources=[
            {
                "resource_key": "resource-1",
                "name": "0x" + arm_id.encode().hex(),
                "product": "Unknown OS",
                "version": "Unknown",
            }
        ],
        catalog=[],
        history=[],
        freshness="2026-08-18T00:00:00Z",
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    assert arm_id.encode().hex() not in json.dumps(engine.analyze()).casefold()


def test_unicode_escape_encoded_identifier_is_redacted_from_public_output():
    arm_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/secret-rg"
    encoded = "".join(f"\\u{ord(character):04x}" for character in arm_id)
    engine = LifecycleIntelligence(
        resources=[
            {
                "resource_key": "resource-1",
                "name": encoded,
                "product": "Unknown OS",
                "version": "Unknown",
            }
        ],
        catalog=[],
        history=[],
        freshness="2026-08-18T00:00:00Z",
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    analysis = engine.analyze()
    public_name = analysis["findings"][0]["resource"]["name"]
    recovered = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        public_name,
    )
    assert recovered != arm_id
    output = json.dumps(analysis).casefold()
    assert "00000000-0000-0000-0000-000000000000" not in output
    assert "secret-rg" not in output


def test_public_outputs_are_bounded_and_serialized_size_capped():
    resources = [
        {
            "resource_key": f"resource-{index}",
            "name": f"server-{index}",
            "product": "Unknown OS",
            "version": "Unknown",
        }
        for index in range(20)
    ]
    engine = LifecycleIntelligence(
        resources=resources,
        catalog=[],
        history=[],
        freshness="2026-08-18T00:00:00Z",
        max_output_items=3,
        max_serialized_bytes=100_000,
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    result = engine.query("Show modernization candidates")
    assert len(result["result"]) == 3
    assert result["collection_metadata"] == {
        "count": 20,
        "returned": 3,
        "truncated": True,
    }
    assert len(json.dumps(result).encode()) <= 100_000


def test_semantic_sources_reject_truthiness_coercion_and_missing_identity():
    class Semantic:
        freshness = "2026-08-18T00:00:00Z"

        def get_resource_context(self, *_args, **_kwargs):
            return {
                "sections": {
                    "ownership": "false",
                    "operational_classification": {},
                    "compliance": {},
                }
            }

    with pytest.raises((TypeError, ValueError)):
        LifecycleIntelligence.from_semantic_engine(
            Semantic(),
            inventory=[
                {
                    "resource_id": "resource-1",
                    "name": "server",
                    "internet_exposed": "false",
                }
            ],
            catalog=[],
            history=[],
        )
    with pytest.raises(ValueError, match="identity"):
        LifecycleIntelligence.from_semantic_engine(
            Semantic(),
            inventory=[{"resource_id": "resource-1"}],
            catalog=[],
            history=[],
        )


def test_known_catalog_products_require_authoritative_source_domains():
    row = {
        "product": "Windows Server",
        "version": "2099",
        "release_date": "2090-01-01",
        "mainstream_support_end": "2095-01-01",
        "extended_support_end": "2100-01-01",
        "last_update_date": "2026-08-18",
        "recommended_upgrade_path": "Attacker OS",
        "source_url": "https://evil.example/fake",
    }
    with pytest.raises(ValueError, match="authoritative"):
        EOLCatalog.from_rows([row])
    row["product"] = "windows server"
    with pytest.raises(ValueError, match="authoritative"):
        EOLCatalog.from_rows([row])

    catalog = EOLCatalog.default()
    assert all(catalog.lookup("Kubernetes", version) for version in ("1.34", "1.35", "1.36"))


def test_all_semantic_members_and_patch_posture_are_validated_before_calls():
    class Semantic:
        freshness = "2026-08-18T00:00:00Z"

        def __init__(self, sections):
            self.sections = sections
            self.calls = 0

        def get_resource_context(self, *_args, **_kwargs):
            self.calls += 1
            return {"sections": self.sections}

    inventory = [{"resource_id": "resource-1", "name": "server"}]
    for sections in ([], {"compliance": []}, {"ownership": [{"name": "Owner"}, "bad"]}):
        semantic = Semantic(sections)
        with pytest.raises(TypeError):
            LifecycleIntelligence.from_semantic_engine(
                semantic, inventory=inventory, catalog=[], history=[]
            )

    semantic = Semantic({})
    with pytest.raises((TypeError, ValueError)):
        LifecycleIntelligence.from_semantic_engine(
            semantic,
            inventory=inventory,
            catalog=[],
            history=[],
            patch_posture={"unmatched": {"compliance_score": True}},
        )
    assert semantic.calls == 0


def test_catalog_history_and_posture_bounds_precede_semantic_enrichment():
    class Semantic:
        freshness = "2026-08-18T00:00:00Z"

        def __init__(self):
            self.calls = 0

        def get_resource_context(self, *_args, **_kwargs):
            self.calls += 1
            return {"sections": {}}

    inventory = [{"resource_id": "resource-1", "name": "server"}]
    semantic = Semantic()
    with pytest.raises(ValueError, match="catalog"):
        LifecycleIntelligence.from_semantic_engine(
            semantic,
            inventory=inventory,
            catalog=[{}, {}],
            history=[],
            max_catalog_rows=1,
        )
    assert semantic.calls == 0

    with pytest.raises(ValueError, match="history"):
        LifecycleIntelligence.from_semantic_engine(
            semantic,
            inventory=inventory,
            catalog=[],
            history=[{}, {}],
            max_history_rows=1,
        )
    assert semantic.calls == 0


def test_nested_rollup_truncation_metadata_is_explicit():
    resources = [
        {
            "resource_key": f"resource-{index}",
            "name": f"server-{index}",
            "subscription": f"Subscription {index}",
            "product": "Unknown OS",
            "version": "Unknown",
        }
        for index in range(5)
    ]
    engine = LifecycleIntelligence(
        resources=resources,
        catalog=[],
        history=[],
        freshness="2026-08-18T00:00:00Z",
        max_output_items=2,
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    result = engine.query("Show lifecycle debt")
    assert result["nested_collection_metadata"]["by_subscription"] == {
        "count": 5,
        "returned": 2,
        "truncated": True,
    }
    report = engine.report("Executive Lifecycle Summary")
    assert report["collection_metadata"]["by_subscription"]["truncated"] is True


def test_canonical_resource_aliases_are_deduplicated():
    with pytest.raises(ValueError, match="Duplicate"):
        LifecycleContextBuilder(
            [
                {"resource_key": "/SUBSCRIPTIONS/X/R1", "name": "one"},
                {"resource_key": " /subscriptions/x/r1 ", "name": "two"},
            ]
        )


def test_history_rejects_invalid_status_and_risk_score():
    common = {
        "resources": [],
        "catalog": [],
        "freshness": "2026-08-18T00:00:00Z",
        "now": lambda: datetime(2026, 8, 18, tzinfo=UTC),
    }
    invalid = {
        "resource_key": "resource-1",
        "observed_at": "2026-08-17T00:00:00Z",
        "ingestion_run_id": "run-1",
        "risk_score": True,
        "lifecycle_status": "Bogus",
    }
    with pytest.raises(ValueError):
        LifecycleIntelligence(**common, history=[invalid])


def test_debt_reduction_uses_latest_in_window_state():
    history = [
        {"resource_key": "r", "observed_at": "2026-01-01T00:00:00Z", "ingestion_run_id": "a", "risk_score": 90, "lifecycle_status": "EOL"},
        {"resource_key": "r", "observed_at": "2026-08-01T00:00:00Z", "ingestion_run_id": "b", "risk_score": 90, "lifecycle_status": "EOL"},
        {"resource_key": "r", "observed_at": "2026-08-17T00:00:00Z", "ingestion_run_id": "c", "risk_score": 10, "lifecycle_status": "Supported"},
    ]
    trend = LifecycleTrendEngine().calculate(
        history, now=datetime(2026, 8, 18, tzinfo=UTC)
    )["30_day"]
    assert trend["lifecycle_debt_reduction"] == 1


def test_unknown_business_service_is_not_counted_as_real_service():
    exposure = lifecycle_engine().summary_engine.exposure(
        [
            {
                "lifecycle_status": "EOL",
                "days_remaining": -1,
                "risk_score": 90,
                "business_service": "Unknown",
                "subscription": "Unknown",
                "environment": "Unknown",
                "application": "Unknown",
                "region": "Unknown",
                "product": "Unknown",
                "modernization_recommendation": {
                    "recommended_action": "Validate the product/version"
                },
            }
        ]
    )
    assert exposure["business_services_at_risk"] == 0


def test_direct_risk_booleans_and_nonfinite_confidence_fail_closed():
    with pytest.raises(TypeError):
        LifecycleRiskEngine().calculate(
            context={"internet_exposed": "false", "ownership_coverage": "false"},
            classification={"status": "Supported"},
        )
    with pytest.raises(ValueError):
        ModernizationEngine().recommend(
            context={"ownership_coverage": True},
            classification={"status": "Supported", "confidence": math.nan},
            risk={"score": 10, "factors": {}, "risk_drivers": []},
            upgrade_path="Example OS 2",
        )


def test_classification_uses_calendar_month_boundaries():
    catalog = EOLCatalog.from_rows(
        [
            {
                "product": "Example OS",
                "version": "1",
                "release_date": "2020-01-01",
                "mainstream_support_end": "2027-02-17",
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
    result = catalog.classify_product(
        "Example OS",
        "1",
        now=datetime(2026, 8, 18, tzinfo=UTC),
        support_channel="mainstream",
    )
    assert result.status.value == "Critical"
