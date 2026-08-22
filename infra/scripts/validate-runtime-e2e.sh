#!/bin/sh
set -eu

: "${API_URL:?Set API_URL to the deployed Operations API URL}"
: "${WEB_URL:?Set WEB_URL to the deployed Workbench URL}"
: "${API_TOKEN:?Set API_TOKEN to an operator/admin bearer token}"
: "${HUB_CONNECTION_ID:?Set HUB_CONNECTION_ID}"
: "${SPOKE_CONNECTION_ID:?Set SPOKE_CONNECTION_ID}"
: "${HERMES_ARG_CONFIG:?Set HERMES_ARG_CONFIG}"
: "${HERMES_FABRIC_CONFIG:?Set HERMES_FABRIC_CONFIG}"

if [ "$HUB_CONNECTION_ID" = "$SPOKE_CONNECTION_ID" ]; then
  echo "Hub and spoke connection IDs must be different" >&2
  exit 2
fi

HERMES_CLI="${HERMES_CLI:-.venv/bin/hermes-arg}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

"$HERMES_CLI" activate \
  --config "$HERMES_ARG_CONFIG" \
  --fabric-config "$HERMES_FABRIC_CONFIG" \
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

python3 - "$tmp_dir" "$HUB_CONNECTION_ID" "$SPOKE_CONNECTION_ID" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
hub = sys.argv[2]
spoke = sys.argv[3]

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

print(
    json.dumps(
        {
            "status": "passed",
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
