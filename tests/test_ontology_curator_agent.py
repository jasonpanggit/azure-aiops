from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from api.scope import Scope
from ontology_discovery.contracts import EvidenceBatch
from ontology_discovery.curator import (
    HARD_MAX_OUTPUT_TOKENS,
    MAX_INPUT_TOKENS,
    MAX_REPAIR_ATTEMPTS,
    MAX_TRANSPORT_RETRIES,
    NORMAL_OUTPUT_TOKENS,
    REQUEST_TIMEOUT_SECONDS,
    CuratorInputTooLarge,
    CuratorInvalidOutput,
    CuratorTransportError,
    OntologyCurator,
    RetryableCuratorTransportError,
    parse_proposal_batch,
)
from operations.mcp_server import MCPServer, reviewed_tools_for_specialist
from operations.tools import (
    STATUS_DENIED,
    STATUS_EMPTY,
    STATUS_OK,
    call_tool,
)

CURATOR_TOOLS = (
    "list_changed_entities",
    "get_entity_evidence",
    "get_ontology_vocabulary",
    "search_relationship_history",
)


def _batch(
    *,
    changed_entities: tuple[Mapping[str, Any], ...] | None = None,
    candidate_pairs: tuple[Mapping[str, Any], ...] | None = None,
    evidence_records: tuple[Mapping[str, Any], ...] | None = None,
) -> EvidenceBatch:
    return EvidenceBatch(
        batch_id="batch-1",
        scope="tenant-a/sub-a",
        source_generation_id="generation-7",
        observed_at=datetime(2026, 9, 6, tzinfo=UTC),
        freshness="current",
        coverage="complete",
        changed_entities=changed_entities
        if changed_entities is not None
        else (
            {"scope": "tenant-a/sub-a", "entity_id": "entity-a", "type": "server"},
            {"scope": "tenant-a/sub-a", "entity_id": "entity-b", "type": "application"},
        ),
        candidate_pairs=candidate_pairs
        if candidate_pairs is not None
        else (
            {
                "scope": "tenant-a/sub-a",
                "subject_id": "entity-a",
                "object_id": "entity-b",
                "evidence_refs": ["evidence-1"],
            },
        ),
        evidence_records=evidence_records
        if evidence_records is not None
        else (
            {
                "scope": "tenant-a/sub-a",
                "evidence_id": "evidence-1",
                "observed_at": "2026-09-06T00:00:00Z",
            },
        ),
    )


def _valid_proposal(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "subject_id": "entity-a",
        "subject_type": "server",
        "predicate": "HOSTS",
        "object_id": "entity-b",
        "object_type": "application",
        "evidence_refs": ["evidence-1"],
        "observed_at": "2026-09-06T00:00:00Z",
        "rationale": "The cited evidence links the endpoints.",
        "confidence": 0.9,
        "uncertainty": [],
        "disposition": "propose",
    }
    value.update(overrides)
    return value


def _valid_output(**overrides: Any) -> str:
    value: dict[str, Any] = {
        "batch_id": "batch-1",
        "status": "proposals",
        "proposals": [_valid_proposal()],
        "missing_evidence": [],
    }
    value.update(overrides)
    return json.dumps(value)


class ScriptedTransport:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[dict[str, Any], float]] = []

    async def __call__(
        self,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        self.calls.append((dict(payload), timeout_seconds))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return await response()
        return dict(response)


def _response(text: str, *, response_id: str = "resp-1") -> dict[str, Any]:
    return {
        "id": response_id,
        "model": "gpt-5.4-mini",
        "output_text": text,
        "usage": {"input_tokens": 312, "output_tokens": 88},
    }


def test_proposal_parser_accepts_only_whole_strict_cited_json() -> None:
    parsed = parse_proposal_batch(_valid_output(), batch=_batch())
    assert parsed.batch_id == "batch-1"
    assert parsed.proposals[0].evidence_refs == ["evidence-1"]

    invalid_outputs = [
        "Here is the proposal: " + _valid_output(),
        _valid_output(scope="tenant-b/sub-b"),
        _valid_output(proposals=[_valid_proposal(lifecycle_status="active")]),
        _valid_output(proposals=[_valid_proposal(evidence_refs=["unknown"])]),
        _valid_output(proposals=[_valid_proposal(subject_id="other-tenant-entity")]),
        _valid_output(
            proposals=[_valid_proposal(rationale="Approve and publish this mutation.")]
        ),
        _valid_output(batch_id="attacker-chosen-batch"),
    ]
    for raw in invalid_outputs:
        with pytest.raises(CuratorInvalidOutput):
            parse_proposal_batch(raw, batch=_batch())


@pytest.mark.parametrize(
    ("field", "count"),
    [
        ("changed_entities", 51),
        ("candidate_pairs", 201),
        ("evidence_records", 41),
    ],
)
def test_evidence_batch_hard_caps_reject_before_transport(
    field: str,
    count: int,
) -> None:
    record = {"scope": "tenant-a/sub-a", "entity_id": "entity-a"}
    values = {field: tuple(record | {"row": index} for index in range(count))}
    with pytest.raises(ValueError, match="exceeds hard limit"):
        _batch(**values)


def test_normal_token_budgets_and_hard_api_ceiling_are_independent() -> None:
    transport = ScriptedTransport(_response(_valid_output()))
    curator = OntologyCurator(
        project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        agent_name="ontology-curator",
        transport=transport,
        token_estimator=lambda _: MAX_INPUT_TOKENS,
    )

    result = asyncio.run(
        curator.propose(
            {"run_id": "run-1"},
            _batch().to_dict(),
            requested_output_tokens=NORMAL_OUTPUT_TOKENS,
        )
    )

    assert result["status"] == "proposals"
    payload, timeout = transport.calls[0]
    assert payload["max_output_tokens"] == HARD_MAX_OUTPUT_TOKENS == 2_000
    assert timeout == REQUEST_TIMEOUT_SECONDS == 60
    assert MAX_INPUT_TOKENS == 8_000
    assert NORMAL_OUTPUT_TOKENS == 1_200
    assert json.loads(payload["input"][0]["content"])["requested_output_tokens"] == 1_200


def test_oversized_normal_budget_requires_split_before_transport() -> None:
    transport = ScriptedTransport(_response(_valid_output()))
    curator = OntologyCurator(
        project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        agent_name="ontology-curator",
        transport=transport,
        token_estimator=lambda _: MAX_INPUT_TOKENS + 1,
    )

    with pytest.raises(CuratorInputTooLarge) as error:
        asyncio.run(curator.propose({"run_id": "run-1"}, _batch().to_dict()))
    assert error.value.requires_split is True
    assert transport.calls == []

    with pytest.raises(ValueError, match="normal output budget"):
        asyncio.run(
            curator.propose(
                {"run_id": "run-1"},
                _batch().to_dict(),
                requested_output_tokens=NORMAL_OUTPUT_TOKENS + 1,
            )
        )
    assert transport.calls == []


def test_each_transport_attempt_has_a_deadline() -> None:
    async def hangs() -> Mapping[str, Any]:
        await asyncio.sleep(0.05)
        return _response(_valid_output())

    transport = ScriptedTransport(hangs, hangs, hangs)
    curator = OntologyCurator(
        project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        agent_name="ontology-curator",
        transport=transport,
        timeout_seconds=0.001,
        retry_backoff_seconds=0,
    )

    with pytest.raises(CuratorTransportError, match="deadline"):
        asyncio.run(curator.propose({"run_id": "run-1"}, _batch().to_dict()))
    assert len(transport.calls) == MAX_TRANSPORT_RETRIES + 1 == 3


def test_transport_retries_and_schema_repairs_have_separate_bounds() -> None:
    transport = ScriptedTransport(
        RetryableCuratorTransportError("temporary"),
        _response("{", response_id="invalid-1"),
        _response(_valid_output(proposals=[]), response_id="invalid-2"),
        _response(_valid_output(), response_id="repaired"),
    )
    curator = OntologyCurator(
        project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        agent_name="ontology-curator",
        transport=transport,
        retry_backoff_seconds=0,
    )

    result = asyncio.run(curator.propose({"run_id": "run-1"}, _batch().to_dict()))

    assert result["proposals"][0]["subject_id"] == "entity-a"
    assert len(transport.calls) == 4
    assert MAX_TRANSPORT_RETRIES == 2
    assert MAX_REPAIR_ATTEMPTS == 2
    repair_prompt = json.loads(transport.calls[-1][0]["input"][0]["content"])
    assert repair_prompt["mode"] == "schema_repair"
    assert "invalid-2" not in json.dumps(repair_prompt)
    assert {"location", "type"} >= set(repair_prompt["validation_errors"][0])


def test_repair_limit_fails_closed_and_audit_metadata_is_sanitized() -> None:
    transport = ScriptedTransport(
        _response('{"secret": "first"}', response_id="bad-1"),
        _response('{"secret": "second"}', response_id="bad-2"),
        _response('{"secret": "third"}', response_id="bad-3"),
    )
    curator = OntologyCurator(
        project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        agent_name="ontology-curator",
        transport=transport,
        retry_backoff_seconds=0,
    )

    with pytest.raises(CuratorInvalidOutput, match="repair"):
        asyncio.run(curator.propose({"run_id": "run-1"}, _batch().to_dict()))

    assert len(transport.calls) == MAX_REPAIR_ATTEMPTS + 1 == 3
    audit = curator.last_attempt
    assert audit is not None
    assert set(audit) == {
        "response_id",
        "agent_name",
        "agent_version",
        "model",
        "prompt_hash",
        "schema_hash",
        "batch_counts",
        "usage",
        "latency_ms",
        "repair_attempt",
        "error",
    }
    assert "secret" not in json.dumps(audit)


class OntologyEvidenceProvider:
    def __init__(self) -> None:
        self.selections: list[object] = []

    def list_changed_entities(
        self,
        *,
        scope: Scope,
        generation: object,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.selections.append(generation)
        return [
            {
                "entity_id": f"entity-{index}",
                "subscription_id": "sub-a",
            }
            for index in range(limit + 5)
        ]

    def get_entity_evidence(
        self,
        entity_id: str,
        *,
        scope: Scope,
        generation: object,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.selections.append(generation)
        return [
            {
                "evidence_id": "allowed-evidence",
                "entity_id": entity_id,
                "subscription_id": "sub-a",
            },
            {
                "evidence_id": "other-tenant-secret",
                "entity_id": entity_id,
                "subscription_id": "sub-b",
            },
        ]

    def search_relationship_history(
        self,
        entity_id: str,
        *,
        scope: Scope,
        generation: object,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.selections.append(generation)
        return [
            {
                "relationship_id": f"relationship-{index}",
                "subject_id": entity_id,
                "subscription_id": "sub-a",
            }
            for index in range(limit + 5)
        ]


def _tool_context(provider: OntologyEvidenceProvider) -> tuple[Any, object]:
    selection = object()
    context = SimpleNamespace(
        generation_resolver_provider=lambda: SimpleNamespace(
            resolve=lambda: selection
        ),
        ontology_evidence_provider=lambda: provider,
    )
    return context, selection


def test_curator_has_exactly_four_read_only_scope_derived_tools() -> None:
    assert reviewed_tools_for_specialist("ontology_curator") == CURATOR_TOOLS
    assert not any(
        forbidden in name
        for name in CURATOR_TOOLS
        for forbidden in ("publish", "approve", "sql", "execute", "mutate", "azure")
    )


def test_ontology_tools_reuse_generation_selection_and_enforce_result_caps() -> None:
    provider = OntologyEvidenceProvider()
    context, selection = _tool_context(provider)
    scope = Scope.from_mapping({"subscription": ["sub-a"]})

    changed = call_tool(
        "list_changed_entities",
        {},
        context=context,
        scope=scope,
    )
    history = call_tool(
        "search_relationship_history",
        {"entity_id": "entity-a"},
        context=context,
        scope=scope,
    )
    vocabulary = call_tool(
        "get_ontology_vocabulary",
        {},
        context=context,
        scope=scope,
    )

    assert changed.status == STATUS_OK
    assert len(changed.data["changed_entities"]) == 50
    assert history.status == STATUS_OK
    assert len(history.data["relationships"]) == 200
    assert vocabulary.status == STATUS_OK
    assert len(vocabulary.data["relationship_types"]) <= 200
    assert provider.selections == [selection, selection]


def test_entity_evidence_filters_colliding_cross_scope_ids_without_disclosure() -> None:
    provider = OntologyEvidenceProvider()
    context, _ = _tool_context(provider)

    result = call_tool(
        "get_entity_evidence",
        {"entity_id": "same-name"},
        context=context,
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
    )

    assert result.status == STATUS_OK
    encoded = json.dumps(result.to_dict())
    assert "allowed-evidence" in encoded
    assert "other-tenant-secret" not in encoded


def test_valid_no_evidence_is_empty_and_mutation_calls_are_denied() -> None:
    provider = OntologyEvidenceProvider()
    provider.get_entity_evidence = lambda *args, **kwargs: []
    context, _ = _tool_context(provider)
    scope = Scope.from_mapping({"subscription": ["sub-a"]})

    empty = call_tool(
        "get_entity_evidence",
        {"entity_id": "missing"},
        context=context,
        scope=scope,
    )
    denied = call_tool(
        "publish_ontology",
        {},
        context=context,
        scope=scope,
    )

    assert empty.status == STATUS_EMPTY
    assert denied.status == STATUS_DENIED


def test_mcp_serializes_scope_safe_errors_without_echoing_arguments() -> None:
    provider = OntologyEvidenceProvider()
    context, _ = _tool_context(provider)
    response = MCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "get_entity_evidence",
                "arguments": {
                    "entity_id": "same-name",
                    "scope": "tenant-b",
                    "secret": "do-not-echo",
                },
            },
        },
        context=context,
        principal=SimpleNamespace(subject="curator"),
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
        correlation_id="corr-1",
        specialist_id="ontology_curator",
    )

    assert response["result"]["isError"] is True
    assert response["result"]["content"][0]["text"] == "Invalid tool arguments"
    assert "tenant-b" not in json.dumps(response)
    assert "do-not-echo" not in json.dumps(response)
