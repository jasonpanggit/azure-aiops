#!/usr/bin/env bash
#
# Credentialed APIM MCP smoke test. Tokens are supplied by the environment and
# are never echoed or written to artifacts.
#
# Required: AIOPS_APIM_MCP_URL, AIOPS_MCP_BEARER_TOKEN
# Optional: AIOPS_APIM_SUBSCRIPTION_KEY, AIOPS_MCP_ALLOWED_ARGUMENTS
set -euo pipefail

: "${AIOPS_APIM_MCP_URL:?set AIOPS_APIM_MCP_URL to the approved APIM /mcp URL}"
: "${AIOPS_MCP_BEARER_TOKEN:?set AIOPS_MCP_BEARER_TOKEN in the environment}"

url="${AIOPS_APIM_MCP_URL%/}"
correlation="apim-smoke-$(date +%s)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
auth=(-H "Authorization: Bearer ${AIOPS_MCP_BEARER_TOKEN}")
if [[ -n "${AIOPS_APIM_SUBSCRIPTION_KEY:-}" ]]; then
  auth+=(-H "Ocp-Apim-Subscription-Key: ${AIOPS_APIM_SUBSCRIPTION_KEY}")
fi

post() {
  curl --silent --show-error --max-time 35 \
    -X POST "${url}" "${auth[@]}" -H "Content-Type: application/json" \
    -H "X-Correlation-ID: ${correlation}" --data "$1"
}
status_without_auth() {
  curl --silent --output /dev/null --write-out '%{http_code}' --max-time 35 \
    -X POST "${url}" -H "Content-Type: application/json" --data "$1"
}
assert_status() {
  local expected="$1" actual="$2" label="$3"
  [[ "$actual" == "$expected" ]] || {
    echo "APIM MCP validation failed (${label}): expected ${expected}, got ${actual}" >&2
    exit 1
  }
}

initialize="$(post '{"jsonrpc":"2.0","id":"initialize","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"aiops-smoke","version":"1"}}}')"
grep -q '"protocolVersion"' <<<"${initialize}"

tools="$(post '{"jsonrpc":"2.0","id":"tools","method":"tools/list","params":{}}')"
python3 -c 'import json,sys; expected={"network_topology","hub_dependents","traffic_flow","firewall_nsg_gaps","business_service_context","application_context","impact_context","fabric_iq_relationships","fabric_iq_topology","fabric_iq_policy_context"}; actual={x["name"] for x in json.load(sys.stdin)["result"]["tools"]}; assert actual == expected, (actual, expected)' <<<"${tools}"

args="${AIOPS_MCP_ALLOWED_ARGUMENTS:-{}}"
call="$(python3 -c 'import json,sys; print(json.dumps({"jsonrpc":"2.0","id":"call","method":"tools/call","params":{"name":"network_topology","arguments":json.load(sys.stdin)}}))' <<<"${args}")"
result="$(post "${call}")"
grep -Eq '"status":"(ok|empty|unavailable|denied)"' <<<"${result}"

# The gateway must reject missing authentication and unsupported methods.
assert_status 401 "$(status_without_auth "${call}")" "missing bearer token"
unsupported='{"jsonrpc":"2.0","id":"bad","method":"resources/list","params":{}}'
unsupported_status="$(curl --silent --output "${tmp}/unsupported.json" --write-out '%{http_code}' --max-time 35 \
  -X POST "${url}" "${auth[@]}" -H "Content-Type: application/json" --data "${unsupported}")"
assert_status 400 "${unsupported_status}" "unsupported method"

# Caller-declared authorization material must not change the trusted request.
for header in \
  "X-AIOps-Scope: attacker" \
  "X-AIOps-Grant: admin" \
  "X-AIOps-Subscription: attacker" \
  "X-AIOps-Principal: attacker" \
  "X-MS-Client-Principal-Name: attacker@example.com"; do
  forged_status="$(curl --silent --output "${tmp}/forged.json" --write-out '%{http_code}' --max-time 35 \
    -X POST "${url}" "${auth[@]}" -H "Content-Type: application/json" \
    -H "X-Correlation-ID: ${correlation}" -H "${header}" --data "${call}")"
  [[ "${forged_status}" =~ ^(200|403)$ ]] || {
    echo "APIM MCP validation failed (forged header ${header}): HTTP ${forged_status}" >&2
    exit 1
  }
done

echo "APIM MCP smoke passed: initialize tools/list scoped tools/call auth/correlation=${correlation}"
