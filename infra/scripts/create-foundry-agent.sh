#!/usr/bin/env bash
#
# Creates (or updates) the Foundry prompt agent that narrates Copilot answers.
#
# Prompt agents exist only on the Foundry data plane — there is no ARM resource
# type for them — so they cannot be declared in Terraform. This script is
# invoked by a local-exec provisioner and is idempotent: creating an agent that
# already exists adds a new version rather than failing.
#
# Required environment (supplied by Terraform):
#   FOUNDRY_PROJECT_ENDPOINT  https://<sub>.services.ai.azure.com/api/projects/<project>
#   FOUNDRY_AGENT_NAME        agent name
#   FOUNDRY_AGENT_MODEL       model deployment name
#   FOUNDRY_AGENT_PROMPT      system instructions
#   AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET

set -euo pipefail

for var in FOUNDRY_PROJECT_ENDPOINT FOUNDRY_AGENT_NAME FOUNDRY_AGENT_MODEL \
           FOUNDRY_AGENT_PROMPT AZURE_TENANT_ID AZURE_CLIENT_ID AZURE_CLIENT_SECRET; do
  if [[ -z "${!var:-}" ]]; then
    echo "create-foundry-agent: ${var} is required" >&2
    exit 1
  fi
done

API_VERSION="${FOUNDRY_API_VERSION:-v1}"
endpoint="${FOUNDRY_PROJECT_ENDPOINT%/}"

# The agent data plane uses its own audience, not the ARM one.
token=$(curl -sS --fail-with-body \
  -X POST "https://login.microsoftonline.com/${AZURE_TENANT_ID}/oauth2/v2.0/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=client_credentials' \
  --data-urlencode "client_id=${AZURE_CLIENT_ID}" \
  --data-urlencode "client_secret=${AZURE_CLIENT_SECRET}" \
  --data-urlencode 'scope=https://ai.azure.com/.default' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

body=$(
  FOUNDRY_AGENT_NAME="$FOUNDRY_AGENT_NAME" \
  FOUNDRY_AGENT_MODEL="$FOUNDRY_AGENT_MODEL" \
  FOUNDRY_AGENT_PROMPT="$FOUNDRY_AGENT_PROMPT" \
  python3 - <<'PY'
import json, os

# Built with json.dumps rather than a heredoc so the instructions — which are
# multi-line and contain quotes — are escaped correctly.
print(json.dumps({
    "name": os.environ["FOUNDRY_AGENT_NAME"],
    "description": "Narrates grounded answers for the Hermes Operations Copilot.",
    "definition": {
        "kind": "prompt",
        "model": os.environ["FOUNDRY_AGENT_MODEL"],
        "instructions": os.environ["FOUNDRY_AGENT_PROMPT"],
    },
}))
PY
)

echo "create-foundry-agent: upserting '${FOUNDRY_AGENT_NAME}' on ${endpoint}"

# Foundry can return 404/409 briefly while a freshly created project
# propagates, so retry rather than failing the apply on a timing artefact.
attempt=1
max_attempts=8
while true; do
  http_status=$(curl -sS -o /tmp/foundry-agent-response.json -w '%{http_code}' \
    -X POST "${endpoint}/agents?api-version=${API_VERSION}" \
    -H "Authorization: Bearer ${token}" \
    -H 'Content-Type: application/json' \
    -d "${body}") || http_status=000

  if [[ "${http_status}" == 2* ]]; then
    echo "create-foundry-agent: done (HTTP ${http_status})"
    exit 0
  fi

  if (( attempt >= max_attempts )); then
    echo "create-foundry-agent: failed after ${attempt} attempts (HTTP ${http_status})" >&2
    cat /tmp/foundry-agent-response.json >&2 || true
    echo >&2
    echo "The platform is otherwise deployed. Create the agent by hand in the" >&2
    echo "Foundry portal, or re-run: terraform apply -replace=terraform_data.foundry_agent[0]" >&2
    exit 1
  fi

  delay=$(( attempt * 10 ))
  echo "create-foundry-agent: HTTP ${http_status}, retrying in ${delay}s (${attempt}/${max_attempts})"
  sleep "${delay}"
  attempt=$(( attempt + 1 ))
done
