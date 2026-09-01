"""Guards the Foundry tool registry in Terraform against the real tool set.

``infra/terraform/foundry.tf`` renders ``foundry_tool_registry`` into every
specialist's system prompt as "- name (server): purpose". That prompt is the
only thing the model knows about a tool before calling it, so two drifts are
possible and both are invisible at runtime:

* An advertised ``operations-mcp`` tool with no entry in ``TOOL_REGISTRY``
  makes the agent burn a turn on a call that ``call_tool`` denies.
* An implemented tool missing from the registry is never offered, so the
  capability exists but no agent can reach it.

Neither shows up as a test failure anywhere else -- the Terraform is data and
the Python is code, and nothing joined them until this test.
"""

from __future__ import annotations

import re
from pathlib import Path

from operations.tools import TOOL_REGISTRY

_FOUNDRY_TF = Path(__file__).resolve().parents[1] / "infra" / "terraform" / "foundry.tf"

# Matches `name = { server = "..." ... }` rows inside foundry_tool_registry.
# The name class is deliberately permissive: a stricter pattern would silently
# skip a malformed row, and a row this parser cannot see is a row the
# implemented-tool assertions below cannot check.
_ROW = re.compile(
    r'^\s*(\S+)\s*=\s*\{\s*server\s*=\s*"([^"]+)"',
    re.MULTILINE,
)


def _registry_rows() -> dict[str, str]:
    """Parse the ``foundry_tool_registry`` block into ``{tool: server}``."""
    text = _FOUNDRY_TF.read_text(encoding="utf-8")
    start = text.index("foundry_tool_registry = {")
    # The block ends at the first line that closes it at the original indent.
    end = text.index("\n  }\n", start)
    return {name: server for name, server in _ROW.findall(text[start:end])}


def test_registry_block_is_parsed() -> None:
    """A silently-empty parse would make every other assertion here vacuous."""
    rows = _registry_rows()
    assert len(rows) > 10, rows
    assert {"operations-mcp", "azure-mcp"} == set(rows.values())


def test_advertised_operations_tools_are_implemented() -> None:
    """Every operations-mcp tool offered to an agent must be callable."""
    advertised = {
        name for name, server in _registry_rows().items() if server == "operations-mcp"
    }
    missing = sorted(advertised - set(TOOL_REGISTRY))
    assert not missing, (
        f"Advertised to Foundry specialists but absent from TOOL_REGISTRY: {missing}. "
        "call_tool() denies unknown names, so the agent wastes a turn."
    )


def test_every_registry_tool_is_assigned_to_a_specialist() -> None:
    """A registry entry no specialist lists is unreachable.

    Terraform indexes ``local.foundry_tool_registry[name]`` directly, so a
    specialist naming a tool that does not exist fails at plan time. The
    reverse -- a tool defined but never assigned -- is silent: it renders into
    no prompt, so no agent can ever call it.
    """
    text = _FOUNDRY_TF.read_text(encoding="utf-8")
    assigned = set(re.findall(r'^\s*"([a-z0-9_\-]+)",\s*$', text, re.MULTILINE))
    unassigned = sorted(set(_registry_rows()) - assigned)
    assert not unassigned, (
        f"Defined in foundry_tool_registry but assigned to no specialist: {unassigned}. "
        "These render into no prompt, so no agent can call them."
    )


def test_traffic_flow_is_not_described_as_observed_traffic() -> None:
    """``traffic_flow`` evaluates rule configuration, not flow logs.

    ``TrafficFlowValidator`` decides a verdict from NSG/firewall rules. If the
    prompt tells the model these are *observed* flows, the model will report
    "traffic was seen" when the truth is only "the rules permit it" -- an
    unfalsifiable claim presented as evidence.
    """
    text = _FOUNDRY_TF.read_text(encoding="utf-8")
    start = text.index("traffic_flow ")
    purpose = text[start : text.index("\n", start)]
    assert "not flow logs" in purpose, purpose
    assert "observed" not in purpose.replace("never what was observed", ""), purpose



def test_new_defender_tools_are_advertised_and_assigned() -> None:
    rows = _registry_rows()
    for name in ("defender_alerts", "defender_attack_paths", "defender_secure_score"):
        assert rows.get(name) == "operations-mcp"
    text = _FOUNDRY_TF.read_text(encoding="utf-8")
    remediation_block = text[text.index("remediation = concat(["):text.index("executive_summary =", text.index("remediation = concat(["))]
    vulnerability_block = text[text.index("vulnerability = concat(["):text.index("patch =", text.index("vulnerability = concat(["))]
    for block in (remediation_block, vulnerability_block):
        for name in ("defender_alerts", "defender_attack_paths", "defender_secure_score"):
            assert f'"{name}"' in block



def test_remediation_decision_tools_are_advertised_and_only_remediation_assigned() -> None:
    rows = _registry_rows()
    for name in ("defender_remediation_cases", "remediation_business_decision"):
        assert rows.get(name) == "operations-mcp"
    text = _FOUNDRY_TF.read_text(encoding="utf-8")
    remediation_block = text[text.index("remediation = concat(["):text.index("executive_summary =", text.index("remediation = concat(["))]
    assert '"defender_remediation_cases"' in remediation_block
    assert '"remediation_business_decision"' in remediation_block
