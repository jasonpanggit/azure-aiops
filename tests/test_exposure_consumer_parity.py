"""Production parity for one scoped truth across every Exposure consumer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.scope import Scope
from fabric_pipelines.vulnerability_pipeline import publish_exposure_page
from intelligence.remediation.action_catalog import EXECUTABLE_ACTION_IDS
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
