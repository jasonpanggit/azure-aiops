from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
