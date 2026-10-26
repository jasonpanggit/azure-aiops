from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.scope import Scope
from operations.observability_arg_reader import (
    ArgObservabilityReader,
    ObservabilityEvidenceUnavailable,
)
from operations.observability_scenarios import (
    ALERT_DELIVERY_COVERAGE,
    DIAGNOSTIC_SETTINGS_COVERAGE,
    evaluate_alert_delivery,
)
from operations.tools import STATUS_UNAVAILABLE, call_tool
from semantic.live_provider import LiveObservation

NOW = datetime(2026, 10, 26, 9, 5, tzinfo=UTC)
OBSERVED = "2026-10-26T09:00:00Z"
SCOPE = Scope.from_mapping({"subscription": ["sub-a"]})
VM1 = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
VM2 = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-2"
AG_OK = "/subscriptions/sub-a/resourceGroups/rg/providers/microsoft.insights/actionGroups/ok"
AG_OFF = "/subscriptions/sub-a/resourceGroups/rg/providers/microsoft.insights/actionGroups/off"
AG_GONE = "/subscriptions/sub-a/resourceGroups/rg/providers/microsoft.insights/actionGroups/gone"
AG_FOREIGN = (
    "/subscriptions/sub-z/resourceGroups/rg/providers/microsoft.insights/actionGroups/x"
)

CONNECTIONS = [
    SimpleNamespace(subscription_id="sub-a", connection_id="c1", is_active=True)
]


def rule(rid, type_, enabled, scopes, groups, sub="sub-a"):
    return {
        "id": rid,
        "type": type_,
        "subscriptionId": sub,
        "enabled": enabled,
        "scopes": scopes,
        "actions": groups,
    }


RULES = [
    rule(
        "r-vm1",
        "microsoft.insights/metricalerts",
        True,
        [VM1],
        [{"actionGroupId": AG_OK}],
    ),
    rule(
        "r-off",
        "microsoft.insights/metricalerts",
        False,
        [VM2],
        [{"actionGroupId": AG_OK}],
    ),
    rule(
        "r-log",
        "microsoft.insights/scheduledqueryrules",
        True,
        [
            "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/w"
        ],
        {"actionGroups": [AG_GONE]},
    ),
    rule(
        "r-none",
        "microsoft.insights/activitylogalerts",
        True,
        ["/subscriptions/sub-a"],
        {"actionGroups": []},
    ),
    rule(
        "r-x",
        "microsoft.insights/metricalerts",
        True,
        [VM1],
        [{"actionGroupId": AG_FOREIGN}, {"actionGroupId": AG_OFF}],
    ),
]
GROUPS = [
    {
        "id": AG_OK,
        "type": "microsoft.insights/actiongroups",
        "subscriptionId": "sub-a",
        "enabled": True,
    },
    {
        "id": AG_OFF,
        "type": "microsoft.insights/actiongroups",
        "subscriptionId": "sub-a",
        "enabled": False,
    },
]
INVENTORY = {
    "resources": [
        {
            "resource_id": VM1,
            "resource_type": "Microsoft.Compute/virtualMachines",
            "subscription_id": "sub-a",
        },
        {
            "resource_id": VM2,
            "resource_type": "Microsoft.Compute/virtualMachines",
            "subscription_id": "sub-a",
        },
    ],
    "total": 2,
    "observed_at": OBSERVED,
    "scope_qualification": {"status": "supported"},
}


class Live:
    def __init__(
        self,
        rules=None,
        groups=None,
        completeness="complete",
        observed=OBSERVED,
        error=None,
    ):
        self.rules = RULES if rules is None else rules
        self.groups = GROUPS if groups is None else groups
        self.completeness = completeness
        self.observed = observed
        self.error = error
        self.calls = []

    def query(self, spec, *, subscription_ids):
        self.calls.append((spec.name, list(subscription_ids)))
        if self.error:
            raise self.error
        rows = self.rules if "rules" in spec.name else self.groups
        return LiveObservation(
            rows=tuple(rows),
            observed_at=self.observed,
            status="ok"
            if self.completeness in {"complete", "healthy-empty"}
            else self.completeness,
            completeness=self.completeness,
        )


def reader(live=None, connections=None):
    return ArgObservabilityReader(
        live or Live(),
        lambda: CONNECTIONS if connections is None else connections,
        clock=lambda: NOW,
    )


def test_normalizes_rules_groups_and_evaluates_gaps_without_delivery_claim():
    live = Live()
    evidence = reader(live).read_alert_delivery(SCOPE)
    assessment = evaluate_alert_delivery(INVENTORY, evidence, scope=SCOPE)

    assert live.calls == [
        ("observability_alert_rules", ["sub-a"]),
        ("observability_action_groups", ["sub-a"]),
    ]
    kinds = {r.rule_id: r.scope_kind for r in evidence.rules}
    assert kinds == {
        "r-vm1": "direct_resource",
        "r-off": "direct_resource",
        "r-log": "log_query",
        "r-none": "other",
        "r-x": "direct_resource",
    }
    coverage = assessment["alert_coverage"]
    assert coverage["disabled_rule_count"] == 1
    assert coverage["missing_action_group_reference_count"] == 1
    # AG_GONE is absent inside the authorized scope; AG_OFF is disabled.
    assert coverage["invalid_action_group_reference_count"] == 2
    # The cross-subscription group cannot be read, so the result is not complete.
    assert coverage["unknown_action_group_reference_count"] == 1
    assert assessment["status"] == "partial"
    assert coverage["delivery_status"] == "not_proven"
    assert coverage["indirect_log_query_rule_coverage"]["rule_count"] == 1
    assert coverage["direct_resource_rule_coverage"]["direct_rule_missing_count"] == 1


def test_clean_configuration_is_still_not_delivery_proof():
    live = Live(rules=RULES[:1], groups=GROUPS[:1])
    evidence = reader(live).read_alert_delivery(SCOPE)
    assessment = evaluate_alert_delivery(INVENTORY, evidence, scope=SCOPE)
    assert assessment["alert_coverage"]["delivery_status"] == "not_proven"
    assert (
        assessment["alert_coverage"]["direct_resource_rule_coverage"][
            "direct_rule_missing_count"
        ]
        == 1
    )


def test_scope_binding_matches_effective_scope_and_foreign_scope_is_rejected():
    evidence = reader().read_alert_delivery(SCOPE)
    assert evidence.scope_binding == {"subscription": ("sub-a",)}
    other = Scope.from_mapping({"subscription": ["sub-b"]})
    with pytest.raises(PermissionError):
        evaluate_alert_delivery(INVENTORY, evidence, scope=other)


def test_rows_outside_authorized_subscriptions_fail_closed():
    foreign = rule(
        "r-f", "microsoft.insights/metricalerts", True, [VM1], [], sub="sub-z"
    )
    with pytest.raises(PermissionError):
        reader(Live(rules=[foreign])).read_alert_delivery(SCOPE)


@pytest.mark.parametrize(
    "scope",
    [
        Scope.from_mapping({"subscription": ["sub-a"], "business_service": ["bs"]}),
        Scope.from_mapping({"subscription": ["sub-unconnected"]}),
        Scope.from_mapping({}),
    ],
)
def test_unenforceable_or_unconnected_scope_is_unavailable_or_incomplete(scope):
    try:
        evidence = reader(connections=[]).read_alert_delivery(scope)
    except (ValueError, PermissionError):
        return
    assert not (evidence.rules_complete and evidence.action_groups_complete)


@pytest.mark.parametrize("completeness", ["partial", "unavailable"])
def test_truncated_or_failed_collection_is_incomplete_and_not_evaluated(completeness):
    evidence = reader(Live(completeness=completeness)).read_alert_delivery(SCOPE)
    assert evidence.rules_complete is False
    with pytest.raises(ValueError):
        evaluate_alert_delivery(INVENTORY, evidence, scope=SCOPE)


def test_stale_evidence_is_not_evaluated():
    evidence = reader(Live(observed="2026-10-26T08:00:00Z")).read_alert_delivery(SCOPE)
    assert evidence.rules_freshness == "stale"
    with pytest.raises(ValueError):
        evaluate_alert_delivery(INVENTORY, evidence, scope=SCOPE)


def test_provider_error_propagates_and_malformed_rows_are_rejected():
    with pytest.raises(RuntimeError):
        reader(Live(error=RuntimeError("bound exceeded"))).read_alert_delivery(SCOPE)
    with pytest.raises(TypeError):
        reader(Live(rules=["bad"])).read_alert_delivery(SCOPE)


@pytest.mark.parametrize("enabled", [None, "false", 0])
def test_unknown_enabled_state_is_never_a_disabled_rule_finding(enabled):
    odd = rule("r-odd", "microsoft.insights/metricalerts", enabled, [VM1], [])
    evidence = reader(Live(rules=[odd], groups=[])).read_alert_delivery(SCOPE)
    assert evidence.rules_complete is False
    with pytest.raises(ValueError):
        evaluate_alert_delivery(INVENTORY, evidence, scope=SCOPE)
    result = call_tool(
        "incidents",
        {"scenario": ALERT_DELIVERY_COVERAGE},
        context=ToolCtx(reader(Live(rules=[odd], groups=[]))),
        scope=SCOPE,
    )
    assert result.status == STATUS_UNAVAILABLE
    coverage = result.data["assessment"]["alert_coverage"]
    assert coverage["disabled_rule_count"] is None
    assert result.data["assessment"]["findings"]["status"] == "not_evaluated"


def test_unclassifiable_rule_type_makes_collection_incomplete():
    odd = rule("r-odd", "microsoft.insights/other", True, [VM1], [])
    evidence = reader(Live(rules=[odd])).read_alert_delivery(SCOPE)
    assert evidence.rules_complete is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"completeness": "partial"},
        {"observed": "2026-10-26T08:00:00Z"},
    ],
)
def test_absent_group_is_unknown_when_group_collection_incomplete_or_stale(kwargs):
    class SplitLive(Live):
        def query(self, spec, *, subscription_ids):
            observation = Live().query(spec, subscription_ids=subscription_ids)
            if "groups" not in spec.name:
                return observation
            degraded = Live(groups=[], **kwargs).query(
                spec, subscription_ids=subscription_ids
            )
            return degraded

    evidence = reader(SplitLive(rules=RULES[2:3])).read_alert_delivery(SCOPE)
    statuses = {ref.action_group_id: ref.status for ref in evidence.action_groups}
    assert statuses[AG_GONE] == "unknown"
    assert not (
        evidence.action_groups_complete and evidence.action_groups_freshness == "fresh"
    )


def test_absent_group_is_invalid_only_when_collection_complete_and_fresh():
    evidence = reader(Live(rules=RULES[2:3])).read_alert_delivery(SCOPE)
    statuses = {ref.action_group_id: ref.status for ref in evidence.action_groups}
    assert statuses[AG_GONE] == "invalid"


def test_singular_scope_property_is_normalized():
    single = rule("r-s", "microsoft.insights/metricalerts", True, None, [])
    single["scope"] = VM2
    del single["scopes"]
    evidence = reader(Live(rules=[single], groups=[])).read_alert_delivery(SCOPE)
    assert evidence.rules[0].scope_kind == "direct_resource"
    assert evidence.rules[0].resource_ids == (VM2,)
    activity = rule("r-a", "microsoft.insights/activitylogalerts", True, None, [])
    activity["scope"] = "/subscriptions/sub-a"
    evidence = reader(Live(rules=[activity], groups=[])).read_alert_delivery(SCOPE)
    assert evidence.rules[0].scope_kind == "other"


def test_diagnostic_settings_has_no_governed_source():
    with pytest.raises(ObservabilityEvidenceUnavailable):
        reader().read_diagnostic_settings(SCOPE)


class ToolCtx:
    provider_runtime = None
    generation_resolver_provider = None

    def __init__(self, port):
        self.port = port

    def resolve_provider(self, name, *, optional=False):
        return {
            "inventory_read_port": SimpleNamespace(
                list_resources=lambda scope, *, offset, limit: INVENTORY
            ),
            "observability_read_port": self.port,
        }.get(name)


def test_tool_path_returns_partial_for_alerts_and_unavailable_for_diagnostics():
    alert = call_tool(
        "incidents",
        {"scenario": ALERT_DELIVERY_COVERAGE},
        context=ToolCtx(reader()),
        scope=SCOPE,
    )
    assert alert.status == STATUS_UNAVAILABLE
    assert alert.data["assessment"]["status"] == "partial"
    assert alert.data["assessment"]["alert_coverage"]["delivery_status"] == "not_proven"

    diag = call_tool(
        "incidents",
        {"scenario": DIAGNOSTIC_SETTINGS_COVERAGE},
        context=ToolCtx(reader()),
        scope=SCOPE,
    )
    assert diag.status == STATUS_UNAVAILABLE
    assert diag.data["assessment"]["status"] == "unavailable"
