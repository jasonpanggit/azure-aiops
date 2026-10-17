"""Bounded governed source acquisition and honest projection comparisons."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.evidence import Evidence
from api.scope import Scope
from operations import investigation_evidence as module
from operations.tools import ToolResult


def test_collection_uses_only_governed_reads_and_preserves_source_provenance(monkeypatch):
    evidence = Evidence(source_engine="fixture.source", timestamp="2020-01-01T00:00:00Z", confidence="low")
    call = Mock(return_value=ToolResult(
        status="ok", data={"knowledge_version": "v1", "rows": [{"name": "source fact"}]},
        evidence=(evidence,), warning="Partial upstream projection",
    ))
    monkeypatch.setattr(module, "call_tool", call)
    context, principal, scope = object(), object(), Scope.from_mapping({"subscription": ["sub-a"]})
    rows = module.collect_investigation_sources(context, scope, principal, entry_type="BusinessService", subject="Payments")
    assert len(rows) == 8
    assert [row.tool for row in rows] == [name for name, _ in module.evidence_tools("BusinessService", "Payments")]
    for row in rows:
        assert row.evidence == [evidence.to_dict()]
        assert row.knowledge_version == "v1"
        assert row.warning == "Partial upstream projection"
        assert row.coverage == "bounded-governed-read-subset"
    for invocation in call.call_args_list:
        assert invocation.kwargs == {"context": context, "scope": scope, "principal": principal}


@pytest.mark.parametrize("data", [{"rows": ["x" * 17000]}, {"value": float("nan")}, {"value": object()}])
def test_oversized_or_non_json_payload_is_explicitly_unavailable_not_truncated_success(monkeypatch, data):
    monkeypatch.setattr(module, "call_tool", Mock(return_value=ToolResult(status="ok", data=data)))
    rows = module.collect_investigation_sources(None, Scope.unrestricted(), None, entry_type="Environment", subject="Prod")
    assert all(row.status == "unavailable" and row.data is None and row.evidence == [] for row in rows)
    assert all("JSON/16 KiB bound" in row.warning for row in rows)


@pytest.mark.parametrize("status", ["unavailable", "denied"])
def test_failed_sources_cannot_preserve_a_decisive_payload_or_claim_a_version(monkeypatch, status):
    monkeypatch.setattr(module, "call_tool", Mock(return_value=ToolResult(
        status=status, data={"secret": "not authorized"}, evidence=(Evidence(source_engine="fixture"),),
    )))
    rows = module.collect_investigation_sources(None, Scope.unrestricted(), None, entry_type="Incident", subject="inc-1")
    assert all(row.status == status and row.data is None and row.evidence == [] and row.knowledge_version == "unknown" for row in rows)


def test_read_only_registry_guard_precedes_execution(monkeypatch):
    original = module.TOOL_REGISTRY["network_topology"]
    monkeypatch.setitem(module.TOOL_REGISTRY, "network_topology", replace(original, read_only=False))
    call = Mock()
    monkeypatch.setattr(module, "call_tool", call)
    with pytest.raises(RuntimeError, match="mutating tool"):
        module.collect_investigation_sources(None, Scope.unrestricted(), None, entry_type="Environment", subject="")
    call.assert_not_called()


@pytest.mark.parametrize("entry_type,subject,expected", [
    ("BusinessService", "Payments", 8), ("Application", "API", 8), ("CVE", "CVE-2026-1234", 7),
    ("Incident", "inc-1", 5), ("NetworkGap", "gap-1", 5), ("Environment", "Prod", 5),
    ("SubscriptionConnection", "connection-1", 5), ("RemediationPlan", "plan-1", 5), ("BusinessService", "", 5),
])
def test_fixed_tools_are_bounded_and_never_accept_injected_operations(entry_type, subject, expected):
    calls = module.evidence_tools(entry_type, subject)
    assert len(calls) == expected
    assert all(module.TOOL_REGISTRY[name].read_only for name, _ in calls)


def test_comparison_never_decides_deltas_for_failed_sources_and_keeps_versions_independent(monkeypatch):
    state = SimpleNamespace(value="old", status="ok", version="v1")
    monkeypatch.setattr(module, "call_tool", lambda *_, **__: ToolResult(
        status=state.status, data={"value": state.value, "knowledge_version": state.version},
    ))
    before = module.collect_investigation_sources(None, Scope.unrestricted(), None, entry_type="Environment", subject="Prod")
    state.value, state.version = "new", "v2"
    after = module.collect_investigation_sources(None, Scope.unrestricted(), None, entry_type="Environment", subject="Prod")
    assert all(row["data_changed"] is True for row in module.compare_investigation_sources(before, after))
    assert before[0].knowledge_version == "v1" and after[0].knowledge_version == "v2"
    state.status = "unavailable"
    missing = module.collect_investigation_sources(None, Scope.unrestricted(), None, entry_type="Environment", subject="Prod")
    assert all(row["data_changed"] is None for row in module.compare_investigation_sources(before, missing))
    with pytest.raises(ValueError, match="contracts differ"):
        module.compare_investigation_sources(before, after[:-1])


def test_invalid_governed_outcome_is_a_service_failure_not_client_validation_error(monkeypatch):
    monkeypatch.setattr(module, "call_tool", Mock(return_value=ToolResult(status="not-a-status")))
    with pytest.raises(RuntimeError, match="invalid retention outcome"):
        module.collect_investigation_sources(None, Scope.unrestricted(), None, entry_type="Environment", subject="Prod")
