"""HTTP tests for the Operational Digital Twin routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService

TOKEN = "twin-token-0123456789abcdef"


class _Topology:
    def to_dict(self):
        return {
            "resources": [
                {
                    "id": "vm-payroll-1",
                    "name": "payroll-vm",
                    "entity_type": "microsoft.compute/virtualmachines",
                    "subscription_id": "sub-prod",
                    "environment": "prod",
                    "business_service": "Payroll",
                    "application": "Payroll API",
                    "owner": "Finance Ops",
                }
            ],
            "relationships": [
                {
                    "source": "vm-payroll-1",
                    "target": "hub-firewall",
                    "relationship_type": "routes_through",
                }
            ],
        }


class _Network:
    def scoped(self, _scope):
        return self

    def analyze(self):
        return type("Analysis", (), {"topology": _Topology()})()


class _Vulnerability:
    def summary(self, _scope):
        return {
            "critical_count": 1,
            "top_priority": [
                {
                    "cve_id": "CVE-2026-0001",
                    "severity": "critical",
                    "expected_risk_reduction": 40,
                }
            ],
        }


class _Incidents:
    def report(self):
        return {
            "incidents": [
                {
                    "incident": {
                        "incident_id": "inc-1",
                        "title": "Payroll outage",
                        "severity": "sev1",
                        "status": "investigating",
                        "started_at": "2026-01-01T01:00:00Z",
                    },
                    "business_impact": {"business_services": ["Payroll"]},
                    "timeline": [
                        {
                            "timestamp": "2026-01-01T01:05:00Z",
                            "event_type": "alert",
                            "summary": "CPU saturation observed",
                        }
                    ],
                }
            ]
        }


class _Remediation:
    def generate_plans(self):
        return {
            "generated_at": "2026-01-01T02:00:00Z",
            "plans": [
                {
                    "plan_id": "plan-1",
                    "title": "Patch payroll VM",
                    "status": "approval_required",
                    "business_service": "Payroll",
                    "simulation_result": {"risk_reduction_percent": 55},
                }
            ],
        }


class _SemanticIndexes:
    entities: ClassVar[dict[str, dict]] = {
        "svc-payroll": {
            "resource_id": "svc-payroll",
            "entity_type": "BusinessService",
            "name": "Payroll",
            "subscription_id": "sub-prod",
        },
        "app-payroll": {
            "resource_id": "app-payroll",
            "entity_type": "Application",
            "name": "Payroll API",
            "subscription_id": "sub-prod",
        },
    }
    relationships: ClassVar[list[dict]] = [
        {
            "subject_id": "app-payroll",
            "object_id": "svc-payroll",
            "relationship_type": "serves",
        }
    ]


class _Semantic:
    indexes = _SemanticIndexes()
    ontology_synchronized_at = "2026-01-01T00:00:00+00:00"


def _client(tmp_path) -> TestClient:
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        semantic_provider=lambda: _Semantic(),
        network_provider=lambda: _Network(),
        vulnerability_provider=lambda: _Vulnerability(),
        incident_provider=lambda: _Incidents(),
        remediation_provider=lambda: _Remediation(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def test_default_twin_scope_uses_active_connection_live_providers(tmp_path):
    client = _client(tmp_path)
    context = client.app.state.context
    context.onboarding.registry.list = lambda **_kwargs: [
        SimpleNamespace(subscription_id="sub-prod", connection_id="conn-prod", is_active=True),
        SimpleNamespace(subscription_id="sub-disabled", connection_id="conn-disabled", is_active=False),
    ]
    calls = []

    def network(subscriptions):
        calls.append(subscriptions)
        return _Network()

    context.hybrid_network_provider = network
    context.network_provider = lambda: None
    response = client.get("/api/v1/twin/graph", headers=_auth())
    assert response.status_code == 200, response.text
    assert calls == [["sub-prod"]]
    assert any(
        entity["name"] == "payroll-vm"
        for entity in response.json()["data"]["entities"]
    )


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_twin_graph_composes_live_sources_with_semantic_envelope(tmp_path):
    response = _client(tmp_path).get("/api/v1/twin/graph", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert body["evidence"][0]["source_engine"] == "semantic.OperationalTwinComposer"
    assert body["source_status"]["snapshot_materialization"] == "disabled"
    assert body["source_status"]["semantic_graph"] == "current"
    assert body["source_status"]["live_operational_sources"] == "request_time"
    assert {entity["kind"] for entity in data["entities"]} >= {
        "resource",
        "business_service",
        "application",
        "vulnerability",
        "incident",
        "remediation",
    }
    assert any(
        relationship["type"] == "serves"
        for relationship in data["relationships"]
    )
    assert data["temporal"]["current_state_version"] == data["version"]
    assert data["timeline"]


def test_twin_source_status_reports_missing_optional_providers(tmp_path):
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        semantic_provider=lambda: None,
        vulnerability_provider=lambda: _Vulnerability(),
    )
    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).get("/api/v1/twin/graph", headers=_auth())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_status"] == {
        "semantic_graph": "unavailable",
        "live_operational_sources": "partial",
        "snapshot_materialization": "disabled",
    }
    assert {
        warning.split(" unavailable:", 1)[0]
        for warning in body["warnings"]
    } >= {"semantic", "network", "incident", "remediation"}


def test_twin_scenario_and_traversal_explain_business_impact(tmp_path):
    client = _client(tmp_path)

    scenario = client.post(
        "/api/v1/twin/scenarios",
        headers=_auth(),
        json={"scenario": "cve_exploitation", "target": "vm-payroll-1"},
    ).json()["data"]
    traversal = client.get("/api/v1/twin/traverse/vm-payroll-1", headers=_auth()).json()[
        "data"
    ]

    assert scenario["scenario"] == "cve_exploitation"
    assert scenario["risk_delta"] > 0
    assert "Payroll" in traversal["business_consequence"]
    assert any(entity["kind"] == "application" for entity in traversal["path"])


def test_twin_export_is_auditable(tmp_path):
    response = _client(tmp_path).get("/api/v1/twin/export", headers=_auth())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["format"] == "operational-twin-export"
    assert data["snapshot"]["version"]
