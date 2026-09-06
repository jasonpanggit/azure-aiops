from operations.foundry_agent import (
    SPECIALIST_IDS,
    AgentAnswer,
    FoundryPromptAgent,
    MicrosoftAgentFrameworkFoundryAgent,
    select_foundry_agent_class,
    specialist_catalog,
)


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
