"""HTTP tests for multi-agent autonomous investigation."""

from __future__ import annotations

from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

import operations.autonomous_investigation as investigation_module
from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.exposure_query import ExposureFilter
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.autonomous_investigation import (
    _deterministic_context_narration,
    _nonnegative_count,
    _resolve_foundry_agent,
    _snapshot_observations,
    _tool_args,
    run_context_investigation,
)
from operations.foundry_agent import AgentAnswer
from operations.page_context import PageSnapshot
from operations.tools import ToolResult, _exposure_query_filter

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
    gaps: ClassVar[list[_Item]] = [_Item({"gap_id": "gap-1", "title": "Firewall bypass", "business_service": "Payroll", "subscription_id": "sub-prod"})]
    rule_findings: ClassVar[list[_Item]] = [_Item({"finding_id": "rule-1", "title": "Any-any NSG", "business_service": "Payroll", "subscription_id": "sub-prod"})]

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


@pytest.mark.parametrize("action", ["accept_finding", "reject_finding"])
def test_finding_decisions_require_observed_identity_and_reason(tmp_path, action):
    client = _client(tmp_path)
    ledger = client.post(
        "/api/v1/agents/investigations?subscription=sub-prod",
        headers=_auth(),
        json={"objective": 'Investigate "Payroll" incident network CVE', "timeout_seconds": 5},
    ).json()["data"]
    findings = [
        finding for run in ledger["agent_runs"] for finding in run["findings"]
    ]
    assert len(findings) >= 2
    selected = findings[1]["finding_id"]
    path = f"/api/v1/agents/investigations/{ledger['ledger_id']}/actions?subscription=sub-prod"
    for invalid in (
        {"finding_id": "not-in-this-ledger", "reason": "Reviewed"},
        {"finding_id": selected, "reason": " "},
        {"finding_id": selected, "reason": "x" * 1001},
        {"reason": "Reviewed"},
    ):
        assert client.post(path, headers=_auth(), json={
            "action": action, "payload": invalid,
        }).status_code == 400
    result = client.post(path, headers=_auth(), json={
        "action": action,
        "payload": {"finding_id": selected, "reason": "Reviewed exact evidence"},
    })
    assert result.status_code == 200, result.text
    decisions = result.json()["data"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["payload"]["finding_id"] == selected


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


def test_page_context_resolves_the_requested_specialist_before_generic_narrator():
    specialist = object()
    generic = object()

    class Context:
        def specialist_agent(self, agent_id):
            assert agent_id == "vulnerability"
            return specialist

        def foundry_agent(self):
            return generic

    assert _resolve_foundry_agent(Context(), "vulnerability") is specialist


def test_network_page_loads_its_own_agent_not_the_legacy_narrator(monkeypatch):
    """The network page must answer as its own specialist.

    ``FOUNDRY_NETWORK_AGENT_NAME`` has to win over the legacy shared
    ``FOUNDRY_AGENT_NAME`` narrator whenever both are configured, which is
    exactly the deployed state.
    """
    from api import runtime

    monkeypatch.setattr(runtime, "_foundry_specialist_agents", {})
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "operations-copilot")
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_NAME", "aiops-network-agent")
    # Resolution must not require a live Foundry data plane.
    monkeypatch.setattr(
        runtime.FoundryPromptAgent, "validate_access", lambda self: None
    )
    monkeypatch.setattr(
        runtime.MicrosoftAgentFrameworkFoundryAgent, "validate_access", lambda self: None
    )

    agent = runtime._load_foundry_specialist_agent("network")

    assert agent is not None
    assert agent.agent_name == "aiops-network-agent"
    assert agent.specialist_id == "network"


def test_operations_copilot_loader_uses_generic_agent_not_network(monkeypatch):
    """The MAF orchestrator must be Operations Copilot, not a page specialist."""
    from api import runtime

    monkeypatch.setattr(runtime, "_foundry_agent", runtime._UNSET)
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "operations-copilot")
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_NAME", "aiops-network-agent")
    monkeypatch.setattr(
        runtime.FoundryPromptAgent, "validate_access", lambda self: None
    )
    monkeypatch.setattr(
        runtime.MicrosoftAgentFrameworkFoundryAgent, "validate_access", lambda self: None
    )

    agent = runtime._load_foundry_agent()

    assert agent is not None
    assert agent.agent_name == "operations-copilot"
    assert agent.specialist_id == "operations_copilot"


def test_maf_mode_loads_operations_copilot_through_maf_adapter(monkeypatch):
    """The default provider construction uses Microsoft Agent Framework."""
    from api import runtime

    created = []

    class MafAgent:
        def __init__(self, **kwargs):
            self.agent_name = kwargs["agent_name"]
            self.specialist_id = kwargs["specialist_id"]

        @classmethod
        def from_env(cls, specialist_id=None):
            created.append(specialist_id)
            return cls(
                agent_name="operations-copilot",
                specialist_id=specialist_id or "operations_copilot",
            )

        def validate_access(self):
            return None

    monkeypatch.setattr(runtime, "_foundry_agent", runtime._UNSET)
    monkeypatch.setattr(runtime, "MicrosoftAgentFrameworkFoundryAgent", MafAgent)
    monkeypatch.delenv("AIOPS_AGENT_ORCHESTRATION_MODE", raising=False)

    agent = runtime._load_foundry_agent()

    assert agent is not None
    assert created == [None]
    assert agent.agent_name == "operations-copilot"
    assert agent.specialist_id == "operations_copilot"


def test_deterministic_rollback_uses_rest_foundry_adapter(monkeypatch):
    """The legacy REST adapter remains available as an explicit rollback path."""
    from api import runtime

    created = []

    class RestAgent:
        def __init__(self, **kwargs):
            self.agent_name = kwargs["agent_name"]
            self.specialist_id = kwargs["specialist_id"]

        @classmethod
        def from_env(cls, specialist_id=None):
            created.append(specialist_id)
            return cls(
                agent_name="operations-copilot",
                specialist_id=specialist_id or "operations_copilot",
            )

        def validate_access(self):
            return None

    monkeypatch.setattr(runtime, "_foundry_agent", runtime._UNSET)
    monkeypatch.setattr(runtime, "FoundryPromptAgent", RestAgent)
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "deterministic")

    agent = runtime._load_foundry_agent()

    assert agent is not None
    assert created == [None]
    assert agent.agent_name == "operations-copilot"
    assert agent.specialist_id == "operations_copilot"


def test_specialist_without_its_own_agent_falls_back_to_the_narrator(monkeypatch):
    """The narrator remains a fallback, but only when nothing better exists."""
    from api import runtime

    narrator = object()
    monkeypatch.setattr(runtime, "_foundry_specialist_agents", {})
    monkeypatch.delenv("FOUNDRY_PATCH_AGENT_NAME", raising=False)
    monkeypatch.delenv("FOUNDRY_AGENT_NAME", raising=False)
    monkeypatch.setattr(runtime, "_load_foundry_agent", lambda: narrator)

    assert runtime._load_foundry_specialist_agent("patch") is narrator


def test_api_context_resolves_network_specialist_without_generic_fallback(tmp_path):
    specialist = object()
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        network_agent_provider=lambda: specialist,
    )

    assert context.specialist_agent("network") is specialist


def test_contextual_network_specialist_answers_question_instead_of_emitting_findings(tmp_path):
    class NetworkAgent:
        def answer(self, *, question, context):
            assert question == "Can UAT reach PROD?"
            assert context["page_kind"] == "network"
            return AgentAnswer(
                text="The available evidence does not establish UAT-to-PROD reachability.",
                agent_name="aiops-network-agent",
            )

        def answer_findings(self, **_kwargs):
            raise AssertionError("contextual chat must request a direct answer")

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        network_provider=lambda: _Network(),
        network_agent_provider=lambda: NetworkAgent(),
    )
    page = PageSnapshot.model_validate({
        "page_kind": "network",
        "page_id": "network-topology",
        "question": "Can UAT reach PROD?",
        "scope": {"declared": {"subscription": ["sub-prod"]}},
        "evidence": [{
            "evidence_id": "network:visible:0",
            "section": "network",
            "data": {"check": "topology", "compliant": True},
        }],
    })

    ledger = run_context_investigation(
        page,
        context=context,
        scope=Scope.from_mapping({"subscription": ["sub-prod"]}),
        principal_subject="operator@example.com",
    )

    assert ledger["synthesis"]["mode"] == "foundry"
    assert ledger["synthesis"]["narration"].startswith("The available evidence")


def test_cve_context_aggregates_visible_findings_and_explains_partial_metadata(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[dict[str, object]] = []

    def call_tool(name, args, *, context, scope, principal=None):
        calls.append({"name": name, "args": dict(args), "principal": principal})
        return ToolResult(
            status="ok",
            data={
                "total_count": 93,
                "returned_count": 50,
                "items": [
                    {
                        "severity": "Critical",
                        "weakness_id": "CVE-2025-49796",
                        "target_kind": "container_image",
                        "source_family": "defender_image",
                        "current_state": "active",
                        "deployment_state": "unknown",
                        "represented_workload_count": 0,
                        "total_workload_count": 0,
                        "recommendation": "",
                    }
                    for _ in range(50)
                ],
            },
        )

    monkeypatch.setattr(investigation_module, "call_tool", call_tool)
    principal = Principal(subject="operator@example.com", grants=(Grant("admin"),))
    page = PageSnapshot.model_validate({
        "page_kind": "vulnerability",
        "page_id": "cve:CVE-2025-49796",
        "question": "Explain CVE-2025-49796",
        "scope": {"declared": {"subscription": ["sub-prod"]}},
        "filters": {"weakness_id": ["CVE-2025-49796"]},
        "freshness": [
            {
                "source": "cve",
                "status": "unavailable",
                "observed_at": "2026-09-10T04:48:09Z",
            },
            {
                "source": "nvd",
                "status": "unavailable",
                "observed_at": "2026-09-10T04:48:09Z",
            },
            {
                "source": "findings",
                "status": "partial",
                "observed_at": "2026-09-10T04:48:09Z",
            },
        ],
        "evidence": [
            {
                "evidence_id": f"finding-{index}",
                "section": "exposure/cve-findings",
                "status": "ok",
                "data": {
                    "severity": "Critical",
                    "source_key": f"image-digest:{index}",
                },
            }
            for index in range(12)
        ] + [{
            "evidence_id": "coverage-findings",
            "section": "coverage",
            "status": "ok",
            "data": {
                "source_key": "findings",
                "coverage": {
                    "visible_count": 12,
                    "total_count": 93,
                    "complete": False,
                    "truncated": True,
                },
            },
        }],
    })

    findings = _snapshot_observations(page)
    ledger = run_context_investigation(
        page,
        context=ApiContext(
            onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
            authenticator=StaticTokenAuthenticator({TOKEN: principal}),
            authorizer=Authorizer(),
            telemetry=ApiTelemetry(),
        ),
        scope=Scope.from_mapping({"subscription": ["sub-prod"]}),
        principal_subject=principal.subject,
        principal=principal,
    )

    assert len(findings) == 2
    assert any("93 scoped findings" in item["summary"] for item in findings)
    assert ledger["synthesis"]["mode"] == "deterministic"
    narration = ledger["synthesis"]["narration"]
    assert "CVE-2025-49796" in narration
    assert "**93** matching findings" in narration
    assert "**50 records were inspected**" in narration
    assert "inspected records target container image" in narration
    assert "**50 are active**" in narration
    assert "Critical" in narration
    assert "running workload impact is unknown" in narration
    assert "CVSS severity and vector are unavailable" in narration
    assert "EPSS probability and percentile are unavailable" in narration
    assert "Inspect the remaining 43 scoped findings" in narration
    assert "Map the affected image digests to deployed workloads" in narration
    assert "authenticated Exposure query confirms" not in narration
    assert ledger["warnings"] == [
        (
            "Vulnerability metadata is unavailable from cve, nvd; "
            "scoped Exposure findings remain available with partial coverage"
        )
    ]
    assert calls
    assert all(call["principal"] is principal for call in calls)
    exposure_call = next(call for call in calls if call["name"] == "cve_exposure")
    assert exposure_call["args"] == {"query": "CVE-2025-49796"}


def test_cve_context_explains_unavailable_exposure_without_implying_zero_risk(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        investigation_module,
        "call_tool",
        lambda *args, **kwargs: ToolResult(
            status="unavailable",
            warning="The vulnerability provider is deferred",
        ),
    )
    principal = Principal(subject="operator@example.com", grants=(Grant("admin"),))
    page = PageSnapshot.model_validate({
        "page_kind": "vulnerability",
        "page_id": "cve:CVE-2025-49796",
        "question": "Explain CVE-2025-49796",
        "filters": {"weakness_id": ["CVE-2025-49796"]},
        "freshness": [
            {"source": "findings", "status": "unavailable", "observed_at": "unknown"},
            {"source": "nvd", "status": "unavailable", "observed_at": "unknown"},
        ],
        "evidence": [{
            "evidence_id": "coverage-findings",
            "section": "coverage",
            "status": "unavailable",
            "data": {
                "source_key": "findings",
                "coverage": {
                    "visible_count": 0,
                    "total_count": 0,
                    "complete": False,
                    "truncated": False,
                },
            },
        }],
    })

    ledger = run_context_investigation(
        page,
        context=ApiContext(
            onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
            authenticator=StaticTokenAuthenticator({TOKEN: principal}),
            authorizer=Authorizer(),
            telemetry=ApiTelemetry(),
        ),
        scope=Scope.from_mapping({"subscription": ["sub-prod"]}),
        principal_subject=principal.subject,
        principal=principal,
    )

    narration = ledger["synthesis"]["narration"]
    assert "cannot determine whether CVE-2025-49796 affects resources" in narration
    assert "page snapshot is retained only as non-authoritative" in narration
    assert "no scoped findings" not in narration
    assert "Restore the scoped Exposure query" in narration
    assert "coverage evidence submitted" not in narration


def test_unavailable_cve_recheck_uses_guarded_narration_and_qualifies_snapshot(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        investigation_module,
        "call_tool",
        lambda *args, **kwargs: ToolResult(
            status="unavailable",
            warning="The vulnerability provider is deferred",
        ),
    )
    narrator = type(
        "_Narrator",
        (),
        {"answer": lambda self, **kwargs: AgentAnswer(
            text="No affected resources exist.",
            agent_name="unsafe-narrator",
            model="test",
            grounded=True,
        )},
    )()
    principal = Principal(subject="operator@example.com", grants=(Grant("admin"),))
    page = PageSnapshot.model_validate({
        "page_kind": "vulnerability",
        "page_id": "cve:CVE-2025-49796",
        "question": "Explain CVE-2025-49796",
        "filters": {"weakness_id": ["CVE-2025-49796"]},
        "freshness": [
            {"source": "findings", "status": "partial", "observed_at": "unknown"},
        ],
        "evidence": [{
            "evidence_id": "finding-1",
            "section": "exposure/cve-findings",
            "status": "ok",
            "data": {"severity": "Critical", "source_key": "target-1"},
        }],
    })

    ledger = run_context_investigation(
        page,
        context=ApiContext(
            onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
            authenticator=StaticTokenAuthenticator({TOKEN: principal}),
            authorizer=Authorizer(),
            telemetry=ApiTelemetry(),
            foundry_agent_provider=lambda: narrator,
        ),
        scope=Scope.from_mapping({"subscription": ["sub-prod"]}),
        principal_subject=principal.subject,
        principal=principal,
    )

    narration = ledger["synthesis"]["narration"]
    assert ledger["synthesis"]["mode"] == "deterministic"
    assert "No affected resources exist" not in narration
    assert "1 scoped findings" in narration
    assert "qualified visible context, not current truth" in narration


def test_empty_cve_recheck_uses_scoped_deterministic_narration(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        investigation_module,
        "call_tool",
        lambda *args, **kwargs: ToolResult(status="empty", data={"total_count": 0}),
    )
    narrator = type(
        "_Narrator",
        (),
        {"answer": lambda self, **kwargs: AgentAnswer(
            text="No affected resources exist anywhere.",
            agent_name="unsafe-narrator",
            model="test",
            grounded=True,
        )},
    )()
    principal = Principal(subject="operator@example.com", grants=(Grant("admin"),))
    page = PageSnapshot.model_validate({
        "page_kind": "vulnerability",
        "page_id": "cve:CVE-2025-49796",
        "question": "Explain CVE-2025-49796",
        "filters": {"weakness_id": ["CVE-2025-49796"]},
        "evidence": [],
    })

    ledger = run_context_investigation(
        page,
        context=ApiContext(
            onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
            authenticator=StaticTokenAuthenticator({TOKEN: principal}),
            authorizer=Authorizer(),
            telemetry=ApiTelemetry(),
            foundry_agent_provider=lambda: narrator,
        ),
        scope=Scope.from_mapping({"subscription": ["sub-prod"]}),
        principal_subject=principal.subject,
        principal=principal,
    )

    narration = ledger["synthesis"]["narration"]
    assert ledger["synthesis"]["mode"] == "deterministic"
    assert "No affected resources exist anywhere" not in narration
    assert "no scoped findings for CVE-2025-49796" in narration
    assert "submitted page snapshot may be stale" in narration


def test_cve_exposure_arguments_use_cve_search_not_business_service() -> None:
    assert _tool_args(
        "cve_exposure",
        "Explain CVE-2025-49796",
        "Explain CVE-2025-49796",
    ) == {"query": "CVE-2025-49796"}


def test_single_visible_cve_finding_preserves_total_coverage() -> None:
    page = PageSnapshot.model_validate({
        "page_kind": "vulnerability",
        "page_id": "cve:CVE-2025-49796",
        "question": "Explain this CVE",
        "filters": {"weakness_id": ["CVE-2025-49796"]},
        "evidence": [
            {
                "evidence_id": "finding-1",
                "section": "exposure/cve-findings",
                "status": "ok",
                "data": {"severity": "Critical", "source_key": "target-1"},
            },
            {
                "evidence_id": "coverage-findings",
                "section": "coverage",
                "status": "ok",
                "data": {
                    "source_key": "findings",
                    "coverage": {
                        "visible_count": 1,
                        "total_count": 93,
                        "complete": False,
                        "truncated": True,
                    },
                },
            },
        ],
    })

    finding = next(
        item
        for item in _snapshot_observations(page)
        if item["check_id"] == "exposure/cve-findings"
    )

    assert finding["details"]["visible_count"] == 1
    assert finding["details"]["total_count"] == 93
    assert "93 scoped findings" in finding["summary"]
    assert _tool_args(
        "cve_exposure",
        "What should I do next?",
        "I",
        "CVE-2025-49796",
    ) == {"query": "CVE-2025-49796"}
    assert _tool_args(
        "cve_exposure",
        "Explain this update",
        "this update",
        "KB6000001",
    ) == {"query": "KB6000001"}


def test_cve_narration_handles_server_targets_and_malformed_counts() -> None:
    snapshot = PageSnapshot.model_validate({
        "page_kind": "vulnerability",
        "page_id": "cve:CVE-2025-49796",
        "question": "What is the impact?",
        "freshness": [
            {
                "source": "nvd",
                "status": "unavailable",
                "observed_at": "2026-09-10T04:48:09Z",
            },
            {
                "source": "kev",
                "status": "fresh",
                "observed_at": "2026-09-10T04:48:09Z",
            },
        ],
    })
    findings = [{
        "check_id": "exposure/cve-findings",
        "summary": "1 scoped finding",
        "details": {"total_count": 1, "visible_count": 1},
    }]
    calls = [{
        "tool": "cve_exposure",
        "status": "ok",
        "result": {
            "data": {
                "total_count": "many",
                "returned_count": "one",
                "items": [{
                    "severity": "High",
                    "target_kind": "server",
                    "represented_workload_count": "unknown",
                }],
            },
        },
    }]

    narration = _deterministic_context_narration(snapshot, findings, calls)

    assert "total count is unavailable" in narration
    assert "affected servers" in narration
    assert "image digests" not in narration
    assert "Activity state is unavailable" in narration
    assert "current: kev" not in narration
    assert "NVD metadata is unresolved" in narration
    assert "page reports unavailable freshness" in narration
    assert "Restore or refresh" not in narration


def test_cve_narration_treats_unknown_activity_sentinels_as_unknown() -> None:
    snapshot = PageSnapshot.model_validate({
        "page_kind": "vulnerability",
        "page_id": "cve:CVE-2025-49796",
        "question": "What is the impact?",
    })
    narration = _deterministic_context_narration(
        snapshot,
        [{
            "check_id": "exposure/cve-findings",
            "summary": "1 scoped finding",
            "details": {"total_count": 1, "visible_count": 1},
        }],
        [{
            "tool": "cve_exposure",
            "status": "ok",
            "result": {
                "data": {
                    "total_count": 1,
                    "items": [{
                        "severity": "Critical",
                        "active": False,
                        "current_state": "unknown",
                    }],
                },
            },
        }],
    )

    assert "Activity state is unavailable" in narration
    assert "0 are currently marked active" not in narration


def test_cve_narration_does_not_treat_unknown_workload_counts_as_zero() -> None:
    snapshot = PageSnapshot.model_validate({
        "page_kind": "vulnerability",
        "page_id": "cve:CVE-2025-49796",
        "question": "What is the workload impact?",
    })
    narration = _deterministic_context_narration(
        snapshot,
        [{
            "check_id": "exposure/cve-findings",
            "summary": "1 scoped finding",
            "details": {"total_count": 1, "visible_count": 1},
        }],
        [{
            "tool": "cve_exposure",
            "status": "ok",
            "result": {
                "data": {
                    "total_count": 1,
                    "items": [{
                        "severity": "Critical",
                        "target_kind": "container_image",
                        "current_state": "active",
                        "represented_workload_count": "unknown",
                    }],
                },
            },
        }],
    )

    assert "Workload relationship counts are unavailable" in narration
    assert "no represented workload relationships are present" not in narration


@pytest.mark.parametrize("value", [True, -1, 1.5, float("inf"), "many", None])
def test_invalid_cve_counts_fail_closed(value) -> None:
    assert _nonnegative_count(value, None) is None


def test_canonical_weakness_queries_are_exact() -> None:
    assert _exposure_query_filter("cve-2025-49796") == (
        ExposureFilter(
            "weakness_id",
            "eq",
            "CVE-2025-49796",
        )
    )
    assert _exposure_query_filter("KB600001") == (
        ExposureFilter("weakness_id", "eq", "KB600001")
    )
    assert _exposure_query_filter("critical kernel") == (
        ExposureFilter(
            "search",
            "contains",
            "critical kernel",
        )
    )
