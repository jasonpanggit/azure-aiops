"""Regression tests for "what depends on <vnet>" style questions.

Bug: on the Topology page, asking Operations Copilot "what depends on demo
vnet" returned an inaccurate answer even though the network specialist was
correctly selected. Three compounding defects were involved:

1. ``_extract_subject`` only recognized quoted or Capitalized text, so a
   lowercase phrase like "demo vnet" extracted as an empty subject.
2. The network agent's tool set (``network_topology``, ``firewall_nsg_gaps``)
   never included ``hub_dependents``/``impact_context`` -- the tools that
   actually answer a "what depends on X" question.
3. ``hub_dependents`` matched VNets by exact ``resource_id`` only, so even a
   correctly extracted subject like "demo vnet" would never resolve to a
   real VNet named "demo-vnet".
"""

from __future__ import annotations

from types import SimpleNamespace

from operations.autonomous_investigation import AGENTS, _extract_subject, _tool_args
from operations.tools import _resolve_vnet_id


def test_extract_subject_handles_lowercase_dependency_question():
    assert _extract_subject("what depends on demo vnet") == "demo vnet"


def test_extract_subject_handles_lowercase_impact_question():
    assert _extract_subject("what is the impact of demo vnet") == "demo vnet"


def test_extract_subject_still_prefers_quoted_text():
    assert _extract_subject('what depends on "Demo Hub"') == "Demo Hub"


def test_extract_subject_still_prefers_capitalized_phrase():
    assert _extract_subject("what depends on Retail Banking") == "Retail Banking"


def test_network_agent_can_answer_dependency_questions():
    network = next(agent for agent in AGENTS if agent.id == "network")
    assert "hub_dependents" in network.tools
    assert "impact_context" in network.tools


def test_tool_args_maps_subject_to_hub_dependents_vnet_id():
    assert _tool_args("hub_dependents", "what depends on demo vnet", "demo vnet") == {
        "vnet_id": "demo vnet"
    }


def test_tool_args_maps_subject_to_impact_context_subject():
    assert _tool_args("impact_context", "what depends on demo vnet", "demo vnet") == {
        "subject": "demo vnet"
    }


def _service(*vnets):
    return SimpleNamespace(snapshot=SimpleNamespace(vnets=list(vnets)))


def test_resolve_vnet_id_matches_friendly_name_with_vnet_suffix():
    service = _service(
        SimpleNamespace(resource_id="/subscriptions/x/vnets/demo-vnet", name="demo-vnet"),
        SimpleNamespace(resource_id="/subscriptions/x/vnets/hub-vnet", name="hub-vnet"),
    )
    assert _resolve_vnet_id(service, "demo vnet") == "/subscriptions/x/vnets/demo-vnet"


def test_resolve_vnet_id_matches_bare_name_without_suffix():
    service = _service(
        SimpleNamespace(resource_id="/subscriptions/x/vnets/demo-vnet", name="demo-vnet"),
    )
    assert _resolve_vnet_id(service, "demo") == "/subscriptions/x/vnets/demo-vnet"


def test_resolve_vnet_id_is_case_insensitive():
    service = _service(
        SimpleNamespace(resource_id="/subscriptions/x/vnets/demo-vnet", name="demo-vnet"),
    )
    assert _resolve_vnet_id(service, "Demo VNet") == "/subscriptions/x/vnets/demo-vnet"


def test_resolve_vnet_id_falls_back_to_raw_text_when_no_match():
    service = _service(
        SimpleNamespace(resource_id="/subscriptions/x/vnets/hub-vnet", name="hub-vnet"),
    )
    assert _resolve_vnet_id(service, "nonexistent") == "nonexistent"


def test_resolve_vnet_id_exact_resource_id_still_works():
    service = _service(
        SimpleNamespace(resource_id="/subscriptions/x/vnets/demo-vnet", name="demo-vnet"),
    )
    assert (
        _resolve_vnet_id(service, "/subscriptions/x/vnets/demo-vnet")
        == "/subscriptions/x/vnets/demo-vnet"
    )
