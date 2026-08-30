"""HTTP tests for multi-agent autonomous investigation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService

TOKEN = "agents-token-0123456789abcdef"


class _Item:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


class _Topology:
    def to_dict(self):
        return {
            "resources": [{"id": "vm-payroll-1", "name": "payroll-vm", "subscription_id": "sub-prod", "business_service": "Payroll", "application": "Payroll API", "environment": "prod"}],
            "relationships": [{"source": "vm-payroll-1", "target": "hub", "relationship_type": "routes_through"}],
        }


class _Analysis:
    topology = _Topology()
    gaps = [_Item({"gap_id": "gap-1", "title": "Firewall bypass", "business_service": "Payroll", "subscription_id": "sub-prod"})]
    rule_findings = [_Item({"finding_id": "rule-1", "title": "Any-any NSG", "business_service": "Payroll", "subscription_id": "sub-prod"})]

    def summary(self):
        return {"resource_count": 1}


class _Network:
    snapshot = type("Snapshot", (), {"observed_at": "2026-01-01T00:00:00+00:00"})()

    def scoped(self, _scope):
        return self

    def analyze(self):
        return _Analysis()


class _Vulnerability:
    freshness = "2026-01-01T00:00:00+00:00"

    def exposures(self, _scope):
        return [{"cve_id": "CVE-2026-0001", "business_service": "Payroll", "severity": "critical"}]


class _Incidents:
    def report(self):
        return {"generated_at": "2026-01-01T00:00:00+00:00", "incidents": [{"incident": {"incident_id": "inc-1", "title": "Payroll outage"}, "business_service": "Payroll", "subscription_id": "sub-prod"}]}


class _Remediation:
    def identify_opportunities(self):
        return {"generated_at": "2026-01-01T00:00:00+00:00", "opportunities": [{"id": "opp-1", "business_service": "Payroll", "subscription_id": "sub-prod"}]}

    def generate_plans(self):
        return {"generated_at": "2026-01-01T00:00:00+00:00", "plans": [{"plan_id": "plan-1", "title": "Patch payroll VM", "business_service": "Payroll", "subscription_id": "sub-prod"}]}


class _Semantic:
    def get_service_context(self, name, subject_type="BusinessService"):
        return {"freshness": "2026-01-01T00:00:00+00:00", "subject": {"name": name, "business_service": name}, "sections": {"ownership": [{"owner": "Finance Ops"}]}}

    def get_application_context(self, name):
        return {"freshness": "2026-01-01T00:00:00+00:00", "subject": {"name": name, "application": name}, "sections": {}}

    def get_risk_context(self, subject):
        return {"freshness": "2026-01-01T00:00:00+00:00", "subject": {"name": subject, "business_service": subject}, "risk": {"score": 80}}

    def search(self, query):
        return {"freshness": "2026-01-01T00:00:00+00:00", "items": [{"name": query, "business_service": "Payroll"}]}


def _client(tmp_path) -> TestClient:
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        semantic_provider=lambda: _Semantic(),
        network_provider=lambda: _Network(),
        vulnerability_provider=lambda: _Vulnerability(),
        hybrid_incident_provider=lambda _subs: _Incidents(),
        remediation_provider=lambda: _Remediation(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_catalog_lists_specialized_agents(tmp_path):
    response = _client(tmp_path).get("/api/v1/agents/catalog", headers=_auth())

    assert response.status_code == 200
    agent_ids = {agent["id"] for agent in response.json()["data"]["agents"]}
    assert {"network", "vulnerability", "patch", "incident", "change", "governance", "remediation", "executive_summary"} <= agent_ids


def test_investigation_builds_auditable_ledger_and_evaluation(tmp_path):
    response = _client(tmp_path).post(
        "/api/v1/agents/investigations?subscription=sub-prod",
        headers=_auth(),
        json={"objective": 'Investigate "Payroll" incident network CVE patch remediation owner', "timeout_seconds": 5},
    )

    assert response.status_code == 200
    ledger = response.json()["data"]
    assert ledger["ledger_id"].startswith("mai-")
    assert ledger["selected_agents"]
    assert ledger["agent_runs"]
    assert ledger["reconciliation"]["evidence_count"] > 0
    assert ledger["synthesis"]["recommended_plan"]
    assert ledger["evaluation"]["groundedness"] > 0
    assert all(run["hidden_reasoning_exposed"] is False for run in ledger["agent_runs"])


def test_human_controls_update_principal_scoped_ledger(tmp_path):
    client = _client(tmp_path)
    ledger = client.post(
        "/api/v1/agents/investigations?subscription=sub-prod",
        headers=_auth(),
        json={"objective": 'Investigate "Payroll" remediation', "timeout_seconds": 5},
    ).json()["data"]

    updated = client.post(
        f"/api/v1/agents/investigations/{ledger['ledger_id']}/actions?subscription=sub-prod",
        headers=_auth(),
        json={"action": "assign_owner", "payload": {"owner": "Finance Ops"}},
    )

    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["status"] == "human_review_in_progress"
    assert data["decisions"][-1]["action"] == "assign_owner"

    reloaded = client.get(
        f"/api/v1/agents/investigations/{ledger['ledger_id']}?subscription=sub-prod",
        headers=_auth(),
    ).json()["data"]
    assert reloaded["decisions"][-1]["payload"]["owner"] == "Finance Ops"


def test_findings_name_subjects_and_severity_not_only_counts(tmp_path):
    """Findings must state what was observed, not just how many rows returned."""
    response = _client(tmp_path).post(
        "/api/v1/agents/investigations?subscription=sub-prod",
        headers=_auth(),
        json={"objective": 'Investigate "Payroll" CVE exposure', "timeout_seconds": 5},
    )

    assert response.status_code == 200
    ledger = response.json()["data"]
    summaries = [
        finding["summary"]
        for run in ledger["agent_runs"]
        for finding in run["findings"]
    ]
    assert summaries
    # The old implementation emitted only "<tool> returned N scoped records".
    assert not any("returned 1 scoped records" in text for text in summaries)
    assert any("CVE-2026-0001" in text for text in summaries), summaries


def test_recommended_plan_is_derived_from_observed_evidence(tmp_path):
    response = _client(tmp_path).post(
        "/api/v1/agents/investigations?subscription=sub-prod",
        headers=_auth(),
        json={"objective": 'Investigate "Payroll" CVE exposure and remediation', "timeout_seconds": 5},
    )

    plan = response.json()["data"]["synthesis"]["recommended_plan"]
    assert plan.startswith("1. ")
    assert "owner" in plan.casefold()


def test_synthesis_degrades_without_foundry_agent(tmp_path):
    """No configured narration agent must still yield a complete synthesis."""
    ledger = _client(tmp_path).post(
        "/api/v1/agents/investigations?subscription=sub-prod",
        headers=_auth(),
        json={"objective": 'Investigate "Payroll" CVE exposure', "timeout_seconds": 5},
    ).json()["data"]

    synthesis = ledger["synthesis"]
    assert synthesis["summary"]
    assert synthesis["recommended_plan"]
    assert synthesis["narration"] == ""
    assert ledger["evaluation"]["cost"]["llm_calls"] == 0
