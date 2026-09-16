from __future__ import annotations

import asyncio
from dataclasses import dataclass

from api.scope import Scope
from fabric.gold_grounding_client import GoldGroundingQueryResult
from fabric_pipelines.gold_grounding_contract import (
    GoldGroundedFinding,
    GoldGroundingStatus,
)
from operations.foundry_agent import AgentAnswer
from operations.gold_grounding_specialist import (
    answer_with_gold_grounding,
    gold_grounding_configured,
)

RESOURCE = (
    "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
    "Microsoft.Compute/virtualMachines/vm-a"
)
GENERATION = "generation-1"


@dataclass(frozen=True)
class _Scope:
    fabric_workspace_id: str = "workspace-id"
    gold_grounding_agent_id: str = "agent-id"
    gold_grounding_tool_name: str = "DataAgent_AI_Ops_Data_Agent"
    fabric_delegated_token: str = "delegated-token"
    evidence_refs: set[str] = frozenset({"ontology"})
    resource_ids: set[str] = frozenset({RESOURCE})


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
    def __init__(self, resource: dict[str, object] | None) -> None:
        self.resource = resource

    def get_resource(self, _scope, _resource_id: str):
        return self.resource


class _Metrics:
    def __init__(self) -> None:
        self.inventory_conflict_calls = 0
        self.query_calls: list[dict[str, object]] = []

    def record_inventory_conflict(self) -> None:
        self.inventory_conflict_calls += 1

    def record_query(self, **kwargs) -> None:
        self.query_calls.append(kwargs)


def _finding_line(
    *,
    resource_id: str = RESOURCE,
    generation_id: str = GENERATION,
    summary: str = "gold finding",
) -> str:
    return GoldGroundedFinding.model_validate(
        {
            "finding_id": "gold-finding-1",
            "generation_id": generation_id,
            "citations": [
                {
                    "resource_id": resource_id,
                    "generation_id": generation_id,
                    "gold_table": "gold_business_service_health",
                    "row_key": "row-1",
                    "as_of": "2026-09-01T00:00:00Z",
                    "confidence": 0.9,
                }
            ],
            "scope_ok": True,
            "summary": summary,
        }
    ).model_dump_json()


def _query_result(
    status: GoldGroundingStatus,
    *,
    text: str = "",
    reason: str = "",
) -> GoldGroundingQueryResult:
    payload = (
        {"isError": False, "content": [{"type": "text", "text": text}]}
        if status == GoldGroundingStatus.SUCCESS
        else None
    )
    return GoldGroundingQueryResult(status, payload=payload, reason=reason)


def _run(
    monkeypatch,
    result: GoldGroundingQueryResult,
    *,
    ontology_context: dict | None = None,
    provider_context=None,
    effective_scope=None,
    metrics=None,
) -> tuple[AgentAnswer, _Agent]:
    async def fake_query(**_kwargs):
        return result

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query,
    )
    agent = _Agent()
    answer = asyncio.run(
        answer_with_gold_grounding(
            question="What changed?",
            ontology_context=ontology_context
            or {"generation_id": GENERATION, "findings": [{"summary": "ontology"}]},
            scope=_Scope(),
            agent=agent,
            provider_context=provider_context,
            effective_scope=effective_scope,
            metrics=metrics,
        )
    )
    return answer, agent


def test_successful_query_merges_generation_bound_evidence(monkeypatch) -> None:
    requested: dict[str, str] = {}

    async def fake_query(**kwargs):
        requested["question"] = kwargs["question"]
        return _query_result(
            GoldGroundingStatus.SUCCESS,
            text=_finding_line(),
        )

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query,
    )
    inventory = {
        "resource_id": RESOURCE,
        "subscription_id": "sub-1",
        "resource_group": "rg-1",
        "lifecycle_status": "active",
    }
    agent = _Agent()
    answer = asyncio.run(
        answer_with_gold_grounding(
            question="What changed?",
            ontology_context={
                "generation_id": GENERATION,
                "findings": [{"summary": "ontology"}],
            },
            scope=_Scope(),
            agent=agent,
            provider_context=_ProviderContext(_InventoryPort(inventory)),
            effective_scope=Scope.from_mapping({"subscription": ["sub-1"]}),
        )
    )

    assert answer.text == "ok"
    assert f"PINNED_GENERATION_ID={GENERATION}" in requested["question"]
    assert '"subscription":["sub-1"]' in requested["question"]
    assert RESOURCE in requested["question"]
    call = agent.calls[0]
    assert call["context"]["gold_grounding"]["status"] == "success"
    assert call["context"]["gold_grounding"]["generation_id"] == GENERATION
    assert (
        call["context"]["gold_grounding"]["findings"][0]["summary"]
        == "1 scoped Gold citation available for deterministic review."
    )
    assert "gold finding" not in str(call["context"])
    assert "gold_grounding" in call["evidence_refs"]
    assert call["max_output_tokens"] == 800


def test_transport_failure_degrades_without_breaking_ontology(monkeypatch) -> None:
    _, agent = _run(
        monkeypatch,
        _query_result(
            GoldGroundingStatus.UNAVAILABLE,
            reason="mcp unavailable",
        ),
    )

    context = agent.calls[0]["context"]
    assert context["findings"] == [{"summary": "ontology"}]
    assert context["gold_grounding"]["status"] == "unavailable"
    assert context["gold_grounding"]["findings"] == []
    assert context["gold_grounding_degraded"] == "mcp unavailable"


def test_unparseable_and_stale_evidence_are_distinct(monkeypatch) -> None:
    _, malformed_agent = _run(
        monkeypatch,
        _query_result(
            GoldGroundingStatus.SUCCESS,
            text="No structured findings available.",
        ),
    )
    _, stale_agent = _run(
        monkeypatch,
        _query_result(
            GoldGroundingStatus.SUCCESS,
            text=_finding_line(generation_id="generation-2"),
        ),
    )

    assert (
        malformed_agent.calls[0]["context"]["gold_grounding"]["status"] == "malformed"
    )
    assert stale_agent.calls[0]["context"]["gold_grounding"]["status"] == "stale"


def test_manifest_backed_empty_proof_is_healthy_empty(monkeypatch) -> None:
    proof = (
        '{"status":"healthy_empty","generation_id":"generation-1",'
        '"gold_table":"metadata_exposure_gold_generations",'
        '"row_key":"generation-1","as_of":"2026-09-01T00:00:00Z",'
        '"reconciliation_status":"reconciled","scoped_row_count":0,'
        '"scope_ok":true}'
    )
    _, agent = _run(
        monkeypatch,
        _query_result(GoldGroundingStatus.SUCCESS, text=proof),
        ontology_context={
            "generation_id": GENERATION,
            "findings": [],
            "gold_empty_manifest": {
                "status": "healthy_empty",
                "generation_id": GENERATION,
                "gold_table": "metadata_exposure_gold_generations",
                "row_key": GENERATION,
                "as_of": "2026-09-01T00:00:00Z",
                "reconciliation_status": "reconciled",
                "scoped_row_count": 0,
                "scope_ok": True,
            },
        },
    )

    context = agent.calls[0]["context"]
    assert context["gold_grounding"]["status"] == "healthy_empty"
    assert context["gold_grounding"]["empty_proof"]["row_key"] == GENERATION


def test_missing_generation_skips_data_agent(monkeypatch) -> None:
    called = False

    async def fake_query(**_kwargs):
        nonlocal called
        called = True
        return _query_result(GoldGroundingStatus.SUCCESS, text=_finding_line())

    monkeypatch.setattr(
        "operations.gold_grounding_specialist.query_gold_grounding",
        fake_query,
    )
    agent = _Agent()
    asyncio.run(
        answer_with_gold_grounding(
            question="What changed?",
            ontology_context={"findings": []},
            scope=_Scope(),
            agent=agent,
        )
    )

    assert called is False
    assert (
        agent.calls[0]["context"]["gold_grounding_degraded"]
        == "ontology generation is not pinned"
    )


def test_environment_token_is_not_treated_as_caller_delegation(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "workspace-id")
    monkeypatch.setenv("FABRIC_GOLD_GROUNDING_AGENT_ID", "agent-id")
    monkeypatch.setenv("FABRIC_DELEGATED_TOKEN", "shared-token")

    assert gold_grounding_configured(Scope.unrestricted()) is False


def test_inventory_conflict_withholds_untrusted_evidence(monkeypatch) -> None:
    metrics = _Metrics()
    _, agent = _run(
        monkeypatch,
        _query_result(
            GoldGroundingStatus.SUCCESS,
            text=_finding_line(summary="must not reach narration"),
        ),
        provider_context=_ProviderContext(_InventoryPort(None)),
        effective_scope=Scope.from_mapping({"subscription": ["sub-1"]}),
        metrics=metrics,
    )

    context = agent.calls[0]["context"]
    assert context["gold_grounding"]["status"] == "unavailable"
    assert context["gold_grounding"]["findings"] == []
    assert context["gold_grounding_inventory_conflicts"] == [
        {"reason": "resource_not_found"}
    ]
    assert "must not reach narration" not in str(context)
    assert metrics.inventory_conflict_calls == 1


def test_inventory_agreement_preserves_evidence(monkeypatch) -> None:
    inventory = {
        "resource_id": RESOURCE,
        "subscription_id": "sub-1",
        "resource_group": "rg-1",
        "lifecycle_status": "active",
    }
    _, agent = _run(
        monkeypatch,
        _query_result(GoldGroundingStatus.SUCCESS, text=_finding_line()),
        provider_context=_ProviderContext(_InventoryPort(inventory)),
        effective_scope=Scope.from_mapping({"subscription": ["sub-1"]}),
    )

    context = agent.calls[0]["context"]
    assert context["gold_grounding"]["status"] == "success"
    assert len(context["gold_grounding"]["findings"]) == 1
    assert "gold_grounding_inventory_conflicts" not in context


def test_transport_timeout_is_preserved_for_narration(monkeypatch) -> None:
    _, agent = _run(
        monkeypatch,
        _query_result(
            GoldGroundingStatus.TIMEOUT,
            reason="Gold-grounding Data Agent exceeded the 30-second request budget",
        ),
    )

    context = agent.calls[0]["context"]
    assert context["gold_grounding"]["status"] == "timeout"
    assert "request budget" in context["gold_grounding_degraded"]
