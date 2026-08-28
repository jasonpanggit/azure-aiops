from operations.foundry_agent import (
    SPECIALIST_IDS,
    FoundryPromptAgent,
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
