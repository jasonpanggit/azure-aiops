#!/usr/bin/env bash
#
# Restore an APIM MCP gateway from a snapshot captured by deploy.sh.
# This script never accepts credentials as arguments and never prints policy
# bodies. It is intentionally restore-only; it does not destroy the APIM service.
set -euo pipefail

: "${AIOPS_APIM_ROLLBACK_SNAPSHOT:?set AIOPS_APIM_ROLLBACK_SNAPSHOT to a snapshot directory}"
snapshot="${AIOPS_APIM_ROLLBACK_SNAPSHOT%/}"
metadata="${snapshot}/metadata.txt"
[[ -f "${metadata}" ]] || { echo "rollback: metadata.txt not found" >&2; exit 1; }
[[ -f "${snapshot}/api.json" ]] || { echo "rollback: api.json not found" >&2; exit 1; }
[[ -f "${snapshot}/api-policy.xml" ]] || { echo "rollback: api-policy.xml not found" >&2; exit 1; }
[[ -f "${snapshot}/operation-policy.xml" ]] || { echo "rollback: operation-policy.xml not found" >&2; exit 1; }

read_meta() { awk -F= -v key="$1" '$1 == key { print substr($0, length($1)+2) }' "${metadata}"; }
rg="$(read_meta resource_group)"
apim="$(read_meta apim_name)"
api="$(read_meta api_name)"
[[ -n "${rg}" && -n "${apim}" && -n "${api}" ]] || {
  echo "rollback: snapshot metadata is incomplete" >&2
  exit 1
}
command -v az >/dev/null 2>&1 || { echo "rollback: Azure CLI is required" >&2; exit 1; }

echo "rollback: restoring APIM service=${apim} api=${api} resource-group=${rg}"
subscription="$(az account show --query id -o tsv)"
resource_id="/subscriptions/${subscription}/resourceGroups/${rg}/providers/Microsoft.ApiManagement/service/${apim}/apis/${api}"
az rest --method put \
  --url "https://management.azure.com${resource_id}?api-version=2022-08-01" \
  --body "@${snapshot}/api.json" --output none
policy_body="$(python3 -c 'import json,sys; print(json.dumps({"properties":{"format":"rawxml","value":open(sys.argv[1]).read()}}))' "${snapshot}/api-policy.xml")"
az rest --method put \
  --url "https://management.azure.com${resource_id}/policies/policy?api-version=2022-08-01" \
  --body "${policy_body}" --output none
echo "rollback: restored policy and API definition; run deploy.sh plan to verify state"
