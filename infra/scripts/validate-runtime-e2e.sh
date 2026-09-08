#!/bin/sh
#
# Deployed-runtime end-to-end gate.
#
# Specialist parity runs FIRST and gates the promotion decision this script
# prints. Offline parity must pass. Live parity is read-only and may report
# BLOCKED when the Foundry project or the two MCP servers are not configured
# for this environment -- a blocked gate holds promotion, it never counts as a
# pass. Only controlled identifiers, statuses, and counts are printed: no
# token, secret, or tool argument is ever echoed.
#
# Optional:
#   PARITY_PYTHON     interpreter used for the parity validator (default python3)
#   PARITY_VALIDATOR  path to scripts/validate_specialist_parity.py
set -eu

: "${API_URL:?Set API_URL to the deployed Operations API URL}"
: "${WEB_URL:?Set WEB_URL to the deployed Workbench URL}"
: "${API_TOKEN:?Set API_TOKEN to an operator/admin bearer token}"
: "${HUB_CONNECTION_ID:?Set HUB_CONNECTION_ID}"
: "${SPOKE_CONNECTION_ID:?Set SPOKE_CONNECTION_ID}"
: "${AIOPS_ARG_CONFIG:?Set AIOPS_ARG_CONFIG}"
: "${AIOPS_FABRIC_CONFIG:?Set AIOPS_FABRIC_CONFIG}"

if [ "$HUB_CONNECTION_ID" = "$SPOKE_CONNECTION_ID" ]; then
  echo "Hub and spoke connection IDs must be different" >&2
  exit 2
fi

AIOPS_CLI="${AIOPS_CLI:-.venv/bin/aiops-inventory}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

# ---------------------------------------------------------------------------
# Staged rollout context (Plan 11-12 Task 2).
#
# The canonical orchestrator is introduced compatibility -> shadow -> canary ->
# default. This gate runs in the fixed order create -> validate -> switch ->
# observe -> promote: specialist parity (below) validates first, the deployed
# runtime is observed, and only then is a promotion decision printed. A canary
# or default promotion is never printed unless live parity passes; any parity
# block or runtime failure holds the current stage and the operator rolls back
# per docs/runbooks/copilot-orchestration-rollout.md.
# ---------------------------------------------------------------------------
COPILOT_ROLLOUT_MODE="${COPILOT_ROLLOUT_MODE:-compatibility}"
case "$COPILOT_ROLLOUT_MODE" in
  compatibility | shadow | canary | default) ;;
  *)
    echo "COPILOT_ROLLOUT_MODE must be compatibility, shadow, canary, or default" >&2
    exit 2
    ;;
esac

# ---------------------------------------------------------------------------
# Specialist parity gate -- runs before anything that could be read as a
# promotion signal.
# ---------------------------------------------------------------------------
PARITY_PYTHON="${PARITY_PYTHON:-python3}"
PARITY_VALIDATOR="${PARITY_VALIDATOR:-scripts/validate_specialist_parity.py}"

if [ ! -f "$PARITY_VALIDATOR" ]; then
  echo "Specialist parity validator not found at $PARITY_VALIDATOR" >&2
  exit 2
fi

if ! "$PARITY_PYTHON" "$PARITY_VALIDATOR" --offline >"$tmp_dir/parity-offline.json"; then
  echo "Offline specialist parity failed; promotion held" >&2
  exit 2
fi

set +e
"$PARITY_PYTHON" "$PARITY_VALIDATOR" --live >"$tmp_dir/parity-live.json"
parity_live_status=$?
set -e

case "$parity_live_status" in
  0) parity_status="pass" ;;
  3) parity_status="blocked" ;;
  *)
    echo "Live specialist parity failed; promotion held" >&2
    exit 2
    ;;
esac

"$AIOPS_CLI" activate \
  --config "$AIOPS_ARG_CONFIG" \
  --fabric-config "$AIOPS_FABRIC_CONFIG" \
  --connection-id "$HUB_CONNECTION_ID" \
  --connection-id "$SPOKE_CONNECTION_ID" \
  >"$tmp_dir/activation.json"

auth_header="Authorization: Bearer $API_TOKEN"
curl -fsS -X POST -H "$auth_header" \
  "$API_URL/api/v1/runtime/refresh" >"$tmp_dir/refresh.json"
curl -fsS "$API_URL/ready" >"$tmp_dir/ready.json"
curl -fsS -H "$auth_header" \
  "$API_URL/api/v1/network/topology" >"$tmp_dir/topology.json"
curl -fsS -H "$auth_header" \
  "$API_URL/api/v1/network/topology?subscription_connection=$HUB_CONNECTION_ID" \
  >"$tmp_dir/hub.json"
curl -fsS -H "$auth_header" \
  "$API_URL/api/v1/network/topology?subscription_connection=$SPOKE_CONNECTION_ID" \
  >"$tmp_dir/spoke.json"
curl -fsS -H "$auth_header" \
  "$API_URL/api/v1/vulnerabilities/summary" >"$tmp_dir/vulnerability.json"
curl -fsS -H "$auth_header" \
  "$API_URL/api/v1/incidents" >"$tmp_dir/incidents.json"
curl -fsS -H "$auth_header" \
  "$API_URL/api/v1/remediation-plans" >"$tmp_dir/remediation.json"
curl -fsS "$WEB_URL" >/dev/null

python3 - "$tmp_dir" "$HUB_CONNECTION_ID" "$SPOKE_CONNECTION_ID" "$parity_status" "$COPILOT_ROLLOUT_MODE" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
hub = sys.argv[2]
spoke = sys.argv[3]
parity_status = sys.argv[4]
rollout_mode = sys.argv[5]

activation = json.loads((root / "activation.json").read_text())
ready = json.loads((root / "ready.json").read_text())
topology = json.loads((root / "topology.json").read_text())["data"]
hub_payload = json.loads((root / "hub.json").read_text())
spoke_payload = json.loads((root / "spoke.json").read_text())

assert activation["status"] == "activated", activation
assert {hub, spoke}.issubset(set(activation["connections"])), activation["connections"]
assert activation["ontology_version"], "activation returned no ontology version"
assert ready["readiness"] in {"ready", "partial", "stale"}, ready
assert ready["last_discovery_run"], "health returned no discovery timestamp"
assert ready["last_ontology_publication"], "health returned no ontology publication timestamp"

required = {"semantic", "network", "vulnerability", "incidents", "remediation"}
providers = ready["providers"]
assert required.issubset(providers), providers.keys()
failed = {
    name: providers[name]
    for name in required
    if not providers[name]["loaded"]
}
assert not failed, failed

summary = topology["summary"]
assert summary["connection_count"] >= 2, summary
assert summary["hub_count"] >= 1, summary
assert summary["spoke_count"] >= 1, summary

for connection_id, payload in ((hub, hub_payload), (spoke, spoke_payload)):
    assert payload["scope"]["subscription_connection"] == [connection_id.casefold()], payload["scope"]
    scoped_topology = payload["data"]["topology"]
    assert scoped_topology["connection_ids"] == [connection_id], scoped_topology["connection_ids"]
    resources = scoped_topology["resources"]
    assert resources, f"{connection_id} returned no scoped network resources"
    leaked = [
        resource
        for resource in resources
        if resource.get("connection_id") != connection_id
    ]
    assert not leaked, {
        "connection_id": connection_id,
        "leaked_resource_ids": [
            resource.get("resource_id") for resource in leaked[:10]
        ],
    }

parity = json.loads((root / "parity-offline.json").read_text())
assert parity["status"] == "pass", parity["failures"]

# Live parity is a promotion prerequisite, not an assumption: a blocked gate
# holds promotion with an explicit reason instead of reporting a pass. A canary
# or default stage additionally requires live parity to pass before promotion;
# earlier stages (compatibility, shadow) never promote.
promotion = "promote" if parity_status == "pass" else "hold"
if rollout_mode in {"compatibility", "shadow"}:
    promotion = "hold"

print(
    json.dumps(
        {
            "status": "passed",
            "promotion": promotion,
            "rollout_mode": rollout_mode,
            "parity_status": parity_status,
            "specialist_count": parity["specialist_count"],
            "ontology_version": ready["ontology_version"],
            "hub_count": summary["hub_count"],
            "spoke_count": summary["spoke_count"],
            "providers": {
                name: providers[name]["state"] for name in sorted(required)
            },
        },
        indent=2,
    )
)
PY
