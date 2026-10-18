"""Gate G-6 coverage for bounded Operations Copilot tool results."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from api.errors import ApiError, ErrorCode
from api.scope import Scope
from operations.tools import STATUS_OK, call_tool


@dataclass(frozen=True)
class _Item:
    item_id: int

    def to_dict(self) -> dict[str, Any]:
        return {"item_id": self.item_id}


@dataclass(frozen=True)
class _CategorizedItem:
    item_id: int
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {"item_id": self.item_id, "category": self.category}


@dataclass(frozen=True)
class _AffectedFinding:
    item_id: int
    affected_resource_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "affected_resource_ids": list(self.affected_resource_ids),
        }


class _NetworkService:
    def __init__(self, *, gaps: int, findings: int) -> None:
        self.snapshot = SimpleNamespace(observed_at="2026-01-01T00:00:00Z")
        self._analysis = SimpleNamespace(
            gaps=tuple(_Item(index) for index in range(gaps)),
            rule_findings=tuple(_Item(index) for index in range(findings)),
        )
        self.scoped_with = None

    def scoped(self, scope):
        self.scoped_with = scope
        return self

    def analyze(self):
        return self._analysis


class _Context:
    provider_runtime = None
    hybrid_network_provider = None

    def __init__(self, service: _NetworkService) -> None:
        self.service = service

    def resolve_provider(self, name: str):
        return self.service if name == "network" else None


class _HubNetworkService:
    def __init__(self, vnet_id: str) -> None:
        self.snapshot = SimpleNamespace(
            observed_at="2026-09-15T00:00:00Z",
            vnets=(SimpleNamespace(resource_id=vnet_id, name="demo-vnet"),),
        )
        self.scoped_with = None
        self._vnet_id = vnet_id

    def scoped(self, scope):
        self.scoped_with = scope
        return self

    def hub_dependents(self, vnet_id: str) -> dict[str, Any]:
        assert vnet_id == self._vnet_id
        return {
            "hub_id": self._vnet_id,
            "hub_name": "demo-vnet",
            "dependent_count": 0,
            "dependents": [],
            "shared_services": [
                {"type": "azure_firewall", "name": "demo-firewall"},
                {"type": "azure_bastion", "name": "demo-bastion"},
                {
                    "type": "private_dns_zone",
                    "name": "privatelink.blob.core.windows.net",
                },
                {
                    "type": "private_dns_zone",
                    "name": "privatelink.vaultcore.azure.net",
                },
            ],
        }


def _connection(
    connection_id: str,
    subscription_id: str,
    *,
    active: bool = True,
):
    return SimpleNamespace(
        connection_id=connection_id,
        subscription_id=subscription_id,
        is_active=active,
    )


def _hybrid_context(
    connections,
    hybrid_network_provider,
    *,
    managed_calls: list[str] | None = None,
):
    managed_calls = managed_calls if managed_calls is not None else []

    def resolve_provider(name: str):
        managed_calls.append(name)
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "The network provider is deferred",
        )

    return SimpleNamespace(
        provider_runtime=None,
        generation_resolver_provider=None,
        onboarding=SimpleNamespace(
            registry=SimpleNamespace(
                list=lambda *, include_disabled=False: [
                    connection
                    for connection in connections
                    if include_disabled or connection.is_active
                ]
            )
        ),
        hybrid_network_provider=hybrid_network_provider,
        resolve_provider=resolve_provider,
    )


def _run(*, gaps: int, findings: int):
    service = _NetworkService(gaps=gaps, findings=findings)
    result = call_tool(
        "firewall_nsg_gaps",
        {},
        context=_Context(service),
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
    )
    return service, result


def test_firewall_tool_can_select_only_inspection_bypass_findings() -> None:
    service = _NetworkService(gaps=0, findings=0)
    service._analysis = SimpleNamespace(
        gaps=(
            _CategorizedItem(1, "firewall_bypass"),
            _CategorizedItem(2, "missing_private_endpoint"),
        ),
        rule_findings=(
            _CategorizedItem(3, "sensitive_port_exposure"),
        ),
    )

    result = call_tool(
        "firewall_nsg_gaps",
        {"category": "firewall_bypass"},
        context=_Context(service),
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
    )

    assert result.status == STATUS_OK
    assert result.data == {
        "gaps": [{"item_id": 1, "category": "firewall_bypass"}],
        "rule_findings": [],
        "filter": {"category": "firewall_bypass"},
    }


def test_unrestricted_network_tool_uses_active_onboarded_subscriptions() -> None:
    subscription_id = "a87a8e64-a52a-4aa8-a760-5e8919d23cd1"
    vnet_id = (
        f"/subscriptions/{subscription_id}/resourcegroups/demo-rg/providers/"
        "microsoft.network/virtualnetworks/demo-vnet"
    )
    service = _HubNetworkService(vnet_id)
    hybrid_calls: list[list[str]] = []
    managed_calls: list[str] = []
    context = _hybrid_context(
        [
            _connection("demo", subscription_id),
            _connection(
                "disabled",
                "b1111111-1111-1111-1111-111111111111",
                active=False,
            ),
        ],
        lambda subscription_ids: hybrid_calls.append(subscription_ids) or service,
        managed_calls=managed_calls,
    )

    result = call_tool(
        "hub_dependents",
        {"vnet_id": vnet_id},
        context=context,
        scope=Scope.unrestricted(),
    )

    assert result.status == STATUS_OK
    assert hybrid_calls == [[subscription_id]]
    assert managed_calls == []
    assert result.data["hub_id"] == vnet_id
    assert result.data["dependent_count"] == 0
    assert [item["type"] for item in result.data["shared_services"]] == [
        "azure_firewall",
        "azure_bastion",
        "private_dns_zone",
        "private_dns_zone",
    ]
    assert result.evidence[0].resource_id == vnet_id
    assert service.scoped_with.subscription_ids == (subscription_id,)


def test_network_tool_explicit_subscription_scope_remains_exact() -> None:
    requested_subscription = "a87a8e64-a52a-4aa8-a760-5e8919d23cd1"
    vnet_id = (
        f"/subscriptions/{requested_subscription}/resourcegroups/demo-rg/providers/"
        "microsoft.network/virtualnetworks/demo-vnet"
    )
    hybrid_calls: list[list[str]] = []
    context = _hybrid_context(
        [_connection("other", "b1111111-1111-1111-1111-111111111111")],
        lambda subscription_ids: (
            hybrid_calls.append(subscription_ids) or _HubNetworkService(vnet_id)
        ),
    )

    result = call_tool(
        "hub_dependents",
        {"vnet_id": vnet_id},
        context=context,
        scope=Scope.from_mapping({"subscription": [requested_subscription]}),
    )

    assert result.status == STATUS_OK
    assert hybrid_calls == [[requested_subscription]]


def test_network_tool_explicit_connection_scope_filters_exact_subscription() -> None:
    selected_subscription = "a87a8e64-a52a-4aa8-a760-5e8919d23cd1"
    other_subscription = "b1111111-1111-1111-1111-111111111111"
    vnet_id = (
        f"/subscriptions/{selected_subscription}/resourcegroups/demo-rg/providers/"
        "microsoft.network/virtualnetworks/demo-vnet"
    )
    service = _HubNetworkService(vnet_id)
    hybrid_calls: list[list[str]] = []
    context = _hybrid_context(
        [
            _connection("demo", selected_subscription),
            _connection("other", other_subscription),
        ],
        lambda subscription_ids: hybrid_calls.append(subscription_ids) or service,
    )

    result = call_tool(
        "hub_dependents",
        {"vnet_id": vnet_id},
        context=context,
        scope=Scope.from_mapping({"subscription_connection": ["demo"]}),
    )

    assert result.status == STATUS_OK
    assert hybrid_calls == [[selected_subscription]]
    assert other_subscription not in str(hybrid_calls)
    assert service.scoped_with.connection_ids == ("demo",)
    assert service.scoped_with.subscription_ids == (selected_subscription,)


@pytest.mark.parametrize(
    ("scope", "connections"),
    [
        (
            Scope.unrestricted(),
            [
                _connection(
                    "disabled",
                    "b1111111-1111-1111-1111-111111111111",
                    active=False,
                )
            ],
        ),
        (
            Scope.from_mapping({"subscription_connection": ["missing"]}),
            [
                _connection(
                    "other",
                    "b1111111-1111-1111-1111-111111111111",
                )
            ],
        ),
        (
            Scope.from_mapping(
                {
                    "subscription": ["a87a8e64-a52a-4aa8-a760-5e8919d23cd1"],
                    "subscription_connection": ["other"],
                }
            ),
            [
                _connection(
                    "other",
                    "b1111111-1111-1111-1111-111111111111",
                )
            ],
        ),
        (Scope.unrestricted(), []),
    ],
    ids=[
        "disabled-only",
        "connection-out-of-scope",
        "disjoint-subscription-and-connection",
        "no-connections",
    ],
)
def test_network_tool_does_not_widen_when_no_active_connection_matches(
    scope: Scope,
    connections,
) -> None:
    hybrid_calls: list[list[str]] = []
    managed_calls: list[str] = []
    context = _hybrid_context(
        connections,
        lambda subscription_ids: hybrid_calls.append(subscription_ids),
        managed_calls=managed_calls,
    )

    result = call_tool(
        "hub_dependents",
        {"vnet_id": "/subscriptions/a/resourcegroups/rg/providers/network/vnets/vnet"},
        context=context,
        scope=scope,
    )

    assert result.status == "unavailable"
    assert "no active subscription connection matches" in result.warning.casefold()
    assert hybrid_calls == []
    assert managed_calls == []


def test_network_tool_without_hybrid_provider_does_not_read_registry() -> None:
    service = _NetworkService(gaps=1, findings=0)

    def fail_if_listed(*, include_disabled: bool = False):
        del include_disabled
        raise AssertionError("registry must not be read without a hybrid provider")

    context = SimpleNamespace(
        provider_runtime=None,
        generation_resolver_provider=None,
        onboarding=SimpleNamespace(registry=SimpleNamespace(list=fail_if_listed)),
        hybrid_network_provider=None,
        resolve_provider=lambda name: service if name == "network" else None,
    )

    result = call_tool(
        "firewall_nsg_gaps",
        {},
        context=context,
        scope=Scope.unrestricted(),
    )

    assert result.status == STATUS_OK


def test_network_registry_failure_returns_unavailable_without_io() -> None:
    hybrid_calls: list[list[str]] = []
    managed_calls: list[str] = []

    def fail_if_listed(*, include_disabled: bool = False):
        assert include_disabled is False
        raise OSError("registry unavailable")

    context = SimpleNamespace(
        provider_runtime=None,
        generation_resolver_provider=None,
        onboarding=SimpleNamespace(registry=SimpleNamespace(list=fail_if_listed)),
        hybrid_network_provider=lambda subscription_ids: hybrid_calls.append(
            subscription_ids
        ),
        resolve_provider=lambda name: managed_calls.append(name),
    )

    result = call_tool(
        "hub_dependents",
        {
            "vnet_id": "/subscriptions/sub-a/resourcegroups/rg/providers/network/vnets/vnet"
        },
        context=context,
        scope=Scope.unrestricted(),
    )

    assert result.status == "unavailable"
    assert result.warning == "Network subscription connections are unavailable"
    assert hybrid_calls == []
    assert managed_calls == []


@pytest.fixture(
    params=[
        ("incidents", "hybrid_incident_provider"),
        ("remediation_plans", "hybrid_remediation_provider"),
    ]
)
def live_operations_tool(request):
    return request.param


def _operations_hybrid_context(tool, connections, rows):
    tool_name, provider_name = tool
    calls: list[list[str]] = []
    managed_calls: list[str] = []
    context = _hybrid_context(connections, None, managed_calls=managed_calls)
    provider = (
        SimpleNamespace(report=lambda: {"incidents": rows})
        if tool_name == "incidents"
        else SimpleNamespace(generate_plans=lambda: {"plans": rows})
    )
    setattr(
        context,
        provider_name,
        lambda subscriptions: calls.append(subscriptions) or provider,
    )
    return context, calls, managed_calls


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        ({}, ["sub-a", "sub-b"]),
        ({"subscription_connection": ["b"]}, ["sub-b"]),
        ({"subscription": ["sub-a"]}, ["sub-a"]),
        ({"subscription": ["sub-a", "sub-b"], "subscription_connection": ["b"]}, ["sub-b"]),
    ],
)
def test_live_operations_tool_resolves_active_connections(
    live_operations_tool, selection, expected
) -> None:
    rows = [
        {"id": "visible", "subscription_id": "sub-b", "subscription_connection": "b"},
    ]
    context, calls, managed_calls = _operations_hybrid_context(
        live_operations_tool,
        [
            _connection("a", "sub-a"),
            _connection("b", "sub-b"),
            _connection("disabled", "sub-hidden", active=False),
        ],
        rows,
    )

    result = call_tool(
        live_operations_tool[0], {}, context=context, scope=Scope.from_mapping(selection)
    )

    assert calls == [expected]
    assert managed_calls == []
    assert result.status == ("empty" if selection == {"subscription": ["sub-a"]} else "ok")
    if result.status == "ok":
        assert result.data == rows
        assert result.evidence


@pytest.mark.parametrize(
    "selection",
    [
        {},
        {"subscription_connection": ["missing"]},
        {"subscription": ["sub-a"], "subscription_connection": ["b"]},
    ],
)
def test_live_operations_tool_never_falls_back_after_unmatched_selection(
    live_operations_tool, selection
) -> None:
    context, calls, managed_calls = _operations_hybrid_context(
        live_operations_tool,
        [_connection("b", "sub-b", active=bool(selection))],
        [{"id": "must-not-be-read"}],
    )

    result = call_tool(
        live_operations_tool[0], {}, context=context, scope=Scope.from_mapping(selection)
    )

    assert result.status == "unavailable"
    assert "no active subscription connection matches" in result.warning
    assert not result.evidence
    assert calls == managed_calls == []


def test_live_operations_tool_retains_every_scope_dimension(live_operations_tool) -> None:
    selection = {
        "subscription": ["sub-b"],
        "subscription_connection": ["b"],
        "business_service": ["payments"],
        "application": ["checkout"],
        "environment": ["production"],
        "owner": ["team-a"],
        "support_team": ["sre"],
        "region": ["australiaeast"],
        "criticality": ["critical"],
    }
    visible = {"id": "visible", **{key: value[0] for key, value in selection.items()}}
    rows = [visible]
    for key in selection:
        rows.append({**visible, "id": f"hidden-{key}", key: "outside"})
    context, calls, managed_calls = _operations_hybrid_context(
        live_operations_tool, [_connection("b", "sub-b")], rows
    )

    result = call_tool(
        live_operations_tool[0], {}, context=context, scope=Scope.from_mapping(selection)
    )

    assert result.status == "ok"
    assert result.data == [visible]
    assert calls == [["sub-b"]]
    assert managed_calls == []


@pytest.mark.parametrize(
    ("stage", "failure"),
    [
        ("registry", OSError),
        ("registry", RuntimeError),
        ("registry", ValueError),
        ("registry", TypeError),
        ("factory", OSError),
        ("factory", LookupError),
        ("factory", RuntimeError),
        ("factory", ValueError),
        ("factory", TypeError),
        ("read", OSError),
        ("read", RuntimeError),
        ("read", TypeError),
        ("registry", ApiError),
        ("factory", ApiError),
        ("read", ApiError),
    ],
)
def test_live_operations_tool_source_failure_is_not_empty(
    live_operations_tool, stage, failure
) -> None:
    context, calls, managed_calls = _operations_hybrid_context(
        live_operations_tool, [_connection("b", "sub-b")], []
    )

    def fail(*args, **kwargs):
        if failure is ApiError:
            raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "private source failure")
        raise failure("private source failure")

    if stage == "registry":
        context.onboarding.registry.list = fail
    elif stage == "factory":
        setattr(context, live_operations_tool[1], fail)
    else:
        service = SimpleNamespace(report=fail, generate_plans=fail)
        setattr(context, live_operations_tool[1], lambda subscriptions: service)

    result = call_tool(
        live_operations_tool[0], {}, context=context, scope=Scope.unrestricted()
    )

    assert result.status == "unavailable"
    assert not result.evidence
    assert "private source failure" not in result.warning
    assert managed_calls == []
    assert calls == []


def test_live_operations_tool_without_adapter_does_not_acquire_connections(
    live_operations_tool,
) -> None:
    context, calls, managed_calls = _operations_hybrid_context(
        live_operations_tool, [], []
    )
    setattr(context, live_operations_tool[1], None)

    def fail_if_listed(**kwargs):
        raise AssertionError("a missing adapter must not query the connection registry")

    context.onboarding.registry.list = fail_if_listed
    result = call_tool(
        live_operations_tool[0], {}, context=context, scope=Scope.unrestricted()
    )

    assert result.status == "unavailable"
    assert calls == []
    assert managed_calls == [
        "incidents" if live_operations_tool[0] == "incidents" else "remediation"
    ]


def test_live_operations_tool_metadata_only_selection_does_not_acquire_connections(
    live_operations_tool,
) -> None:
    context, calls, managed_calls = _operations_hybrid_context(
        live_operations_tool, [], []
    )

    def fail_if_listed(**kwargs):
        raise AssertionError("metadata-only scope must not acquire live connections")

    context.onboarding.registry.list = fail_if_listed
    result = call_tool(
        live_operations_tool[0],
        {},
        context=context,
        scope=Scope.from_mapping({"business_service": ["payments"]}),
    )

    assert result.status == "unavailable"
    assert calls == []
    assert managed_calls == ["incidents" if live_operations_tool[0] == "incidents" else "remediation"]


def test_g6_discloses_the_bound_and_true_totals_when_agent_lists_truncate() -> None:
    service, result = _run(gaps=30, findings=40)

    assert result.status == STATUS_OK
    assert len(result.data["gaps"]) == 25
    assert len(result.data["rule_findings"]) == 25
    assert "bound 25" in result.warning
    assert "30" in result.warning
    assert "40" in result.warning
    assert service.scoped_with.subscription_ids == ("sub-a",)


def test_cve_detail_prefers_live_durable_external_catalog() -> None:
    requested: list[str] = []

    class QueryService:
        def authorization_for(self, principal, scope):
            assert principal.subject == "operator@example.com"
            assert scope.values("subscription") == frozenset({"sub-a"})
            return "authorized"

        def catalog_item(self, authorization, *, generation_id, weakness_id):
            assert authorization == "authorized"
            assert generation_id == "generation-1"
            requested.append(weakness_id)
            return {
                "contract_version": "1.0.0",
                "catalog_scope": "external_public_metadata",
                "environment_membership_included": False,
                "generation": "generation-1",
                "item": {
                    "cve_id": weakness_id,
                    "sources": {
                        "nvd": {
                            "status": "succeeded",
                            "payload": {"description": "Live NVD detail"},
                        },
                        "epss": {
                            "status": "succeeded",
                            "payload": {"epss_score": 0.42},
                        },
                        "kev": {
                            "status": "succeeded",
                            "payload": None,
                        },
                    },
                },
            }

        def list_page(self, authorization, *, generation_id, query):
            assert authorization == "authorized"
            assert generation_id == "generation-1"
            filters = {item.field: item.value for item in query.filters}
            assert filters["weakness_id"] == "CVE-2026-59873"
            active_only = filters.get("active") is True
            items = (
                {
                    "weakness_id": "CVE-2026-59873",
                    "severity": "Critical",
                    "target_kind": "container_image",
                    "current_state": "active",
                    "represented_workload_count": 0,
                },
            )
            return SimpleNamespace(
                total_count=32,
                items=items[:1] if active_only else items,
                next_cursor=None,
                generation="generation-1",
                applied_scope={"subscription": ["sub-a"]},
                applied_filters=tuple(
                    {"field": item.field, "operator": item.operator, "value": item.value}
                    for item in query.filters
                ),
                applied_sort={"field": "priority_score", "direction": "desc"},
                facets={},
                completeness={"state": "complete"},
                freshness={"state": "fresh", "as_of": "2026-09-14T00:00:00Z"},
            )

        def readable_generation_id(self):
            return "generation-1"

    context = SimpleNamespace(
        provider_runtime=None,
        generation_resolver_provider=None,
        exposure_query_provider=lambda: QueryService(),
        resolve_provider=lambda _name: pytest.fail(
            "legacy vulnerability provider must not run"
        ),
    )

    result = call_tool(
        "cve_detail",
        {"cve_id": "CVE-2026-59873"},
        context=context,
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
        principal=SimpleNamespace(subject="operator@example.com"),
    )

    assert result.status == STATUS_OK
    assert requested == ["CVE-2026-59873"]
    assert result.data["item"]["sources"]["nvd"]["payload"]["description"] == (
        "Live NVD detail"
    )
    assert result.data["cve_id"] == "CVE-2026-59873"
    assert result.data["scoped_exposure"]["total_count"] == 32
    assert result.data["scoped_exposure"]["affected_active_count"] == 32
    assert result.data["source_state"]["external_catalog"]["status"] == "ok"
    assert result.data["source_state"]["scoped_exposure"]["status"] == "ok"


def test_cve_exposure_read_port_filters_exact_cve_and_active_rows() -> None:
    class ReadPort:
        def list_exposures(self, scope, *, offset, limit, business_service):
            assert scope.values("subscription") == frozenset({"sub-a"})
            assert (offset, limit, business_service) == (0, 25, None)
            return {
                "findings": [
                    {
                        "exposure_id": "wanted-active",
                        "weakness_id": "CVE-2026-13221",
                        "current_state": "active",
                        "severity": "Critical",
                    },
                    {
                        "exposure_id": "wanted-inactive",
                        "weakness_id": "CVE-2026-13221",
                        "current_state": "resolved",
                        "severity": "Critical",
                    },
                    {
                        "exposure_id": "other-cve",
                        "weakness_id": "CVE-2026-99999",
                        "current_state": "active",
                        "severity": "Critical",
                    },
                ],
                "returned_count": 3,
                "total_count": 300,
                "read_model_generation_id": "generation-1",
                "completeness": {
                    "state": "complete",
                    "represented_count": 3,
                    "total_count": 3,
                    "excluded_count": 0,
                },
                "freshness_state": "fresh",
                "freshness_as_of": "2026-09-14T00:00:00Z",
            }

    context = SimpleNamespace(
        provider_runtime=None,
        generation_resolver_provider=None,
        exposure_query_provider=None,
        exposure_read_port_provider=lambda: ReadPort(),
        resolve_provider=lambda _name: None,
    )
    result = call_tool(
        "cve_exposure",
        {
            "query": "CVE-2026-13221",
            "active": True,
            "generation": "generation-1",
        },
        context=context,
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
    )

    assert result.status == STATUS_OK
    assert result.data["returned_count"] == result.data["total_count"] == 1
    assert [row["exposure_id"] for row in result.data["findings"]] == [
        "wanted-active"
    ]
    assert "other-cve" not in str(result.data)


def test_cve_detail_rejects_mixed_generation_results() -> None:
    class QueryService:
        def authorization_for(self, principal, scope):
            return "authorized"

        def readable_generation_id(self):
            return "generation-1"

        def list_page(self, authorization, *, generation_id, query):
            return SimpleNamespace(
                total_count=1,
                items=(
                    {
                        "weakness_id": "CVE-2026-13221",
                        "current_state": "active",
                    },
                ),
                next_cursor=None,
                generation="generation-2",
                applied_scope={"subscription": ["sub-a"]},
                applied_filters=(),
                applied_sort={"field": "priority_score", "direction": "desc"},
                facets={},
                completeness={"state": "complete"},
                freshness={"state": "fresh"},
            )

        def catalog_item(self, authorization, *, generation_id, weakness_id):
            return {
                "generation": "generation-1",
                "item": {"cve_id": weakness_id, "sources": {}},
            }

    context = SimpleNamespace(
        provider_runtime=None,
        generation_resolver_provider=None,
        exposure_query_provider=lambda: QueryService(),
        resolve_provider=lambda _name: None,
    )
    result = call_tool(
        "cve_detail",
        {"cve_id": "CVE-2026-13221"},
        context=context,
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
        principal=SimpleNamespace(subject="operator@example.com"),
    )

    assert result.status == "unavailable"
    assert "generation changed" in result.warning


def test_g6_stays_silent_when_agent_lists_are_complete() -> None:
    _, result = _run(gaps=2, findings=3)

    assert result.status == STATUS_OK
    assert result.warning == ""


def test_nested_finding_ids_are_bounded_to_the_disclosed_count() -> None:
    service = _NetworkService(gaps=0, findings=0)
    service._analysis = SimpleNamespace(
        gaps=(),
        rule_findings=(
            _AffectedFinding(
                1,
                tuple(f"resource-{index}" for index in range(300)),
            ),
            _AffectedFinding(
                2,
                tuple(f"other-resource-{index}" for index in range(40)),
            ),
        ),
    )

    result = call_tool(
        "firewall_nsg_gaps",
        {},
        context=_Context(service),
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
    )

    first_ids = result.data["rule_findings"][0]["affected_resource_ids"]
    second_ids = result.data["rule_findings"][1]["affected_resource_ids"]
    assert len(first_ids) == 25
    assert len(second_ids) == 25
    assert result.warning == (
        "Agent result bound 25: "
        f"rule_findings.affected_resource_ids showing {len(first_ids)} of 300."
    )
