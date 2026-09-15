import json
import time

import pytest

from operations.foundry_agent import (
    SPECIALIST_IDS,
    AgentAnswer,
    FoundryAgentError,
    FoundryCoordinatorPlanner,
    FoundryCoordinatorSynthesisAgent,
    FoundryPromptAgent,
    MicrosoftAgentFrameworkFoundryAgent,
    normalize_cited_findings,
    select_foundry_agent_class,
    specialist_catalog,
    validate_executive_synthesis,
)
from operations.orchestration_contract import (
    EvidenceSnapshotV2,
    InvestigationRequest,
    SnapshotCoverage,
)


class _Coordinator:
    agent_name = "operations-copilot"
    agent_version = "5"

    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.calls: list[dict] = []

    def answer(self, **kwargs) -> AgentAnswer:
        self.calls.append(kwargs)
        return AgentAnswer(
            text=self.answers.pop(0),
            agent_name=self.agent_name,
            agent_version=self.agent_version,
        )


def _network_request() -> InvestigationRequest:
    return InvestigationRequest(
        question="Show inspection bypass paths.",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="network",
            page_id="network-topology",
            coverage=SnapshotCoverage(
                visible_count=0,
                total_count=0,
                complete=True,
            ),
        ),
    )


def test_operations_copilot_returns_typed_untrusted_coordinator_plan() -> None:
    coordinator = _Coordinator([
        json.dumps({
            "steps": [{
                "specialist_id": "network",
                "tool_calls": [{
                    "tool": "firewall_nsg_gaps",
                    "arguments": {"category": "firewall_bypass"},
                    "citation_ids": ["snapshot:coverage"],
                    "mutation": False,
                }],
                "depends_on": [],
            }],
            "estimated_tokens": 0,
            "max_wall_seconds": 30,
            "mutation_intent": False,
        })
    ])

    plan = FoundryCoordinatorPlanner(
        coordinator,
        required_hint={
            "specialist_id": "network",
            "tool": "firewall_nsg_gaps",
            "arguments": {"category": "firewall_bypass"},
        },
    )(_network_request())

    assert plan.steps[0].specialist_id == "network"
    assert plan.steps[0].tool_calls[0].tool == "firewall_nsg_gaps"
    assert coordinator.calls[0]["context"]["required_hint"]["arguments"] == {
        "category": "firewall_bypass"
    }
    grants = coordinator.calls[0]["context"][
        "allowed_policy_domains_and_local_tools"
    ]
    assert set(grants) == {"network", "vulnerability", "governance"}
    assert grants["network"] == [
        "network_topology",
        "hub_dependents",
        "traffic_flow",
        "firewall_nsg_gaps",
        "business_service_context",
        "application_context",
        "impact_context",
        "fabric_iq_relationships",
        "fabric_iq_topology",
        "fabric_iq_policy_context",
    ]
    assert "specialist IDs do not claim" in (
        coordinator.calls[0]["context"]["execution_model"]
    )


def test_operations_copilot_synthesis_requires_citation_closed_json() -> None:
    coordinator = _Coordinator([
        json.dumps({
            "findings": [{
                "finding_id": "network-1",
                "evidence_refs": ["tool:network:0"],
                "confidence": "high",
                "uncertainty": [],
                "freshness": "fresh",
                "actionable": False,
                "next_check": "Review the cited route.",
                "summary": "The subnet bypasses inspection.",
            }]
        })
    ])

    answer = FoundryCoordinatorSynthesisAgent(coordinator).answer(
        question="Show inspection bypass paths.",
        context={"findings": [{"evidence_refs": ["tool:network:0"]}]},
    )

    assert "network-1" in answer.text
    assert "Return ONLY JSON" in coordinator.calls[0]["question"]


def test_operations_copilot_normalizes_safe_synthesis_type_drift() -> None:
    coordinator = _Coordinator([
        json.dumps({
            "findings": [{
                "finding_id": "network-1",
                "evidence_refs": "tool:network:0",
                "confidence": "HIGH",
                "uncertainty": "Coverage is partial.",
                "freshness": "FRESH",
                "actionable": "yes",
                "next_check": "Review the cited route.",
                "summary": "The subnet bypasses inspection.",
                "ignored_extra_field": "not authority",
            }]
        })
    ])

    answer = FoundryCoordinatorSynthesisAgent(coordinator).answer(
        question="Show inspection bypass paths.",
        context={"findings": [{"evidence_refs": ["tool:network:0"]}]},
    )
    payload = json.loads(answer.text)

    assert payload == {
        "findings": [{
            "finding_id": "network-1",
            "evidence_refs": ["tool:network:0"],
            "confidence": "high",
            "uncertainty": ["Coverage is partial."],
            "freshness": "fresh",
            "actionable": False,
            "next_check": "Review the cited route.",
            "summary": "The subnet bypasses inspection.",
        }]
    }
    assert validate_executive_synthesis(
        answer.text,
        evidence_refs={"tool:network:0"},
    )


def test_operations_copilot_maps_current_freshness_alias_to_unknown() -> None:
    coordinator = _Coordinator([
        json.dumps({
            "findings": [{
                "finding_id": "network-hub",
                "evidence_refs": ["tool:hub:0"],
                "confidence": "high",
                "uncertainty": [],
                "freshness": "current",
                "actionable": False,
                "next_check": "Review the cited hub dependencies.",
                "summary": "The hub has two dependent spokes.",
            }]
        })
    ])

    answer = FoundryCoordinatorSynthesisAgent(coordinator).answer(
        question="What depends on this hub?",
        context={"findings": [{"evidence_refs": ["tool:hub:0"]}]},
    )
    payload = json.loads(answer.text)

    assert payload["findings"][0]["freshness"] == "unknown"
    assert validate_executive_synthesis(
        answer.text,
        evidence_refs={"tool:hub:0"},
    )


def test_hub_dependents_projects_bounded_facts_for_coordinator() -> None:
    services = [
        {"service_kind": "azure_firewall", "name": "demo-firewall"},
        {"service_kind": "azure_bastion", "name": "demo-bastion"},
        {
            "service_kind": "private_dns_zone",
            "name": "privatelink.documents.azure.com",
        },
        {
            "service_kind": "private_dns_zone",
            "name": "privatelink.postgres.database.azure.com",
        },
        *[
            {
                "service_kind": "unbounded",
                "name": f"must-not-pass-{index}",
            }
            for index in range(20)
        ],
    ]
    findings = normalize_cited_findings([{
        "call_id": "hub:0",
        "specialist_id": "network",
        "tool": "hub_dependents",
        "status": "ok",
        "data": {
            "hub_vnet_id": "/subscriptions/sub-a/resourceGroups/rg/providers/"
            "Microsoft.Network/virtualNetworks/demo-vnet",
            "hub_name": "demo-vnet",
            "dependent_vnets": [],
            "dependent_count": 0,
            "shared_services": services,
            "raw_nested_payload": {"secret": "must-not-pass"},
        },
        "evidence": [{"evidence_id": "tool:hub:0"}],
    }])

    assert findings[0]["summary"] == (
        "Hub demo-vnet has 0 dependent VNets. Shared services (24 total; "
        "showing 8): azure_firewall demo-firewall; azure_bastion demo-bastion; "
        "private_dns_zone privatelink.documents.azure.com; private_dns_zone "
        "privatelink.postgres.database.azure.com; unbounded must-not-pass-0; "
        "unbounded must-not-pass-1; unbounded must-not-pass-2; unbounded "
        "must-not-pass-3."
    )
    assert findings[0]["evidence_refs"] == ["tool:hub:0"]
    assert "must-not-pass-4" not in findings[0]["summary"]
    assert "secret" not in findings[0]["summary"]
    assert len(findings[0]["summary"]) < 1_000


def test_hub_dependents_drops_unresolved_ids_and_nested_labels() -> None:
    findings = normalize_cited_findings([{
        "call_id": "hub:unresolved",
        "specialist_id": "network",
        "tool": "hub_dependents",
        "status": "ok",
        "data": {
            "hub_vnet_id": "/subscriptions/sub-a/resourceGroups/rg/providers/"
            "Microsoft.Network/virtualNetworks/demo-vnet",
            "hub_name": {"nested": "must-not-pass"},
            "dependent_vnets": [{
                "name": "",
                "vnet_id": "/subscriptions/sub-a/resourceGroups/rg/providers/"
                "Microsoft.Network/virtualNetworks/spoke-a",
            }],
            "dependent_count": 1,
            "shared_services": [{
                "service_kind": {"nested": "must-not-pass"},
                "name": ["must-not-pass"],
            }],
        },
        "evidence": [{"evidence_id": "tool:hub:unresolved"}],
    }])

    assert findings[0]["summary"] == (
        "Hub the requested hub has 1 dependent VNets."
    )
    assert "/subscriptions/" not in findings[0]["summary"]
    assert "must-not-pass" not in findings[0]["summary"]


def test_hub_dependents_caps_utf8_bytes_and_skips_invalid_early_rows() -> None:
    invalid = [{"name": {"nested": "drop"}} for _ in range(8)]
    invalid_services = [
        {"service_kind": {"nested": "drop"}, "name": ["drop"]}
        for _ in range(8)
    ]
    findings = normalize_cited_findings([{
        "call_id": "hub:mixed",
        "specialist_id": "network",
        "tool": "hub_dependents",
        "status": "ok",
        "data": {
            "hub_name": "中" * 200,
            "dependent_vnets": [
                *invalid,
                {"name": "valid-spoke"},
            ],
            "dependent_count": 9,
            "shared_services": [
                *invalid_services,
                {
                    "service_kind": "private_dns_zone",
                    "name": "valid.zone.example",
                },
            ],
        },
        "evidence": [{"evidence_id": "tool:hub:mixed"}],
    }])

    summary = findings[0]["summary"]
    assert "valid-spoke" in summary
    assert "private_dns_zone valid.zone.example" in summary
    assert len(summary.encode("utf-8")) <= 2_000


def test_operations_copilot_cannot_change_required_page_hint() -> None:
    coordinator = _Coordinator([
        json.dumps({
            "steps": [{
                "specialist_id": "network",
                "tool_calls": [{
                    "tool": "network_topology",
                    "arguments": {},
                    "citation_ids": ["snapshot:coverage"],
                }],
            }],
        })
    ])

    with pytest.raises(FoundryAgentError, match="changed the required page hint"):
        FoundryCoordinatorPlanner(
            coordinator,
            required_hint={
                "specialist_id": "network",
                "tool": "firewall_nsg_gaps",
                "arguments": {"category": "firewall_bypass"},
            },
        )(_network_request())


def test_large_executive_context_is_transmitted_as_bounded_valid_json() -> None:
    agent = FoundryPromptAgent(
        project_endpoint="https://example",
        agent_name="executive-agent",
        specialist_id="executive_summary",
    )
    context = {
        "findings": [],
        "retained_evidence": [
            {
                "evidence_id": f"thread:prior:{index}",
                "source": "x" * 2_000,
                "status": "ok",
                "observation_status": "historical",
            }
            for index in range(50)
        ],
    }

    prompt = agent.build_prompt("Summarize.", context)
    serialized = prompt.split("PAGE CONTEXT (JSON):\n", 1)[1]

    transmitted = json.loads(serialized)
    assert len(serialized) <= 24_000
    assert {
        item["evidence_id"] for item in transmitted["retained_evidence"]
    } <= {
        item["evidence_id"] for item in context["retained_evidence"]
    }


def test_many_list_valued_context_keys_remain_within_prompt_limit() -> None:
    agent = FoundryPromptAgent(
        project_endpoint="https://example",
        agent_name="network-agent",
    )
    context = {f"field-{index}": [] for index in range(4_000)}

    prompt = agent.build_prompt("Summarize.", context)
    serialized = prompt.split("PAGE CONTEXT (JSON):\n", 1)[1]

    assert len(serialized) <= 24_000
    assert json.loads(serialized)["_truncation"] == "(truncated)"


def test_rest_agent_honors_per_call_timeout_override(monkeypatch) -> None:
    captured: dict[str, object] = {}
    agent = FoundryPromptAgent(
        project_endpoint="https://example",
        agent_name="executive-agent",
        timeout_seconds=60,
    )

    def fake_post(path, payload, *, versioned=True, timeout_seconds=None):
        captured["timeout_seconds"] = timeout_seconds
        return {"output_text": "Bounded response", "model": "test"}

    monkeypatch.setattr(agent, "_post", fake_post)

    agent.answer(
        question="Summarize.",
        context={"findings": []},
        timeout_seconds=0.25,
    )

    assert captured["timeout_seconds"] == 0.25


def test_rest_agent_enforces_end_to_end_call_deadline(monkeypatch) -> None:
    agent = FoundryPromptAgent(
        project_endpoint="https://example",
        agent_name="executive-agent",
        timeout_seconds=60,
    )

    def slow_post(path, payload, *, versioned=True, timeout_seconds=None):
        time.sleep(0.25)
        return {"output_text": "Late response", "model": "test"}

    monkeypatch.setattr(agent, "_post", slow_post)
    started = time.monotonic()

    with pytest.raises(FoundryAgentError, match="exceeded its time budget"):
        agent.answer(
            question="Summarize.",
            context={"findings": []},
            timeout_seconds=0.02,
        )

    assert time.monotonic() - started < 0.15


def test_rest_agent_deadline_is_not_reset_by_slow_response_chunks(monkeypatch) -> None:
    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read1(self, size):
            time.sleep(0.01)
            return b" "

    monkeypatch.setattr(
        "operations.foundry_agent.urllib.request.urlopen",
        lambda request, timeout: SlowResponse(),
    )
    agent = FoundryPromptAgent(
        project_endpoint="https://example",
        agent_name="executive-agent",
        timeout_seconds=60,
        max_retries=0,
    )
    monkeypatch.setattr(agent._tokens, "token", lambda: "test-token")
    started = time.monotonic()

    with pytest.raises(FoundryAgentError, match="exceeded its time budget"):
        agent.answer(
            question="Summarize.",
            context={"findings": []},
            timeout_seconds=0.04,
        )

    assert time.monotonic() - started < 0.15


def test_specialist_catalog_has_independent_names_and_versions(monkeypatch) -> None:
    for specialist in SPECIALIST_IDS:
        monkeypatch.setenv(f"FOUNDRY_{specialist.upper()}_AGENT_NAME", f"{specialist}-agent")
        monkeypatch.setenv(f"FOUNDRY_{specialist.upper()}_AGENT_VERSION", "2026.08.1")

    catalog = specialist_catalog()

    assert {entry["id"] for entry in catalog} == set(SPECIALIST_IDS)
    assert all(entry["name"] and entry["version"] for entry in catalog)
    assert len({entry["name"] for entry in catalog}) == len(SPECIALIST_IDS)


def test_maf_foundry_agent_invokes_sdk_agent_with_existing_contract(monkeypatch) -> None:
    class Response:
        text = "demo-vnet is depended on by app-subnet."

    calls = []

    class SdkAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def run(self, prompt):
            calls.append(prompt)
            return Response()

    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "operations-copilot")

    agent = MicrosoftAgentFrameworkFoundryAgent.from_env(agent_factory=SdkAgent)

    assert agent is not None
    answer = agent.answer(
        question="What depends on demo-vnet?",
        context={"findings": [{"summary": "demo-vnet observed"}]},
    )
    assert isinstance(answer, AgentAnswer)
    assert answer.text == "demo-vnet is depended on by app-subnet."
    assert answer.agent_name == "operations-copilot"
    assert answer.model == "microsoft-agent-framework"
    assert "What depends on demo-vnet?" in calls[0]


def test_versioned_rest_agent_sends_exact_provider_version(monkeypatch) -> None:
    captured: dict[str, object] = {}
    agent = FoundryPromptAgent(
        project_endpoint="https://example",
        agent_name="network-agent",
        agent_version="provider-version-42",
    )

    def fake_post(path, payload, *, versioned=True):
        captured["path"] = path
        captured["payload"] = payload
        captured["versioned"] = versioned
        return {"output_text": "Pinned response", "model": "test"}

    monkeypatch.setattr(agent, "_post", fake_post)

    answer = agent.answer(question="What changed?", context={"findings": []})

    assert answer.text == "Pinned response"
    assert captured["payload"]["agent_reference"] == {
        "type": "agent_reference",
        "name": "network-agent",
        "version": "provider-version-42",
    }


def test_versioned_runtime_uses_rest_path_instead_of_preview_maf(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_VERSION", "provider-version-42")

    selected = select_foundry_agent_class("network", prefer_maf=True)

    assert selected is FoundryPromptAgent


def test_unversioned_runtime_may_use_preview_maf(monkeypatch) -> None:
    monkeypatch.delenv("FOUNDRY_NETWORK_AGENT_VERSION", raising=False)

    selected = select_foundry_agent_class("network", prefer_maf=True)

    assert selected is MicrosoftAgentFrameworkFoundryAgent


def test_version_pinning_required_disables_unversioned_legacy_agent(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_NAME", "network-agent")
    monkeypatch.delenv("FOUNDRY_NETWORK_AGENT_VERSION", raising=False)
    monkeypatch.setenv("AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED", "true")

    assert FoundryPromptAgent.from_env("network") is None
    assert MicrosoftAgentFrameworkFoundryAgent.from_env("network") is None


def test_version_pinning_required_accepts_pinned_shared_coordinator(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "operations-copilot")
    monkeypatch.setenv("FOUNDRY_AGENT_VERSION", "provider-coordinator-42")
    monkeypatch.setenv("AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED", "true")

    rest = FoundryPromptAgent.from_env()
    maf = MicrosoftAgentFrameworkFoundryAgent.from_env()

    assert rest is not None
    assert maf is not None
    assert rest.agent_version == "provider-coordinator-42"
    assert maf.agent_version == "provider-coordinator-42"


def test_legacy_foundry_configuration_is_a_compatible_network_fallback(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "operations-copilot")
    monkeypatch.delenv("FOUNDRY_NETWORK_AGENT_NAME", raising=False)

    agent = FoundryPromptAgent.from_env("network")

    assert agent is not None
    assert agent.agent_name == "operations-copilot"
    assert agent.specialist_id == "network"


def test_specialist_prompt_never_advertises_acquisition_or_mutation_tools(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_NAME", "network-agent")

    agent = FoundryPromptAgent.from_env("network")

    assert agent is not None
    prompt = agent.build_prompt("check topology", {"findings": ["scoped"]})
    assert "delete" not in prompt.casefold()
    assert "acquire" not in prompt.casefold()


def test_specialist_prompt_permits_tool_use_beyond_the_page_context(monkeypatch) -> None:
    """The page context must seed the answer without capping it.

    A restrictive "using only the operational context below" instruction
    stopped the agent calling its own governed MCP tools, so any question
    naming a resource absent from the pre-computed context (for example
    "what depends on demo-vnet?" while the page describes a different VNet)
    degraded into an unrelated findings dump.
    """
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_NAME", "network-agent")

    agent = FoundryPromptAgent.from_env("network")

    assert agent is not None
    prompt = agent.build_prompt(
        "What depends on demo-vnet?", {"findings": ["unrelated-vnet"]}
    )
    lowered = prompt.casefold()
    assert "using only the operational context" not in lowered
    assert "call your governed tools" in lowered
    # The question must survive verbatim, and grounding must still be required.
    assert "What depends on demo-vnet?" in prompt
    assert "never speculate" in lowered


# Phase 6: Test coverage for 7 new specialist agents


def test_vulnerability_agent_from_env_returns_configured_agent(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_VULNERABILITY_AGENT_NAME", "vulnerability-agent")
    monkeypatch.setenv("FOUNDRY_VULNERABILITY_AGENT_VERSION", "2026.08.1")

    agent = FoundryPromptAgent.from_env("vulnerability")

    assert agent is not None
    assert agent.agent_name == "vulnerability-agent"
    assert agent.specialist_id == "vulnerability"
    assert agent.agent_version == "2026.08.1"


def test_patch_agent_from_env_returns_configured_agent(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_PATCH_AGENT_NAME", "patch-agent")
    monkeypatch.setenv("FOUNDRY_PATCH_AGENT_VERSION", "2026.08.1")

    agent = FoundryPromptAgent.from_env("patch")

    assert agent is not None
    assert agent.agent_name == "patch-agent"
    assert agent.specialist_id == "patch"
    assert agent.agent_version == "2026.08.1"


def test_incident_agent_from_env_returns_configured_agent(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_INCIDENT_AGENT_NAME", "incident-agent")
    monkeypatch.setenv("FOUNDRY_INCIDENT_AGENT_VERSION", "2026.08.1")

    agent = FoundryPromptAgent.from_env("incident")

    assert agent is not None
    assert agent.agent_name == "incident-agent"
    assert agent.specialist_id == "incident"
    assert agent.agent_version == "2026.08.1"


def test_change_agent_from_env_returns_configured_agent(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_CHANGE_AGENT_NAME", "change-agent")
    monkeypatch.setenv("FOUNDRY_CHANGE_AGENT_VERSION", "2026.08.1")

    agent = FoundryPromptAgent.from_env("change")

    assert agent is not None
    assert agent.agent_name == "change-agent"
    assert agent.specialist_id == "change"
    assert agent.agent_version == "2026.08.1"


def test_governance_agent_from_env_returns_configured_agent(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_GOVERNANCE_AGENT_NAME", "governance-agent")
    monkeypatch.setenv("FOUNDRY_GOVERNANCE_AGENT_VERSION", "2026.08.1")

    agent = FoundryPromptAgent.from_env("governance")

    assert agent is not None
    assert agent.agent_name == "governance-agent"
    assert agent.specialist_id == "governance"
    assert agent.agent_version == "2026.08.1"


def test_remediation_agent_from_env_returns_configured_agent(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_REMEDIATION_AGENT_NAME", "remediation-agent")
    monkeypatch.setenv("FOUNDRY_REMEDIATION_AGENT_VERSION", "2026.08.1")

    agent = FoundryPromptAgent.from_env("remediation")

    assert agent is not None
    assert agent.agent_name == "remediation-agent"
    assert agent.specialist_id == "remediation"
    assert agent.agent_version == "2026.08.1"


def test_executive_summary_agent_from_env_returns_configured_agent(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_EXECUTIVE_SUMMARY_AGENT_NAME", "executive-summary-agent")
    monkeypatch.setenv("FOUNDRY_EXECUTIVE_SUMMARY_AGENT_VERSION", "2026.08.1")

    agent = FoundryPromptAgent.from_env("executive_summary")

    assert agent is not None
    assert agent.agent_name == "executive-summary-agent"
    assert agent.specialist_id == "executive_summary"
    assert agent.agent_version == "2026.08.1"


def test_unconfigured_specialist_agent_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    # Do not set any specialist-specific env vars

    agent = FoundryPromptAgent.from_env("vulnerability")

    assert agent is None


def test_specialist_agent_falls_back_to_legacy_foundry_config(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "legacy-copilot")
    monkeypatch.delenv("FOUNDRY_VULNERABILITY_AGENT_NAME", raising=False)

    agent = FoundryPromptAgent.from_env("vulnerability")

    assert agent is not None
    assert agent.agent_name == "legacy-copilot"
    assert agent.specialist_id == "vulnerability"


def test_all_specialist_agents_have_distinct_ids_and_versions(monkeypatch) -> None:
    endpoint = "https://example"
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", endpoint)
    
    agents = {}
    for specialist in SPECIALIST_IDS:
        monkeypatch.setenv(f"FOUNDRY_{specialist.upper()}_AGENT_NAME", f"{specialist}-agent")
        monkeypatch.setenv(f"FOUNDRY_{specialist.upper()}_AGENT_VERSION", f"2026.08.{SPECIALIST_IDS.index(specialist)}")
        agent = FoundryPromptAgent.from_env(specialist)
        agents[specialist] = agent

    assert len(agents) == len(SPECIALIST_IDS)
    assert all(agents[s] is not None for s in SPECIALIST_IDS)
    
    specialist_ids = [agents[s].specialist_id for s in SPECIALIST_IDS]
    assert specialist_ids == list(SPECIALIST_IDS)
    
    versions = [agents[s].agent_version for s in SPECIALIST_IDS]
    assert len(set(versions)) == len(SPECIALIST_IDS)


def test_specialist_catalog_status_ready_when_all_configured(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    for specialist in SPECIALIST_IDS:
        monkeypatch.setenv(f"FOUNDRY_{specialist.upper()}_AGENT_NAME", f"{specialist}-agent")
        monkeypatch.setenv(f"FOUNDRY_{specialist.upper()}_AGENT_VERSION", "2026.08.1")

    catalog = specialist_catalog()

    assert all(entry["status"] == "ready" for entry in catalog)


def test_specialist_catalog_status_unconfigured_when_missing_env_vars(monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example")
    # Only configure network agent; others are unconfigured
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_NAME", "network-agent")
    monkeypatch.setenv("FOUNDRY_NETWORK_AGENT_VERSION", "2026.08.1")

    catalog = specialist_catalog()

    network_entry = next(e for e in catalog if e["id"] == "network")
    assert network_entry["status"] == "ready"
    
    other_entries = [e for e in catalog if e["id"] != "network"]
    assert all(e["status"] == "unavailable" for e in other_entries)
