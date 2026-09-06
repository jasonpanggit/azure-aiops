from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOUNDRY_TF = ROOT / "infra" / "terraform" / "foundry.tf"
CREATE_AGENT = ROOT / "infra" / "scripts" / "create-foundry-agent.sh"

EXPECTED_TOOLS = (
    "list_changed_entities",
    "get_entity_evidence",
    "get_ontology_vocabulary",
    "search_relationship_history",
)


def _resource(text: str, kind: str, name: str) -> str:
    marker = f'resource "{kind}" "{name}"'
    start = text.index(marker)
    next_resource = text.find('\nresource "', start + len(marker))
    return text[start:] if next_resource == -1 else text[start:next_resource]


def test_curator_is_a_separately_versioned_gpt_54_mini_prompt_agent() -> None:
    terraform = FOUNDRY_TF.read_text(encoding="utf-8")
    resource = _resource(
        terraform,
        "terraform_data",
        "foundry_ontology_curator_agent",
    )

    assert 'ontology_curator_agent_version = "${var.foundry_specialist_release}.1"' in terraform
    assert "FOUNDRY_AGENT_VERSION" in resource
    assert "= local.ontology_curator_agent_version" in resource
    assert "FOUNDRY_AGENT_MODEL" in resource
    assert "= var.foundry_model_name" in resource
    assert "FOUNDRY_EXPECTED_CURATOR_MODEL" in resource
    assert '= "gpt-5.4-mini"' in resource
    assert "FOUNDRY_AGENT_SPECIALIST_ID" in resource
    assert '= "ontology_curator"' in resource
    assert "local.ontology_curator_prompt" in resource
    assert "var.enable_ontology_curator_agent" in resource
    assert "enable_foundry_specialist_candidate_publish" not in resource

    variables = (
        ROOT / "infra" / "terraform" / "variables.tf"
    ).read_text(encoding="utf-8")
    curator_flag = variables.split(
        'variable "enable_ontology_curator_agent"', maxsplit=1
    )[1].split("}", maxsplit=1)[0]
    assert "type        = bool" in curator_flag
    assert "default     = false" in curator_flag


def test_curator_has_exactly_four_read_only_operations_mcp_tools() -> None:
    terraform = FOUNDRY_TF.read_text(encoding="utf-8")
    tools = terraform.split("ontology_curator_tools = [", maxsplit=1)[1].split(
        "]", maxsplit=1
    )[0]

    assert tuple(
        line.strip().strip('",')
        for line in tools.splitlines()
        if line.strip().startswith('"')
    ) == EXPECTED_TOOLS
    assert "foundry_mcp_tool_config" in terraform
    for forbidden in (
        "foundry_azure_mcp_tool_config",
        "foundry_ai_search_tool_config",
        "publish",
        "write",
        "execute_query",
    ):
        assert forbidden not in tools


def test_creation_script_fails_closed_on_curator_model_or_tool_drift() -> None:
    script = CREATE_AGENT.read_text(encoding="utf-8")

    assert '== "ontology_curator"' in script
    assert "ontology_curator model mismatch" in script
    assert "len(expected) != 4" in script
    assert 'definition.get("type") != "mcp"' in script
    assert 'definition.get("allowed_tools") != expected' in script
