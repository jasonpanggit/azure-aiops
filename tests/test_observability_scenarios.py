"""Bounded Resource Health observability scenarios and supplied-evidence evaluators."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.scope import Scope
from operations.mcp_server import MCPServer, validate_tool_arguments
from operations.observability_scenarios import (
    ALERT_DELIVERY_COVERAGE,
    DIAGNOSTIC_SETTINGS_COVERAGE,
    OBSERVABILITY_SCENARIO_CONTRACT,
    ActionGroupReference,
    AlertDeliveryEvidence,
    AlertRule,
    DiagnosticSetting,
    DiagnosticSettingsEvidence,
    PolicyException,
    evaluate_alert_delivery,
    evaluate_diagnostic_settings,
    unavailable_assessment,
    validate_parameters,
)
from operations.specialist_manifest import load_specialist_manifest
from operations.tools import STATUS_DENIED, STATUS_UNAVAILABLE, call_tool

ROOT = Path(__file__).parent
FIXTURE = json.loads((ROOT / "fixtures" / "observability_scenarios.json").read_text())
SCOPE = Scope.from_mapping({"subscription": ["sub-a"]})
OBSERVED_AT = "2026-10-26T09:00:00Z"


class InventoryPort:
    def __init__(self, result=None, error=None):
        self.result = FIXTURE["inventory"] if result is None else result
        self.error = error
        self.calls = []

    def list_resources(self, scope, *, offset, limit):
        self.calls.append((scope, offset, limit))
        if self.error:
            raise self.error
        return self.result


class ToolContext:
    provider_runtime = None
    generation_resolver_provider = None

    def __init__(self, port, observability_port=None):
        self.port = port
        self.observability_port = observability_port

    def resolve_provider(self, name, *, optional=False):
        return {
            "inventory_read_port": self.port,
            "observability_read_port": self.observability_port,
        }.get(name)


class ObservabilityPort:
    def __init__(self, diagnostic=None, alert=None, error=None):
        self.diagnostic = diagnostic
        self.alert = alert
        self.error = error
        self.calls = []

    def read_diagnostic_settings(self, scope):
        self.calls.append(("diagnostic", scope))
        if self.error:
            raise self.error
        return self.diagnostic

    def read_alert_delivery(self, scope):
        self.calls.append(("alert", scope))
        if self.error:
            raise self.error
        return self.alert


def diagnostic_evidence(payload=None):
    payload = payload or FIXTURE["evaluated_diagnostic"]
    return DiagnosticSettingsEvidence(
        scope_binding=payload["scope_binding"],
        supported_resource_types=tuple(payload["supported_resource_types"]),
        policy_version=payload["policy_version"],
        policy_observed_at=OBSERVED_AT,
        policy_freshness="fresh",
        policy_complete=True,
        required_categories={
            key: tuple(values) for key, values in payload["required_categories"].items()
        },
        required_destinations={
            key: tuple(values)
            for key, values in payload["required_destinations"].items()
        },
        exceptions=tuple(
            PolicyException(
                resource_id=item["resource_id"],
                categories=tuple(item["categories"]),
                destinations=tuple(item["destinations"]),
                expires_at=item["expires_at"],
            )
            for item in payload["exceptions"]
        ),
        settings_observed_at=OBSERVED_AT,
        settings_freshness="fresh",
        settings_complete=True,
        settings=tuple(
            DiagnosticSetting(
                resource_id=item["resource_id"],
                categories=tuple(item["categories"]),
                destinations=tuple(item["destinations"]),
            )
            for item in payload["settings"]
        ),
    )


def alert_evidence(payload=None):
    payload = payload or FIXTURE["evaluated_alert"]
    return AlertDeliveryEvidence(
        scope_binding=payload["scope_binding"],
        supported_resource_types=tuple(payload["supported_resource_types"]),
        rules_observed_at=OBSERVED_AT,
        rules_freshness="fresh",
        rules_complete=True,
        action_groups_observed_at=OBSERVED_AT,
        action_groups_freshness="fresh",
        action_groups_complete=True,
        rules=tuple(
            AlertRule(
                rule_id=item["rule_id"],
                enabled=item["enabled"],
                scope_kind=item["scope_kind"],
                resource_ids=tuple(item["resource_ids"]),
                action_group_ids=tuple(item["action_group_ids"]),
            )
            for item in payload["rules"]
        ),
        action_groups=tuple(
            ActionGroupReference(
                action_group_id=item["action_group_id"],
                status=item["status"],
            )
            for item in payload["action_groups"]
        ),
    )


def run_scenario(scenario, port=None, observability_port=None):
    return call_tool(
        "incidents",
        {"scenario": scenario},
        context=ToolContext(port, observability_port),
        scope=SCOPE,
    )


@pytest.mark.parametrize(
    "scenario,evidence_key",
    [
        (DIAGNOSTIC_SETTINGS_COVERAGE, "diagnostic_settings"),
        (ALERT_DELIVERY_COVERAGE, "azure_monitor_alert_rules"),
    ],
)
def test_scenarios_return_inventory_cited_unavailable_fixture(scenario, evidence_key):
    port = InventoryPort()
    result = run_scenario(scenario, port)
    assessment = result.data["assessment"]
    expected = FIXTURE["expected"]

    assert result.status == STATUS_UNAVAILABLE
    assert assessment["scenario_id"] == scenario
    assert assessment["status"] == expected["status"]
    assert assessment["inventory"]["status"] == expected["inventory_status"]
    assert (
        assessment["inventory"]["observed_resource_count"]
        == expected["observed_inventory_count"]
    )
    assert (
        assessment["resource_denominator"]["authorized_scope_inventory_count"]
        == expected["authorized_scope_inventory_count"]
    )
    assert assessment["inventory"]["complete"] is expected["inventory_complete"]
    assert assessment["inventory"]["freshness"] == expected["inventory_freshness"]
    assert (
        assessment["resource_denominator"]["supported_resource_types"]
        == expected["supported_resource_types"]
    )
    assert (
        assessment["resource_denominator"]["type_support_status"]
        == expected["type_support_status"]
    )
    assert (
        assessment["resource_denominator"]["unsupported_resource_count"]
        == expected["unsupported_resource_count"]
    )
    assert (
        assessment["resource_denominator"]["unreadable_observed_resource_count"]
        == expected["unreadable_observed_resource_count"]
    )
    assert (
        assessment["resource_denominator"]["unknown_observed_resource_count"]
        == expected["unknown_observed_resource_count"]
    )
    assert assessment["policy"]["status"] == expected["policy_status"]
    assert assessment["policy"]["exception_count"] == expected["policy_exception_count"]
    assert (
        assessment["policy"]["required_log_categories"]
        == expected["required_log_categories"]
    )
    assert (
        assessment["policy"]["required_destinations"]
        == expected["required_destinations"]
    )
    assert (
        assessment["configuration_evidence"][evidence_key]["status"]
        == expected[
            "diagnostic_settings_status"
            if scenario == DIAGNOSTIC_SETTINGS_COVERAGE
            else "alert_rule_status"
        ]
    )
    assert assessment["findings"]["status"] == expected["findings_status"]
    assert assessment["findings"]["count"] is expected["finding_count"]
    if scenario == DIAGNOSTIC_SETTINGS_COVERAGE:
        assert assessment["alert_coverage"] is None
    else:
        assert (
            assessment["alert_coverage"]["disabled_rule_count"]
            == expected["disabled_rule_count"]
        )
        assert (
            assessment["alert_coverage"]["missing_action_group_reference_count"]
            == expected["missing_action_group_reference_count"]
        )
        assert (
            assessment["alert_coverage"]["invalid_action_group_reference_count"]
            == expected["invalid_action_group_reference_count"]
        )
        assert (
            assessment["alert_coverage"]["direct_resource_rule_coverage"]
            == expected["direct_resource_rule_coverage"]
        )
        assert (
            assessment["alert_coverage"]["indirect_log_query_rule_coverage"]
            == expected["indirect_log_query_rule_coverage"]
        )
        assert (
            assessment["alert_coverage"]["delivery_status"]
            == expected["delivery_status"]
        )
    assert (
        result.evidence[0].source_engine == "intelligence.inventory.InventoryReadPort"
    )
    assert result.evidence[0].timestamp == OBSERVED_AT
    assert port.calls == [(SCOPE, 0, None)]
    serialized = json.dumps(result.to_dict())
    for resource_id in (
        row["resource_id"] for row in FIXTURE["inventory"]["resources"]
    ):
        assert resource_id not in serialized
    assert "healthy" not in serialized.casefold()


def test_inventory_pagination_mismatch_and_unqualified_scope_stay_unknown():
    partial = {
        **FIXTURE["inventory"],
        "resources": FIXTURE["inventory"]["resources"][:2],
        "total": 8,
    }
    assessment = unavailable_assessment(
        DIAGNOSTIC_SETTINGS_COVERAGE,
        inventory=partial,
    )
    assert assessment["status"] == "unavailable"
    assert assessment["inventory"]["status"] == "partial"
    assert assessment["inventory"]["observed_resource_count"] == 2
    assert (
        assessment["resource_denominator"]["authorized_scope_inventory_count"] is None
    )
    assert (
        assessment["resource_denominator"]["unreadable_observed_resource_count"] is None
    )
    assert assessment["resource_denominator"]["unknown_observed_resource_count"] == 2

    unqualified = {
        **FIXTURE["inventory"],
        "scope_qualification": {
            "status": "unsupported",
            "unsupported_dimensions": ["subscription_connection"],
        },
    }
    assessment = unavailable_assessment(
        ALERT_DELIVERY_COVERAGE,
        inventory=unqualified,
    )
    assert assessment["inventory"]["status"] == "partial"
    assert (
        assessment["resource_denominator"]["authorized_scope_inventory_count"] is None
    )
    assert (
        assessment["alert_coverage"]["indirect_log_query_rule_coverage"]
        == "not_assessed"
    )


def test_diagnostic_settings_evaluator_checks_categories_destinations_and_exceptions():
    evidence = diagnostic_evidence()
    assessment = evaluate_diagnostic_settings(
        FIXTURE["inventory"],
        evidence,
        scope=SCOPE,
    )
    expected = FIXTURE["evaluated_diagnostic"]["expected"]

    assert assessment["status"] == expected["status"]
    assert assessment["findings"]["status"] == expected["finding_status"]
    assert assessment["resource_denominator"]["supported_resource_types"] == sorted(
        value.casefold() for value in evidence.supported_resource_types
    )
    assert (
        assessment["resource_denominator"]["excluded_resource_count"]
        == expected["excluded_resource_count"]
    )
    assert assessment["resource_denominator"]["complete"] is False
    assert (
        assessment["policy"]["active_exception_count"]
        == expected["active_exception_count"]
    )
    assert (
        assessment["policy"]["expired_exception_count"]
        == expected["expired_exception_count"]
    )
    assert (
        assessment["diagnostic_settings_coverage"]["missing_category_count"]
        == expected["missing_category_count"]
    )
    assert (
        assessment["diagnostic_settings_coverage"]["missing_destination_count"]
        == expected["missing_destination_count"]
    )
    assert assessment["diagnostic_settings_coverage"]["outcome"] == expected["outcome"]
    assert (
        assessment["configuration_evidence"]["workload_logging_policy"]["observed_at"]
        == OBSERVED_AT
    )
    assert all(
        row["resource_id"] not in json.dumps(assessment)
        for row in FIXTURE["inventory"]["resources"]
    )

    without_exception = replace(evidence, exceptions=())
    negative = evaluate_diagnostic_settings(
        FIXTURE["inventory"],
        without_exception,
        scope=SCOPE,
    )
    assert negative["diagnostic_settings_coverage"]["missing_category_count"] == 3
    assert negative["diagnostic_settings_coverage"]["missing_destination_count"] == 3

    vm2 = FIXTURE["inventory"]["resources"][2]["resource_id"]
    complete_settings = replace(
        evidence,
        settings=(
            *evidence.settings,
            DiagnosticSetting(
                resource_id=FIXTURE["inventory"]["resources"][0]["resource_id"],
                categories=("Metrics",),
                destinations=("storage-archive",),
            ),
            DiagnosticSetting(
                resource_id=vm2,
                categories=("Audit", "Metrics"),
                destinations=("law-main", "storage-archive"),
            ),
        ),
    )
    no_gap_result = evaluate_diagnostic_settings(
        FIXTURE["inventory"],
        complete_settings,
        scope=SCOPE,
    )
    assert no_gap_result["diagnostic_settings_coverage"]["missing_category_count"] == 0
    assert (
        no_gap_result["diagnostic_settings_coverage"]["missing_destination_count"] == 0
    )
    assert no_gap_result["diagnostic_settings_coverage"]["outcome"] == "incomplete"
    assert no_gap_result["status"] == "partial"


def test_alert_evaluator_counts_disabled_and_bad_references_without_delivery_claims():
    evidence = alert_evidence()
    assessment = evaluate_alert_delivery(
        FIXTURE["inventory"],
        evidence,
        scope=SCOPE,
    )
    expected = FIXTURE["evaluated_alert"]["expected"]
    coverage = assessment["alert_coverage"]

    assert assessment["status"] == expected["status"]
    assert assessment["findings"]["status"] == expected["finding_status"]
    assert coverage["enabled_rule_count"] == expected["enabled_rule_count"]
    assert coverage["disabled_rule_count"] == expected["disabled_rule_count"]
    assert (
        coverage["missing_action_group_reference_count"]
        == expected["missing_action_group_reference_count"]
    )
    assert (
        coverage["invalid_action_group_reference_count"]
        == expected["invalid_action_group_reference_count"]
    )
    assert (
        coverage["direct_resource_rule_coverage"]["covered_resource_count"]
        == expected["direct_covered_resource_count"]
    )
    assert (
        coverage["direct_resource_rule_coverage"]["direct_rule_missing_count"]
        == expected["direct_missing_resource_count"]
    )
    assert (
        coverage["indirect_log_query_rule_coverage"]["rule_count"]
        == expected["indirect_log_query_rule_count"]
    )
    assert (
        coverage["indirect_log_query_rule_coverage"]["status"]
        == expected["indirect_status"]
    )
    assert coverage["delivery_status"] == expected["delivery_status"]
    assert "broader log-query coverage" in " ".join(assessment["limitations"])

    clean_alert = replace(
        evidence,
        rules=(
            AlertRule(
                rule_id="all-resources",
                enabled=True,
                scope_kind="direct_resource",
                resource_ids=tuple(
                    row["resource_id"] for row in FIXTURE["inventory"]["resources"][:3]
                ),
                action_group_ids=("ag-valid",),
            ),
        ),
        action_groups=(ActionGroupReference("ag-valid", "valid"),),
    )
    no_gap_alert = evaluate_alert_delivery(
        FIXTURE["inventory"],
        clean_alert,
        scope=SCOPE,
    )
    assert no_gap_alert["findings"]["count"] == 0
    assert no_gap_alert["status"] == "partial"
    assert no_gap_alert["alert_coverage"]["delivery_status"] == "not_proven"


def test_disabled_rules_with_missing_references_are_counted_without_attribution():
    payload = json.loads(json.dumps(FIXTURE["evaluated_alert"]))
    disabled = next(item for item in payload["rules"] if not item["enabled"])
    disabled["action_group_ids"] = []
    evidence = alert_evidence(payload)
    assessment = evaluate_alert_delivery(FIXTURE["inventory"], evidence, scope=SCOPE)
    assert assessment["alert_coverage"]["missing_action_group_reference_count"] == 2


@pytest.mark.parametrize(
    "scenario", [DIAGNOSTIC_SETTINGS_COVERAGE, ALERT_DELIVERY_COVERAGE]
)
def test_injected_reader_returns_partial_cited_evaluation_without_claiming_live_health(
    scenario,
):
    diagnostic = diagnostic_evidence()
    alert = alert_evidence()
    reader = ObservabilityPort(diagnostic=diagnostic, alert=alert)
    result = run_scenario(
        scenario,
        InventoryPort(),
        reader,
    )
    assessment = result.data["assessment"]

    assert result.status == STATUS_UNAVAILABLE
    assert assessment["status"] == "partial"
    assert assessment["findings"]["status"] == "evaluated"
    assert any(
        row.source_engine == "operations.ObservabilityReadPort"
        and row.timestamp == OBSERVED_AT
        for row in result.evidence
    )
    assert reader.calls == [
        (
            "alert" if scenario == ALERT_DELIVERY_COVERAGE else "diagnostic",
            SCOPE,
        )
    ]
    assert "inventory freshness is unknown" in result.warning


def test_stale_or_foreign_scope_configuration_evidence_fails_closed():
    stale = replace(diagnostic_evidence(), settings_freshness="stale")
    with pytest.raises(ValueError, match="incomplete or stale"):
        evaluate_diagnostic_settings(FIXTURE["inventory"], stale, scope=SCOPE)

    stale_result = run_scenario(
        DIAGNOSTIC_SETTINGS_COVERAGE,
        InventoryPort(),
        ObservabilityPort(diagnostic=stale),
    )
    stale_assessment = stale_result.data["assessment"]
    assert stale_result.status == STATUS_UNAVAILABLE
    assert stale_assessment["configuration_evidence"]["diagnostic_settings"] == {
        "status": "stale",
        "observed_at": OBSERVED_AT,
        "freshness": "stale",
    }
    assert any(
        item.source_table == "azure_monitor/diagnostic_settings"
        and item.timestamp == OBSERVED_AT
        for item in stale_result.evidence
    )

    foreign_scope = replace(
        diagnostic_evidence(),
        scope_binding={"subscription": ("sub-b",)},
    )
    with pytest.raises(PermissionError, match="different scope"):
        evaluate_diagnostic_settings(
            FIXTURE["inventory"],
            foreign_scope,
            scope=SCOPE,
        )

    foreign_inventory = json.loads(json.dumps(FIXTURE["inventory"]))
    foreign_inventory["resources"][0]["subscription_id"] = "sub-b"
    with pytest.raises(PermissionError, match="outside the effective scope"):
        evaluate_diagnostic_settings(
            foreign_inventory,
            diagnostic_evidence(),
            scope=SCOPE,
        )


def test_unreadable_and_unknown_resource_counts_are_not_reported_as_findings():
    rows = FIXTURE["inventory"]["resources"]
    evidence = replace(
        diagnostic_evidence(),
        unreadable_resource_ids=(rows[0]["resource_id"],),
        unknown_resource_ids=(rows[1]["resource_id"],),
    )
    result = evaluate_diagnostic_settings(FIXTURE["inventory"], evidence, scope=SCOPE)
    coverage = result["diagnostic_settings_coverage"]
    assert coverage["unreadable_resource_count"] == 1
    assert coverage["unknown_resource_count"] == 1
    assert result["status"] == "partial"


def test_empty_or_partial_inventory_never_produces_complete_coverage():
    evidence = diagnostic_evidence()
    empty = {**FIXTURE["inventory"], "resources": [], "total": 0}
    empty_result = evaluate_diagnostic_settings(empty, evidence, scope=SCOPE)
    assert empty_result["status"] == "partial"
    assert empty_result["findings"]["status"] == "not_evaluated"
    assert empty_result["resource_denominator"]["complete"] is False

    paged = {
        **FIXTURE["inventory"],
        "resources": FIXTURE["inventory"]["resources"][:2],
        "total": 9,
    }
    partial = evaluate_diagnostic_settings(paged, evidence, scope=SCOPE)
    assert partial["status"] == "partial"
    assert partial["resource_denominator"]["authorized_scope_inventory_count"] is None
    assert partial["inventory"]["status"] == "partial"


def test_empty_and_stale_inventory_never_imply_healthy_coverage():
    empty = {
        **FIXTURE["inventory"],
        "resources": [],
        "total": 0,
    }
    assessment = unavailable_assessment(
        DIAGNOSTIC_SETTINGS_COVERAGE,
        inventory=empty,
    )
    assert assessment["status"] == "unavailable"
    assert assessment["resource_denominator"]["authorized_scope_inventory_count"] == 0
    assert assessment["resource_denominator"]["complete"] is False
    assert assessment["findings"]["status"] == "not_evaluated"

    stale = {**FIXTURE["inventory"], "observed_at": "2020-01-01T00:00:00Z"}
    assessment = unavailable_assessment(
        ALERT_DELIVERY_COVERAGE,
        inventory=stale,
    )
    assert assessment["inventory"]["observed_at"] == "2020-01-01T00:00:00Z"
    assert assessment["inventory"]["freshness"] == "unknown"
    assert assessment["alert_coverage"]["delivery_status"] == "not_proven"


def test_inventory_denial_is_not_empty_or_authoritative():
    result = run_scenario(
        DIAGNOSTIC_SETTINGS_COVERAGE, InventoryPort(error=PermissionError)
    )
    assert result.status == STATUS_DENIED
    assert result.data["assessment"]["status"] == "unavailable"
    assert result.data["assessment"]["inventory"]["observed_resource_count"] is None
    assert result.evidence == ()


def test_missing_inventory_provider_remains_unavailable_with_unknown_denominator():
    result = run_scenario(DIAGNOSTIC_SETTINGS_COVERAGE)
    assessment = result.data["assessment"]
    assert result.status == STATUS_UNAVAILABLE
    assert assessment["status"] == "unavailable"
    assert assessment["inventory"]["status"] == "unavailable"
    assert (
        assessment["resource_denominator"]["authorized_scope_inventory_count"] is None
    )
    assert (
        assessment["resource_denominator"]["unreadable_observed_resource_count"] is None
    )
    assert result.evidence == ()


@pytest.mark.parametrize(
    "arguments",
    [
        {"scenario": "unsupported"},
        {"scenario": DIAGNOSTIC_SETTINGS_COVERAGE, "since": OBSERVED_AT},
        {"scenario": ALERT_DELIVERY_COVERAGE, "resource_id": "/subscriptions/sub-a"},
    ],
)
def test_malformed_scenario_arguments_are_rejected_before_reads(arguments):
    with pytest.raises(ValueError):
        validate_tool_arguments("incidents", arguments)
    with pytest.raises(ValueError):
        validate_parameters(arguments)


def test_resource_health_uses_existing_tool_grant_without_new_provider_or_grant():
    manifest = load_specialist_manifest()
    health = manifest.require("resource_health_observability")
    assert "incidents" in health.operations_mcp_tools
    assert OBSERVABILITY_SCENARIO_CONTRACT["existing_tool"] == "incidents"
    assert "diagnostic_settings" not in manifest.operations_tool_names()
    assert "alert_delivery" not in manifest.operations_tool_names()


def test_foreign_tool_is_denied_before_inventory_handler_runs():
    port = InventoryPort()
    server = MCPServer()
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "foreign",
            "method": "tools/call",
            "params": {"name": "inventory_resources", "arguments": {}},
        },
        context=ToolContext(port),
        principal=SimpleNamespace(subject="resource_health_observability"),
        scope=SCOPE,
        correlation_id="obs-test",
        specialist_id="resource_health_observability",
    )
    assert response["result"]["isError"] is True
    assert port.calls == []


@pytest.mark.parametrize("specialist_id", ["incident", None])
def test_observability_scenario_mcp_call_requires_existing_resource_health_specialist(
    specialist_id,
):
    port = InventoryPort()
    response = MCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": "foreign-scenario",
            "method": "tools/call",
            "params": {
                "name": "incidents",
                "arguments": {"scenario": DIAGNOSTIC_SETTINGS_COVERAGE},
            },
        },
        context=ToolContext(port),
        principal=SimpleNamespace(subject=specialist_id or "operator"),
        scope=SCOPE,
        correlation_id="obs-test",
        specialist_id=specialist_id,
    )
    assert response["result"]["isError"] is True
    assert port.calls == []


def test_existing_resource_health_specialist_can_dispatch_scenario_tool():
    port = InventoryPort()
    response = MCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": "health-scenario",
            "method": "tools/call",
            "params": {
                "name": "incidents",
                "arguments": {"scenario": ALERT_DELIVERY_COVERAGE},
            },
        },
        context=ToolContext(port),
        principal=SimpleNamespace(subject="resource_health_observability"),
        scope=SCOPE,
        correlation_id="obs-test",
        specialist_id="resource_health_observability",
    )
    assert response["result"]["isError"] is False
    assert response["result"]["structuredContent"]["status"] == STATUS_UNAVAILABLE
    assert port.calls == [(SCOPE, 0, None)]


@pytest.mark.parametrize(
    "scenario",
    [DIAGNOSTIC_SETTINGS_COVERAGE, ALERT_DELIVERY_COVERAGE],
)
@pytest.mark.parametrize("canonical", [True, False])
def test_canonical_copilot_page_action_is_scoped_and_cited(
    tmp_path,
    monkeypatch,
    scenario,
    canonical,
):
    from fastapi.testclient import TestClient
    from test_api_copilot_investigation import HEADERS, _context

    from api.app import create_app
    from tests.copilot_authorization_fixtures import enable_authorized_canary

    enable_authorized_canary(monkeypatch)
    if not canonical:
        monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    port = InventoryPort()
    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: port
    client = TestClient(create_app(context), raise_server_exceptions=False)
    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json={
            "contract_version": "1",
            "question": "Review observability coverage for this scope.",
            "requested_scope": SCOPE.to_dict(),
            "snapshot": {
                "version": "2",
                "page_kind": "resource_health",
                "page_id": "resource-health",
                "coverage": {"visible_count": 4, "total_count": 4, "complete": True},
                "evidence": [],
            },
            "hint": {
                "specialist_id": "resource_health_observability",
                "tool": "incidents",
                "arguments": {"scenario": scenario},
            },
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assessment = data["tool_results"][0]["data"]["assessment"]
    assert data["selected_tools"] == ["incidents"]
    assert assessment["scenario_id"] == scenario
    assert assessment["status"] == "unavailable"
    assert port.calls == [(SCOPE, 0, None)]
    assert any(
        evidence["source_table"] == "inventory/resource_observations"
        and evidence["timestamp"] == OBSERVED_AT
        for evidence in data["tool_results"][0]["evidence"]
    )
    assert data["mutation_authorized"] is False
    if canonical:
        assert data["synthesis"]["status"] == "deterministic"
        assert data["synthesis"]["reason"] == "bounded_observability_scenario_evidence"
        assert "coverage is unavailable" in data["synthesis"]["claims"][0]["summary"]
        refs = set(data["synthesis"]["claims"][0]["evidence_refs"])
        assert refs
        assert refs <= {row["citation_id"] for row in data["citations"]}
    else:
        assert (
            "coverage is unavailable"
            in data["synthesis"]["compatibility_answer"]["text"]
        )


@pytest.mark.parametrize(
    "scenario",
    [DIAGNOSTIC_SETTINGS_COVERAGE, ALERT_DELIVERY_COVERAGE],
)
def test_canonical_copilot_evaluates_injected_scope_bound_evidence(
    tmp_path,
    monkeypatch,
    scenario,
):
    from fastapi.testclient import TestClient
    from test_api_copilot_investigation import HEADERS, _context

    from api.app import create_app
    from tests.copilot_authorization_fixtures import enable_authorized_canary

    enable_authorized_canary(monkeypatch)
    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    context.observability_read_port_provider = lambda: ObservabilityPort(
        diagnostic=diagnostic_evidence(),
        alert=alert_evidence(),
    )
    response = TestClient(create_app(context), raise_server_exceptions=False).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json={
            "contract_version": "1",
            "question": "Review observability coverage for this scope.",
            "requested_scope": SCOPE.to_dict(),
            "snapshot": {
                "version": "2",
                "page_kind": "resource_health",
                "page_id": "resource-health",
                "coverage": {"visible_count": 4, "total_count": 4, "complete": True},
                "evidence": [],
            },
            "hint": {
                "specialist_id": "resource_health_observability",
                "tool": "incidents",
                "arguments": {"scenario": scenario},
            },
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assessment = data["tool_results"][0]["data"]["assessment"]
    assert assessment["status"] == "partial"
    assert assessment["findings"]["status"] == "evaluated"
    assert data["synthesis"]["status"] == "deterministic"
    summary = data["synthesis"]["claims"][0]["summary"]
    assert "observability coverage is partial" in summary
    assert "No live estate completeness" in summary
    cited_tables = {
        item["source_table"] for item in data["tool_results"][0]["evidence"]
    }
    if scenario == DIAGNOSTIC_SETTINGS_COVERAGE:
        assert "workload/logging_policy" in cited_tables
        assert "azure_monitor/diagnostic_settings" in cited_tables
        assert "2 required log categories" in summary
    else:
        assert "azure_monitor/alert_rules" in cited_tables
        assert "azure_monitor/action_group_references" in cited_tables
        assert "1 disabled alert rules" in summary
    assert data["mutation_authorized"] is False


def test_observability_scenario_is_not_authorized_from_another_page(
    tmp_path,
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from test_api_copilot_investigation import HEADERS, _context

    from api.app import create_app
    from tests.copilot_authorization_fixtures import enable_authorized_canary

    enable_authorized_canary(monkeypatch)
    port = InventoryPort()
    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: port
    response = TestClient(create_app(context), raise_server_exceptions=False).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json={
            "contract_version": "1",
            "question": "Review observability coverage.",
            "requested_scope": SCOPE.to_dict(),
            "snapshot": {
                "version": "2",
                "page_kind": "changes",
                "page_id": "incident-change-investigation",
                "coverage": {"visible_count": 0, "total_count": 0, "complete": False},
                "evidence": [],
            },
            "hint": {
                "specialist_id": "incident",
                "tool": "incidents",
                "arguments": {"scenario": DIAGNOSTIC_SETTINGS_COVERAGE},
            },
        },
    )
    assert response.status_code == 400, response.text
    assert port.calls == []
