from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from api.dependencies import ApiContext
from api.scope import Scope
from operations.autonomous_investigation import (
    AGENTS,
    AgentDefinition,
    _agent_run,
    _resolve_context_narrator,
    _select_context_specialists,
    _tool_args,
    agent_catalog,
    run_context_investigation,
)
from operations.foundry_agent import (
    SPECIALIST_IDS,
    _agent_contract,
    _build_prompt,
    specialist_catalog,
)
from operations.mcp_server import (
    REVIEWED_TOOLS,
    reviewed_tools_for_specialist,
    tool_definitions,
)
from operations.page_context import PageSnapshot
from operations.specialist_manifest import (
    LOCKED_NON_INTERACTIVE_CONSUMER_IDS,
    LOCKED_SPECIALIST_IDS,
    ONTOLOGY_CURATOR_ID,
    load_specialist_manifest,
)
from operations.tools import TOOL_REGISTRY

EXPECTED_SPECIALIST_IDS = (
    "network",
    "vulnerability",
    "patch",
    "incident",
    "change",
    "governance",
    "remediation",
    "executive_summary",
    "inventory_data_health",
    "identity_access",
    "finops",
    "resource_health_observability",
)
EXPECTED_ONTOLOGY_CURATOR_TOOLS = (
    "list_changed_entities",
    "get_entity_evidence",
    "get_ontology_vocabulary",
    "search_relationship_history",
)

FORBIDDEN_TOOL_MARKERS = {
    "approve",
    "create",
    "delete",
    "execute",
    "patch_apply",
    "restart",
    "update",
    "write",
}


def _manifest_payload() -> dict:
    manifest = load_specialist_manifest()
    return json.loads(manifest.model_dump_json())


def _write_manifest(tmp_path, payload: dict):
    path = tmp_path / "specialists.v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_locked_portfolio_and_runtime_projection_are_exact():
    manifest = load_specialist_manifest()

    assert LOCKED_SPECIALIST_IDS == EXPECTED_SPECIALIST_IDS
    assert manifest.specialist_ids == EXPECTED_SPECIALIST_IDS
    assert SPECIALIST_IDS == EXPECTED_SPECIALIST_IDS
    assert tuple(agent.id for agent in AGENTS) == EXPECTED_SPECIALIST_IDS
    assert len({agent.id for agent in AGENTS}) == 12

    runtime = {item["id"]: item for item in manifest.runtime_projection()}
    assert {agent.id: agent.to_dict() for agent in AGENTS} == runtime
    assert runtime["inventory_data_health"]["tools"] == ["inventory_resources"]
    assert runtime["executive_summary"]["tools"] == []
    assert set(runtime["executive_summary"]["depends_on"]) == (
        set(EXPECTED_SPECIALIST_IDS) - {"executive_summary"}
    )


def test_operations_mcp_and_registry_grants_are_exact_and_read_only():
    manifest = load_specialist_manifest()
    expected_grants = manifest.operations_mcp_grants()

    assert set(REVIEWED_TOOLS) == set(TOOL_REGISTRY)
    assert set(manifest.operations_tool_names()) == set(TOOL_REGISTRY)
    for specialist_id, expected in expected_grants.items():
        assert reviewed_tools_for_specialist(specialist_id) == expected
        assert all(
            marker not in tool.casefold()
            for tool in expected
            for marker in FORBIDDEN_TOOL_MARKERS
        )

    assert {"cve_exposure", "remediation_plans"} <= set(expected_grants["patch"])
    assert {"incidents", "search"} <= set(expected_grants["change"])
    assert "risk_context" in expected_grants["governance"]
    assert reviewed_tools_for_specialist("unknown") == ()
    schemas = {item["name"]: item["inputSchema"] for item in tool_definitions()}
    assert schemas["risk_context"]["required"] == ["subject"]
    assert schemas["search"]["required"] == ["query"]
    assert schemas["remediation_business_decision"]["required"] == ["name"]
    assert "business_service" in schemas["defender_remediation_cases"]["properties"]


def test_ontology_curator_is_an_exact_non_interactive_tool_consumer():
    manifest = load_specialist_manifest()
    manifest_grants = manifest.non_interactive_operations_mcp_grants()
    runtime_grants = reviewed_tools_for_specialist(ONTOLOGY_CURATOR_ID)

    assert manifest_grants == {
        ONTOLOGY_CURATOR_ID: EXPECTED_ONTOLOGY_CURATOR_TOOLS
    }
    assert LOCKED_NON_INTERACTIVE_CONSUMER_IDS == (ONTOLOGY_CURATOR_ID,)
    assert runtime_grants == manifest_grants[ONTOLOGY_CURATOR_ID]
    assert ONTOLOGY_CURATOR_ID not in manifest.specialist_ids
    assert ONTOLOGY_CURATOR_ID not in {
        specialist_id
        for specialist_ids in manifest.page_mapping_projection().values()
        for specialist_id in specialist_ids
    }
    interactive_tools = {
        tool
        for grants in manifest.operations_mcp_grants().values()
        for tool in grants
    }
    assert interactive_tools.isdisjoint(EXPECTED_ONTOLOGY_CURATOR_TOOLS)
    assert set(manifest.operations_tool_names()) == interactive_tools | set(
        EXPECTED_ONTOLOGY_CURATOR_TOOLS
    )
    consumer = manifest.non_interactive_tool_consumers[0]
    assert set(consumer.model_dump()) == {
        "id",
        "purpose",
        "operations_mcp_tools",
        "read_only",
    }
    assert consumer.read_only is True


def test_azure_mcp_projection_is_exact_and_contains_no_mutation_grants():
    manifest = load_specialist_manifest()

    assert manifest.azure_mcp_grants() == {
        specialist.id: specialist.azure_mcp_tools
        for specialist in manifest.specialists
    }
    assert manifest.azure_mcp_grants()["identity_access"] == (
        "subscription_list",
        "group_list",
        "role_assignment_list",
        "arm_execute_query",
    )
    assert manifest.azure_mcp_grants()["finops"] == (
        "subscription_list",
        "group_list",
        "arm_query_costs",
        "advisor_recommendation_list",
        "advisor_recommendation_summary",
    )
    assert manifest.azure_mcp_grants()["resource_health_observability"] == (
        "subscription_list",
        "group_list",
        "resourcehealth_availability-status_get",
        "resourcehealth_health-events_list",
        "monitor_activitylog_list",
        "monitor_resource_log_query",
    )


def test_catalog_page_mapping_prompt_and_output_projections_are_exact(monkeypatch):
    manifest = load_specialist_manifest()
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)

    foundry = {item["id"]: item for item in specialist_catalog()}
    runtime_catalog = {item["id"]: item for item in agent_catalog()}
    manifest_catalog = {
        item["id"]: item for item in manifest.catalog_projection()
    }

    assert set(foundry) == set(EXPECTED_SPECIALIST_IDS)
    assert all(item["status"] == "unavailable" for item in foundry.values())
    assert {
        specialist_id: {
            key: value
            for key, value in entry.items()
            if key in {"id", "display_name", "purpose", "ui_metadata", "page_mappings"}
        }
        for specialist_id, entry in runtime_catalog.items()
    } == manifest_catalog
    assert manifest.page_mapping_projection()["identity"] == ("identity_access",)
    assert manifest.page_mapping_projection()["finops"] == ("finops",)
    assert manifest.page_mapping_projection()["resource_health"] == (
        "resource_health_observability",
    )
    assert manifest.page_mapping_projection()["resource"] == (
        "governance",
        "resource_health_observability",
    )
    assert manifest.page_mapping_projection()["remediation"] == (
        "remediation",
        "governance",
    )

    for specialist in manifest.specialists:
        assert _agent_contract(specialist.id) == {
            "required": set(specialist.output_contract.required_fields),
            "domain_fields": set(specialist.output_contract.domain_fields),
        }
        prompt = _build_prompt(
            question="What is known?",
            context={"evidence": []},
            specialist_id=specialist.id,
        )
        expected_tools = (
            ", ".join(specialist.operations_mcp_tools)
            or "none (aggregation only)"
        )
        assert f"Purpose: {specialist.purpose}" in prompt
        assert f"Governed Operations MCP tools: {expected_tools}." in prompt
        assert "report it as unavailable" in prompt


def test_neutral_remediation_question_preserves_remediation_narrator_priority():
    page_specialists = load_specialist_manifest().page_mapping_projection()
    selected = _select_context_specialists(
        page_kind="remediation",
        question="Summarize what I am looking at",
        page_specialists=page_specialists,
    )
    remediation_agent = object()
    governance_agent = object()
    context = SimpleNamespace(
        specialist_agent=lambda specialist_id: {
            "remediation": remediation_agent,
            "governance": governance_agent,
        }.get(specialist_id)
    )

    narrator, narrator_id = _resolve_context_narrator(
        context,
        selected,
        prefer_copilot=False,
    )

    assert selected == ["remediation", "governance"]
    assert narrator is remediation_agent
    assert narrator_id == "remediation"


def test_all_manifest_specialists_resolve_through_provider_runtime():
    sentinel = object()

    class Runtime:
        def get(self, name, *, optional=False):
            assert optional is True
            assert name.endswith("_agent")
            return sentinel

    context = object.__new__(ApiContext)
    context.provider_runtime = Runtime()

    assert all(
        context.specialist_agent(specialist_id) is sentinel
        for specialist_id in EXPECTED_SPECIALIST_IDS
    )


def test_parameterized_tool_arguments_are_bounded_and_missing_inputs_skip_io(
    monkeypatch,
):
    assert _tool_args(
        "cve_detail",
        "Investigate CVE-2026-12345",
        "CVE-2026-12345",
    ) == {"cve_id": "CVE-2026-12345"}
    assert _tool_args(
        "traffic_flow",
        "Can traffic flow from web-subnet to data-subnet?",
        "",
    ) == {"source": "web-subnet", "destination": "data-subnet"}
    assert _tool_args(
        "remediation_business_decision",
        "Review plan RMP-123",
        "RMP-123",
    ) == {"name": "RMP-123"}
    assert _tool_args(
        "defender_remediation_cases",
        "Show defender remediation cases",
        "Show",
    ) == {}
    assert _tool_args(
        "defender_remediation_cases",
        "Show defender remediation cases for business service Retail Banking",
        "Show",
    ) == {"business_service": "Retail Banking"}

    calls: list[str] = []
    monkeypatch.setattr(
        "operations.autonomous_investigation.call_tool",
        lambda name, args, **kwargs: calls.append(name),
    )
    agent = AgentDefinition(
        id="network",
        name="Network Agent",
        role="Network",
        tools=("traffic_flow",),
        keywords=("network",),
    )

    run = _agent_run(
        agent,
        "Summarize network health",
        context=object(),
        scope=Scope.unrestricted(),
    )

    assert calls == []
    assert run["tool_calls"] == []


def test_empty_network_snapshot_skips_fabric_iq_enrichment_io(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "deterministic")
    monkeypatch.setattr(
        "operations.autonomous_investigation._agent_run",
        lambda agent, objective, **kwargs: {
            "agent_id": agent.id,
            "agent_name": agent.name,
            "status": "empty",
            "tool_calls": [],
            "findings": [],
            "evidence": [],
        },
    )
    monkeypatch.setattr(
        "operations.autonomous_investigation.call_tool",
        lambda name, args, **kwargs: calls.append((name, args)),
    )

    ledger = run_context_investigation(
        PageSnapshot(
            page_kind="network",
            page_id="topology",
            question="Summarize network health",
        ),
        context=SimpleNamespace(),
        scope=Scope.unrestricted(),
        principal_subject="operator@example.com",
    )

    assert calls == []
    assert all(
        call["operation"] != "enrichment" for call in ledger["tool_calls"]
    )


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda payload: payload["specialists"][0].update({"unexpected": True}),
            "extra",
        ),
        (
            lambda payload: payload["specialists"].__setitem__(
                1,
                {
                    **deepcopy(payload["specialists"][1]),
                    "id": payload["specialists"][0]["id"],
                },
            ),
            "unique",
        ),
        (
            lambda payload: (
                payload["specialists"][0].update(
                    {"dependencies": [payload["specialists"][1]["id"]]}
                ),
                payload["specialists"][1].update(
                    {"dependencies": [payload["specialists"][0]["id"]]}
                ),
            ),
            "cycle",
        ),
        (
            lambda payload: payload["specialists"][0].update(
                {"operations_mcp_tools": ["missing_read_tool"]}
            ),
            "missing Operations MCP tools",
        ),
        (
            lambda payload: payload["specialists"][0].update(
                {"operations_mcp_tools": ["execute_remediation"]}
            ),
            "read-only",
        ),
        (
            lambda payload: payload["non_interactive_tool_consumers"][0][
                "operations_mcp_tools"
            ].append("risk_context"),
            "grants overlap",
        ),
        (
            lambda payload: payload["non_interactive_tool_consumers"][0][
                "operations_mcp_tools"
            ].append("missing_read_tool"),
            "missing Operations MCP tools",
        ),
        (
            lambda payload: payload["non_interactive_tool_consumers"][0][
                "operations_mcp_tools"
            ].append("execute_remediation"),
            "read-only",
        ),
        (
            lambda payload: payload["non_interactive_tool_consumers"][0][
                "operations_mcp_tools"
            ].remove("list_changed_entities"),
            "unassigned Operations MCP tools",
        ),
        (
            lambda payload: payload["non_interactive_tool_consumers"][0].update(
                {"page_mappings": ["connections"]}
            ),
            "extra",
        ),
        (
            lambda payload: payload["non_interactive_tool_consumers"][0].update(
                {"client_secret": "forbidden"}
            ),
            "credentials are forbidden",
        ),
        (
            lambda payload: payload["specialists"][0].update(
                {"page_mappings": ["not_a_page"]}
            ),
            "page_mappings",
        ),
        (
            lambda payload: payload["specialists"][0].update(
                {"azure_mcp_tools": ["communication_sms_send"]}
            ),
            "missing or non-read-only Azure MCP tools",
        ),
        (
            lambda payload: payload["specialists"][0].update(
                {"client_secret": "forbidden"}
            ),
            "credentials are forbidden",
        ),
        (
            lambda payload: payload["specialists"][0].update(
                {"purpose": "Use client_secret=real-secret"}
            ),
            "credentials are forbidden",
        ),
        (
            lambda payload: payload["specialists"][8][
                "operations_mcp_tools"
            ].append("cve_detail"),
            "locked specialist contract",
        ),
        (
            lambda payload: payload["specialists"][0][
                "output_contract"
            ].update({"requires_citations": False}),
            "requires_citations",
        ),
        (
            lambda payload: payload["specialists"][0]["output_contract"][
                "required_fields"
            ].remove("summary"),
            "locked specialist contract",
        ),
        (
            lambda payload: payload["specialists"][0]["intent_examples"].append(
                "routing drift"
            ),
            "locked specialist contract",
        ),
        (
            lambda payload: payload["specialists"][0]["page_mappings"].__setitem__(
                1, "overview"
            ),
            "locked specialist contract",
        ),
        (
            lambda payload: payload["specialists"][0]["knowledge_policy"][
                "optional_sources"
            ].remove("fabric_iq"),
            "locked specialist contract",
        ),
        (
            lambda payload: payload["specialists"][0]["foundry"].update(
                {"model": "gpt-4.2"}
            ),
            "locked specialist contract",
        ),
    ],
)
def test_manifest_rejects_drift_and_security_widening(tmp_path, mutate, error):
    payload = _manifest_payload()
    mutate(payload)

    with pytest.raises((ValueError, RuntimeError), match=error):
        load_specialist_manifest(_write_manifest(tmp_path, payload))


def test_manifest_contains_no_credentials_or_mutation_grants():
    serialized = load_specialist_manifest().model_dump_json().casefold()

    assert all(
        marker not in serialized
        for marker in (
            "access_token",
            "api_key",
            "client_secret",
            "password",
            "private_key",
        )
    )
    assert all(
        tool == "arm_execute_query" or marker not in tool.casefold()
        for specialist in load_specialist_manifest().specialists
        for tool in (
            *specialist.operations_mcp_tools,
            *specialist.azure_mcp_tools,
        )
        for marker in FORBIDDEN_TOOL_MARKERS
    )
