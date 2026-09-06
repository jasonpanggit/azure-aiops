"""Production parity for one scoped truth across every Exposure consumer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import aiops_plugin
from api.app import create_app
from api.exposure_query import (
    ExposureAuthorization,
    ExposureFilter,
    ExposureQueryPage,
)
from api.rbac import Principal
from api.scope import Scope
from fabric_pipelines.vulnerability_pipeline import publish_exposure_page
from intelligence.remediation.action_catalog import EXECUTABLE_ACTION_IDS
from intelligence.vulnerability.exposure_contracts import (
    EXPOSURE_CONTRACT_VERSION,
    ExposureApiPage,
    exposure_catalog,
    exposure_page_from_read_port,
)
from operations.tools import STATUS_OK, call_tool
from storage.datasets import DatasetStore
from tests.exposure_scenario import load_exposure_scenario

TOKEN = "exposure-consumer-token-0123456789"
IMAGE_EXPOSURE_ID = "exposure:image:platform-api:cve-2026-2001"


def _finding_rows(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    connections = {
        row["subscription_id"]: row["connection_id"]
        for row in scenario["scope"]["connections"]
    }
    rows = [
        {
            **identity,
            "tenant_id": scenario["scope"]["tenant_id"],
            "subscription_id": identity["target_id"].split("/")[2],
            "connection_ids": [connections[identity["target_id"].split("/")[2]]],
            "read_model_generation_id": scenario["read_model_generation_id"],
            "completeness": "complete",
        }
        for identity in scenario["identity_cases"].values()
    ]
    image = scenario["container_cases"]["digests"][0]
    rows.append(
        {
            "exposure_id": IMAGE_EXPOSURE_ID,
            "target_id": image["digest"],
            "target_kind": "container_image",
            "weakness_id": image["cve_ids"][0],
            "source_families": ["defender"],
            "tenant_id": scenario["scope"]["tenant_id"],
            "subscription_id": scenario["scope"]["authorized_subscriptions"][1],
            "connection_ids": ["connection-defender-west"],
            "read_model_generation_id": scenario["read_model_generation_id"],
            "completeness": "complete",
            "registry_id": scenario["container_cases"]["registry_id"],
            "image_repository": scenario["container_cases"]["repository"],
            "image_tags": image["tags"],
            "workload_state": image["workload_state"],
            "workload_cluster_id": image["workload"]["cluster_id"],
            "workload_namespace": image["workload"]["namespace"],
            "workload_controller_kind": image["workload"]["controller_kind"],
            "workload_controller_name": image["workload"]["controller_name"],
            "workload_pod_uid": image["workload"]["pod_uid"],
            "application_id": image["workload"]["application_id"],
            "business_service_id": image["workload"]["business_service_id"],
        }
    )
    return rows


@pytest.fixture
def production_consumers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from api.runtime import build_context

    scenario = load_exposure_scenario()
    home = tmp_path / "aiops"
    publish_exposure_page(
        DatasetStore(home),
        _finding_rows(scenario),
        generation_id=scenario["read_model_generation_id"],
        source_status=scenario["source_partitions"][:2],
    )
    monkeypatch.setenv("AIOPS_HOME", str(home))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv(
        "AIOPS_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "subject": "exposure-reader@example.com",
                    "grants": [
                        {
                            "role": "reader",
                            "scope": {
                                "subscription": scenario["scope"][
                                    "authorized_subscriptions"
                                ]
                            },
                        }
                    ],
                }
            }
        ),
    )
    context = build_context()
    scope = Scope.from_mapping(
        {"subscription": scenario["scope"]["authorized_subscriptions"]}
    )
    return scenario, context, scope


def _ids(page: dict[str, Any]) -> set[str]:
    return {str(row["exposure_id"]) for row in page["findings"]}


def _expected_ids(scenario: dict[str, Any]) -> set[str]:
    return {
        scenario["identity_cases"]["aum_only"]["exposure_id"],
        scenario["identity_cases"]["defender_only"]["exposure_id"],
        scenario["identity_cases"]["merged"]["exposure_id"],
        IMAGE_EXPOSURE_ID,
    }


def test_consumer_fixture_names_one_generation_and_all_required_consumers() -> None:
    scenario = load_exposure_scenario()

    assert scenario["read_model_generation_id"] == "exposure-generation-0001"
    assert scenario["consumer_contract"]["consumers"] == [
        "api",
        "web",
        "copilot",
        "remediation",
    ]
    assert scenario["identity_cases"]["unauthorized"]["target_id"].split("/")[2] in set(
        scenario["scope"]["unauthorized_subscriptions"]
    )


def test_api_web_copilot_and_remediation_return_identical_ids_and_generation(
    production_consumers,
) -> None:
    scenario, context, scope = production_consumers
    expected_ids = _expected_ids(scenario)
    read_port = context.resolve_provider("exposure_read_port")
    persisted = read_port.list_exposures(scope)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/vulnerabilities/exposures",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200, response.text
    api_page = response.json()["data"]
    ontology = context.exposure_ontology_provider(scope)
    remediation = context.exposure_remediation_provider().exposure_cases(scope)
    copilot = call_tool("cve_exposure", {}, context=context, scope=scope)

    assert _ids(persisted) == _ids(api_page) == expected_ids
    assert {
        json.loads(row["payload_json"])["exposure_id"]
        for row in ontology.entities
        if row["entity_type"] == "VulnerabilityObservation"
    } == expected_ids
    assert {row["exposure_id"] for row in remediation} == expected_ids
    assert copilot.status == STATUS_OK
    assert _ids(copilot.data) == expected_ids
    assert {
        persisted["read_model_generation_id"],
        api_page["read_model_generation_id"],
        copilot.data["read_model_generation_id"],
        *(row["read_model_generation_id"] for row in remediation),
    } == {scenario["read_model_generation_id"]}


def test_every_consumer_excludes_the_unauthorized_subscription_before_counting(
    production_consumers,
) -> None:
    scenario, context, scope = production_consumers
    unauthorized = scenario["identity_cases"]["unauthorized"]["exposure_id"]

    page = context.resolve_provider("exposure_read_port").list_exposures(scope)
    ontology = context.exposure_ontology_provider(scope)
    remediation = context.exposure_remediation_provider().exposure_cases(scope)
    copilot = call_tool("cve_exposure", {}, context=context, scope=scope)

    assert page["returned_count"] == page["total_count"] == 4
    assert copilot.data["returned_count"] == copilot.data["total_count"] == 4
    assert unauthorized not in _ids(page)
    assert unauthorized not in {row["exposure_id"] for row in remediation}
    assert unauthorized not in json.dumps(ontology.entities, sort_keys=True)


def test_consumer_contract_preserves_completeness_and_source_evidence(
    production_consumers,
) -> None:
    scenario, context, scope = production_consumers
    page = context.resolve_provider("exposure_read_port").list_exposures(scope)
    copilot = call_tool("cve_exposure", {}, context=context, scope=scope)
    remediation = context.exposure_remediation_provider().exposure_cases(scope)

    expected_completeness = {
        "state": "complete",
        "represented_connections": 2,
        "expected_connections": 2,
    }
    expected_sources = [
        {"source_family": "aum", "finding_count": 2},
        {"source_family": "defender", "finding_count": 3},
    ]
    assert page["completeness"] == copilot.data["completeness"] == expected_completeness
    assert page["source_attribution"] == copilot.data["source_attribution"] == expected_sources
    assert {
        tuple(row["source_families"]) for row in remediation
    } == {("aum",), ("defender",), ("aum", "defender")}
    assert {
        row["read_model_generation_id"] for row in remediation
    } == {scenario["read_model_generation_id"]}


def test_container_finding_stops_at_review_handoff_and_invokes_no_action_adapter(
    monkeypatch: pytest.MonkeyPatch,
    production_consumers,
) -> None:
    _scenario, context, scope = production_consumers
    calls: list[str] = []

    def forbidden_adapter() -> object:
        calls.append("provider-action-adapter")
        raise AssertionError("read-only container handoff invoked an action adapter")

    monkeypatch.setattr("api.runtime._patch_execution_adapter", forbidden_adapter)
    monkeypatch.setattr(
        "api.runtime._defender_configuration_adapter", forbidden_adapter
    )

    cases = context.exposure_remediation_provider().exposure_cases(scope)
    container = next(row for row in cases if row["target_kind"] == "container_image")

    assert container["outcome"] in {"review_handoff", "no_safe_action"}
    assert container["direct_execution_supported"] is False
    assert container["action_id"] == ""
    assert container["review_handoff"]["target_kind"] == "container_image"
    assert calls == []
    assert EXECUTABLE_ACTION_IDS == {
        "controlled-patch-recovery",
        "defender-enable-servers-plan-p1",
        "defender-enable-storage-plan-v2",
    }


def test_production_factories_share_one_exposure_read_port_instance(
    production_consumers,
) -> None:
    _scenario, context, scope = production_consumers

    read_port = context.resolve_provider("exposure_read_port")
    assert context.exposure_read_port_provider() is read_port
    assert context.exposure_ontology_provider(scope).quality_report["passed"] is True
    assert context.exposure_remediation_provider().exposure_read_port is read_port


def test_common_contract_compares_query_and_evidence_semantics_not_only_counts(
    production_consumers,
) -> None:
    scenario, context, scope = production_consumers
    persisted = context.resolve_provider("exposure_read_port").list_exposures(scope)
    contract = exposure_page_from_read_port(
        persisted,
        scope=scope,
        filters=(
            ExposureFilter("target_kind", "eq", "container_image"),
        ),
        sort={"field": "priority_score", "direction": "desc"},
    ).contract_data()

    assert contract["version"] == EXPOSURE_CONTRACT_VERSION
    assert contract["query"] == {
        "scope": scope.to_dict(),
        "generation": scenario["read_model_generation_id"],
        "filters": [
            {
                "field": "target_kind",
                "operator": "eq",
                "value": "container_image",
            }
        ],
        "sort": {"field": "priority_score", "direction": "desc"},
        "target_kind": "container_image",
    }
    assert contract["counts"] == {
        "unit": "findings",
        "returned": 4,
        "represented": 4,
        "total": 4,
        "excluded": 0,
    }
    assert contract["units"]["sla_age"] == "seconds"
    assert contract["units"]["secure_score"] == "percent"
    assert {row["source_family"] for row in contract["freshness"]["thresholds"]} == {
        "aum",
        "defender",
        "enrichment",
        "images",
        "workloads",
    }
    assert contract["completeness"]["represented"] == 4
    assert contract["completeness"]["total"] == 4
    assert contract["completeness"]["excluded"] == 0
    assert {row["exposure_id"] for row in contract["evidence_refs"]} == _expected_ids(
        scenario
    )
    assert contract["deep_link_action"]["action_id"] == "open_exposure_detail"
    assert contract["safe_error"] is None


def test_server_owned_catalog_separates_scoped_truth_from_external_lookup() -> None:
    catalog = exposure_catalog()

    assert catalog["version"] == EXPOSURE_CONTRACT_VERSION
    assert {item["field"] for item in catalog["filters"]} >= {
        "severity",
        "target_kind",
        "source_family",
    }
    assert {item["field"] for item in catalog["sorts"]} >= {
        "priority_score",
        "severity",
    }
    assert catalog["target_kinds"] == ["server", "container_image"]
    assert catalog["external_catalog_lookup"] == {
        "label": "External vulnerability catalog lookup",
        "path_template": "/api/v1/vulnerabilities/exposure/external-catalog/{weakness_id}",
        "environment_membership_included": False,
    }


class _Plan13QueryService:
    def __init__(self) -> None:
        self.authorization_calls: list[tuple[str, dict[str, list[str]]]] = []
        self.query_calls: list[dict[str, Any]] = []

    def authorization_for(
        self,
        principal: Principal,
        scope: Scope,
    ) -> ExposureAuthorization:
        self.authorization_calls.append((principal.subject, scope.to_dict()))
        return ExposureAuthorization(
            subject=principal.subject,
            tenant_id="tenant-exposure",
            connection_ids=(
                "connection-aum-east",
                "connection-defender-west",
            ),
            scope={
                "subscription": tuple(scope.values("subscription")),
            },
        )

    def list_page(
        self,
        authorization: ExposureAuthorization,
        **values: Any,
    ) -> ExposureQueryPage:
        self.query_calls.append({"authorization": authorization, **values})
        return ExposureQueryPage(
            items=(
                {
                    "exposure_id": IMAGE_EXPOSURE_ID,
                    "target_id": "sha256:" + ("a" * 64),
                    "target_kind": "container_image",
                    "weakness_id": "CVE-2026-2001",
                    "source_family": "defender",
                    "detail_path": "/exposure/cves/CVE-2026-2001",
                },
            ),
            total_count=1,
            facets={},
            generation="exposure-generation-0001",
            applied_scope=authorization.canonical_scope(),
            applied_filters=(
                {
                    "field": "target_kind",
                    "operator": "eq",
                    "value": "container_image",
                },
            ),
            applied_sort={"field": "severity", "direction": "desc"},
            next_position=None,
            completeness={
                "state": "complete",
                "represented_count": 1,
                "total_count": 1,
                "excluded_count": 0,
            },
            freshness={
                "state": "reported",
                "as_of": "2026-09-06T08:00:00Z",
            },
        )


def test_copilot_and_plugin_use_authenticated_plan13_query_contract() -> None:
    service = _Plan13QueryService()
    scope = Scope.from_mapping({"subscription": ["subscription-east"]})
    principal = Principal(subject="exposure-reader@example.com")
    context = type(
        "Context",
        (),
        {
            "exposure_query_provider": lambda self: service,
            "provider_runtime": None,
        },
    )()
    args = {
        "generation": "exposure-generation-0001",
        "target_kind": "container_image",
        "sort_by": "severity",
        "sort_direction": "desc",
    }

    copilot = call_tool(
        "cve_exposure",
        args,
        context=context,
        scope=scope,
        principal=principal,
    )
    plugin = json.loads(
        aiops_plugin._handle_exposure_query(
            args,
            context=context,
            scope=scope,
            principal=principal,
        )
    )

    assert copilot.status == STATUS_OK
    assert plugin == copilot.to_dict()
    assert plugin["data"]["contract"]["query"]["target_kind"] == "container_image"
    assert plugin["data"]["contract"]["query"]["generation"] == (
        "exposure-generation-0001"
    )
    assert service.authorization_calls == [
        ("exposure-reader@example.com", scope.to_dict()),
        ("exposure-reader@example.com", scope.to_dict()),
    ]
    assert all(
        call["query"].filters
        == (ExposureFilter("target_kind", "eq", "container_image"),)
        for call in service.query_calls
    )
    assert all(call["generation_id"] == "exposure-generation-0001" for call in service.query_calls)


def test_plugin_contract_has_no_caller_controlled_scope_and_fails_closed() -> None:
    properties = aiops_plugin.EXPOSURE_QUERY_SCHEMA["parameters"]["properties"]

    assert "scope" not in properties
    assert {"generation", "target_kind", "sort_by", "sort_direction"} <= set(
        properties
    )
    assert json.loads(aiops_plugin._handle_exposure_query({})) == {
        "status": "denied",
        "data": None,
        "evidence": [],
        "warning": "Exposure query requires authenticated API context",
    }
