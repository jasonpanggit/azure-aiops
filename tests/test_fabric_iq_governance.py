from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api import runtime as api_runtime
from api.scope import Scope
from operations.tools import (
    STATUS_DENIED,
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    FabricIQToolAdapter,
)


class Context:
    pass


def test_fabric_iq_is_bounded_scope_checked_and_not_identity_authority():
    context = Context()
    context.fabric_iq_provider = lambda: FabricIQToolAdapter(
        source="fabric-iq",
        query=lambda kind, args, scope: {
            "data": {"subject": args["subject"], "items": list(range(100))},
            "freshness": "fresh",
            "provenance": "ontology-test",
        },
    )
    result = context.fabric_iq_provider().run(
        "topology", {"subject": "/subscriptions/sub-1"}, Scope.unrestricted()
    )
    assert result.status == STATUS_OK
    assert len(result.data["enrichment"]["items"]) == 25
    assert result.data["metadata"]["identity_authority"] is False
    assert result.data["metadata"]["provenance"] == "ontology-test"


def test_fabric_iq_allowlist_and_provider_outcomes_are_explicit():
    scope = Scope.unrestricted()
    denied = FabricIQToolAdapter(lambda *_: {}).run("inventory", {}, scope)
    assert denied.status == STATUS_DENIED
    unavailable = FabricIQToolAdapter(lambda *_: (_ for _ in ()).throw(TimeoutError())).run(
        "topology", {"subject": "x"}, scope
    )
    assert unavailable.status == STATUS_UNAVAILABLE
    empty = FabricIQToolAdapter(lambda *_: {"data": {}}).run(
        "topology", {"subject": "x"}, scope
    )
    assert empty.status == STATUS_EMPTY


def test_data_agent_backs_fabric_iq_with_generation_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            auth=object(),
            workspace_id="workspace-id",
        )
    )
    credential = SimpleNamespace(
        get_token=lambda *_scopes: SimpleNamespace(token="managed-token")
    )

    def query_data_agent(**kwargs):
        calls.append(kwargs)
        finding = {
            "finding_id": "relationship-1",
            "resource_ids": [
                (
                    "/subscriptions/sub-a/resourceGroups/rg/providers/"
                    "Microsoft.Compute/virtualMachines/vm-a"
                )
            ],
            "citations": [
                {
                    "gold_table": "ontology_relationships",
                    "row_key": "relationship-1",
                    "as_of": "2026-09-23T00:00:00Z",
                    "confidence": 0.95,
                }
            ],
            "scope_ok": True,
            "summary": "Validated relationship context.",
        }
        return {"content": [{"type": "text", "text": json.dumps(finding)}]}

    monkeypatch.setenv("AIOPS_ENABLE_FABRIC_IQ", "true")
    monkeypatch.setenv("AIOPS_ENABLE_FABRIC_DATA_AGENT_GROUNDING", "true")
    monkeypatch.setenv("FABRIC_GOLD_GROUNDING_AGENT_ID", "agent-id")
    monkeypatch.setattr(
        api_runtime,
        "_fabric_runtime_from_environment",
        lambda: runtime,
    )
    monkeypatch.setattr(api_runtime, "build_credential", lambda _auth: credential)
    monkeypatch.setattr(api_runtime, "query_gold_grounding", query_data_agent)

    adapter = api_runtime._load_fabric_iq_adapter()

    assert adapter is not None
    result = adapter.run(
        "relationships",
        {"subject": "vm-a", "generation_id": "generation:abc"},
        Scope.from_mapping({"subscription": ["sub-a"]}),
    )

    assert result.status == STATUS_OK
    assert result.data["metadata"]["source"] == "fabric-data-agent"
    assert result.data["metadata"]["provenance"] == "fabric-data-agent"
    assert result.data["enrichment"]["generation_id"] == "generation:abc"
    question = str(calls[0]["question"])
    assert "Immutable generation: generation:abc" in question
    assert '"subscription": ["sub-a"]' in question


def test_data_agent_grounding_fails_closed_without_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        config=SimpleNamespace(auth=object(), workspace_id="workspace-id")
    )
    credential = SimpleNamespace(
        get_token=lambda *_scopes: SimpleNamespace(token="managed-token")
    )
    monkeypatch.setenv("AIOPS_ENABLE_FABRIC_IQ", "true")
    monkeypatch.setenv("AIOPS_ENABLE_FABRIC_DATA_AGENT_GROUNDING", "true")
    monkeypatch.setenv("FABRIC_GOLD_GROUNDING_AGENT_ID", "agent-id")
    monkeypatch.setattr(
        api_runtime,
        "_fabric_runtime_from_environment",
        lambda: runtime,
    )
    monkeypatch.setattr(api_runtime, "build_credential", lambda _auth: credential)

    adapter = api_runtime._load_fabric_iq_adapter()

    assert adapter is not None
    result = adapter.run(
        "relationships",
        {"subject": "vm-a"},
        Scope.from_mapping({"subscription": ["sub-a"]}),
    )
    assert result.status == STATUS_UNAVAILABLE
    assert "immutable generation" in result.warning


def test_data_agent_grounding_rejects_out_of_scope_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        config=SimpleNamespace(auth=object(), workspace_id="workspace-id")
    )
    credential = SimpleNamespace(
        get_token=lambda *_scopes: SimpleNamespace(token="managed-token")
    )
    finding = {
        "finding_id": "relationship-1",
        "resource_ids": [
            (
                "/subscriptions/sub-b/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/vm-b"
            )
        ],
        "citations": [
            {
                "gold_table": "ontology_relationships",
                "row_key": "relationship-1",
                "as_of": "2026-09-23T00:00:00Z",
                "confidence": 0.95,
            }
        ],
        "scope_ok": True,
        "summary": "Cross-scope result.",
    }
    monkeypatch.setenv("AIOPS_ENABLE_FABRIC_IQ", "true")
    monkeypatch.setenv("AIOPS_ENABLE_FABRIC_DATA_AGENT_GROUNDING", "true")
    monkeypatch.setenv("FABRIC_GOLD_GROUNDING_AGENT_ID", "agent-id")
    monkeypatch.setattr(
        api_runtime,
        "_fabric_runtime_from_environment",
        lambda: runtime,
    )
    monkeypatch.setattr(api_runtime, "build_credential", lambda _auth: credential)
    monkeypatch.setattr(
        api_runtime,
        "query_gold_grounding",
        lambda **_kwargs: {
            "content": [{"type": "text", "text": json.dumps(finding)}]
        },
    )

    adapter = api_runtime._load_fabric_iq_adapter()

    assert adapter is not None
    result = adapter.run(
        "relationships",
        {"subject": "vm-b", "generation_id": "generation:abc"},
        Scope.from_mapping({"subscription": ["sub-a"]}),
    )
    assert result.status == STATUS_DENIED
    assert result.warning == "Fabric IQ access is not authorized"
