from __future__ import annotations

import pytest

from onboarding.query_catalog import QuerySpec
from semantic.live_operations import (
    collect_live_patch_snapshot,
    live_incident_engine,
    live_vulnerability_service,
)
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
    assert "contains 'payments'" in reader.spec.query
    assert reader.scope == ["sub-1"]


@pytest.mark.parametrize("query", ["show list of VMs", "servers"])
def test_live_resource_provider_maps_server_search_to_resource_types(query):
    reader = Reader()

    LiveResourceProvider(reader).search_resources(
        query, subscription_ids=["sub-1"]
    )

    assert "type =~ 'microsoft.compute/virtualmachines'" in reader.spec.query
    assert "type =~ 'microsoft.hybridcompute/machines'" in reader.spec.query
    assert "contains~" not in reader.spec.query


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
                    "subscriptionId": "sub-1",
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
        provider,
        subscription_ids=["sub-1"],
        software_rows=[
            {
                "_ResourceId": (
                    "/subscriptions/sub-1/resourceGroups/rg/providers/"
                    "Microsoft.Compute/virtualMachines/vm"
                ),
                "SoftwareName": "openssl",
                "CurrentVersion": "3.0.1",
            }
        ],
        build_service=build_service,
    )

    assert service == "service"
    assert [name for name, _scope in reader.queries] == [
        "live_patch_assessment_details",
        "live_patch_installations",
    ]
    assert captured["tables"][0]["silver_patch_findings"][0]["kb_id"] == "5001"
    assert captured["tables"][0]["silver_patch_findings"][0]["status"] == "missing"
    assert captured["tables"][0]["silver_patch_findings"][0]["subscription_id"] == "sub-1"
    assert captured["tables"][0]["silver_patch_findings"][0][
        "software_observations"
    ] == ["openssl 3.0.1"]
    assert captured["freshness"]


def test_live_vulnerability_service_reuses_durable_snapshot_without_arg() -> None:
    class NoQueryProvider:
        def query(self, *_args, **_kwargs):
            raise AssertionError("ARG must not run for a supplied snapshot")

    captured = {}
    snapshot = {
        "schema_version": "1.0.0",
        "subscription_ids": ["sub-1"],
        "observed_at": "2026-09-14T00:00:00Z",
        "findings": [
            {
                "finding_id": "finding-1",
                "target_resource_id": "/subscriptions/sub-1/vm",
                "kb_id": "5001",
                "status": "missing",
                "software_observations": ["openssl 3.0.1"],
            }
        ],
    }

    result = live_vulnerability_service(
        NoQueryProvider(),
        subscription_ids=["sub-1"],
        snapshot=snapshot,
        build_service=lambda tables, freshness, **_kwargs: captured.update(
            tables=tables,
            freshness=freshness,
        )
        or "cached-service",
    )

    assert result == "cached-service"
    assert captured["freshness"] == "2026-09-14T00:00:00Z"
    assert captured["tables"][0]["silver_patch_findings"] == snapshot["findings"]


def test_collect_live_patch_snapshot_rejects_incomplete_arg_evidence() -> None:
    class IncompleteProvider:
        def query(self, *_args, **_kwargs):
            from semantic.live_provider import LiveObservation

            return LiveObservation(
                rows=(),
                observed_at="",
                status="unavailable",
                completeness="unavailable",
            )

    with pytest.raises(RuntimeError, match="assessment evidence is incomplete"):
        collect_live_patch_snapshot(
            IncompleteProvider(),
            subscription_ids=["sub-1"],
        )


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
