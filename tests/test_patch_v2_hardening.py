from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest

from fabric.config import FabricRuntimeConfig
from intelligence.patch.patch_compliance_engine import PatchComplianceEngine
from intelligence.patch.patch_context_builder import PatchContextBuilder
from intelligence.patch.patch_intelligence import (
    MissingUpdate,
    PatchIntelligence,
    PatchPolicy,
    ResourceCompliance,
    Update,
)
from intelligence.patch.patch_priority_engine import PatchPriorityEngine
from intelligence.patch.patch_risk_engine import PatchRiskEngine
from intelligence.patch.patch_summary_engine import PatchSummaryEngine
from intelligence.patch.patch_trend_engine import PatchTrendEngine


def _empty(**kwargs):
    return PatchIntelligence(
        resources=[],
        assessments=[],
        installations=[],
        history=[],
        security_findings=[],
        advisor_recommendations=[],
        policies=[],
        freshness="2026-08-18T00:00:00Z",
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        **kwargs,
    )


def test_direct_patch_bounds_reject_boolean_fractional_zero_and_negative():
    for name, value in (
        ("max_resources", True),
        ("max_evidence_rows", 0),
        ("max_output_items", 1.5),
        ("max_serialized_bytes", -1),
    ):
        with pytest.raises((TypeError, ValueError)):
            _empty(**{name: value})


def test_semantic_inventory_bound_precedes_context_calls_and_requires_identity():
    class Semantic:
        freshness = "2026-08-18T00:00:00Z"

        def __init__(self):
            self.calls = 0

        def get_resource_context(self, *_args, **_kwargs):
            self.calls += 1
            return {"sections": {}}

        def get_impact_context(self, *_args, **_kwargs):
            self.calls += 1
            return {}

    semantic = Semantic()
    inventory = [
        {"resource_id": f"resource-{index}", "name": f"Resource {index}"}
        for index in range(2)
    ]
    with pytest.raises(ValueError, match="bound"):
        PatchIntelligence.from_semantic_engine(
            semantic,
            inventory=inventory,
            assessments=[],
            installations=[],
            history=[],
            policies=[],
            max_resources=1,
        )
    assert semantic.calls == 0

    with pytest.raises(ValueError, match="identity"):
        PatchIntelligence.from_semantic_engine(
            semantic,
            inventory=[{"resource_id": "resource-1"}],
            assessments=[],
            installations=[],
            history=[],
            policies=[],
        )


def test_semantic_sections_and_members_fail_closed_on_malformed_types():
    class Semantic:
        freshness = "2026-08-18T00:00:00Z"

        def __init__(self, sections):
            self.sections = sections

        def get_resource_context(self, *_args, **_kwargs):
            return {"sections": self.sections}

        def get_impact_context(self, *_args, **_kwargs):
            return {}

    inventory = [{"resource_id": "resource-1", "name": "server"}]
    for sections in (
        [],
        {"ownership": "false"},
        {"security_findings": [{"name": "finding"}, "bad"]},
    ):
        with pytest.raises(TypeError):
            PatchIntelligence.from_semantic_engine(
                Semantic(sections),
                inventory=inventory,
                assessments=[],
                installations=[],
                history=[],
                policies=[],
            )


def test_semantic_patch_evidence_skips_unmatched_canonical_target():
    class Semantic:
        freshness = "2026-08-18T00:00:00Z"

        def get_resource_context(self, *_args, **_kwargs):
            return {"sections": {}}

        def get_impact_context(self, *_args, **_kwargs):
            return {}

    # Evidence rows referencing a resource absent from inventory (e.g. stale
    # or partially-synced data) are coverage gaps, not fatal errors -- they
    # must be skipped rather than aborting construction for every consumer.
    intelligence = PatchIntelligence.from_semantic_engine(
        Semantic(),
        inventory=[{"resource_id": "resource-1", "name": "server"}],
        assessments=[
            {
                "assessed_resource_id": "resource-missing",
                "last_modified": "2026-08-17T00:00:00Z",
            },
            {
                "assessed_resource_id": "resource-1",
                "last_modified": "2026-08-17T00:00:00Z",
            },
        ],
        installations=[],
        history=[],
        policies=[],
    )
    assert len(intelligence.assessments) == 1
    assert intelligence.assessments[0]["resource_key"] == "resource-1"


def test_semantic_enrichment_collections_are_bounded_before_analysis():
    class Semantic:
        freshness = "2026-08-18T00:00:00Z"

        def get_resource_context(self, *_args, **_kwargs):
            return {
                "sections": {
                    "security_findings": [
                        {"name": "one"},
                        {"name": "two"},
                    ]
                }
            }

        def get_impact_context(self, *_args, **_kwargs):
            return {}

    with pytest.raises(ValueError, match="security_findings"):
        PatchIntelligence.from_semantic_engine(
            Semantic(),
            inventory=[{"resource_id": "resource-1", "name": "server"}],
            assessments=[],
            installations=[],
            history=[],
            policies=[],
            max_evidence_rows=1,
        )


@pytest.mark.parametrize(
    "collection,row",
    [
        ("assessments", {"resource_key": "r", "assessed_at": "2026-08-17T00:00:00Z", "missing_critical_updates": True}),
        ("installations", {"resource_key": "r", "installed_at": "2026-08-17T00:00:00Z", "status": "failed", "severity": "Critical", "age_days": 1.5}),
        ("history", {"resource_key": "r", "observed_at": "2026-08-17T00:00:00Z", "risk_score": True, "status": "failed"}),
    ],
)
def test_patch_source_numeric_types_fail_closed(collection, row):
    args = {
        "resources": [{"resource_key": "r", "name": "server"}],
        "assessments": [],
        "installations": [],
        "history": [],
        "security_findings": [],
        "advisor_recommendations": [],
        "policies": [],
        "freshness": "2026-08-18T00:00:00Z",
        "now": lambda: datetime(2026, 8, 18, tzinfo=UTC),
    }
    args[collection] = [row]
    with pytest.raises((TypeError, ValueError)):
        PatchIntelligence(**args)


def test_canonical_resource_aliases_are_deduplicated():
    with pytest.raises(ValueError, match="Duplicate"):
        PatchContextBuilder(
            [
                {"resource_key": "/SUBSCRIPTIONS/X/R1", "name": "one"},
                {"resource_key": " %2fsubscriptions%2fx%2fr1 ", "name": "two"},
            ]
        )


def test_patch_context_rejects_malformed_blast_radius_counts():
    with pytest.raises((TypeError, ValueError)):
        PatchContextBuilder(
            [
                {
                    "resource_key": "resource-1",
                    "name": "server",
                    "blast_radius": {"application_count": True},
                }
            ]
        )


def test_public_output_is_sanitized_bounded_and_counted_before_truncation():
    arm_id = "/subscriptions/sub/resourceGroups/secret-rg/providers/Microsoft.Compute/virtualMachines/vm"
    encoded = base64.b64encode(arm_id.encode()).decode()
    resources = [
        {
            "resource_key": f"resource-{index}",
            "name": encoded if index == 0 else f"server-{index}",
            "application": f"id={encoded}" if index == 0 else f"App {index}",
        }
        for index in range(10)
    ]
    engine = PatchIntelligence(
        resources=resources,
        assessments=[
            {
                "resource_key": f"resource-{index}",
                "assessed_at": "2026-08-17T00:00:00Z",
                "status": "noncompliant",
                "missing_security_updates": 1,
            }
            for index in range(10)
        ],
        installations=[],
        history=[],
        security_findings=[],
        advisor_recommendations=[],
        policies=[],
        freshness="2026-08-18T00:00:00Z",
        max_output_items=2,
        max_serialized_bytes=100_000,
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    result = engine.query("Show patch priority list")
    assert len(result["result"]) == 2
    assert result["collection_metadata"] == {
        "count": 10,
        "returned": 2,
        "truncated": True,
    }
    assert encoded.casefold() not in json.dumps(result).casefold()
    assert len(json.dumps(result).encode()) <= 100_000

    impact = engine.query("Show business impact")
    assert impact["collection_metadata"] == {
        "count": 10,
        "returned": 2,
        "truncated": True,
    }


def test_duplicate_installation_evidence_fails_closed():
    row = {
        "resource": "Server One",
        "update_id": "KB-1",
        "installed_at": "2026-08-17T00:00:00Z",
        "status": "failed",
    }
    padded = dict(row)
    padded["update_id"] = " KB-1 "
    with pytest.raises(ValueError, match="Duplicate"):
        PatchIntelligence(
            resources=[{"name": "Server One"}],
            assessments=[],
            installations=[row, padded],
            history=[],
            security_findings=[],
            advisor_recommendations=[],
            policies=[],
            freshness="2026-08-18T00:00:00Z",
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        )


def test_installation_evidence_requires_stable_update_identity():
    with pytest.raises(ValueError, match="update_id"):
        PatchIntelligence(
            resources=[{"name": "Server One"}],
            assessments=[],
            installations=[
                {
                    "resource": "Server One",
                    "update_id": "",
                    "installed_at": "2026-08-17T00:00:00Z",
                    "status": "failed",
                }
            ],
            history=[],
            security_findings=[],
            advisor_recommendations=[],
            policies=[],
            freshness="2026-08-18T00:00:00Z",
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        )


def test_duplicate_history_evidence_fails_closed():
    row = {
        "resource": "Server One",
        "observed_at": "2026-08-17T00:00:00Z",
        "status": "failed",
        "risk_score": 80,
    }
    with pytest.raises(ValueError, match="Duplicate"):
        PatchIntelligence(
            resources=[{"name": "Server One"}],
            assessments=[],
            installations=[],
            history=[row, dict(row)],
            security_findings=[],
            advisor_recommendations=[],
            policies=[],
            freshness="2026-08-18T00:00:00Z",
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        )


def test_unknown_trend_risk_is_not_converted_to_zero():
    trend = PatchTrendEngine().calculate(
        [
            {
                "resource": "server",
                "resource_key": "r",
                "observed_at": "2026-08-17T00:00:00Z",
                "risk_score": None,
                "status": "unknown",
            }
        ],
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )["7_day"]
    assert trend["risk_trend"] == {"first": None, "last": None, "change": None}


def test_unknown_trend_status_does_not_create_compliance_degradation():
    trend = PatchTrendEngine().calculate(
        [
            {
                "resource": "server",
                "observed_at": "2026-08-16T00:00:00Z",
                "status": "compliant",
            },
            {
                "resource": "server",
                "observed_at": "2026-08-17T00:00:00Z",
                "status": "unknown",
            },
        ],
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )["7_day"]
    assert trend["compliance_trend"] == "stable"
    assert trend["patch_failure_trend"] == 0.0


def test_malformed_assessment_status_does_not_become_healthy():
    with pytest.raises(ValueError, match="status"):
        PatchComplianceEngine().resource_compliance(
            {"status": "garbage"},
            [],
            now=datetime(2026, 8, 18, tzinfo=UTC),
        )


def test_semantic_history_preserves_confirmed_zero_risk():
    class Semantic:
        freshness = "2026-08-18T00:00:00Z"

        def get_resource_context(self, *_args, **_kwargs):
            return {
                "sections": {
                    "operational_classification": {"criticality": "Critical"}
                }
            }

        def get_impact_context(self, *_args, **_kwargs):
            return {}

    engine = PatchIntelligence.from_semantic_engine(
        Semantic(),
        inventory=[{"resource_id": "resource-1", "name": "server"}],
        assessments=[],
        installations=[],
        history=[
            {
                "assessed_resource_id": "resource-1",
                "observed_at": "2026-08-17T00:00:00Z",
                "status": "compliant",
                "risk_score": 0,
            }
        ],
        policies=[],
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    assert engine.history[0]["risk_score"] == 0


def test_future_patch_publication_exceeding_snapshot_freshness_fails_closed():
    with pytest.raises(ValueError, match="published_at"):
        PatchIntelligence(
            resources=[{"name": "Server One"}],
            assessments=[],
            installations=[
                {
                    "resource": "Server One",
                    "update_id": "KB-1",
                    "published_at": "2099-01-01T00:00:00Z",
                    "installed_at": "2026-08-17T00:00:00Z",
                    "status": "failed",
                }
            ],
            history=[],
            security_findings=[],
            advisor_recommendations=[],
            policies=[],
            freshness="2026-08-18T00:00:00Z",
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        )


def test_direct_risk_compliance_and_priority_types_fail_closed():
    with pytest.raises((TypeError, ValueError)):
        PatchRiskEngine().calculate(
            context={"ownership_coverage": "false"},
            compliance={"patch_age_days": True},
            security_findings=[],
            advisor_recommendations=[],
        )
    with pytest.raises((TypeError, ValueError)):
        PatchComplianceEngine().resource_compliance(
            {"missing_critical_updates": True},
            [],
            now=datetime(2026, 8, 18, tzinfo=UTC),
        )
    with pytest.raises((TypeError, ValueError)):
        PatchComplianceEngine().resource_compliance(
            {"status": "compliant"},
            [],
            now=datetime(2026, 8, 18, tzinfo=UTC),
            policy={"minimum_compliance_score": True},
        )
    with pytest.raises((TypeError, ValueError)):
        PatchPriorityEngine().prioritize(
            context={"ownership_coverage": True},
            compliance={"missing_critical_updates": 0},
            risk={"score": True},
        )


def test_patch_data_model_direct_constructors_validate_exact_types():
    update = Update(update_id="KB-1", name="Security update")
    with pytest.raises((TypeError, ValueError)):
        MissingUpdate(resource="server", update=update, age_days=True)
    with pytest.raises((TypeError, ValueError)):
        PatchPolicy(
            name="baseline",
            environment="Production",
            max_patch_age_days=True,
            minimum_compliance_score=90,
        )
    with pytest.raises((TypeError, ValueError)):
        ResourceCompliance(
            resource="server",
            compliance_score=True,
            patch_success_percent=100,
            patch_failure_percent=0,
            missing_critical_updates=0,
            missing_security_updates=0,
            unpatched=False,
        )


def test_unknown_business_context_is_not_counted_as_real_exposure():
    finding = {
        "risk_score": 90,
        "resource": {"name": "server"},
        "business_service": "Unknown",
        "application": "Unknown",
        "subscription": "Unknown",
        "missing_security_updates": 1,
        "compliance_debt": 1,
        "compliance_score": 10,
    }
    exposure = PatchSummaryEngine.exposure([finding])
    assert exposure["business_exposure"] == []
    assert exposure["vulnerable_applications"] == []


@pytest.mark.parametrize("value", ["true", "1.5", "0", "-1"])
def test_patch_runtime_bounds_fail_closed(tmp_path, value):
    path = tmp_path / "fabric.yaml"
    path.write_text(
        f"""
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  patch_intelligence:
    enabled: true
    max_resources: {value}
"""
    )
    with pytest.raises((TypeError, ValueError)):
        FabricRuntimeConfig.load(path)


def test_patch_runtime_configuration_exposes_strict_output_bounds(tmp_path):
    path = tmp_path / "fabric.yaml"
    path.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  patch_intelligence:
    enabled: true
    max_resources: 2000
    max_evidence_rows: 30000
    max_output_items: 75
    max_serialized_bytes: 750000
"""
    )
    config = FabricRuntimeConfig.load(path).patch_intelligence
    assert config.enabled is True
    assert config.max_resources == 2000
    assert config.max_evidence_rows == 30000
    assert config.max_output_items == 75
    assert config.max_serialized_bytes == 750000


def test_patch_policy_runtime_rejects_boolean_numeric_fields(tmp_path):
    path = tmp_path / "fabric.yaml"
    path.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  patch_policies:
    - name: Production
      environment: Production
      max_patch_age_days: true
      minimum_compliance_score: 90
"""
    )
    with pytest.raises((TypeError, ValueError)):
        FabricRuntimeConfig.load(path)
