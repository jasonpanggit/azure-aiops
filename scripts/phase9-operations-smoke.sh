#!/usr/bin/env bash
#
# Secret-free live contract smoke for the Phase 09 Operations path.
# Credentials are environment-only and are never printed, persisted, or sent
# anywhere except the approved APIM URL.
set -euo pipefail

: "${AIOPS_APIM_MCP_URL:?set AIOPS_APIM_MCP_URL to the approved APIM /mcp URL}"
: "${AIOPS_MCP_BEARER_TOKEN:?set AIOPS_MCP_BEARER_TOKEN in the environment}"

url="${AIOPS_APIM_MCP_URL%/}"
correlation="phase9-operations-$(date +%s)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
auth=(-H "Authorization: ******")
[[ -n "${AIOPS_APIM_SUBSCRIPTION_KEY:-}" ]] &&
  auth+=(-H "Ocp-Apim-Subscription-Key: ${AIOPS_APIM_SUBSCRIPTION_KEY}")

post() {
  curl --silent --show-error --fail --max-time 35 -X POST "$1" "${auth[@]}" \
    -H "Content-Type: application/json" -H "X-Correlation-ID: ${correlation}" \
    --data "$2"
}
json_assert() {
  python3 - "$@" <<'PY'
import json, sys
payload = json.load(sys.stdin)
assert payload.get("jsonrpc") == "2.0", payload
PY
}

initialize='{"jsonrpc":"2.0","id":"initialize","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"phase9-smoke","version":"1"}}}'
post "$url" "$initialize" >"$tmp/initialize.json"
grep -q '"protocolVersion"' "$tmp/initialize.json"

post "$url" '{"jsonrpc":"2.0","id":"tools","method":"tools/list","params":{}}' >"$tmp/tools.json"
python3 -c 'import json,sys; expected={"network_topology","hub_dependents","traffic_flow","firewall_nsg_gaps","business_service_context","application_context","impact_context","fabric_iq_relationships","fabric_iq_topology","fabric_iq_policy_context"}; actual={x["name"] for x in json.load(sys.stdin)["result"]["tools"]}; assert actual == expected, (actual, expected)' <"$tmp/tools.json"

post "$url" '{"jsonrpc":"2.0","id":"network","method":"tools/call","params":{"name":"network_topology","arguments":{}}}' >"$tmp/network.json"
grep -Eq '"status":"(ok|empty|unavailable|denied)"' "$tmp/network.json"

snapshot='{"snapshot":{"version":"1","page_kind":"network","page_id":"phase9-smoke","question":"What should I review?","scope":{"declared":{},"authorized":true},"selected_resources":[{"resource_id":"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/smoke/providers/Microsoft.Network/virtualNetworks/smoke","resource_type":"Microsoft.Network/virtualNetworks"}],"evidence":[{"evidence_id":"smoke-nsg","section":"nsg","resource_id":"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/smoke/providers/Microsoft.Network/networkSecurityGroups/smoke","data":{"finding":"Smoke-only evidence","compliant":false},"status":"ok"}]}}'
post "${url%/mcp}/api/v1/mcp/snapshots" "$snapshot" >"$tmp/snapshot.json" || {
  # APIM may expose only the MCP protocol route; preserve the failure without
  # attempting provider rehydration or emitting the bearer token.
  echo "snapshot endpoint is not exposed through this APIM route" >&2
  exit 1
}
ledger_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["ledger_id"])' <"$tmp/snapshot.json")"
post "${url%/mcp}/api/v1/mcp/snapshots/${ledger_id}/replay" '{}' >"$tmp/replay.json"
python3 -c 'import json,sys; a=json.load(open(sys.argv[1])); b=json.load(open(sys.argv[2])); assert a["snapshot_hash"] == b["snapshot_hash"]; assert b["ledger_id"] == a["ledger_id"]' "$tmp/snapshot.json" "$tmp/replay.json"

echo "Phase 09 Operations smoke passed: MCP/APIM correlation=${correlation}; snapshot replay is non-rehydrating"
