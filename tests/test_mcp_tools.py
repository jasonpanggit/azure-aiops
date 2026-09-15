from operations.mcp_server import (
    REVIEWED_TOOLS,
    MCPServer,
    reviewed_tools_for_specialist,
    tool_definitions,
)
from operations.specialist_manifest import INVENTORY_DATA_HEALTH_ID
from operations.tools import STATUS_EMPTY, STATUS_OK, call_tool


def test_catalog_has_bounded_json_schemas():
    assert tuple(item["name"] for item in tool_definitions()) == REVIEWED_TOOLS
    assert all(item["inputSchema"]["additionalProperties"] is False for item in tool_definitions())


def test_inventory_tool_is_an_exact_specialist_bound_reviewed_grant():
    assert reviewed_tools_for_specialist(INVENTORY_DATA_HEALTH_ID) == (
        "inventory_resources",
    )
    assert "inventory_resources" in REVIEWED_TOOLS

    class Context:
        provider_runtime = None

        def resolve_provider(self, name):
            return None

    allowed = MCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": "x",
            "method": "tools/call",
            "params": {"name": "inventory_resources", "arguments": {}},
        },
        context=Context(),
        principal=type("P", (), {"subject": INVENTORY_DATA_HEALTH_ID})(),
        scope=__import__("api.scope", fromlist=["Scope"]).Scope.unrestricted(),
        correlation_id="corr",
        specialist_id=INVENTORY_DATA_HEALTH_ID,
    )
    assert allowed["result"]["isError"] is False
    assert allowed["result"]["structuredContent"]["status"] == "unavailable"

    legacy_denied = MCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": "x",
            "method": "tools/call",
            "params": {"name": "inventory_resources", "arguments": {}},
        },
        context=Context(),
        principal=type("P", (), {"subject": "operator"})(),
        scope=__import__("api.scope", fromlist=["Scope"]).Scope.unrestricted(),
        correlation_id="corr",
    )
    assert legacy_denied["result"]["isError"] is True

    cross_specialist_denied = MCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": "x",
            "method": "tools/call",
            "params": {"name": "network_topology", "arguments": {}},
        },
        context=Context(),
        principal=type("P", (), {"subject": INVENTORY_DATA_HEALTH_ID})(),
        scope=__import__("api.scope", fromlist=["Scope"]).Scope.unrestricted(),
        correlation_id="corr",
        specialist_id=INVENTORY_DATA_HEALTH_ID,
    )
    assert cross_specialist_denied["result"]["isError"] is True


def test_dispatch_preserves_tool_result_shape_and_status():
    class Context:
        def resolve_provider(self, name):
            return None
        provider_runtime = None
    response = MCPServer().handle(
        {"jsonrpc": "2.0", "id": "x", "method": "tools/call",
         "params": {"name": "network_topology", "arguments": {}}},
        context=Context(), principal=type("P", (), {"subject": "test"})(),
        scope=__import__("api.scope", fromlist=["Scope"]).Scope.unrestricted(),
        correlation_id="corr",
    )
    assert response["result"]["structuredContent"]["status"] in {"unavailable", STATUS_EMPTY, STATUS_OK, "denied"}


def test_dispatch_records_redacted_ledger_metadata():
    class Context:
        def resolve_provider(self, name):
            return None
        provider_runtime = None
    server = MCPServer()
    server.handle(
        {"jsonrpc": "2.0", "id": "x", "method": "tools/call",
         "params": {"name": "network_topology", "arguments": {}}},
        context=Context(), principal=type("P", (), {"subject": "operator"})(),
        scope=__import__("api.scope", fromlist=["Scope"]).Scope.unrestricted(),
        correlation_id="corr-123",
    )
    assert server.audit_entries[-1] == {
        "correlation_id": "corr-123",
        "actor": "operator",
        "scope": {},
        "tool": "network_topology",
        "status": "unavailable",
        "evidence": [],
    }


class _VulnerabilityProvider:
    freshness = "2026-09-01T00:00:00Z"

    def __init__(self):
        self.alert_rows = [{"id": f"alert-{i}", "status": "Active", "severity": "high", "subscription": "sub-a", "resourceIds": ["/subscriptions/123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"], "timeGenerated": f"2026-09-01T00:{i:02d}:00Z"} for i in range(40)]
        self.path_rows = [{"id": f"path-{i}", "subscription": "sub-a", "resourceIds": ["/subscriptions/123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"], "nodes": [{"id": f"node-{i}", "resourceId": "/subscriptions/123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"}]} for i in range(40)]
        self.score_rows = [{"subscription_id": "sub-a", "currentScore": 40, "maxScore": 60, "observedAt": "2026-09-01T00:00:00Z"}]
        self.control_rows = [{"id": f"control-{i}", "subscription": "sub-a", "assessmentDefinitions": ["/subscriptions/123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"], "unhealthyResourceCount": i + 1, "currentScore": 0, "maxScore": 10, "title": f"Control {i}", "observedAt": "2026-09-01T00:00:00Z"} for i in range(40)]

    def security_alerts(self, scope, active_only=True):
        rows = self.alert_rows
        return [row for row in rows if scope.is_unrestricted() or str(row.get("subscription") or "") in set(scope.values("subscription"))]

    def defender_attack_paths_for_scope(self, scope):
        rows = self.path_rows
        return [row for row in rows if scope.is_unrestricted() or str(row.get("subscription") or "") in set(scope.values("subscription"))]

    def secure_score_overview(self, scope):
        rows = self.score_rows
        return [row for row in rows if scope.is_unrestricted() or str(row.get("subscription_id") or "") in set(scope.values("subscription"))]

    def secure_score_controls(self, scope):
        rows = self.control_rows
        return [row for row in rows if scope.is_unrestricted() or str(row.get("subscription") or "") in set(scope.values("subscription"))]


class _ContextWithVulnerability:
    provider_runtime = None

    def __init__(self, provider):
        self._provider = provider

    def resolve_provider(self, name):
        if name == "vulnerability":
            return self._provider
        return None


class _PatchPriorityProvider:
    freshness = "2026-09-15T17:26:31Z"

    def patch_priorities(self, scope):
        assert scope.to_dict() == {"subscription": ["sub-a"]}
        return [
            {
                "priority_id": "DEFENDER:CVE-2026-63076",
                "priority_type": "defender_cve",
                "kb_id": "",
                "cve_ids": ["CVE-2026-63076"],
                "affected_server_count": 658,
                "affected_application_count": 12,
                "affected_business_service_count": 5,
                "expected_risk_reduction": 19917.66,
                "priority_score": 19927.66,
                "recommended_action": "Review the Defender recommendation.",
            },
            {
                "priority_id": "DEFENDER:CVE-2026-70000",
                "priority_type": "kb",
                "kb_id": "",
                "cve_ids": ["CVE-2026-70000"],
                "affected_server_count": 4,
                "affected_application_count": 1,
                "affected_business_service_count": 1,
                "expected_risk_reduction": 19000.0,
                "priority_score": 19010.0,
                "recommended_action": "Review the malformed priority.",
            },
            {
                "priority_id": "5123099",
                "priority_type": "kb",
                "kb_id": "5123099",
                "cve_ids": [f"CVE-2026-{index:05d}" for index in range(126)],
                "affected_server_count": 1,
                "affected_application_count": 1,
                "affected_business_service_count": 1,
                "expected_risk_reduction": 16391.2,
                "priority_score": 17651.2,
                "recommended_action": (
                    "Patch through the approved change process; "
                    "this platform executes no remediation."
                ),
            },
            {
                "priority_id": "5030000",
                "priority_type": "kb",
                "kb_id": "5030000",
                "cve_ids": ["CVE-2026-60000"],
                "affected_server_count": 1,
                "affected_application_count": 1,
                "affected_business_service_count": 1,
                "expected_risk_reduction": 900.0,
                "priority_score": 910.0,
                "recommended_action": "Review KB5030000.",
            },
        ]


class _KbQueryProvider:
    def authorization_for(self, principal, scope):
        assert principal.subject == "operator"
        assert scope.to_dict() == {"subscription": ["sub-a"]}
        return object()

    def kb_item(self, authorization, *, kb_id):
        assert authorization is not None
        assert kb_id == "KB5123099"
        return {
            "kb_id": kb_id,
            "title": "Windows Server 2016",
            "severity": "Important",
            "published_at": "2026-09-08",
            "cve_ids": [f"CVE-2026-{index:05d}" for index in range(126)],
            "affected_servers": ["/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"],
            "affected_server_count": 1,
            "affected_business_services": ["Payments"],
            "snapshot": {
                "completeness": "complete",
                "freshness": "stale",
                "as_of": "2026-09-15T14:37:44Z",
            },
            "enrichment": {
                "status": "complete",
                "complete": True,
                "stale": False,
                "expected_count": 379,
                "available_count": 379,
            },
        }


class _PatchContext:
    provider_runtime = None

    def resolve_provider(self, name):
        if name == "vulnerability":
            return _PatchPriorityProvider()
        return None

    def exposure_query_provider(self):
        return _KbQueryProvider()


def test_patch_priority_and_kb_tools_use_server_catalog_not_exposure_images():
    from api.scope import Scope

    context = _PatchContext()
    principal = type("P", (), {"subject": "operator"})()
    scope = Scope({"subscription": ["sub-a"]})
    priorities = call_tool(
        "patch_priorities",
        {},
        context=context,
        scope=scope,
        principal=principal,
    )
    detail = call_tool(
        "kb_detail",
        {"kb_id": "5123099"},
        context=context,
        scope=scope,
        principal=principal,
    )

    assert priorities.status == STATUS_OK
    assert priorities.data["top_priority"] == {
        **priorities.data["items"][0],
        "kb_id": "KB5123099",
        "product": "Windows Server 2016",
        "published_at": "2026-09-08",
        "kb_detail_status": STATUS_OK,
        "kb_enrichment": {
            "status": "complete",
            "complete": True,
            "stale": False,
            "expected_count": 379,
            "available_count": 379,
        },
        "kb_snapshot": {
            "completeness": "complete",
            "freshness": "stale",
            "as_of": "2026-09-15T14:37:44Z",
        },
    }
    assert priorities.data["top_priority"]["cve_count"] == 126
    assert priorities.data["total_count"] == 2
    assert priorities.data["returned_count"] == 2
    assert [
        (item["rank"], item["priority_id"], item["priority_type"])
        for item in priorities.data["items"]
    ] == [
        (1, "5123099", "kb"),
        (2, "5030000", "kb"),
    ]
    assert all(item["kb_id"] for item in priorities.data["items"])
    assert priorities.data["top_priority"]["recommended_action"].startswith(
        "Patch through the approved change process"
    )
    assert "DEFENDER:CVE-2026-63076" not in str(priorities.data)
    assert "container_image" not in str(priorities.data)
    assert [item.source_table for item in priorities.evidence] == [
        "vulnerability_projection",
        "silver_patch_snapshot_findings",
    ]
    assert "KB snapshot freshness is stale" in priorities.warning

    assert detail.status == STATUS_OK
    assert detail.data["kb_id"] == "KB5123099"
    assert detail.data["product"] == "Windows Server 2016"
    assert detail.data["published_at"] == "2026-09-08"
    assert detail.data["cve_count"] == 126
    assert len(detail.data["cve_ids"]) == 25


def _call(server, name, arguments, scope):
    return server.handle(
        {"jsonrpc": "2.0", "id": "x", "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        context=_ContextWithVulnerability(_VulnerabilityProvider()),
        principal=type("P", (), {"subject": "operator"})(),
        scope=scope,
        correlation_id="corr",
    )


def test_new_defender_tools_are_advertised_with_schemas():
    defs = {item["name"]: item for item in tool_definitions()}
    for name in ("defender_alerts", "defender_attack_paths", "defender_secure_score"):
        assert name in defs
        assert defs[name]["description"]
        assert defs[name]["inputSchema"]["additionalProperties"] is False


def test_defender_alerts_tool_returns_evidence_and_empty_status_when_no_rows():
    from api.scope import Scope
    response = _call(MCPServer(), "defender_alerts", {}, Scope({"subscription": ["sub-z"]}))
    assert response["result"]["structuredContent"]["status"] == STATUS_EMPTY

    response = _call(MCPServer(), "defender_alerts", {}, Scope({"subscription": ["sub-a"]}))
    body = response["result"]["structuredContent"]
    assert body["status"] == STATUS_OK
    assert body["data"]
    assert body["evidence"][0]["source_engine"] == "intelligence.VulnerabilityIntelligenceService"
    assert body["evidence"][0]["source_table"] == "defender_alerts"
    assert len(body["data"]) == 25


def test_defender_attack_paths_tool_inherits_scope_filtering_and_bounds_results():
    from api.scope import Scope
    denied = _call(MCPServer(), "defender_attack_paths", {}, Scope({"subscription": ["sub-z"]}))
    assert denied["result"]["structuredContent"]["status"] == STATUS_EMPTY
    allowed = _call(MCPServer(), "defender_attack_paths", {}, Scope({"subscription": ["sub-a"]}))
    body = allowed["result"]["structuredContent"]
    assert body["status"] == STATUS_OK
    assert body["evidence"][0]["source_table"] == "defender_attack_paths"
    assert len(body["data"]) == 25


def test_defender_secure_score_tool_returns_overview_and_unhealthy_controls():
    from api.scope import Scope
    response = _call(MCPServer(), "defender_secure_score", {}, Scope({"subscription": ["sub-a"]}))
    body = response["result"]["structuredContent"]
    assert body["status"] == STATUS_OK
    assert set(body["data"]) == {"overview", "controls"}
    assert body["evidence"][0]["source_table"] == "defender_secure_scores"
    assert len(body["data"]["controls"]) == 25


class _DecisionStore:
    def __init__(self, plan):
        self._plan = plan

    def get(self, plan_id):
        return self._plan if plan_id == self._plan["plan_id"] else None


class _PlannerWithCorrelator:
    def __init__(self):
        self.defender_correlator = type("Corr", (), {"cases": lambda self, scope=None: [
            {
                "case_id": "CASE-001",
                "resource_key": "/subscriptions/123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                "business_service": "Checkout",
                "evidence_citations": [{"source_id": "alert-1"}],
                "business_context": {"affected_services": ["Checkout"]},
                "disposition": "act_now",
                "urgency_rationale": {"message": "customer path at risk"},
                "confidence": 0.8,
                "outcome": "catalog_action",
                "business_mapping_review_required": False,
            },
            {
                "case_id": "CASE-002",
                "resource_key": "/subscriptions/123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm2",
                "business_service": "Billing",
                "evidence_citations": [{"source_id": "alert-2"}],
                "business_context": {"affected_services": ["Billing"]},
                "disposition": "escalate",
                "urgency_rationale": {"message": "mapping unknown"},
                "confidence": 0.4,
                "outcome": "no_safe_action",
                "business_mapping_review_required": True,
            },
        ]})()
        self.repository = _DecisionStore({
            "plan_id": "RMP-123",
            "case_id": "CASE-001",
            "business_decision": {
                "cost_of_action": {"service_risk": {"status": "known"}},
                "cost_of_inaction": {"service_risk": {"status": "known"}},
                "options": [{"option_id": "act_now", "recommended": True}],
                "urgency_rationale": {"message": "customer impact now"},
                "confidence": 0.85,
                "review_requirements": ["owner review"],
            },
        })

    def generate_plans(self):
        return {"plans": [self.repository._plan], "generated_at": "2026-09-01T00:00:00Z"}


def test_remediation_cases_tool_filters_by_business_service_and_keeps_no_safe_action_visible():
    from api.scope import Scope
    from operations.tools import call_tool
    planner = _PlannerWithCorrelator()
    context = type("Ctx", (), {"provider_runtime": None, "resolve_provider": lambda self, name: planner if name == "remediation" else None})()
    result = call_tool("defender_remediation_cases", {"business_service": "Checkout"}, context=context, scope=Scope.unrestricted())
    assert result.status == STATUS_OK
    assert len(result.data) == 1
    assert result.data[0]["business_service"] == "Checkout"
    result = call_tool("defender_remediation_cases", {}, context=context, scope=Scope.unrestricted())
    assert {row["outcome"] for row in result.data} == {"catalog_action", "no_safe_action"}
    assert any(row["business_mapping_review_required"] for row in result.data)


def test_remediation_business_decision_tool_returns_business_decision_by_plan_or_case():
    from api.scope import Scope
    from operations.tools import call_tool
    planner = _PlannerWithCorrelator()
    context = type("Ctx", (), {"provider_runtime": None, "resolve_provider": lambda self, name: planner if name == "remediation" else None})()
    result = call_tool("remediation_business_decision", {"name": "RMP-123"}, context=context, scope=Scope.unrestricted())
    assert result.status == STATUS_OK
    assert result.data["plan_id"] == "RMP-123"
    assert "cost_of_action" in result.data["business_decision"]
    by_case = call_tool("remediation_business_decision", {"name": "CASE-001"}, context=context, scope=Scope.unrestricted())
    assert by_case.status == STATUS_OK
    assert by_case.data["case_id"] == "CASE-001"
