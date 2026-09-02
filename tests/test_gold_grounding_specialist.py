from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from api.scope import Scope
from fabric.gold_grounding_client import GoldGroundingUnavailable
from fabric_pipelines.gold_grounding_contract import GoldGroundedFinding
from operations.foundry_agent import AgentAnswer
from operations.gold_grounding_specialist import answer_with_gold_grounding


@dataclass(frozen=True)
class _Scope:
    fabric_workspace_id: str = "workspace-id"
    gold_grounding_agent_id: str = "agent-id"
    gold_grounding_tool_name: str = "DataAgent_gold_grounding_agent"
    fabric_delegated_token: str = "delegated-token"
    evidence_refs: set[str] = frozenset({"ontology"})
    resource_ids: set[str] = frozenset(
        {"/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-a"}
    )


class _Agent:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def answer_findings(self, **kwargs):
        self.calls.append(kwargs)
        return AgentAnswer(text="ok", agent_name="operations-copilot")


class _ProviderContext:
    def __init__(self, inventory_read_port) -> None:
        self._inventory_read_port = inventory_read_port

    def resolve_provider(self, name: str):
        if name != "inventory_read_port":
            raise AssertionError(name)
        return self._inventory_read_port


class _InventoryPort:
    def __init__(self, mapping: dict[str, dict[str, object] | None]) -> None:
        self.mapping = {key.casefold(): value for key, value in mapping.items()}
        self.calls: list[tuple[object, str]] = []

    def get_resource(self, scope, resource_id: str):
        self.calls.append((scope, resource_id))
        return self.mapping.get(resource_id.casefold())


class _Metrics:
    def __init__(self) -> None:
        self.inventory_conflict_calls = 0
        self.query_calls: list[dict[str, object]] = []

    def record_inventory_conflict(self) -> None:
        self.inventory_conflict_calls += 1

    def record_query(
        self, *, degraded: bool, degraded_reason: str, citation_count: int, duration_ms: float
    ) -> None:
        self.query_calls.append(
            {
                "degraded": degraded,
                "degraded_reason": degraded_reason,
                "citation_count": citation_count,
                "duration_ms": duration_ms,
            }
        )


def _finding_line(
    *,
    resource_ids: list[str] | None = None,
    citations: list[dict[str, object]] | None = None,
    summary: str = "gold finding",
) -> str:
    payload = {
        "finding_id": "gold-finding-1",
        "resource_ids": resource_ids
        or ["/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-a"],
        "citations": citations
        or [
            {
                "gold_table": "gold_business_service_health",
                "row_key": "row-1",
                "as_of": "2026-09-01T00:00:00Z",
                "confidence": 0.9,
            }
        ],
        "scope_ok": True,
        "degraded": False,
        "degraded_reason": "",
        "summary": summary,
    }
    return GoldGroundedFinding.model_validate(payload).model_dump_json()


def test_successful_query_merges_gold_evidence_into_existing_context(monkeypatch) -> None:
    def fake_query_gold_grounding(**_kwargs):
        return {
            "isError": False,
            "content": [{"type": "text", "text": _finding_line()}],
        }

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query_gold_grounding,
    )
    agent = _Agent()
    ontology_context = {"findings": [{"summary": "ontology"}], "ontology_only": True}

    answer = asyncio.run(
        answer_with_gold_grounding(
            question="What is the health?",
            ontology_context=ontology_context,
            scope=_Scope(),
            agent=agent,
        )
    )

    assert answer.text == "ok"
    call = agent.calls[0]
    merged_context = call["context"]
    assert isinstance(merged_context, dict)
    assert merged_context["ontology_only"] is True
    assert merged_context["gold_grounding"] is not None
    assert "gold_grounding" in call["evidence_refs"]


def test_gold_unavailable_degrades_without_breaking_ontology_answer(monkeypatch) -> None:
    def fake_query_gold_grounding(**_kwargs):
        raise GoldGroundingUnavailable("mcp unavailable")

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query_gold_grounding,
    )
    agent = _Agent()
    ontology_context = {"findings": [{"summary": "ontology-still-present"}]}

    answer = asyncio.run(
        answer_with_gold_grounding(
            question="What changed?",
            ontology_context=ontology_context,
            scope=_Scope(),
            agent=agent,
        )
    )

    assert answer.text == "ok"
    call = agent.calls[0]
    merged_context = call["context"]
    assert merged_context["findings"] == ontology_context["findings"]
    assert merged_context["gold_grounding_degraded"] == "mcp unavailable"


def test_unparseable_gold_response_degrades_without_claiming_gold_success(monkeypatch) -> None:
    def fake_query_gold_grounding(**_kwargs):
        return {
            "isError": False,
            "content": [{"type": "text", "text": "No structured findings available."}],
        }

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query_gold_grounding,
    )
    agent = _Agent()
    metrics = _Metrics()

    asyncio.run(
        answer_with_gold_grounding(
            question="What changed?",
            ontology_context={"findings": [{"summary": "ontology-still-present"}]},
            scope=_Scope(),
            agent=agent,
            metrics=metrics,
        )
    )

    merged_context = agent.calls[0]["context"]
    assert merged_context["gold_grounding"] is None
    assert merged_context["gold_grounding_degraded"] == "unparseable Gold evidence"
    assert metrics.query_calls[0]["degraded"] is True
    assert metrics.query_calls[0]["citation_count"] == 0


def test_gold_citations_are_ranked_and_truncated_before_ontology_context(monkeypatch) -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    citations: list[dict[str, object]] = []
    for index in range(8):
        citations.append(
            {
                "gold_table": "gold_topology",
                "row_key": f"row-{index}-" + ("x" * 700),
                "as_of": (now - timedelta(hours=index)).isoformat().replace("+00:00", "Z"),
                "confidence": round(1.0 - (index * 0.1), 2),
            }
        )
    # Scramble order so ranking must be applied.
    unsorted = [citations[i] for i in (5, 7, 1, 6, 0, 4, 2, 3)]

    def fake_query_gold_grounding(**_kwargs):
        return {
            "isError": False,
            "content": [{"type": "text", "text": _finding_line(citations=unsorted)}],
        }

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query_gold_grounding,
    )
    agent = _Agent()
    ontology_context = {"ontology_payload": "o" * 19_000}

    asyncio.run(
        answer_with_gold_grounding(
            question="What depends on demo-vnet?",
            ontology_context=ontology_context,
            scope=_Scope(),
            agent=agent,
        )
    )

    merged_context = agent.calls[0]["context"]
    assert merged_context["ontology_payload"] == ontology_context["ontology_payload"]
    kept = merged_context["gold_grounding"]["findings"][0]["citations"]
    assert len(kept) < len(unsorted)
    assert kept[0]["row_key"].startswith("row-0-")
    kept_row_indices = [int(citation["row_key"].split("-")[1]) for citation in kept]
    assert kept_row_indices == sorted(kept_row_indices)


def test_narration_call_sets_max_output_tokens_800(monkeypatch) -> None:
    def fake_query_gold_grounding(**_kwargs):
        return {"isError": False, "content": [{"type": "text", "text": _finding_line()}]}

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query_gold_grounding,
    )
    agent = _Agent()

    asyncio.run(
        answer_with_gold_grounding(
            question="Question",
            ontology_context={"findings": []},
            scope=_Scope(),
            agent=agent,
        )
    )

    assert agent.calls[0]["max_output_tokens"] == 800


def test_inventory_missing_resource_adds_conflict_notice(monkeypatch) -> None:
    def fake_query_gold_grounding(**_kwargs):
        return {"isError": False, "content": [{"type": "text", "text": _finding_line()}]}

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query_gold_grounding,
    )
    agent = _Agent()
    inventory = _InventoryPort(mapping={})
    metrics = _Metrics()
    effective_scope = Scope.from_mapping({"subscription": ["sub-1"]})

    asyncio.run(
        answer_with_gold_grounding(
            question="Question",
            ontology_context={"findings": []},
            scope=_Scope(),
            agent=agent,
            provider_context=_ProviderContext(inventory),
            effective_scope=effective_scope,
            metrics=metrics,
        )
    )

    merged_context = agent.calls[0]["context"]
    assert "gold_grounding_inventory_conflicts" in merged_context
    conflicts = merged_context["gold_grounding_inventory_conflicts"]
    assert conflicts[0]["reason"] == "resource_not_found"
    assert conflicts[0]["citation"]["row_key"] == "row-1"
    assert "Inventory is authoritative" in merged_context["gold_grounding_inventory_conflict_notice"]
    assert metrics.inventory_conflict_calls == 1
    assert inventory.calls and inventory.calls[0][0] == effective_scope


def test_inventory_ownership_or_lifecycle_mismatch_adds_conflict_notice(monkeypatch) -> None:
    resource_a = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-a"
    resource_b = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-b"

    def fake_query_gold_grounding(**_kwargs):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": _finding_line(
                        resource_ids=[resource_a, resource_b],
                        citations=[
                            {
                                "gold_table": "gold_business_service_health",
                                "row_key": "row-subscription-mismatch",
                                "as_of": "2026-09-01T00:00:00Z",
                                "confidence": 0.9,
                            },
                            {
                                "gold_table": "gold_business_service_health",
                                "row_key": "row-lifecycle-retired",
                                "as_of": "2026-09-01T00:00:00Z",
                                "confidence": 0.8,
                            },
                        ],
                    ),
                }
            ],
        }

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query_gold_grounding,
    )
    agent = _Agent()
    inventory = _InventoryPort(
        mapping={
            resource_a: {
                "resource_id": resource_a,
                "subscription_id": "sub-other",
                "resource_group": "rg-1",
                "lifecycle_status": "active",
            },
            resource_b: {
                "resource_id": resource_b,
                "subscription_id": "sub-1",
                "resource_group": "rg-1",
                "lifecycle_status": "retired",
            },
        }
    )
    metrics = _Metrics()

    asyncio.run(
        answer_with_gold_grounding(
            question="Question",
            ontology_context={"findings": []},
            scope=_Scope(resource_ids=frozenset({resource_a, resource_b})),
            agent=agent,
            provider_context=_ProviderContext(inventory),
            effective_scope=Scope.from_mapping({"subscription": ["sub-1"]}),
            metrics=metrics,
        )
    )

    conflicts = agent.calls[0]["context"]["gold_grounding_inventory_conflicts"]
    reasons = {conflict["reason"] for conflict in conflicts}
    assert "subscription_mismatch" in reasons
    assert "lifecycle_mismatch" in reasons
    assert metrics.inventory_conflict_calls == 2


def test_inventory_conflict_counter_increments_per_conflicting_citation(monkeypatch) -> None:
    resource = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-a"

    def fake_query_gold_grounding(**_kwargs):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": _finding_line(
                        resource_ids=[resource],
                        citations=[
                            {
                                "gold_table": "gold_business_service_health",
                                "row_key": "row-conflict-1",
                                "as_of": "2026-09-01T00:00:00Z",
                                "confidence": 0.9,
                            },
                            {
                                "gold_table": "gold_business_service_health",
                                "row_key": "row-conflict-2",
                                "as_of": "2026-09-01T00:00:00Z",
                                "confidence": 0.8,
                            },
                        ],
                    ),
                }
            ],
        }

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query_gold_grounding,
    )
    agent = _Agent()
    inventory = _InventoryPort(mapping={resource: None})
    metrics = _Metrics()

    asyncio.run(
        answer_with_gold_grounding(
            question="Question",
            ontology_context={"findings": []},
            scope=_Scope(resource_ids=frozenset({resource})),
            agent=agent,
            provider_context=_ProviderContext(inventory),
            effective_scope=Scope.from_mapping({"subscription": ["sub-1"]}),
            metrics=metrics,
        )
    )

    assert metrics.inventory_conflict_calls == 2
    assert len(agent.calls[0]["context"]["gold_grounding_inventory_conflicts"]) == 2


def test_inventory_agreement_adds_no_conflict_and_no_counter_increment(monkeypatch) -> None:
    resource = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-a"

    def fake_query_gold_grounding(**_kwargs):
        return {"isError": False, "content": [{"type": "text", "text": _finding_line(resource_ids=[resource])}]}

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query_gold_grounding,
    )
    agent = _Agent()
    inventory = _InventoryPort(
        mapping={
            resource: {
                "resource_id": resource,
                "subscription_id": "sub-1",
                "resource_group": "rg-1",
                "lifecycle_status": "active",
            }
        }
    )
    metrics = _Metrics()

    asyncio.run(
        answer_with_gold_grounding(
            question="Question",
            ontology_context={"findings": []},
            scope=_Scope(resource_ids=frozenset({resource})),
            agent=agent,
            provider_context=_ProviderContext(inventory),
            effective_scope=Scope.from_mapping({"subscription": ["sub-1"]}),
            metrics=metrics,
        )
    )

    merged_context = agent.calls[0]["context"]
    assert "gold_grounding_inventory_conflicts" not in merged_context
    assert metrics.inventory_conflict_calls == 0
