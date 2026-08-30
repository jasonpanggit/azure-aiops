from operations.mcp_server import MCPServer, REVIEWED_TOOLS, tool_definitions
from operations.tools import STATUS_EMPTY, STATUS_OK, ToolResult


def test_catalog_has_bounded_json_schemas():
    assert tuple(item["name"] for item in tool_definitions()) == REVIEWED_TOOLS
    assert all(item["inputSchema"]["additionalProperties"] is False for item in tool_definitions())


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
