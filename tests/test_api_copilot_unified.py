from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, _context

from api.app import create_app
from api.evidence import Evidence
from api.providers import ProviderRuntime, ProviderSpec
from api.scope import Scope
from operations.foundry_agent import FoundryAgentError
from operations.investigation_thread_store import (
    InvestigationThreadStore,
    ThreadNotFound,
    ThreadRevisionConflict,
    ThreadStoreUnavailable,
)
from operations.orchestration_contract import (
    CandidatePlan,
    EvidenceSnapshotV2,
    InvestigationRequest,
    SnapshotCoverage,
    SnapshotEvidence,
    SnapshotFreshness,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_policy import PolicyViolation
from operations.orchestration_service import (
    OrchestrationService,
    PlannerUnavailableError,
)
from operations.specialist_manifest import INVENTORY_DATA_HEALTH_ID
from operations.tools import STATUS_OK, ToolResult


def _request(*, thread_id: str | None = None) -> InvestigationRequest:
    return InvestigationRequest(
        question="Show inventory resources and data health.",
        requested_scope={"subscription": ["sub-a"]},
        thread_id=thread_id,
        snapshot=EvidenceSnapshotV2(
            page_kind="inventory",
            page_id="inventory",
            coverage=SnapshotCoverage(visible_count=1, total_count=2, complete=False),
            freshness=[
                SnapshotFreshness(
                    source="inventory",
                    observed_at="2026-09-01T00:00:00Z",
                    status="stale",
                )
            ],
            evidence=[
                SnapshotEvidence(
                    evidence_id="inventory:visible",
                    source="inventory-page",
                    status="ok",
                    observed_at="2026-09-01T00:00:00Z",
                    data={"visible": 1},
                )
            ],
        ),
    )


def _candidate(**overrides) -> CandidatePlan:
    payload = {
        "steps": [
            SpecialistStep(
                specialist_id=INVENTORY_DATA_HEALTH_ID,
                tool_calls=[
                    ToolCallCandidate(
                        tool="inventory_resources",
                        arguments={},
                        citation_ids=["inventory:visible"],
                    )
                ],
            )
        ],
        "estimated_tokens": 500,
        "max_wall_seconds": 5,
    }
    payload.update(overrides)
    return CandidatePlan.model_validate(payload)


def _result() -> ToolResult:
    return ToolResult(
        status=STATUS_OK,
        data={
            "resources": [{"id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"}],
            "total": 1,
        },
        evidence=(
            Evidence(
                source_engine="intelligence.inventory.InventoryReadPort",
                source_table="inventory/resource_observations",
                resource_id="/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
                confidence="high",
            ),
        ),
    )


def test_canonical_inventory_tracer_returns_citations_uncertainty_and_thread():
    calls: list[tuple[str, dict[str, object], dict[str, list[str]]]] = []

    def execute(name, arguments, *, context, scope):
        calls.append((name, dict(arguments), scope.to_dict()))
        return _result()

    store = InvestigationThreadStore()
    service = OrchestrationService(
        planner=lambda request: _candidate(),
        executor=execute,
        thread_store=store,
    )
    result = service.execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert result.policy_status == "accepted"
    assert result.fallback_reason == ""
    assert result.selected_specialists == [INVENTORY_DATA_HEALTH_ID]
    assert result.selected_tools == ["inventory_resources"]
    assert calls == [
        ("inventory_resources", {}, {"subscription": ["sub-a"]})
    ]
    assert result.coverage.complete is False
    assert "visible subset is incomplete" in result.uncertainty
    assert "inventory freshness is stale" in result.uncertainty
    citation_ids = {item.citation_id for item in result.citations}
    assert "inventory:visible" in citation_ids
    tool_citation = next(
        citation_id for citation_id in citation_ids if citation_id.startswith("tool:")
    )
    assert result.thread_id in tool_citation
    assert tool_citation.endswith(
        ":0:0:inventory_data_health:inventory_resources:0"
    )
    assert result.thread_id.startswith("thr-")
    assert result.thread_revision == 1
    assert store.history(
        result.thread_id,
        "operator-a",
        Scope({"subscription": ["sub-a"]}),
    )


def test_default_executor_uses_scoped_governed_inventory_read_port():
    observed: list[dict[str, list[str]]] = []

    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            observed.append(scope.to_dict())
            assert family is None
            assert resource_type is None
            assert limit == 25
            return {
                "resources": [
                    {
                        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
                        "subscription": "sub-a",
                    }
                ],
                "total": 1,
            }

    class Context:
        provider_runtime = None

        def resolve_provider(self, name):
            return InventoryPort() if name == "inventory_read_port" else None

    result = OrchestrationService().execute(
        _request(),
        context=Context(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert observed == [{"subscription": ["sub-a"]}]
    assert result.selected_tools == ["inventory_resources"]
    assert result.tool_results[0]["status"] == STATUS_OK
    assert result.mutation_authorized is False


@pytest.mark.parametrize(
    ("planner", "reason"),
    [
        (lambda request: (_ for _ in ()).throw(TimeoutError()), "planner_timeout"),
        (lambda request: (_ for _ in ()).throw(ValueError("bad JSON")), "planner_parse_error"),
        (lambda request: (_ for _ in ()).throw(ConnectionError()), "planner_unavailable"),
        (
            lambda request: (_ for _ in ()).throw(PlannerUnavailableError()),
            "planner_unavailable",
        ),
        (
            lambda request: (_ for _ in ()).throw(FoundryAgentError("offline")),
            "planner_unavailable",
        ),
        (None, "planner_unavailable"),
    ],
)
def test_planner_failure_uses_validated_deterministic_fallback(planner, reason):
    calls: list[str] = []

    def execute(name, arguments, *, context, scope):
        calls.append(name)
        return _result()

    result = OrchestrationService(planner=planner, executor=execute).execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert result.policy_status == "fallback"
    assert result.fallback_reason == reason
    assert calls == ["inventory_resources"]
    assert result.citations


def test_rejected_candidate_executes_only_the_validated_fallback():
    calls: list[str] = []
    rejected = _candidate(mutation_intent=True)

    def execute(name, arguments, *, context, scope):
        calls.append(name)
        return _result()

    result = OrchestrationService(
        planner=lambda request: rejected,
        executor=execute,
    ).execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert result.fallback_reason == "candidate_rejected:mutation_forbidden"
    assert calls == ["inventory_resources"]


def test_foreign_principal_cannot_continue_thread_and_causes_zero_calls():
    calls: list[str] = []

    def execute(name, arguments, *, context, scope):
        calls.append(name)
        return _result()

    store = InvestigationThreadStore()
    service = OrchestrationService(executor=execute, thread_store=store)
    first = service.execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )
    calls.clear()

    with pytest.raises(ThreadNotFound):
        service.execute(
            _request(thread_id=first.thread_id),
            context=object(),
            principal_subject="operator-b",
            effective_scope=Scope({"subscription": ["sub-a"]}),
        )

    assert calls == []


def test_expected_thread_revision_rejects_stale_turn_before_tool_io():
    calls: list[str] = []

    def execute(name, arguments, *, context, scope):
        calls.append(name)
        return _result()

    store = InvestigationThreadStore()
    service = OrchestrationService(
        planner=lambda request: _candidate(),
        executor=execute,
        thread_store=store,
    )
    first = service.execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )
    second_payload = _request(thread_id=first.thread_id).model_dump(mode="json")
    second_payload["expected_thread_revision"] = first.thread_revision
    second = service.execute(
        InvestigationRequest.model_validate(second_payload),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )
    assert second.thread_revision == 2

    calls.clear()
    stale_payload = _request(thread_id=first.thread_id).model_dump(mode="json")
    stale_payload["expected_thread_revision"] = first.thread_revision
    with pytest.raises(ThreadRevisionConflict) as conflict:
        service.execute(
            InvestigationRequest.model_validate(stale_payload),
            context=object(),
            principal_subject="operator-a",
            effective_scope=Scope({"subscription": ["sub-a"]}),
        )

    assert conflict.value.current_revision == 2
    assert calls == []


def test_thread_history_rechecks_current_scope():
    store = InvestigationThreadStore()
    thread = store.create("operator-a", Scope({"subscription": ["sub-a"]}))
    store.append(
        thread.thread_id,
        "operator-a",
        Scope({"subscription": ["sub-a"]}),
        {"status": "ok"},
    )

    with pytest.raises(ThreadNotFound):
        store.history(
            thread.thread_id,
            "operator-a",
            Scope({"subscription": ["sub-b"]}),
        )


def test_scope_narrowing_redacts_wider_historical_turns():
    store = InvestigationThreadStore()
    broad = Scope({"subscription": ["sub-a", "sub-b"]})
    narrow = Scope({"subscription": ["sub-a"]})
    thread = store.create("operator-a", broad)
    store.append(
        thread.thread_id,
        "operator-a",
        broad,
        {
            "status": "ok",
            "tool_results": [{"data": {"subscription": "sub-b", "secret": "b-only"}}],
            "citations": [{"resource_id": "/subscriptions/sub-b/resourceGroups/rg"}],
        },
    )
    store.append(
        thread.thread_id,
        "operator-a",
        narrow,
        {"status": "ok", "tool_results": [{"data": {"subscription": "sub-a"}}]},
    )

    history = store.history(thread.thread_id, "operator-a", narrow)

    assert history[0]["status"] == "historical_scope_restricted"
    assert history[0]["tool_results"] == []
    assert "b-only" not in str(history)
    assert history[1]["tool_results"][0]["data"]["subscription"] == "sub-a"


def test_empty_snapshot_fallback_uses_canonical_coverage_citation():
    request = _request().model_copy(
        update={
            "snapshot": EvidenceSnapshotV2(
                page_kind="inventory",
                page_id="inventory",
                coverage=SnapshotCoverage(
                    visible_count=0,
                    total_count=0,
                    complete=True,
                ),
            )
        }
    )

    result = OrchestrationService(executor=lambda *args, **kwargs: _result()).execute(
        request,
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert result.policy_status == "fallback"
    assert "snapshot:coverage" in {
        citation.citation_id for citation in result.citations
    }


def test_repeated_tool_calls_retain_distinct_citations():
    candidate = CandidatePlan(
        steps=[
            SpecialistStep(
                specialist_id=INVENTORY_DATA_HEALTH_ID,
                tool_calls=[
                    ToolCallCandidate(
                        tool="inventory_resources",
                        arguments={},
                        citation_ids=["inventory:visible"],
                    ),
                    ToolCallCandidate(
                        tool="inventory_resources",
                        arguments={"family": "paas"},
                        citation_ids=["inventory:visible"],
                    ),
                ],
            )
        ],
        estimated_tokens=500,
        max_wall_seconds=5,
    )
    result = OrchestrationService(
        planner=lambda request: candidate,
        executor=lambda *args, **kwargs: _result(),
    ).execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    tool_citations = [
        citation.citation_id
        for citation in result.citations
        if citation.citation_id.startswith("tool:")
    ]
    assert len(tool_citations) == 2
    assert len(set(tool_citations)) == 2
    assert all(result.thread_id in citation_id for citation_id in tool_citations)
    assert tool_citations[0].endswith(
        ":0:0:inventory_data_health:inventory_resources:0"
    )
    assert tool_citations[1].endswith(
        ":0:1:inventory_data_health:inventory_resources:0"
    )


def test_wall_clock_budget_stops_before_tool_io():
    ticks = iter([0.0, 6.0])
    calls: list[str] = []
    service = OrchestrationService(
        planner=lambda request: _candidate(),
        executor=lambda name, arguments, *, context, scope: calls.append(name),
        clock=lambda: next(ticks),
    )

    result = service.execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert calls == []
    assert result.status == "partial"
    assert "orchestration wall-clock budget exhausted" in result.uncertainty


def test_widened_request_scope_causes_zero_calls():
    calls: list[str] = []
    request = _request().model_copy(
        update={"requested_scope": {"subscription": ["sub-a", "sub-b"]}}
    )
    service = OrchestrationService(
        executor=lambda name, arguments, *, context, scope: calls.append(name)
    )

    with pytest.raises(PolicyViolation, match="scope_widening"):
        service.execute(
            request,
            context=object(),
            principal_subject="operator-a",
            effective_scope=Scope({"subscription": ["sub-a"]}),
        )

    assert calls == []


def _canonical_body(**overrides):
    body = {
        "contract_version": "1",
        "question": "Show inventory resources and data health.",
        "requested_scope": {"subscription": ["sub-a"]},
        "snapshot": {
            "version": "2",
            "page_kind": "inventory",
            "page_id": "inventory",
            "coverage": {
                "visible_count": 1,
                "total_count": 2,
                "complete": False,
            },
            "freshness": [
                {
                    "source": "inventory",
                    "observed_at": "2026-09-01T00:00:00Z",
                    "status": "partial",
                }
            ],
            "evidence": [
                {
                    "evidence_id": "inventory:os:stable",
                    "source": "inventory/os_observations",
                    "status": "ok",
                    "observed_at": "2026-09-01T00:00:00Z",
                    "resource_id": "inventory://os/Windows%20Server%7C2019",
                    "data": {
                        "os_name": "Windows Server",
                        "os_version": "2019",
                        "machine_count": 1,
                        "selected": False,
                        "inventory_context": {
                            "tab": "os",
                            "filters": {
                                "os_name": "all",
                                "os_version": "all",
                            },
                        },
                    },
                }
            ],
        },
        "hint": {
            "specialist_id": INVENTORY_DATA_HEALTH_ID,
            "tool": "inventory_resources",
            "arguments": {},
        },
    }
    body.update(overrides)
    return body


def _cve_canonical_body(cve_id: str = "CVE-2026-13221"):
    """Adapter-derived v2 payload emitted for `/exposure/cves/[id]`.

    `normalizeCopilotSnapshotV2` maps the legacy `cve:*` page id to the
    route-disposition page kind `cve_detail`; keeping that wire value here
    prevents API regressions from testing the impossible pre-adapter
    `vulnerability`/`cve:*` combination.
    """

    return {
        "contract_version": "1",
        "question": f"Explain {cve_id}",
        "requested_scope": {"subscription": ["sub-a"]},
        "snapshot": {
            "version": "2",
            "page_kind": "cve_detail",
            "page_id": f"cve:{cve_id}",
            "filters": {"weakness_id": [cve_id]},
            "coverage": {
                "visible_count": 25,
                "total_count": 32,
                "complete": False,
            },
            "freshness": [
                {
                    "source": "nvd",
                    "status": "fresh",
                    "observed_at": "2026-09-14T00:00:00Z",
                },
                {
                    "source": "epss",
                    "status": "fresh",
                    "observed_at": "2026-09-14T00:00:00Z",
                },
                {
                    "source": "kev",
                    "status": "fresh",
                    "observed_at": "2026-09-14T00:00:00Z",
                },
                {
                    "source": "findings",
                    "status": "partial",
                    "observed_at": "2026-09-14T00:00:00Z",
                },
            ],
            "selected_entities": [],
            "evidence": [],
            "material_claims": [],
        },
        "hint": {
            "specialist_id": "vulnerability",
            "tool": "cve_detail",
            "arguments": {"cve_id": cve_id},
        },
    }


def test_cve_api_fixture_matches_browser_adapter_page_kind_contract():
    from pathlib import Path

    adapter = (
        Path(__file__).resolve().parents[1]
        / "web/src/lib/copilot/page-adapters.ts"
    ).read_text()
    assert (
        '"/exposure/cves/[id]": { kind: "integrated", pageKind: "cve_detail" }'
        in adapter
    )
    assert (
        'if (snapshot.page_id.startsWith("cve:")) return "cve_detail";'
        in adapter
    )
    assert _cve_canonical_body()["snapshot"]["page_kind"] == "cve_detail"


def _network_hub_canonical_body():
    vnet_id = (
        "/subscriptions/sub-a/resourceGroups/demo-rg/providers/"
        "Microsoft.Network/virtualNetworks/demo-vnet"
    )
    return {
        "contract_version": "1",
        "question": "What depends on demo-vnet?",
        "requested_scope": {"subscription": ["sub-a"]},
        "snapshot": {
            "version": "2",
            "page_kind": "network",
            "page_id": "network-topology",
            "coverage": {
                "visible_count": 1,
                "total_count": 2,
                "complete": False,
            },
            "freshness": [
                {
                    "source": "network_topology",
                    "status": "fresh",
                    "observed_at": "2026-09-14T00:00:00Z",
                }
            ],
            "selected_entities": [
                {"type": "azure", "resource_id": vnet_id},
            ],
            "evidence": [
                {
                    "evidence_id": "network:summary",
                    "source": "network/topology",
                    "status": "ok",
                    "observed_at": "2026-09-14T00:00:00Z",
                    "source_key": "network-summary",
                    "entity": {
                        "type": "domain",
                        "namespace": "network",
                        "kind": "topology_summary",
                        "source_key": "network-summary",
                    },
                    "claim_type": "topology_summary",
                    "citations": [],
                    "selected": False,
                    "direct": False,
                    "actionable": False,
                    "severity": "unknown",
                    "quality": "high",
                    "data": {
                        "untrusted_browser_summary": "must not be retained",
                        "mutation_authorized": False,
                    },
                },
                {
                    "evidence_id": "network:demo-vnet",
                    "source": "network/topology",
                    "status": "ok",
                    "observed_at": "2026-09-14T00:00:00Z",
                    "resource_id": vnet_id,
                    "source_key": vnet_id,
                    "entity": {"type": "azure", "resource_id": vnet_id},
                    "claim_type": "virtual_network",
                    "citations": [],
                    "selected": True,
                    "direct": True,
                    "actionable": False,
                    "severity": "unknown",
                    "quality": "high",
                    "data": {
                        "name": "demo-vnet",
                        "mutation_authorized": False,
                    },
                },
            ],
            "material_claims": [
                {
                    "claim_id": "network-visible-summary",
                    "evidence_refs": ["network:summary", "network:demo-vnet"],
                    "requires_complete_coverage": False,
                }
            ],
        },
        "hint": {
            "specialist_id": "network",
            "tool": "hub_dependents",
            "arguments": {"vnet_id": vnet_id},
        },
    }


def test_canonical_cve_fallback_narrates_exact_durable_and_scoped_evidence(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    cve_id = "CVE-2026-13221"
    findings = [
        {
            "weakness_id": cve_id,
            "severity": "Critical",
            "target_kind": "container_image",
            "current_state": "active",
            "represented_workload_count": 0,
        }
        for _ in range(25)
    ]
    catalog = {
        "contract_version": "1.0.0",
        "catalog_scope": "external_public_metadata",
        "environment_membership_included": False,
        "item": {
            "cve_id": cve_id,
            "sources": {
                "nvd": {
                    "source": "nvd",
                    "identifier": cve_id,
                    "status": "succeeded",
                    "stale": False,
                    "payload": {
                        "description": "Perl alternation trie overflow.",
                        "severity": "CRITICAL",
                        "cvss": {
                            "base_score": 9.1,
                            "vector": (
                                "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H"
                            ),
                            "severity": "CRITICAL",
                        },
                        "associated_kbs": [],
                    },
                },
                "epss": {
                    "source": "epss",
                    "identifier": cve_id,
                    "status": "succeeded",
                    "stale": False,
                    "payload": {
                        "epss_score": 0.00432,
                        "epss_percentile": 0.36545,
                    },
                },
                "kev": {
                    "source": "kev",
                    "identifier": cve_id,
                    "status": "succeeded",
                    "stale": False,
                    "payload": None,
                },
            },
        },
    }
    tool_data = {
        **catalog,
        "cve_id": cve_id,
        "external_catalog": catalog,
        "scoped_exposure_status": "ok",
        "scoped_exposure": {
            "query_cve_id": cve_id,
            "total_count": 32,
            "returned_count": 25,
            "affected_active_count": 32,
            "items": findings,
        },
    }

    monkeypatch.setattr(
        "api.routers.copilot.call_tool",
        lambda name, arguments, **_kwargs: ToolResult(
            status="ok",
            data=tool_data,
            evidence=(
                Evidence(
                    source_engine="api.ExposureQueryService",
                    source_table="enrichment/exposure-items.json",
                    resource_id=cve_id,
                    confidence="high",
                ),
                Evidence(
                    source_engine="api.ExposureQueryService",
                    source_table="gold_exposure_facts",
                    resource_id=cve_id,
                    confidence="high",
                ),
            ),
        ),
    )
    response = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=_cve_canonical_body(cve_id),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    narration = data["synthesis"]["claims"][0]["summary"]
    assert "CVE-2026-13221" in narration
    assert "CVSS 9.1 Critical" in narration
    assert "0.432%" in narration
    assert "no listing for CVE-2026-13221" in narration
    assert "**32** matching findings" in narration
    assert "**25 records were inspected**" in narration
    assert "**32 are active**" in narration
    assert "External CVE metadata is current from" not in narration
    assert data["synthesis"]["status"] == "degraded"
    assert "not configured" in data["synthesis"]["warning"]
    assert all(
        reference.startswith("tool:")
        for reference in data["synthesis"]["claims"][0]["evidence_refs"]
    )


def test_retained_cve_rollout_narrates_exact_tool_evidence_without_foundry(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    cve_id = "CVE-2026-13221"
    findings = [
        {
            "weakness_id": cve_id,
            "severity": "Critical",
            "target_kind": "container_image",
            "current_state": "active",
            "represented_workload_count": 0,
        }
        for _ in range(25)
    ]
    tool_data = {
        "cve_id": cve_id,
        "external_catalog": {
            "item": {
                "cve_id": cve_id,
                "sources": {
                    "nvd": {
                        "source": "nvd",
                        "identifier": cve_id,
                        "status": "succeeded",
                        "stale": False,
                        "payload": {
                            "description": "Perl alternation trie overflow.",
                            "severity": "CRITICAL",
                            "cvss": {
                                "base_score": 9.1,
                                "vector": (
                                    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/"
                                    "C:N/I:H/A:H"
                                ),
                                "severity": "CRITICAL",
                            },
                            "associated_kbs": [],
                        },
                    },
                    "epss": {
                        "source": "epss",
                        "identifier": cve_id,
                        "status": "succeeded",
                        "stale": False,
                        "payload": {
                            "epss_score": 0.00432,
                            "epss_percentile": 0.36545,
                        },
                    },
                    "kev": {
                        "source": "kev",
                        "identifier": cve_id,
                        "status": "succeeded",
                        "stale": False,
                        "payload": None,
                    },
                },
            },
        },
        "scoped_exposure_status": "ok",
        "scoped_exposure": {
            "query_cve_id": cve_id,
            "total_count": 37,
            "returned_count": 25,
            "affected_active_count": 37,
            "items": findings,
        },
    }
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        lambda name, arguments, **_kwargs: ToolResult(
            status="ok",
            data=tool_data,
            evidence=(
                Evidence(
                    source_engine="api.ExposureQueryService",
                    source_table="enrichment/exposure-items.json",
                    resource_id=cve_id,
                    confidence="high",
                ),
                Evidence(
                    source_engine="api.ExposureQueryService",
                    source_table="gold_exposure_facts",
                    resource_id=cve_id,
                    confidence="high",
                ),
            ),
        ),
    )

    response = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=_cve_canonical_body(cve_id),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["rollout"]["mode"] == "compatibility"
    assert data["selected_tools"] == ["cve_detail"]
    assert data["tool_results"][0]["data"] == tool_data
    assert data["synthesis"]["reason"] == "retained_compatibility"
    assert data["synthesis"]["compatibility_answer"] is None
    narration = data["synthesis"]["claims"][0]["summary"]
    assert "CVSS 9.1 Critical" in narration
    assert "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H" in narration
    assert "0.432%" in narration
    assert "36.545th percentile" in narration
    assert "no listing for CVE-2026-13221" in narration
    assert "No KB association" in narration
    assert "**37** matching findings" in narration
    assert "**25 records were inspected**" in narration
    assert "**37 are active**" in narration
    assert "no represented workload mapping" in narration
    assert all(
        ref.startswith("tool:")
        for ref in data["synthesis"]["claims"][0]["evidence_refs"]
    )


def test_canonical_cve_uses_durable_tool_when_semantic_provider_is_deferred(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    cve_id = "CVE-2026-8376"
    body = _cve_canonical_body(cve_id)
    body["snapshot"]["selected_entities"] = [
        {
            "type": "domain",
            "namespace": "vulnerability",
            "kind": "cve",
            "source_key": cve_id,
        }
    ]
    body["snapshot"]["evidence"] = [
        {
            "evidence_id": "cve-page:visible",
            "source": "exposure/cve",
            "status": "ok",
            "observed_at": "2026-09-14T00:00:00Z",
            "source_key": cve_id,
            "entity": {
                "type": "domain",
                "namespace": "vulnerability",
                "kind": "cve",
                "source_key": cve_id,
            },
            "claim_type": "cve",
            "citations": [],
            "selected": True,
            "direct": True,
            "actionable": False,
            "severity": "critical",
            "quality": "high",
            "data": {"untrusted_browser_description": "must not be retained"},
        }
    ]
    body["snapshot"]["material_claims"] = [
        {
            "claim_id": "visible-cve",
            "evidence_refs": ["cve-page:visible"],
            "requires_complete_coverage": False,
        }
    ]
    tool_calls: list[tuple[str, dict[str, object]]] = []

    def durable_cve_tool(name, arguments, **_kwargs):
        tool_calls.append((name, dict(arguments)))
        return ToolResult(
            status="ok",
            data={
                "cve_id": cve_id,
                "external_catalog": {
                    "item": {
                        "cve_id": cve_id,
                        "sources": {},
                    }
                },
                "scoped_exposure_status": "empty",
                "scoped_exposure": {
                    "query_cve_id": cve_id,
                    "total_count": 0,
                    "returned_count": 0,
                    "affected_active_count": 0,
                    "items": [],
                },
            },
            evidence=(
                Evidence(
                    source_engine="api.ExposureQueryService",
                    source_table="enrichment/exposure-items.json",
                    resource_id=cve_id,
                    confidence="high",
                ),
            ),
        )

    monkeypatch.setattr("api.routers.copilot.call_tool", durable_cve_tool)
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    assert tool_calls == [("cve_detail", {"cve_id": cve_id})]
    data = response.json()["data"]
    assert data["tool_results"][0]["status"] == "ok"
    assert data["synthesis"]["status"] == "degraded"
    assert all(
        citation["citation_id"].startswith("tool:")
        for citation in data["citations"]
    )
    assert "must not be retained" not in response.text


def test_canonical_page_degrades_when_domain_resolution_is_deferred(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    body = _canonical_body()
    body.pop("hint")
    body["question"] = "Summarize the visible governance context."
    body["snapshot"] = {
        "version": "2",
        "page_kind": "governance",
        "page_id": "governance",
        "coverage": {
            "visible_count": 1,
            "total_count": 1,
            "complete": True,
        },
        "freshness": [
            {
                "source": "governance",
                "status": "fresh",
                "observed_at": "2026-09-14T00:00:00Z",
            }
        ],
        "selected_entities": [
            {
                "type": "domain",
                "namespace": "governance",
                "kind": "policy",
                "source_key": "policy-visible",
            }
        ],
        "evidence": [
            {
                "evidence_id": "governance:visible",
                "source": "governance/page",
                "status": "ok",
                "observed_at": "2026-09-14T00:00:00Z",
                "source_key": "policy-visible",
                "entity": {
                    "type": "domain",
                    "namespace": "governance",
                    "kind": "policy",
                    "source_key": "policy-visible",
                },
                "claim_type": "policy",
                "citations": [],
                "selected": True,
                "direct": True,
                "actionable": False,
                "severity": "unknown",
                "quality": "high",
                "data": {"untrusted_browser_policy": "must not be retained"},
            }
        ],
        "material_claims": [
            {
                "claim_id": "governance-visible",
                "evidence_refs": ["governance:visible"],
                "requires_complete_coverage": False,
            }
        ],
    }
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["mutation_authorized"] is False
    assert any(
        "semantic identity resolution is unavailable" in warning.casefold()
        for warning in data["uncertainty"]
    )
    assert "must not be retained" not in response.text


@pytest.mark.parametrize(
    ("rollout_mode", "canary_percentage"),
    [
        ("compatibility", "0"),
        ("shadow", "0"),
        ("canary", "0"),
        ("canary", "100"),
        ("default", "0"),
    ],
)
def test_bound_network_hub_uses_network_tool_when_semantic_provider_is_deferred(
    tmp_path,
    monkeypatch,
    rollout_mode,
    canary_percentage,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", rollout_mode)
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", canary_percentage)
    body = _network_hub_canonical_body()
    vnet_id = body["hint"]["arguments"]["vnet_id"]
    tool_calls: list[tuple[str, dict[str, object]]] = []

    def durable_network_tool(name, arguments, **_kwargs):
        tool_calls.append((name, dict(arguments)))
        return ToolResult(
            status="ok",
            data={
                "hub_id": vnet_id,
                "hub_name": "demo-vnet",
                "dependent_count": 0,
                "dependents": [],
            },
            evidence=(
                Evidence(
                    source_engine="network.NetworkIntelligenceService",
                    source_table="ontology_entities",
                    resource_id=vnet_id,
                    confidence="high",
                ),
            ),
        )

    monkeypatch.setattr(
        "operations.investigation.call_tool",
        durable_network_tool,
    )
    monkeypatch.setattr(
        "api.routers.copilot.call_tool",
        durable_network_tool,
    )
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    assert tool_calls == [("hub_dependents", {"vnet_id": vnet_id})]
    data = response.json()["data"]
    assert data["rollout"]["mode"] == rollout_mode
    assert data["selected_tools"] == ["hub_dependents"]
    assert data["tool_results"][0]["status"] == "ok"
    assert data["tool_results"][0]["data"]["hub_name"] == "demo-vnet"
    assert data["mutation_authorized"] is False
    assert all(
        citation["citation_id"].startswith("tool:")
        for citation in data["citations"]
    )
    assert "untrusted_browser_summary" not in response.text
    assert "semantic provider is deferred" not in response.text.casefold()


@pytest.mark.parametrize("rollout_mode", ["compatibility", "default"])
def test_network_dependency_question_without_hint_binds_selected_vnet(
    tmp_path,
    monkeypatch,
    rollout_mode,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", rollout_mode)
    body = _network_hub_canonical_body()
    body.pop("hint")
    vnet_id = body["snapshot"]["selected_entities"][0]["resource_id"]
    tool_calls: list[tuple[str, dict[str, object]]] = []

    def durable_network_tool(name, arguments, **_kwargs):
        tool_calls.append((name, dict(arguments)))
        return ToolResult(
            status="ok",
            data={
                "hub_id": vnet_id,
                "hub_name": "demo-vnet",
                "dependent_count": 0,
                "dependents": [],
            },
            evidence=(
                Evidence(
                    source_engine="network.NetworkIntelligenceService",
                    source_table="ontology_entities",
                    resource_id=vnet_id,
                    confidence="high",
                ),
            ),
        )

    monkeypatch.setattr(
        "operations.investigation.call_tool",
        durable_network_tool,
    )
    monkeypatch.setattr(
        "api.routers.copilot.call_tool",
        durable_network_tool,
    )
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert tool_calls == [("hub_dependents", {"vnet_id": vnet_id})]
    assert data["selected_tools"] == ["hub_dependents"]
    assert data["tool_results"][0]["data"]["hub_name"] == "demo-vnet"
    assert data["mutation_authorized"] is False
    assert data["citations"]
    assert all(
        citation["citation_id"].startswith("tool:")
        for citation in data["citations"]
    )


@pytest.mark.parametrize(
    "unsafe_variant",
    ["no_selected_vnet", "ambiguous_vnets", "non_vnet", "free_form"],
)
def test_network_no_hint_derivation_does_not_widen_tool_authority(
    tmp_path,
    monkeypatch,
    unsafe_variant,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    body = _network_hub_canonical_body()
    body.pop("hint")
    if unsafe_variant == "no_selected_vnet":
        body["snapshot"]["selected_entities"] = []
    elif unsafe_variant == "ambiguous_vnets":
        body["snapshot"]["selected_entities"].append(
            {
                "type": "azure",
                "resource_id": (
                    "/subscriptions/sub-a/resourceGroups/demo-rg/providers/"
                    "Microsoft.Network/virtualNetworks/other-vnet"
                ),
            }
        )
    elif unsafe_variant == "non_vnet":
        body["snapshot"]["selected_entities"] = [
            {
                "type": "azure",
                "resource_id": (
                    "/subscriptions/sub-a/resourceGroups/demo-rg/providers/"
                    "Microsoft.Compute/virtualMachines/demo-vm"
                ),
            }
        ]
    else:
        body["question"] = "Tell me something interesting about demo-vnet."

    tool_calls: list[tuple[str, dict[str, object]]] = []

    def bounded_network_tool(name, arguments, **_kwargs):
        tool_calls.append((name, dict(arguments)))
        return ToolResult(status="empty")

    monkeypatch.setattr(
        "operations.investigation.call_tool",
        bounded_network_tool,
    )
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert all(name != "hub_dependents" for name, _arguments in tool_calls)
    assert "hub_dependents" not in data["selected_tools"]
    assert data["mutation_authorized"] is False


def test_shadow_endpoint_accepts_matching_plans_without_duplicate_tool_io(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "shadow")
    body = _network_hub_canonical_body()
    vnet_id = body["hint"]["arguments"]["vnet_id"]
    tool_calls: list[tuple[str, dict[str, object]]] = []

    def durable_network_tool(name, arguments, **_kwargs):
        tool_calls.append((name, dict(arguments)))
        return ToolResult(
            status="ok",
            data={"hub_id": vnet_id, "dependent_count": 0, "dependents": []},
            evidence=(
                Evidence(
                    source_engine="network.NetworkIntelligenceService",
                    source_table="ontology_entities",
                    resource_id=vnet_id,
                    confidence="high",
                ),
            ),
        )

    monkeypatch.setattr("operations.investigation.call_tool", durable_network_tool)
    monkeypatch.setattr("api.routers.copilot.call_tool", durable_network_tool)
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    rollout = response.json()["data"]["rollout"]
    assert tool_calls == [("hub_dependents", {"vnet_id": vnet_id})]
    assert rollout["shadow_validated"] is True
    assert rollout["shadow_reason"] == "accepted"
    assert rollout["comparison"]["divergent_fields"] == []
    assert rollout["comparison"]["matches"]["plan_outcome"] is True
    assert rollout["comparison"]["matches"]["selected_tools"] is True


def test_shadow_endpoint_reports_canonical_policy_fallback_without_duplicate_io(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "shadow")
    body = _network_hub_canonical_body()
    body["hint"]["specialist_id"] = "vulnerability"
    vnet_id = body["hint"]["arguments"]["vnet_id"]
    tool_calls: list[tuple[str, dict[str, object]]] = []

    def durable_network_tool(name, arguments, **_kwargs):
        tool_calls.append((name, dict(arguments)))
        return ToolResult(status="empty")

    monkeypatch.setattr("operations.investigation.call_tool", durable_network_tool)
    monkeypatch.setattr("api.routers.copilot.call_tool", durable_network_tool)
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    rollout = response.json()["data"]["rollout"]
    assert tool_calls == [("hub_dependents", {"vnet_id": vnet_id})]
    assert rollout["shadow_validated"] is False
    assert rollout["shadow_reason"].startswith("candidate_rejected:")
    assert rollout["comparison"]["canonical"]["policy_status"] == "fallback"


def test_absent_rollout_mode_fails_closed_to_compatibility(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("AIOPS_COPILOT_ROLLOUT_MODE", raising=False)
    monkeypatch.delenv("AIOPS_AGENT_ORCHESTRATION_MODE", raising=False)
    body = _network_hub_canonical_body()
    vnet_id = body["hint"]["arguments"]["vnet_id"]
    compatibility_calls: list[tuple[str, dict[str, object]]] = []

    def compatibility_tool(name, arguments, **_kwargs):
        compatibility_calls.append((name, dict(arguments)))
        return ToolResult(status="empty")

    monkeypatch.setattr("operations.investigation.call_tool", compatibility_tool)
    monkeypatch.setattr(
        "api.routers.copilot.call_tool",
        lambda *_args, **_kwargs: pytest.fail(
            "absent rollout mode reached canonical tool execution"
        ),
    )
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    rollout = response.json()["data"]["rollout"]
    assert compatibility_calls == [("hub_dependents", {"vnet_id": vnet_id})]
    assert rollout["mode"] == "compatibility"
    assert rollout["canonical_enabled"] is False


@pytest.mark.parametrize("binding_variant", ["mismatched_hint", "selected_domain"])
def test_deferred_semantic_network_does_not_require_a_page_specific_exception(
    tmp_path,
    monkeypatch,
    binding_variant,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    body = _network_hub_canonical_body()
    if binding_variant == "mismatched_hint":
        body["hint"]["arguments"]["vnet_id"] = (
            "/subscriptions/sub-a/resourceGroups/demo-rg/providers/"
            "Microsoft.Network/virtualNetworks/other-vnet"
        )
    else:
        body["snapshot"]["selected_entities"].append(
            {
                "type": "domain",
                "namespace": "network",
                "kind": "virtual_network",
                "source_key": "demo-vnet",
            }
        )
    expected_vnet_id = body["hint"]["arguments"]["vnet_id"]
    tool_calls: list[tuple[str, dict[str, object]]] = []
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        lambda name, arguments, **_kwargs: (
            tool_calls.append((name, dict(arguments)))
            or ToolResult(status="empty")
        ),
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert tool_calls == [("hub_dependents", {"vnet_id": expected_vnet_id})]
    assert data["mutation_authorized"] is False
    assert any(
        "semantic identity resolution is unavailable" in warning.casefold()
        for warning in data["uncertainty"]
    )
    assert "untrusted_browser_summary" not in response.text


def test_deferred_semantic_network_fallback_still_rejects_widened_azure_entity(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    body = _network_hub_canonical_body()
    widened_vnet_id = (
        "/subscriptions/sub-b/resourceGroups/demo-rg/providers/"
        "Microsoft.Network/virtualNetworks/demo-vnet"
    )
    body["snapshot"]["selected_entities"][0]["resource_id"] = widened_vnet_id
    body["snapshot"]["evidence"][1]["resource_id"] = widened_vnet_id
    body["snapshot"]["evidence"][1]["source_key"] = widened_vnet_id
    body["snapshot"]["evidence"][1]["entity"]["resource_id"] = widened_vnet_id
    body["hint"]["arguments"]["vnet_id"] = widened_vnet_id
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        lambda *_args, **_kwargs: pytest.fail(
            "out-of-scope network binding reached the tool"
        ),
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["field"] == "snapshot"


def test_deferred_semantic_cve_fallback_rejects_conflicting_selected_cve(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    body = _cve_canonical_body("CVE-2026-8376")
    body["snapshot"]["selected_entities"] = [
        {
            "type": "domain",
            "namespace": "vulnerability",
            "kind": "cve",
            "source_key": "CVE-2026-99999",
        }
    ]
    context = _context(tmp_path, None)
    context.provider_runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: object(),
                required=False,
                scheduled=False,
            ),
        }
    )
    monkeypatch.setattr(
        "api.routers.copilot.call_tool",
        lambda *_args, **_kwargs: pytest.fail("conflicting CVE reached the tool"),
    )

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["field"] == "snapshot.page_id"


def test_canonical_cve_rejects_prompt_or_hint_from_stale_visible_context(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    body = _cve_canonical_body("CVE-2026-13221")
    body["question"] = "Explain CVE-2026-99999"
    body["hint"]["arguments"]["cve_id"] = "CVE-2026-99999"

    response = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["field"] == "snapshot.page_id"


def test_authenticated_canonical_route_preserves_governed_result(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    observed_calls: list[tuple[dict[str, list[str]], str | None, str | None]] = []

    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            observed_calls.append((scope.to_dict(), family, resource_type))
            return {
                "resources": [
                    {
                        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/"
                        "Microsoft.Compute/virtualMachines/vm-1"
                    }
                ],
                "total": 1,
            }

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)

    assert client.post(
        "/api/v1/copilot/investigations",
        json=_canonical_body(),
    ).status_code == 401

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=_canonical_body(),
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert observed_calls == [
        ({"subscription": ["sub-a"]}, "os", None)
    ]
    assert data["policy_status"] == "accepted"
    assert data["fallback_reason"] == ""
    assert data["coverage"] == {
        "visible_count": 1,
        "total_count": 2,
        "complete": False,
    }
    assert "visible subset is incomplete" in data["uncertainty"]
    assert data["citations"]
    assert all(
        citation["citation_id"].startswith("tool:")
        for citation in data["citations"]
    )
    assert "inventory:os:stable" not in {
        citation["citation_id"] for citation in data["citations"]
    }
    assert data["thread_id"].startswith("thr-")
    assert data["mutation_authorized"] is False


def test_canonical_route_uses_snapshot_selectors_for_governed_reads(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    observed_calls: list[tuple[str | None, str | None]] = []

    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            observed_calls.append((family, resource_type))
            return {
                "resources": [{"family": family, "resource_type": resource_type}],
                "total": 1,
            }

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)

    os_response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=_canonical_body(),
        headers=HEADERS,
    )
    azure_body = _canonical_body()
    azure_body["snapshot"] = {
        **azure_body["snapshot"],
        "page_id": "inventory:azure",
        "evidence": [{
            "evidence_id": "inventory:azure:stable",
            "source": "inventory/resource_observations",
            "status": "ok",
            "observed_at": "2026-09-01T00:00:00Z",
            "resource_id": "inventory://azure/microsoft.app",
            "data": {
                "resource_type": "microsoft.app/containerapps",
                "sku": "",
                "tier": "",
                "selected": False,
                "inventory_context": {
                    "tab": "azure",
                    "filters": {
                        "resource_type": "microsoft.app/containerapps",
                    },
                },
            },
        }],
    }
    azure_response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=azure_body,
        headers=HEADERS,
    )

    assert os_response.status_code == 200
    assert azure_response.status_code == 200
    assert observed_calls == [
        ("os", None),
        ("paas", "microsoft.app/containerapps"),
    ]
    assert os_response.json()["data"]["tool_results"][0]["data"] != (
        azure_response.json()["data"]["tool_results"][0]["data"]
    )


def test_canonical_route_resolves_selected_software_through_scoped_service(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    observed: list[tuple[str, str, dict[str, list[str]], int]] = []

    class InventoryService:
        def software_detail(
            self, software_name, software_version, scope, *, offset, limit
        ):
            observed.append(
                (software_name, software_version, scope.to_dict(), limit)
            )
            return {
                "data": {
                    "group": {
                        "software_name": software_name,
                        "software_version": software_version,
                    },
                    "machines": [{"machine_name": "server-1"}],
                },
                "total": 1,
                "evidence": [{
                    "source_engine": "Azure Monitor Logs",
                    "source_table": "ConfigurationData",
                    "timestamp": "2026-09-01T00:00:00Z",
                    "resource_id": "/subscriptions/sub-a/machines/server-1",
                    "confidence": "high",
                }],
                "warnings": [],
            }

    context = _context(tmp_path, None)
    context.inventory_provider = lambda: InventoryService()
    context.inventory_read_port_provider = lambda: pytest.fail(
        "software context must not use the generic resource read port"
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    body = _canonical_body()
    body["snapshot"] = {
        **body["snapshot"],
        "page_id": "inventory:software",
        "evidence": [{
            "evidence_id": "inventory:software:stable",
            "source": "inventory/software_observations",
            "status": "ok",
            "observed_at": "2026-09-01T00:00:00Z",
            "resource_id": "inventory://software/7-Zip%7C19.00",
            "data": {
                "software_name": "7-Zip",
                "software_version": "19.00",
                "selected": True,
                "inventory_context": {
                    "tab": "software",
                    "filters": {"software": "7-Zip"},
                },
            },
        }],
    }

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=body,
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert observed == [
        ("7-Zip", "19.00", {"subscription": ["sub-a"]}, 25)
    ]
    result = response.json()["data"]
    assert result["tool_results"][0]["data"]["group"] == {
        "software_name": "7-Zip",
        "software_version": "19.00",
    }
    assert result["citations"]
    assert all(
        citation["citation_id"].startswith("tool:")
        for citation in result["citations"]
    )
    assert all(
        citation["citation_id"] != "inventory:software:stable"
        for citation in result["citations"]
    )


def test_canonical_route_bounds_large_selected_paas_evidence(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    evidence_count = 300

    class InventoryService:
        def paas_detail(self, key, scope, *, offset, limit):
            assert key == "microsoft.app:containerapps|Unknown|Unknown"
            assert scope.to_dict() == {"subscription": ["sub-a"]}
            return {
                "data": {
                    "group": {"key": key},
                    "resources": [{"resource_name": f"app-{index}"} for index in range(limit)],
                },
                "total": evidence_count,
                "evidence": [{
                    "source_engine": "Azure Resource Graph",
                    "source_table": "Resources",
                    "timestamp": "2026-09-01T00:00:00Z",
                    "resource_id": f"/subscriptions/sub-a/apps/app-{index}",
                    "confidence": "high",
                } for index in range(evidence_count)],
                "warnings": [],
            }

    context = _context(tmp_path, None)
    context.inventory_provider = lambda: InventoryService()
    client = TestClient(create_app(context), raise_server_exceptions=False)
    body = _canonical_body()
    body["snapshot"] = {
        **body["snapshot"],
        "page_id": "inventory:azure",
        "evidence": [{
            "evidence_id": "inventory:azure:stable",
            "source": "inventory/resource_observations",
            "status": "ok",
            "observed_at": "2026-09-01T00:00:00Z",
            "resource_id": "inventory://azure/microsoft.app",
            "data": {
                "resource_type": "microsoft.app/containerapps",
                "sku": "",
                "tier": "",
                "selected": True,
                "inventory_context": {
                    "tab": "azure",
                    "filters": {"resource_type": "microsoft.app/containerapps"},
                },
            },
        }],
    }

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=body,
        headers=HEADERS,
    )

    assert response.status_code == 200, response.json()
    result = response.json()["data"]
    assert len(result["citations"]) == 255
    assert result["tool_results"][0]["data"]["total"] == evidence_count
    assert len(result["tool_results"][0]["data"]["resources"]) == 25
    assert result["tool_results"][0]["warning"] == (
        "Server evidence truncated to 255 of 300 records"
    )


def test_canonical_route_rejects_conflicting_inventory_context_before_io(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    calls: list[object] = []

    class InventoryPort:
        def list_resources(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"resources": [], "total": 0}

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)
    body = _canonical_body()
    body["snapshot"]["evidence"][0]["data"]["inventory_context"]["tab"] = (
        "software"
    )

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=body,
        headers=HEADERS,
    )

    assert response.status_code == 400
    assert calls == []


def test_canonical_route_validates_hints_and_scope_before_tool_io(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    calls: list[dict[str, list[str]]] = []

    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            calls.append(scope.to_dict())
            return {"resources": [], "total": 0}

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)

    invalid_hint = _canonical_body(
        hint={
            "specialist_id": "remediation",
            "tool": "inventory_resources",
            "arguments": {},
        }
    )
    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=invalid_hint,
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["data"]["policy_status"] == "fallback"
    assert response.json()["data"]["fallback_reason"].startswith("candidate_rejected:")
    assert response.json()["data"]["selected_specialists"] == [
        INVENTORY_DATA_HEALTH_ID
    ]
    assert calls == [{"subscription": ["sub-a"]}]

    conflicting_hint = _canonical_body(
        hint={
            "specialist_id": INVENTORY_DATA_HEALTH_ID,
            "tool": "inventory_resources",
            "arguments": {"family": "paas"},
        }
    )
    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=conflicting_hint,
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["data"]["policy_status"] == "fallback"
    assert response.json()["data"]["fallback_reason"].startswith(
        "candidate_rejected:"
    )
    assert calls == [
        {"subscription": ["sub-a"]},
        {"subscription": ["sub-a"]},
    ]

    widened = _canonical_body(
        requested_scope={"subscription": ["sub-a", "sub-b"]}
    )
    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=widened,
        headers=HEADERS,
    )
    assert response.status_code == 400
    assert calls == [
        {"subscription": ["sub-a"]},
        {"subscription": ["sub-a"]},
    ]


def test_canonical_route_rejects_browser_authority_assertions(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)
    body = _canonical_body()
    body["snapshot"]["authorized"] = True

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=body,
        headers=HEADERS,
    )

    assert response.status_code == 400


def test_canonical_route_never_promotes_browser_observations_to_authority(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            return {"resources": [], "total": 0}

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)
    body = _canonical_body()
    body["snapshot"]["coverage"] = {
        "visible_count": 1,
        "total_count": 1,
        "complete": True,
    }
    body["snapshot"]["freshness"][0]["status"] = "fresh"
    body["snapshot"]["evidence"][0]["resource_id"] = (
        "/subscriptions/sub-b/resourceGroups/rg/providers/"
        "Microsoft.Compute/virtualMachines/untrusted"
    )

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=body,
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["coverage"] == {
        "visible_count": 1,
        "total_count": 1,
        "complete": False,
    }
    assert "visible subset is incomplete" in data["uncertainty"]
    assert "inventory freshness is unavailable" in data["uncertainty"]
    assert "inventory:os:stable" not in {
        citation["citation_id"] for citation in data["citations"]
    }


# ---------------------------------------------------------------------------
# Plan 11-03 Task 2: Thin canonical compatibility adapters for legacy routes
# ---------------------------------------------------------------------------


def test_investigate_canonical_mode_stamps_contract_version(tmp_path, monkeypatch):
    """When canonical orchestration is active, /copilot/investigate stamps
    contract_version on the response so consumers can distinguish the
    canonical result from the legacy wire shape."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigate?subscription=sub-a",
        json={"question": "Show inventory resources", "session_id": ""},
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data.get("contract_version") == "1"


def test_investigate_canonical_preserves_legacy_wire_fields(tmp_path, monkeypatch):
    """Canonical mode must preserve the question, tool_calls, fact_status, and
    warnings fields so existing clients do not break."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigate?subscription=sub-a",
        json={"question": "Show inventory resources", "session_id": ""},
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert "question" in data
    assert "tool_calls" in data
    assert "fact_status" in data
    assert data["contract_version"] == "1"


def test_investigate_context_canonical_stamps_contract_version(tmp_path, monkeypatch):
    """When canonical orchestration is active, /copilot/investigate-context
    stamps contract_version on the ledger."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigate-context?subscription=sub-a",
        json={
            "snapshot": {
                "version": "1",
                "page_kind": "network",
                "page_id": "topology",
                "question": "What firewall gaps exist?",
                "scope": {"declared": {}},
                "evidence": [{
                    "evidence_id": "route-1",
                    "section": "route",
                    "resource_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/routeTables/rt-1",
                    "data": {"finding": "Default route bypasses firewall"},
                }],
                "selected_resources": [],
                "freshness": [],
                "rechecks": [],
            }
        },
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data.get("contract_version") == "1"


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        (ThreadStoreUnavailable(), 503, "provider_unavailable"),
        (ThreadRevisionConflict(current_revision=3), 409, "conflict"),
    ],
)
def test_investigate_context_maps_canonical_continuity_failures(
    tmp_path,
    monkeypatch,
    failure,
    expected_status,
    expected_code,
):
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    monkeypatch.setattr(
        "api.routers.copilot._run_context_via_canonical",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigate-context?subscription=sub-a",
        json={
            "snapshot": {
                "version": "1",
                "page_kind": "network",
                "page_id": "topology",
                "question": "What firewall gaps exist?",
                "scope": {"declared": {}},
                "evidence": [],
                "selected_resources": [],
                "freshness": [],
                "rechecks": [],
            }
        },
        headers=HEADERS,
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def test_multi_agent_canonical_stamps_contract_version(tmp_path, monkeypatch):
    """When canonical orchestration is active, /agents/investigations stamps
    contract_version on new ledger writes."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        json={"objective": "Investigate inventory health", "timeout_seconds": 3},
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data.get("contract_version") == "1"


def test_old_ledger_read_projected_with_defaults(tmp_path):
    """Persisted old ledgers without contract_version are readable via
    project_legacy_ledger without bulk rewrite."""
    from operations.autonomous_investigation import project_legacy_ledger

    old_ledger = {
        "ledger_id": "mai-abc123def456",
        "objective": "Old investigation",
        "scope": {"subscription": ["sub-a"]},
        "created_by": "admin@example.com",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
        "status": "synthesized",
        "selected_agents": [],
        "agent_runs": [],
        "reconciliation": {},
        "synthesis": {},
        "human_controls": {"available_actions": []},
        "decisions": [],
        "approvals": [],
        "outcome": "",
        "stop_reason": "",
        "evaluation": {},
    }

    projected = project_legacy_ledger(old_ledger)

    assert projected["contract_version"] == "1"
    assert projected["ledger_id"] == "mai-abc123def456"
    # Original is not mutated
    assert "contract_version" not in old_ledger


def test_multi_agent_old_ledger_readable_via_get(tmp_path, monkeypatch):
    """GET /agents/investigations/{id} projects old ledgers on read."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    from operations.autonomous_investigation import ledger_store

    store = ledger_store()
    old_ledger = {
        "ledger_id": "mai-oldledger001",
        "objective": "Old network investigation",
        "scope": {"subscription": ["sub-a"]},
        "created_by": "admin@example.com",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
        "status": "synthesized",
        "selected_agents": [],
        "agent_runs": [],
        "reconciliation": {},
        "synthesis": {},
        "human_controls": {"available_actions": []},
        "decisions": [],
        "approvals": [],
        "outcome": "",
        "stop_reason": "",
        "evaluation": {},
        "warnings": [],
    }
    store.add(old_ledger)

    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/agents/investigations/mai-oldledger001?subscription=sub-a",
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data.get("contract_version") == "1"


# ---------------------------------------------------------------------------
# Code-review findings CR-01 through CR-04
# ---------------------------------------------------------------------------


def test_action_on_old_ledger_projects_version_in_canonical_mode(
    tmp_path, monkeypatch
):
    """CR-02: POST /agents/investigations/{id}/actions must project
    record_decision output through project_legacy_ledger in canonical mode."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    from operations.autonomous_investigation import ledger_store as get_store

    store = get_store()
    old_ledger = {
        "ledger_id": "mai-oldaction001",
        "objective": "Old investigation",
        "scope": {"subscription": ["sub-a"]},
        "created_by": "admin@example.com",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
        "status": "synthesized",
        "selected_agents": [],
        "agent_runs": [],
        "reconciliation": {},
        "synthesis": {},
        "human_controls": {"available_actions": ["accept_finding"]},
        "decisions": [],
        "approvals": [],
        "outcome": "",
        "stop_reason": "",
        "evaluation": {},
        "warnings": [],
    }
    store.add(old_ledger)

    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/agents/investigations/mai-oldaction001/actions?subscription=sub-a",
        json={"action": "accept_finding", "payload": {}},
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data.get("contract_version") == "1", (
        "Action on old unversioned ledger must include contract_version"
    )


def test_project_legacy_ledger_always_returns_shallow_copy():
    """CR-03: project_legacy_ledger must return a new dict even when the
    ledger already carries a truthy contract_version, to avoid mutable
    store aliases."""
    from operations.autonomous_investigation import project_legacy_ledger

    versioned = {
        "ledger_id": "mai-copy001",
        "contract_version": "1",
        "decisions": [],
    }
    projected = project_legacy_ledger(versioned)

    assert projected is not versioned, (
        "Must return a shallow copy, not the original dict"
    )
    assert projected["contract_version"] == "1"
    assert projected["ledger_id"] == "mai-copy001"


def test_project_legacy_ledger_mutation_does_not_reach_original():
    """CR-03: Mutating the projected dict must not alter the persisted
    original — mutable store aliases are forbidden."""
    from operations.autonomous_investigation import project_legacy_ledger

    original = {
        "ledger_id": "mai-mut001",
        "contract_version": "1",
        "status": "synthesized",
    }
    snapshot = dict(original)
    projected = project_legacy_ledger(original)
    projected["status"] = "tampered"

    assert original == snapshot, (
        "Mutations on projected must not propagate to the original"
    )


# ---------------------------------------------------------------------------
# Review fix: canonical mode must invoke OrchestrationService, not legacy
# planners (acceptance violations V1 and V2)
# ---------------------------------------------------------------------------


def test_investigate_canonical_invokes_service_not_legacy_planner(
    tmp_path, monkeypatch
):
    """V1: In canonical mode /copilot/investigate must route through
    OrchestrationService.execute and must NOT call run_investigation."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")

    legacy_calls: list[object] = []
    service_calls: list[object] = []

    def _spy_legacy(*args, **kwargs):
        legacy_calls.append(True)
        from operations.investigation import Investigation

        return Investigation(
            question="q", calls=(), answer=None,
            fact_status="empty", warnings=(),
        )

    monkeypatch.setattr(
        "api.routers.copilot.run_investigation", _spy_legacy
    )

    _orig_execute = OrchestrationService.execute

    def _spy_execute(self, *args, **kwargs):
        service_calls.append(True)
        return _orig_execute(self, *args, **kwargs)

    monkeypatch.setattr(OrchestrationService, "execute", _spy_execute)

    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigate?subscription=sub-a",
        json={"question": "Show inventory resources", "session_id": ""},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert not legacy_calls, (
        "Legacy run_investigation must not be called in canonical mode"
    )
    assert service_calls, (
        "OrchestrationService.execute must be invoked in canonical mode"
    )
    data = response.json()["data"]
    assert data.get("contract_version") == "1"
    assert data.get("question") == "Show inventory resources"
    assert "fact_status" in data
    assert "tool_calls" in data
    assert "thread_id" in data


def test_investigate_non_canonical_preserves_legacy_planner(
    tmp_path, monkeypatch
):
    """V1 preserve: /copilot/investigate must still use run_investigation
    when canonical mode is not enabled."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "maf")

    legacy_calls: list[object] = []
    service_calls: list[object] = []

    import operations.investigation as _inv_mod

    _orig_run = _inv_mod.run_investigation

    def _spy_legacy(*args, **kwargs):
        legacy_calls.append(True)
        return _orig_run(*args, **kwargs)

    monkeypatch.setattr(
        "api.routers.copilot.run_investigation", _spy_legacy
    )

    _orig_execute = OrchestrationService.execute

    def _spy_execute(self, *args, **kwargs):
        service_calls.append(True)
        return _orig_execute(self, *args, **kwargs)

    monkeypatch.setattr(OrchestrationService, "execute", _spy_execute)

    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigate?subscription=sub-a",
        json={"question": "Show inventory resources", "session_id": ""},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert legacy_calls, (
        "Legacy run_investigation must be called in non-canonical mode"
    )
    assert not service_calls, (
        "OrchestrationService.execute must not be called in non-canonical mode"
    )


def test_multi_agent_canonical_invokes_service_not_legacy_loop(
    tmp_path, monkeypatch
):
    """V2: In canonical mode POST /agents/investigations must route through
    OrchestrationService.execute and must NOT call run_autonomous_investigation."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")

    legacy_calls: list[object] = []
    service_calls: list[object] = []

    def _spy_legacy(*args, **kwargs):
        legacy_calls.append(True)
        return {
            "contract_version": "1",
            "ledger_id": "mai-fake001",
            "objective": args[0] if args else "obj",
            "scope": {}, "created_by": "", "created_at": "",
            "updated_at": "", "status": "synthesized",
            "selected_agents": [], "agent_runs": [],
            "reconciliation": {}, "synthesis": {},
            "human_controls": {"available_actions": []},
            "decisions": [], "approvals": [], "outcome": "",
            "stop_reason": "", "evaluation": {}, "warnings": [],
        }

    monkeypatch.setattr(
        "api.routers.multi_agent.run_autonomous_investigation", _spy_legacy
    )

    _orig_execute = OrchestrationService.execute

    def _spy_execute(self, *args, **kwargs):
        service_calls.append(True)
        return _orig_execute(self, *args, **kwargs)

    monkeypatch.setattr(OrchestrationService, "execute", _spy_execute)

    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        json={"objective": "Investigate inventory health", "timeout_seconds": 3},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert not legacy_calls, (
        "Legacy run_autonomous_investigation must not be called in canonical mode"
    )
    assert service_calls, (
        "OrchestrationService.execute must be invoked in canonical mode"
    )
    data = response.json()["data"]
    assert data.get("contract_version") == "1"
    assert "ledger_id" in data
    assert data["objective"] == "Investigate inventory health"
    assert data.get("scope") == {"subscription": ["sub-a"]}
    assert "thread_id" in data


def test_multi_agent_non_canonical_preserves_legacy_loop(
    tmp_path, monkeypatch
):
    """V2 preserve: POST /agents/investigations must still use
    run_autonomous_investigation when canonical mode is not enabled."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "maf")

    legacy_calls: list[object] = []
    service_calls: list[object] = []

    import operations.autonomous_investigation as _auto_mod

    _orig_run = _auto_mod.run_autonomous_investigation

    def _spy_legacy(*args, **kwargs):
        legacy_calls.append(True)
        return _orig_run(*args, **kwargs)

    monkeypatch.setattr(
        "api.routers.multi_agent.run_autonomous_investigation", _spy_legacy
    )

    _orig_execute = OrchestrationService.execute

    def _spy_execute(self, *args, **kwargs):
        service_calls.append(True)
        return _orig_execute(self, *args, **kwargs)

    monkeypatch.setattr(OrchestrationService, "execute", _spy_execute)

    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        json={"objective": "Investigate inventory health", "timeout_seconds": 3},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert legacy_calls, (
        "Legacy run_autonomous_investigation must be called in non-canonical mode"
    )
    assert not service_calls, (
        "OrchestrationService.execute must not be called in non-canonical mode"
    )


# ---------------------------------------------------------------------------
# BLOCKER A: context canonical fidelity — page kind, evidence, and ledger
# ---------------------------------------------------------------------------


def test_context_canonical_supported_page_translates_evidence_and_kind(
    tmp_path, monkeypatch
):
    """BLOCKER-A: When a page kind IS in the canonical contract,
    _run_context_via_canonical must translate the ACTUAL page kind, submitted
    evidence, freshness, and selected resources into the canonical request;
    select specialists through the canonical loop (not hardcoded inventory);
    and project a complete legacy ledger preserving canonical findings,
    citations, status, and warnings."""
    from types import SimpleNamespace

    from operations.orchestration_contract import Citation, SnapshotCoverage

    captured_requests: list[object] = []

    # Build a controlled OrchestrationResult via the real dataclass
    from operations.orchestration_contract import OrchestrationResult

    fake_result = OrchestrationResult(
        status="ok",
        policy_status="fallback",
        fallback_reason="planner_unavailable",
        selected_specialists=["connections_health"],
        selected_tools=["connections_status"],
        tool_results=[
            {
                "call_id": "0:0:connections_health:connections_status",
                "specialist_id": "connections_health",
                "tool": "connections_status",
                "status": "ok",
                "data": {"connections": [{"id": "conn-1", "status": "healthy"}]},
                "warning": "",
                "evidence": [],
            }
        ],
        uncertainty=["visible subset is incomplete"],
        coverage=SnapshotCoverage(visible_count=2, total_count=5, complete=False),
        citations=[
            Citation(
                citation_id="conn-ev-1",
                source="connections-panel",
                status="ok",
                observed_at="2026-09-01T00:00:00Z",
            )
        ],
        thread_id="thr-" + "a" * 32,
        thread_revision=1,
    )

    def _capture_execute(self, request, **kwargs):
        captured_requests.append(request)
        return fake_result

    monkeypatch.setattr(OrchestrationService, "execute", _capture_execute)

    # Duck-typed snapshot with canonical-supported page_kind="connections"
    evidence_row = SimpleNamespace(
        evidence_id="conn-ev-1",
        resource_id="/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/connections/c1",
        section="connection",
        data={"status": "connected"},
        status="ok",
        observed_at="2026-09-01T00:00:00Z",
    )
    freshness_rec = SimpleNamespace(
        source="connections",
        observed_at="2026-09-01T00:00:00Z",
        status="fresh",
    )
    selected_res = SimpleNamespace(
        resource_id="/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/connections/c1",
        resource_type="Microsoft.Network/connections",
    )
    snapshot = SimpleNamespace(
        page_kind="connections",
        page_id="connections-panel",
        question="What is the connection health status?",
        evidence=[evidence_row],
        freshness=[freshness_rec],
        selected_resources=[selected_res],
    )
    scope = SimpleNamespace(to_dict=lambda: {"subscription": ["sub-a"]})

    from api.routers.copilot import _run_context_via_canonical

    ledger = _run_context_via_canonical(
        snapshot,
        context=_context(tmp_path, None),
        scope=scope,
        principal=SimpleNamespace(subject="test@example.com"),
        principal_subject="test@example.com",
    )

    # --- Canonical request must carry the ACTUAL page kind ---
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.snapshot.page_kind == "connections", (
        "Canonical snapshot must use the real page_kind, not hardcoded 'inventory'"
    )

    # --- Submitted evidence must be translated into canonical snapshot ---
    assert len(req.snapshot.evidence) >= 1, (
        "Submitted evidence rows must be translated into canonical snapshot evidence"
    )
    assert req.snapshot.evidence[0].evidence_id == "conn-ev-1"
    assert req.snapshot.evidence[0].resource_id == selected_res.resource_id

    # --- Legacy ledger must preserve canonical results ---
    assert ledger["page_kind"] == "connections"
    assert ledger["contract_version"] == "1"
    assert ledger["orchestration"]["selected_ids"] == ["connections_health"]

    # Tool calls must preserve canonical data (not strip it)
    assert len(ledger["tool_calls"]) == 1
    assert ledger["tool_calls"][0]["tool"] == "connections_status"
    assert ledger["tool_calls"][0]["status"] == "ok"
    assert ledger["tool_calls"][0].get("data"), (
        "Canonical tool data must be preserved in legacy projection"
    )

    # Findings must be populated from canonical results (not empty [])
    assert ledger.get("findings"), (
        "Findings must be projected from canonical tool results"
    )

    # Citations must be projected
    assert ledger.get("citations"), (
        "Canonical citations must be projected into legacy ledger"
    )

    # Synthesis must include canonical status
    assert ledger["synthesis"].get("status") == "ok", (
        "Synthesis must include canonical result status"
    )

    # Warnings must reflect canonical uncertainty
    assert "visible subset is incomplete" in ledger["warnings"]
    assert ledger.get("thread_id", "").startswith("thr-")


# ---------------------------------------------------------------------------
# BLOCKER B: deep-copy audit immutability for project_legacy_ledger
# ---------------------------------------------------------------------------


def test_project_legacy_ledger_deep_copy_nested_mutation_isolation():
    """BLOCKER-B: project_legacy_ledger must deep-copy so nested mutations to
    decisions, approvals, agent_runs, synthesis, and human_controls in the
    projected copy never affect the original store record."""
    import json

    from operations.autonomous_investigation import project_legacy_ledger

    original = {
        "ledger_id": "mai-deepcopy001",
        "contract_version": "1",
        "status": "synthesized",
        "decisions": [{"action": "approve", "by": "admin"}],
        "approvals": [{"role": "operator", "approved": True}],
        "agent_runs": [{"agent_id": "inv", "tool_calls": [{"tool": "t1"}]}],
        "synthesis": {"mode": "canonical", "narration": "all good"},
        "human_controls": {
            "available_actions": ["approve_plan", "stop_investigation"]
        },
    }
    snapshot = json.loads(json.dumps(original))

    projected = project_legacy_ledger(original)

    # Mutate every nested structure in the projected copy
    projected["decisions"].append({"action": "reject", "by": "attacker"})
    projected["approvals"][0]["approved"] = False
    projected["agent_runs"][0]["tool_calls"].append({"tool": "injected"})
    projected["synthesis"]["narration"] = "tampered"
    projected["human_controls"]["available_actions"].append("escalate")

    # Original must be entirely unchanged
    assert original == snapshot, (
        "Deep nested mutations on projected copy must never propagate to original"
    )


def test_project_legacy_ledger_preserves_explicit_falsy_contract_version():
    """BLOCKER-B: An explicit falsy contract_version key (empty string) must
    be preserved by project_legacy_ledger, not overwritten with default."""
    from operations.autonomous_investigation import project_legacy_ledger

    ledger = {
        "ledger_id": "mai-falsy001",
        "contract_version": "",
        "status": "synthesized",
    }
    projected = project_legacy_ledger(ledger)

    assert projected["contract_version"] == "", (
        "Explicit falsy contract_version must be preserved"
    )


# ---------------------------------------------------------------------------
# BLOCKER C: Terraform mode validation includes canonical
# ---------------------------------------------------------------------------


def test_terraform_orchestration_mode_includes_canonical():
    """BLOCKER-C: The Terraform agent_orchestration_mode variable must accept
    'canonical' (runtime support via MODE_CANONICAL) and must NOT accept
    'shadow' (no runtime support)."""
    import re
    from pathlib import Path

    tf = Path("infra/terraform/variables.tf").read_text()
    # Extract the contains() validation for agent_orchestration_mode
    match = re.search(
        r'variable\s+"agent_orchestration_mode".*?'
        r'condition\s*=\s*contains\(\[(.*?)\]',
        tf,
        re.DOTALL,
    )
    assert match, "agent_orchestration_mode validation block not found"
    allowed_modes = match.group(1)
    assert '"canonical"' in allowed_modes, (
        "canonical must be an allowed orchestration mode in Terraform"
    )
    assert '"shadow"' not in allowed_modes, (
        "shadow must NOT be allowed — no runtime support exists"
    )


# ---------------------------------------------------------------------------
# Final comprehensive-review regressions
# ---------------------------------------------------------------------------


def test_canonical_contract_accepts_public_context_page_kinds():
    """Every public v1 PageSnapshot kind must have a real canonical identity."""
    for page_kind in (
        "network",
        "vulnerability",
        "patch",
        "incident",
        "governance",
        "resource",
    ):
        snapshot = EvidenceSnapshotV2(
            page_kind=page_kind,
            page_id=f"{page_kind}-page",
            coverage=SnapshotCoverage(
                visible_count=0,
                total_count=0,
                complete=False,
            ),
        )
        assert snapshot.page_kind == page_kind


def test_context_canonical_network_preserves_page_evidence_and_results(
    tmp_path, monkeypatch
):
    """A valid network snapshot must stay network throughout canonical routing."""
    from operations.orchestration_contract import Citation, OrchestrationResult

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    captured_requests: list[InvestigationRequest] = []
    legacy_calls: list[object] = []

    def _legacy(*_args, **_kwargs):
        legacy_calls.append(True)
        raise AssertionError("network is a canonical-supported page")

    def _execute(self, request, **_kwargs):
        captured_requests.append(request)
        return OrchestrationResult(
            status="ok",
            policy_status="fallback",
            fallback_reason="planner_unavailable",
            selected_specialists=["network"],
            selected_tools=["traffic_flow"],
            tool_results=[
                {
                    "call_id": "0:0:network:traffic_flow",
                    "specialist_id": "network",
                    "tool": "traffic_flow",
                    "arguments": {"source": "uat", "destination": "prod"},
                    "status": "ok",
                    "data": {"nodes": [{"id": "vnet-a"}]},
                    "evidence": [
                        {
                            "source_engine": "azure-resource-graph",
                            "source_table": "resources",
                            "timestamp": "2026-09-01T00:00:00Z",
                            "resource_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-a",
                            "confidence": "high",
                        }
                    ],
                    "warning": "",
                }
            ],
            uncertainty=[],
            coverage=SnapshotCoverage(
                visible_count=1,
                total_count=1,
                complete=True,
            ),
            citations=[
                Citation(
                    citation_id="network:route-1",
                    source="network-route-table",
                    status="ok",
                    resource_id="/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/routeTables/rt-a",
                )
            ],
            thread_id="thr-" + "b" * 32,
            thread_revision=1,
        )

    monkeypatch.setattr(
        "api.routers.copilot.run_context_investigation",
        _legacy,
    )
    monkeypatch.setattr(OrchestrationService, "execute", _execute)

    client = TestClient(create_app(_context(tmp_path, None)))
    response = client.post(
        "/api/v1/copilot/investigate-context?subscription=sub-a",
        headers=HEADERS,
        json={
            "snapshot": {
                "version": "1",
                "page_kind": "network",
                "page_id": "topology",
                "question": "Show network topology",
                "scope": {"declared": {"subscription": ["sub-a"]}},
                "evidence": [
                    {
                        "evidence_id": "network:route-1",
                        "section": "route",
                        "resource_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/routeTables/rt-a",
                        "data": {"next_hop": "firewall"},
                        "status": "ok",
                        "observed_at": "2026-09-01T00:00:00Z",
                    }
                ],
                "selected_resources": [],
                "freshness": [
                    {
                        "source": "network",
                        "observed_at": "2026-09-01T00:00:00Z",
                        "status": "fresh",
                    }
                ],
                "rechecks": [],
            }
        },
    )

    assert response.status_code == 200
    assert not legacy_calls
    assert captured_requests[0].snapshot.page_kind == "network"
    assert captured_requests[0].snapshot.evidence[0].evidence_id == "network:route-1"
    data = response.json()["data"]
    assert data["selected_agents"][0]["id"] == "network"
    assert data["agent_runs"][0]["tool_calls"][0]["call_id"].startswith("0:0:network")
    assert data["findings"][0]["data"]["nodes"][0]["id"] == "vnet-a"
    assert data["citations"][0]["citation_id"] == "network:route-1"
    assert data["synthesis"]["status"] == "ok"


@pytest.mark.parametrize(
    ("question", "expected_page_kind"),
    [
        ("Can UAT reach PROD through the firewall?", "network"),
        ("Which CVEs expose production?", "vulnerability"),
        ("Summarize incident INC-42", "incident"),
    ],
)
def test_execute_from_question_routes_domain_intent(
    question, expected_page_kind, monkeypatch
):
    """Question-only canonical requests must not masquerade as inventory."""
    from operations.orchestration_contract import OrchestrationResult
    from operations.orchestration_service import execute_from_question

    captured: list[InvestigationRequest] = []

    def _execute(self, request, **_kwargs):
        captured.append(request)
        return OrchestrationResult(
            status="unavailable",
            policy_status="fallback",
            fallback_reason="planner_unavailable",
            coverage=request.snapshot.coverage,
            thread_id="thr-" + "c" * 32,
            thread_revision=1,
        )

    monkeypatch.setattr(OrchestrationService, "execute", _execute)
    execute_from_question(
        question,
        scope=Scope({"subscription": ["sub-a"]}),
        context=object(),
        principal_subject="operator@example.com",
    )

    assert captured[0].snapshot.page_kind == expected_page_kind


def test_investigate_canonical_session_continuity_and_stale_hint(
    tmp_path, monkeypatch
):
    """Legacy session IDs map to scoped canonical threads before hint validation."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    monkeypatch.setattr(
        "operations.orchestration_service.call_tool",
        lambda *_args, **_kwargs: ToolResult(status="empty"),
    )
    legacy_calls: list[object] = []
    monkeypatch.setattr(
        "api.routers.copilot.run_investigation",
        lambda *_args, **_kwargs: legacy_calls.append(True),
    )

    client = TestClient(create_app(_context(tmp_path, None)))
    body = {
        "question": "Can UAT reach PROD?",
        "session_id": "legacy-session-routing",
        "tool": "retired_legacy_tool",
        "tool_arguments": {},
    }
    first = client.post(
        "/api/v1/copilot/investigate?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )
    second = client.post(
        "/api/v1/copilot/investigate?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert not legacy_calls
    assert first.json()["data"]["thread_id"] == second.json()["data"]["thread_id"]
    assert second.json()["data"]["thread_revision"] == 2

    history_response = client.get(
        "/api/v1/copilot/history/legacy-session-routing?subscription=sub-a",
        headers=HEADERS,
    )
    assert history_response.status_code == 200
    assert len(history_response.json()["data"]["turns"]) == 2


def test_canonical_investigate_projects_thread_storage_outage_as_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    monkeypatch.setattr(
        "api.routers.copilot.execute_from_question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ThreadStoreUnavailable()),
    )
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigate?subscription=sub-a",
        headers=HEADERS,
        json={
            "question": "Show inventory health",
            "session_id": "outage-session",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_canonical_history_projects_thread_storage_outage_as_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    monkeypatch.setattr(
        "api.routers.copilot.legacy_session_history",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ThreadStoreUnavailable()),
    )
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/copilot/history/outage-session?subscription=sub-a",
        headers=HEADERS,
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_canonical_history_projects_binding_contention_as_conflict(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    monkeypatch.setattr(
        "api.routers.copilot.legacy_session_history",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ThreadRevisionConflict(current_revision=4)
        ),
    )
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/copilot/history/contention-session?subscription=sub-a",
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_canonical_endpoint_projects_thread_storage_outage_as_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    context = _context(tmp_path, None)
    monkeypatch.setattr(
        OrchestrationService,
        "execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ThreadStoreUnavailable()),
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=_canonical_body(),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_canonical_endpoint_projects_sustained_thread_contention_as_conflict(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    monkeypatch.setattr(
        OrchestrationService,
        "execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ThreadRevisionConflict(current_revision=3)
        ),
    )
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=_canonical_body(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_canonical_endpoint_preserves_used_retained_citations(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    from operations.orchestration_contract import Citation, OrchestrationResult

    retained_id = f"retained:thr-{'a' * 32}:rev-1:citation-0"
    result = OrchestrationResult(
        status="ok",
        policy_status="accepted",
        coverage=SnapshotCoverage(
            visible_count=0,
            total_count=0,
            complete=True,
        ),
        citations=[
            Citation(
                citation_id="snapshot:coverage",
                source="page_snapshot:inventory:coverage",
                status="empty",
            ),
            Citation(
                citation_id=retained_id,
                source="page_snapshot:vulnerability:coverage",
                status="ok",
            ),
        ],
        thread_id="thr-" + "a" * 32,
        thread_revision=2,
    )
    monkeypatch.setattr(
        OrchestrationService,
        "execute",
        lambda *_args, **_kwargs: result,
    )
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=_canonical_body(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["citations"] == [
        {
            "citation_id": retained_id,
            "source": "page_snapshot:vulnerability:coverage",
            "status": "ok",
            "observed_at": "",
            "resource_id": "",
        }
    ]


def test_multi_agent_projects_thread_storage_outage_as_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    monkeypatch.setattr(
        "api.routers.multi_agent.execute_from_question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ThreadStoreUnavailable()),
    )
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        headers=HEADERS,
        json={"objective": "Show inventory health"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_legacy_adapter_does_not_reset_thread_on_storage_outage(monkeypatch):
    from operations.orchestration_service import execute_from_question

    calls = 0

    def _execute(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise ThreadStoreUnavailable()

    monkeypatch.setattr(OrchestrationService, "execute", _execute)
    monkeypatch.setattr(
        "operations.orchestration_service._legacy_session_thread_for_execution",
        lambda *_args, **_kwargs: "thr-" + "a" * 32,
    )

    with pytest.raises(ThreadStoreUnavailable):
        execute_from_question(
            "Show inventory health",
            scope=Scope({"subscription": ["sub-a"]}),
            context=object(),
            principal_subject="operator@example.com",
            session_id="outage-session",
        )

    assert calls == 1


def test_legacy_history_does_not_hide_thread_storage_outage(monkeypatch):
    from operations.orchestration_service import legacy_session_history

    class UnavailableStore:
        def history(self, *_args, **_kwargs):
            raise ThreadStoreUnavailable()

    monkeypatch.setattr(
        "operations.orchestration_service._legacy_session_thread",
        lambda *_args, **_kwargs: "thr-" + "a" * 32,
    )
    monkeypatch.setattr(
        "operations.orchestration_service.investigation_thread_store",
        UnavailableStore,
    )

    with pytest.raises(ThreadStoreUnavailable):
        legacy_session_history(
            "outage-session",
            principal_subject="operator@example.com",
            scope=Scope({"subscription": ["sub-a"]}),
        )


def test_multi_agent_canonical_projection_retains_complete_results(
    tmp_path, monkeypatch
):
    """The compatibility ledger must retain canonical evidence and findings."""
    from operations.orchestration_contract import Citation, OrchestrationResult

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    result = OrchestrationResult(
        status="partial",
        policy_status="fallback",
        fallback_reason="planner_unavailable",
        selected_specialists=["network"],
        selected_tools=["traffic_flow"],
        tool_results=[
            {
                "call_id": "0:0:network:traffic_flow",
                "specialist_id": "network",
                "tool": "traffic_flow",
                "arguments": {"source": "uat", "destination": "prod"},
                "status": "ok",
                "data": {"nodes": [{"id": "vnet-a"}]},
                "evidence": [
                    {
                        "source_engine": "azure-resource-graph",
                        "source_table": "resources",
                        "timestamp": "2026-09-01T00:00:00Z",
                        "resource_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-a",
                        "confidence": "high",
                    }
                ],
                "warning": "",
            }
        ],
        uncertainty=["visible subset is incomplete"],
        coverage=SnapshotCoverage(
            visible_count=0,
            total_count=0,
            complete=False,
        ),
        citations=[
            Citation(
                citation_id="tool:0:0:network:traffic_flow:0",
                source="azure-resource-graph:resources",
                status="ok",
            )
        ],
        thread_id="thr-" + "d" * 32,
        thread_revision=1,
    )
    monkeypatch.setattr(
        "api.routers.multi_agent.execute_from_question",
        lambda *_args, **_kwargs: result,
    )

    client = TestClient(create_app(_context(tmp_path, None)))
    response = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        headers=HEADERS,
        json={"objective": "Can UAT reach PROD?"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["selected_agents"][0]["id"] == "network"
    assert data["agent_runs"][0]["agent_id"] == "network"
    assert data["agent_runs"][0]["agent_name"] == "Network Agent"
    assert data["agent_runs"][0]["findings"]
    assert data["agent_runs"][0]["evidence"]
    assert data["agent_runs"][0]["hidden_reasoning_exposed"] is False
    assert data["tool_calls"][0]["call_id"] == "0:0:network:traffic_flow"
    assert data["tool_calls"][0]["arguments"] == {
        "source": "uat",
        "destination": "prod",
    }
    assert data["tool_calls"][0]["data"]["nodes"][0]["id"] == "vnet-a"
    assert data["tool_calls"][0]["evidence"][0]["source_engine"] == "azure-resource-graph"
    assert data["findings"][0]["citation_ids"] == [
        "tool:0:0:network:traffic_flow:0"
    ]
    assert data["citations"][0]["citation_id"].startswith("tool:")
    assert data["synthesis"]["policy_status"] == "fallback"
    assert data["synthesis"]["fallback_reason"] == "planner_unavailable"
    assert data["synthesis"]["status"] == "partial"
    assert data["synthesis"]["uncertainty"] == ["visible subset is incomplete"]
    assert set(data["reconciliation"]) >= {
        "conflicts",
        "stale_evidence",
        "missing_providers",
        "unsupported_conclusions",
        "evidence_count",
        "reconciled_confidence",
    }
    assert set(data["synthesis"]) >= {
        "summary",
        "recommended_plan",
        "required_decision",
        "unresolved_questions",
        "confidence",
        "narration",
        "narrated_by",
        "llm_calls",
    }
    assert set(data["evaluation"]) == {
        "groundedness",
        "scope_isolation",
        "tool_correctness",
        "convergence",
        "latency_ms",
        "cost",
    }


def test_projected_store_ledger_nested_mutations_do_not_touch_store():
    """A projected store object must be deeply isolated from persisted audit state."""
    from operations.autonomous_investigation import ledger_store, project_legacy_ledger

    store = ledger_store()
    ledger_id = "mai-deep-store-001"
    original = {
        "ledger_id": ledger_id,
        "created_by": "admin@example.com",
        "decisions": [{"action": "accept"}],
        "approvals": [{"approved": True}],
        "agent_runs": [{"tool_calls": [{"tool": "network_topology"}]}],
        "synthesis": {"status": "ok"},
        "human_controls": {"available_actions": ["stop_investigation"]},
    }
    store.add(original)

    projected = project_legacy_ledger(
        store.get(ledger_id, "admin@example.com")
    )
    projected["decisions"][0]["action"] = "tampered"
    projected["approvals"][0]["approved"] = False
    projected["agent_runs"][0]["tool_calls"][0]["tool"] = "mutated"
    projected["synthesis"]["status"] = "denied"
    projected["human_controls"]["available_actions"].append("execute")

    persisted = store.get(ledger_id, "admin@example.com")
    assert persisted["decisions"][0]["action"] == "accept"
    assert persisted["approvals"][0]["approved"] is True
    assert persisted["agent_runs"][0]["tool_calls"][0]["tool"] == "network_topology"
    assert persisted["synthesis"]["status"] == "ok"
    assert persisted["human_controls"]["available_actions"] == [
        "stop_investigation"
    ]


def test_multi_agent_projection_marks_unexecuted_specialist_not_started(
    tmp_path, monkeypatch
):
    """A selected specialist with no attempted calls must never report success."""
    from operations.orchestration_contract import OrchestrationResult

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    result = OrchestrationResult(
        status="partial",
        policy_status="fallback",
        fallback_reason="planner_unavailable",
        selected_specialists=["network", "incident"],
        selected_tools=["network_topology"],
        tool_results=[
            {
                "call_id": "0:0:network:network_topology",
                "specialist_id": "network",
                "tool": "network_topology",
                "status": "ok",
                "data": {"nodes": []},
                "evidence": [],
                "warning": "",
            }
        ],
        uncertainty=["orchestration wall-clock budget exhausted"],
        coverage=SnapshotCoverage(
            visible_count=0,
            total_count=0,
            complete=False,
        ),
        citations=[],
        thread_id="thr-" + "e" * 32,
        thread_revision=1,
    )
    monkeypatch.setattr(
        "api.routers.multi_agent.execute_from_question",
        lambda *_args, **_kwargs: result,
    )

    client = TestClient(create_app(_context(tmp_path, None)))
    response = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        headers=HEADERS,
        json={"objective": "Correlate network and incident state"},
    )

    assert response.status_code == 200
    runs = {
        run["agent_id"]: run
        for run in response.json()["data"]["agent_runs"]
    }
    assert runs["network"]["status"] == "ok"
    assert runs["incident"]["status"] == "not_started"
    assert runs["incident"]["tool_calls"] == []


def test_multi_agent_read_and_action_reauthorize_stored_scope(
    tmp_path, monkeypatch
):
    """Ledger reads and decisions must fail closed after scope loss."""
    from operations.autonomous_investigation import ledger_store

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    ledger_id = "mai-scope-bound-001"
    ledger_store().add(
        {
            "ledger_id": ledger_id,
            "created_by": "admin@example.com",
            "scope": {"subscription": ["sub-a", "sub-b"]},
            "decisions": [],
            "approvals": [],
            "agent_runs": [
                {
                    "agent_id": "network",
                    "tool_calls": [
                        {
                            "data": {"subscription": "sub-b"},
                            "evidence": [
                                {
                                    "resource_id": "/subscriptions/sub-b/resourceGroups/rg-b"
                                }
                            ],
                        }
                    ],
                }
            ],
            "synthesis": {"status": "ok"},
            "human_controls": {"available_actions": ["accept_finding"]},
            "warnings": [],
        }
    )
    client = TestClient(create_app(_context(tmp_path, None)))

    read = client.get(
        f"/api/v1/agents/investigations/{ledger_id}?subscription=sub-a",
        headers=HEADERS,
    )
    action = client.post(
        f"/api/v1/agents/investigations/{ledger_id}/actions?subscription=sub-a",
        headers=HEADERS,
        json={"action": "accept_finding", "payload": {}},
    )

    assert read.status_code == 404
    assert action.status_code == 404
    persisted = ledger_store().get(ledger_id, "admin@example.com")
    assert persisted["decisions"] == []
    assert (
        persisted["agent_runs"][0]["tool_calls"][0]["evidence"][0]["resource_id"]
        == "/subscriptions/sub-b/resourceGroups/rg-b"
    )


def test_canonical_history_retains_question_and_validated_tool_arguments(
    tmp_path, monkeypatch
):
    """History retains only policy-validated arguments from executed calls."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    monkeypatch.setattr(
        "operations.orchestration_service.call_tool",
        lambda *_args, **_kwargs: ToolResult(status="empty"),
    )
    client = TestClient(create_app(_context(tmp_path, None)))
    body = {
        "question": "Can UAT reach PROD?",
        "session_id": "traffic-session-history",
        "tool": "traffic_flow",
        "tool_arguments": {"source": "uat", "destination": "prod"},
    }

    response = client.post(
        "/api/v1/copilot/investigate?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )
    history_response = client.get(
        "/api/v1/copilot/history/traffic-session-history?subscription=sub-a",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["data"]["tool_calls"][0]["arguments"] == {
        "source": "uat",
        "destination": "prod",
    }
    turns = history_response.json()["data"]["turns"]
    assert turns[0]["question"] == "Can UAT reach PROD?"
    assert turns[0]["tool_results"][0]["arguments"] == {
        "source": "uat",
        "destination": "prod",
    }


@pytest.mark.parametrize(
    ("question", "expected_page_kind"),
    [
        ("Which servers are vulnerable?", "vulnerability"),
        ("Summarize vulnerabilities by severity", "vulnerability"),
        ("Which route can reach production?", "network"),
    ],
)
def test_question_route_handles_stable_aliases(
    question, expected_page_kind, monkeypatch
):
    """Common inflections must resolve to their domain instead of incident."""
    from operations.orchestration_contract import OrchestrationResult
    from operations.orchestration_service import execute_from_question

    captured: list[InvestigationRequest] = []

    def _execute(self, request, **_kwargs):
        captured.append(request)
        return OrchestrationResult(
            status="unavailable",
            policy_status="fallback",
            fallback_reason="planner_unavailable",
            coverage=request.snapshot.coverage,
            thread_id="thr-" + "f" * 32,
            thread_revision=1,
        )

    monkeypatch.setattr(OrchestrationService, "execute", _execute)
    execute_from_question(
        question,
        scope=Scope({"subscription": ["sub-a"]}),
        context=object(),
        principal_subject="operator@example.com",
    )

    assert captured[0].snapshot.page_kind == expected_page_kind


def test_unmatched_question_returns_explicit_unsupported_without_tool_io(
    monkeypatch,
):
    """An unmatched question must not inherit the incident page fallback."""
    from operations.orchestration_service import execute_from_question

    calls: list[str] = []
    monkeypatch.setattr(
        "operations.orchestration_service.call_tool",
        lambda name, *_args, **_kwargs: calls.append(name),
    )

    result = execute_from_question(
        "Please explain this view",
        scope=Scope({"subscription": ["sub-a"]}),
        context=object(),
        principal_subject="operator@example.com",
    )

    assert result.status == "unavailable"
    assert result.fallback_reason == "unsupported_intent"
    assert result.selected_specialists == []
    assert calls == []


def test_ownership_question_without_subject_is_explicitly_unavailable(
    monkeypatch,
):
    """Required-argument governance tools must never execute with empty args."""
    from operations.orchestration_service import execute_from_question

    calls: list[str] = []
    monkeypatch.setattr(
        "operations.orchestration_service.call_tool",
        lambda name, *_args, **_kwargs: calls.append(name),
    )

    result = execute_from_question(
        "Who has ownership of this resource?",
        scope=Scope({"subscription": ["sub-a"]}),
        context=object(),
        principal_subject="operator@example.com",
    )

    assert result.status == "unavailable"
    assert result.fallback_reason == "missing_required_arguments"
    assert result.selected_specialists == []
    assert result.citations[0].source == "page_snapshot:governance:coverage"
    assert calls == []


def test_empty_required_argument_hint_is_unavailable_without_fallback_io(
    monkeypatch,
):
    """Invalid hints must not fall through to an unrelated specialist tool."""
    from operations.orchestration_service import execute_from_question

    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "operations.orchestration_service.call_tool",
        lambda name, arguments, **_kwargs: calls.append((name, arguments)),
    )

    result = execute_from_question(
        "Who has ownership of this resource?",
        scope=Scope({"subscription": ["sub-a"]}),
        context=object(),
        principal_subject="operator@example.com",
        hint_tool="business_service_context",
        hint_arguments={},
    )

    assert result.status == "unavailable"
    assert result.fallback_reason == "missing_required_arguments"
    assert result.selected_specialists == []
    assert result.selected_tools == []
    assert calls == []


def test_incident_terms_take_precedence_over_embedded_network_markers(
    monkeypatch,
):
    """The word breach must not match the network reach marker."""
    from operations.orchestration_contract import OrchestrationResult
    from operations.orchestration_service import execute_from_question

    captured: list[InvestigationRequest] = []

    def _execute(self, request, **_kwargs):
        captured.append(request)
        return OrchestrationResult(
            status="unavailable",
            policy_status="fallback",
            fallback_reason="planner_unavailable",
            coverage=request.snapshot.coverage,
            thread_id="thr-" + "a" * 32,
            thread_revision=1,
        )

    monkeypatch.setattr(OrchestrationService, "execute", _execute)
    execute_from_question(
        "Investigate the security breach incident",
        scope=Scope({"subscription": ["sub-a"]}),
        context=object(),
        principal_subject="operator@example.com",
    )

    assert captured[0].snapshot.page_kind == "incident"


def test_canonical_endpoint_accepts_non_inventory_manifest_snapshot(
    tmp_path,
    monkeypatch,
):
    """The shared canonical route accepts every manifest-backed page kind."""
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    body = _canonical_body()
    body["snapshot"]["page_kind"] = "network"
    body["snapshot"]["page_id"] = "network"
    body["snapshot"]["evidence"] = []
    client = TestClient(create_app(_context(tmp_path, None)))

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200
    assert response.json()["data"]["mutation_authorized"] is False


@pytest.mark.parametrize(
    ("page_kind", "page_id", "question", "expected_specialists"),
    (
        (
            "governance",
            "governance",
            "Who owns governance decisions for this resource?",
            {"governance"},
        ),
        (
            "identity",
            "identity",
            "Which principals have risky access to this resource?",
            {"identity_access"},
        ),
        (
            "finops",
            "finops",
            "Where can we reduce cost for this resource?",
            {"finops"},
        ),
        (
            "overview",
            "operations-overview",
            "Give an executive overview of network, vulnerability, incident, and cost risk.",
            {"network", "vulnerability", "incident", "finops"},
        ),
    ),
)
def test_unhinted_typed_questions_use_governed_page_context(
    tmp_path,
    monkeypatch,
    page_kind,
    page_id,
    question,
    expected_specialists,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    calls: list[tuple[str, dict[str, object]]] = []
    resource_id = (
        "/subscriptions/sub-a/resourceGroups/rg/providers/"
        "Microsoft.Compute/virtualMachines/vm-1"
    )

    def call_tool(name, arguments, *, context, scope, principal):
        calls.append((name, dict(arguments)))
        return ToolResult(
            status=STATUS_OK,
            data={"resource_id": resource_id, "status": "observed"},
            evidence=(
                Evidence(
                    source_engine="test",
                    source_table="page_context",
                    resource_id=resource_id,
                    confidence="high",
                ),
            ),
        )

    monkeypatch.setattr("api.routers.copilot.call_tool", call_tool)
    body = _canonical_body()
    body.pop("hint")
    body["question"] = question
    body["snapshot"] = {
        **body["snapshot"],
        "page_kind": page_kind,
        "page_id": page_id,
        "selected_entities": [{"type": "azure", "resource_id": resource_id}],
        "evidence": [
            {
                "evidence_id": f"{page_kind}:selected",
                "source": f"{page_kind}/page",
                "status": "ok",
                "observed_at": "2026-09-01T00:00:00Z",
                "resource_id": resource_id,
                "entity": {"type": "azure", "resource_id": resource_id},
                "selected": True,
                "direct": True,
                "data": {"resource_id": resource_id},
            }
        ],
    }

    response = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert expected_specialists <= set(result["selected_specialists"])
    assert result["selected_tools"]
    assert result["fallback_reason"] != "no_safe_tool_arguments"
    assert calls
    assert result["citations"]
    assert f"{page_kind}:selected" not in {
        citation["citation_id"] for citation in result["citations"]
    }
    if page_kind == "overview":
        assert result["synthesis"]["domain_count"] >= 2
        assert result["synthesis"]["reason"] == "explicit_intent"


def test_canonical_endpoint_returns_409_for_stale_revision_before_tool_io(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    calls: list[str] = []

    def execute(name, arguments, *, context, scope):
        calls.append(name)
        return _result()

    service = OrchestrationService(
        planner=lambda _request: CandidatePlan(
            steps=[
                SpecialistStep(
                    specialist_id=INVENTORY_DATA_HEALTH_ID,
                    tool_calls=[
                        ToolCallCandidate(
                            tool="inventory_resources",
                            arguments={},
                            citation_ids=["snapshot:coverage"],
                        )
                    ],
                )
            ],
        ),
        executor=execute,
        thread_store=InvestigationThreadStore(),
    )
    monkeypatch.setattr(
        "api.routers.copilot.OrchestrationService",
        lambda **_kwargs: service,
    )
    client = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    )

    first = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=_canonical_body(),
    )
    assert first.status_code == 200, first.text
    thread_id = first.json()["data"]["thread_id"]
    second_body = _canonical_body(
        thread_id=thread_id,
        expected_thread_revision=1,
    )
    second = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=second_body,
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["thread_revision"] == 2
    assert calls == ["inventory_resources", "inventory_resources"]

    stale = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=second_body,
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"
    assert calls == ["inventory_resources", "inventory_resources"]


def test_concurrent_first_legacy_session_turns_share_one_thread(monkeypatch):
    """Concurrent first turns must both remain reachable from session history."""
    from operations.orchestration_service import (
        execute_from_question,
        legacy_session_history,
    )

    barrier = threading.Barrier(2)
    original_execute = OrchestrationService.execute

    def _synchronized_execute(self, request, **kwargs):
        barrier.wait(timeout=5)
        return original_execute(self, request, **kwargs)

    monkeypatch.setattr(OrchestrationService, "execute", _synchronized_execute)
    monkeypatch.setattr(
        "operations.orchestration_service.call_tool",
        lambda *_args, **_kwargs: ToolResult(status="empty"),
    )
    session_id = "concurrent-first-turns"

    def _run(question):
        return execute_from_question(
            question,
            scope=Scope({"subscription": ["sub-a"]}),
            context=object(),
            principal_subject="operator@example.com",
            session_id=session_id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                _run,
                ("Show network topology", "Summarize network traffic"),
            )
        )

    history = legacy_session_history(
        session_id,
        principal_subject="operator@example.com",
        scope=Scope({"subscription": ["sub-a"]}),
    )
    assert results[0].thread_id == results[1].thread_id
    assert {turn["question"] for turn in history} == {
        "Show network topology",
        "Summarize network traffic",
    }


def test_multi_agent_canonical_propagates_requested_timeout(
    tmp_path, monkeypatch
):
    """The public timeout remains authoritative in canonical mode."""
    from operations.orchestration_contract import OrchestrationResult

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    captured: list[float] = []

    def _execute(*_args, **kwargs):
        captured.append(kwargs["max_wall_seconds"])
        return OrchestrationResult(
            status="unavailable",
            policy_status="fallback",
            fallback_reason="unsupported_intent",
            coverage=SnapshotCoverage(
                visible_count=0,
                total_count=0,
                complete=False,
            ),
            thread_id="thr-" + "b" * 32,
            thread_revision=1,
        )

    monkeypatch.setattr("api.routers.multi_agent.execute_from_question", _execute)
    client = TestClient(create_app(_context(tmp_path, None)))
    response = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        headers=HEADERS,
        json={"objective": "Explain current state", "timeout_seconds": 1.5},
    )

    assert response.status_code == 200
    assert captured == [1.5]


def test_multi_agent_reconciliation_counts_only_observed_evidence(
    tmp_path, monkeypatch
):
    """Coverage citations must not inflate evidence-backed finding counts."""
    from operations.orchestration_contract import Citation, OrchestrationResult

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    result = OrchestrationResult(
        status="ok",
        policy_status="accepted",
        selected_specialists=["network"],
        selected_tools=["network_topology"],
        tool_results=[
            {
                "call_id": "0:0:network:network_topology",
                "specialist_id": "network",
                "tool": "network_topology",
                "arguments": {},
                "status": "ok",
                "data": {"nodes": []},
                "evidence": [],
                "warning": "",
            }
        ],
        coverage=SnapshotCoverage(
            visible_count=0,
            total_count=0,
            complete=True,
        ),
        citations=[
            Citation(
                citation_id="snapshot:coverage",
                source="page_snapshot:network:coverage",
                status="empty",
            )
        ],
        thread_id="thr-" + "c" * 32,
        thread_revision=1,
    )
    monkeypatch.setattr(
        "api.routers.multi_agent.execute_from_question",
        lambda *_args, **_kwargs: result,
    )
    client = TestClient(create_app(_context(tmp_path, None)))

    response = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        headers=HEADERS,
        json={"objective": "Show network topology"},
    )
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["reconciliation"]["evidence_count"] == 0
    assert data["reconciliation"]["reconciled_confidence"] == "unknown"
    assert data["findings"][0]["unsupported"] is True
    assert data["reconciliation"]["unsupported_conclusions"] == [
        data["findings"][0]
    ]
    assert data["evaluation"]["convergence"] == "converged_with_open_questions"
    assert data["synthesis"]["summary"].startswith(
        "Canonical investigation produced 0 evidence-backed"
    )


# ---------------------------------------------------------------------------
# Plan 11-11: dedicated multi-agent surface converges on the canonical service
# ---------------------------------------------------------------------------


def _canonical_multi_agent_result():
    """One canonical OrchestrationResult shared by the equivalence assertions."""
    from operations.orchestration_contract import (
        Citation,
        OrchestrationResult,
        SnapshotCoverage,
    )

    return OrchestrationResult(
        status="ok",
        policy_status="accepted",
        fallback_reason="",
        selected_specialists=["network"],
        selected_tools=["network_topology"],
        tool_results=[
            {
                "call_id": "0:0:network:network_topology",
                "specialist_id": "network",
                "tool": "network_topology",
                "arguments": {},
                "status": "ok",
                "data": {"nodes": [{"id": "vnet-a"}]},
                "evidence": [
                    {
                        "source_engine": "azure-resource-graph",
                        "source_table": "resources",
                        "timestamp": "2026-09-01T00:00:00Z",
                        "resource_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-a",
                        "confidence": "high",
                    }
                ],
                "warning": "",
            }
        ],
        uncertainty=["visible subset is incomplete"],
        coverage=SnapshotCoverage(visible_count=1, total_count=2, complete=False),
        citations=[
            Citation(
                citation_id="tool:0:0:network:network_topology:0",
                source="azure-resource-graph",
                status="ok",
                observed_at="2026-09-01T00:00:00Z",
                resource_id="/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-a",
            )
        ],
        thread_id="thr-" + "d" * 32,
        thread_revision=1,
        synthesis={
            "status": "skipped",
            "reason": "single_domain",
            "domain_count": 1,
            "claims": [],
            "warning": "",
        },
    )


def test_canonical_multi_agent_route_shares_orchestration_semantics_with_copilot(
    tmp_path, monkeypatch
):
    """T-11-35: The dedicated /agents surface and /copilot/investigate submit
    through the same canonical service, so an equivalent question yields the
    same governed policy/coverage/citation/thread semantics rather than a
    second, divergent planner."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    shared = _canonical_multi_agent_result()
    monkeypatch.setattr(
        "api.routers.multi_agent.execute_from_question",
        lambda *_args, **_kwargs: shared,
    )
    monkeypatch.setattr(
        "api.routers.copilot.execute_from_question",
        lambda *_args, **_kwargs: shared,
    )
    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    agents = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        json={"objective": "Summarize network topology", "timeout_seconds": 3},
        headers=HEADERS,
    ).json()["data"]
    copilot = client.post(
        "/api/v1/copilot/investigate?subscription=sub-a",
        json={"question": "Summarize network topology"},
        headers=HEADERS,
    ).json()["data"]

    # Both dedicated surfaces project the identical canonical result semantics.
    assert agents["contract_version"] == copilot["contract_version"] == "1"
    assert agents["orchestration"]["policy_status"] == copilot["policy_status"]
    assert agents["reconciliation"]["coverage"] == copilot["coverage"]
    assert agents["citations"] == copilot["citations"]
    assert agents["thread_id"] == copilot["thread_id"]
    # Neither surface asserts any execution authority.
    assert "mutation_authorized" not in agents
    assert copilot.get("mutation_authorized") in (None, False)


def test_canonical_multi_agent_catalog_exposes_manifest_deployment_status(
    tmp_path, monkeypatch
):
    """T-11-37: The /agents catalog is manifest-derived and every specialist
    carries an explicit deployment status, so the UI renders configured/
    unavailable from the API instead of a local, drift-prone card list."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    agents = client.get(
        "/api/v1/agents/catalog?subscription=sub-a", headers=HEADERS
    ).json()["data"]["agents"]

    assert agents, "catalog must list manifest specialists"
    for agent in agents:
        assert "foundry" in agent, "each agent must carry deployment status"
        status = agent["foundry"].get("status")
        assert status in {"ready", "unavailable"}, status
        # With no FOUNDRY_* env configured, every specialist is honestly
        # reported unavailable rather than implied to exist.
        assert agent["foundry"].get("configured") is False
        assert status == "unavailable"


def test_canonical_multi_agent_ledger_isolated_from_foreign_principal(
    tmp_path, monkeypatch
):
    """T-11-36: A canonical ledger stays principal-scoped — a second principal
    can neither read it nor record a decision against it."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    from test_api_copilot_investigation import TOKEN

    from api.rbac import Grant, Principal

    other_token = "other-token-0123456789abcdef"
    principals = {
        TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        other_token: Principal(
            subject="intruder@example.com", grants=(Grant("admin"),)
        ),
    }
    monkeypatch.setattr(
        "api.routers.multi_agent.execute_from_question",
        lambda *_args, **_kwargs: _canonical_multi_agent_result(),
    )
    context = _context(tmp_path, None, principals=principals)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    ledger_id = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        json={"objective": "Summarize network topology", "timeout_seconds": 3},
        headers=HEADERS,
    ).json()["data"]["ledger_id"]

    other_headers = {"Authorization": "Bearer " + other_token}
    assert client.get(
        f"/api/v1/agents/investigations/{ledger_id}?subscription=sub-a",
        headers=other_headers,
    ).status_code == 404
    assert client.post(
        f"/api/v1/agents/investigations/{ledger_id}/actions?subscription=sub-a",
        json={"action": "accept_finding", "payload": {}},
        headers=other_headers,
    ).status_code == 404

    # The owning principal still controls the ledger.
    assert client.get(
        f"/api/v1/agents/investigations/{ledger_id}?subscription=sub-a",
        headers=HEADERS,
    ).status_code == 200


def test_canonical_multi_agent_ledger_action_confers_no_execution_authority(
    tmp_path, monkeypatch
):
    """T-11-36: Approving the plan on the dedicated ledger records a governed
    human decision only — it is not a production mutation and grants no
    execution authority."""
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "canonical")
    monkeypatch.setattr(
        "api.routers.multi_agent.execute_from_question",
        lambda *_args, **_kwargs: _canonical_multi_agent_result(),
    )
    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    ledger_id = client.post(
        "/api/v1/agents/investigations?subscription=sub-a",
        json={"objective": "Summarize network topology", "timeout_seconds": 3},
        headers=HEADERS,
    ).json()["data"]["ledger_id"]

    updated = client.post(
        f"/api/v1/agents/investigations/{ledger_id}/actions?subscription=sub-a",
        json={
            "action": "approve_plan",
            "payload": {"approved_by": "admin@example.com", "guardrail": "governed handoff only"},
        },
        headers=HEADERS,
    ).json()["data"]

    # The decision is recorded, the ledger confers no execution, and no field
    # authorizes a mutation.
    assert any(
        decision["action"] == "approve_plan" for decision in updated["decisions"]
    )
    assert "mutation_authorized" not in updated
    assert updated["outcome"] != "executed"
