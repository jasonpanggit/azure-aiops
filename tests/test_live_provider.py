from __future__ import annotations

import pytest

from onboarding.query_catalog import QuerySpec
from semantic.live_operations import live_incident_engine, live_vulnerability_service
from semantic.live_provider import LiveResourceProvider


class Reader:
    def __init__(self) -> None:
        self.spec = None
        self.scope = None

    def query(self, spec, scope_ids):
        self.spec = spec
        self.scope = scope_ids
        return [{"id": "/subscriptions/sub-1/resourceGroups/rg/providers/x/y"}]


def test_live_resource_provider_queries_arg_at_request_time_with_scope():
    reader = Reader()
    observation = LiveResourceProvider(reader).get_resource(
        "/subscriptions/sub-1/resourceGroups/rg/providers/x/y",
        subscription_ids=["sub-1"],
    )

    assert observation.source == "azure-resource-graph"
    assert observation.status == "ok"
    assert observation.rows[0]["id"].startswith("/subscriptions/")
    assert reader.scope == ["sub-1"]
    assert "| where id =~" in reader.spec.query
    assert reader.spec.incremental is False


def test_live_resource_provider_rejects_unscoped_or_invalid_reads():
    reader = Reader()
    provider = LiveResourceProvider(reader)
    with pytest.raises(ValueError, match="scope"):
        provider.get_resource("resource", subscription_ids=[])
    with pytest.raises(ValueError, match="id"):
        provider.get_resource("", subscription_ids=["sub-1"])


def test_live_resource_provider_search_is_scoped_and_request_time():
    reader = Reader()
    observation = LiveResourceProvider(reader).search_resources(
        "payments", subscription_ids=["sub-1"]
    )
    assert observation.rows
    assert "contains~ 'payments'" in reader.spec.query
    assert reader.scope == ["sub-1"]


def test_live_resource_provider_executes_bounded_generic_query():
    reader = Reader()
    provider = LiveResourceProvider(reader)
    observation = provider.query(
        QuerySpec("custom", "Resources", "Resources | limit 1", False),
        subscription_ids=["sub-1"],
    )

    assert observation.rows
    assert reader.spec.name == "custom"
    assert reader.scope == ["sub-1"]


class MultiReader:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def query(self, spec, scope_ids):
        self.queries.append((spec.name, scope_ids))
        return self.responses.pop(0)


def test_live_vulnerability_service_uses_request_time_patch_rows():
    reader = MultiReader(
        [
            [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm/providers/Microsoft.GuestConfiguration/patchAssessmentResults/latest/softwarePatches/KB5001",
                    "name": "KB5001",
                    "properties": {"kbId": "KB5001", "patchName": "Security update"},
                }
            ],
            [],
        ]
    )
    provider = LiveResourceProvider(reader)

    captured = {}

    def build_service(tables, freshness, **kwargs):
        captured["tables"] = tables
        captured["freshness"] = freshness
        return "service"

    service = live_vulnerability_service(
        provider, subscription_ids=["sub-1"], build_service=build_service
    )

    assert service == "service"
    assert [name for name, _scope in reader.queries] == [
        "live_patch_assessment_details",
        "live_patch_installations",
    ]
    assert captured["tables"][0]["silver_patch_findings"][0]["kb_id"] == "5001"
    assert captured["tables"][0]["silver_patch_findings"][0]["status"] == "missing"
    assert captured["freshness"]


def test_live_incident_engine_projects_alerts_without_snapshot():
    reader = MultiReader(
        [
            [
                {
                    "id": "/subscriptions/sub-1/providers/Microsoft.AlertsManagement/alerts/a1",
                    "name": "a1",
                    "subscriptionId": "sub-1",
                    "properties": {
                        "essentials": {
                            "alertId": "alert-1",
                            "alertRule": "CPU high",
                            "severity": "Sev1",
                            "monitorCondition": "Fired",
                            "startDateTime": "2026-08-23T00:00:00Z",
                            "targetResource": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
                        }
                    },
                }
            ]
        ]
    )
    engine = live_incident_engine(
        LiveResourceProvider(reader), subscription_ids=["sub-1"]
    )

    report = engine.report()
    assert reader.queries[0][0] == "live_alerts"
    assert report["incidents"][0]["incident"]["incident_id"] == "alert-1"
    assert report["incidents"][0]["business_impact"]["risk_score"] == 90
