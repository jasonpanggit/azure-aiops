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
#
# Optional:
#   FOUNDRY_SPECIALISTS_JSON     map of specialists (name/version/model/prompt/tools)
#   FOUNDRY_AGENT_TOOLS_JSON_B64 base64 JSON array of MCP tool definitions for
#                                this single agent (only set on the recursive
#                                per-specialist invocation)

set -euo pipefail

for var in FOUNDRY_PROJECT_ENDPOINT FOUNDRY_AGENT_NAME FOUNDRY_AGENT_MODEL \
           FOUNDRY_AGENT_PROMPT AZURE_TENANT_ID AZURE_CLIENT_ID AZURE_CLIENT_SECRET; do
  if [[ -z "${!var:-}" ]]; then
    echo "create-foundry-agent: ${var} is required" >&2
    exit 1
  fi
done

# A deployment may provide a catalog of independently released specialists.
# Reuse this idempotent single-agent path for each entry so old callers that
# provide only FOUNDRY_AGENT_NAME remain fully compatible.
if [[ -n "${FOUNDRY_SPECIALISTS_JSON:-}" ]]; then
  while IFS=$'\t' read -r specialist_name specialist_version specialist_model specialist_prompt_b64 specialist_tools_b64; do
    [[ -z "${specialist_name}" ]] && continue
    specialist_prompt=$(printf '%s' "${specialist_prompt_b64}" | python3 -c \
      'import base64,sys; print(base64.b64decode(sys.stdin.read()).decode())')
    FOUNDRY_AGENT_NAME="${specialist_name}" \
    FOUNDRY_AGENT_VERSION="${specialist_version}" \
    FOUNDRY_AGENT_MODEL="${specialist_model:-$FOUNDRY_AGENT_MODEL}" \
    FOUNDRY_AGENT_PROMPT="${specialist_prompt:-$FOUNDRY_AGENT_PROMPT}" \
    FOUNDRY_AGENT_TOOLS_JSON_B64="${specialist_tools_b64}" \
    FOUNDRY_SPECIALISTS_JSON="" \
    "$0"
  done < <(FOUNDRY_SPECIALISTS_JSON="$FOUNDRY_SPECIALISTS_JSON" python3 -c '
import base64, json, os
d = json.loads(os.environ["FOUNDRY_SPECIALISTS_JSON"])
for v in d.values():
    name = v["name"]
    version = v.get("version", "")
    model = v.get("model", "")
    prompt_b64 = base64.b64encode(v.get("prompt", "").encode()).decode()
    tools_b64 = base64.b64encode(json.dumps(v.get("tools", [])).encode()).decode()
    print(f"{name}\t{version}\t{model}\t{prompt_b64}\t{tools_b64}")
')
  exit 0
fi

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

create_body=$(
  FOUNDRY_AGENT_NAME="$FOUNDRY_AGENT_NAME" \
  FOUNDRY_AGENT_MODEL="$FOUNDRY_AGENT_MODEL" \
  FOUNDRY_AGENT_PROMPT="$FOUNDRY_AGENT_PROMPT" \
  FOUNDRY_AGENT_TOOLS_JSON_B64="${FOUNDRY_AGENT_TOOLS_JSON_B64:-}" \
  python3 - <<'PY'
import base64, json, os

definition = {
    "kind": "prompt",
    "model": os.environ["FOUNDRY_AGENT_MODEL"],
    "instructions": os.environ["FOUNDRY_AGENT_PROMPT"],
}
tools_b64 = os.environ.get("FOUNDRY_AGENT_TOOLS_JSON_B64", "")
if tools_b64:
    tools = json.loads(base64.b64decode(tools_b64).decode())
    if tools:
        definition["tools"] = tools

# Built with json.dumps rather than a heredoc so the instructions — which are
# multi-line and contain quotes — are escaped correctly.
print(json.dumps({
    "name": os.environ["FOUNDRY_AGENT_NAME"],
    "description": "Narrates grounded answers for the AIOps Operations Copilot.",
    "definition": definition,
}))
PY
)

# The versions endpoint takes only "definition" -- the agent identity (name)
# already exists, so name/description are not accepted there.
version_body=$(
  FOUNDRY_AGENT_MODEL="$FOUNDRY_AGENT_MODEL" \
  FOUNDRY_AGENT_PROMPT="$FOUNDRY_AGENT_PROMPT" \
  FOUNDRY_AGENT_TOOLS_JSON_B64="${FOUNDRY_AGENT_TOOLS_JSON_B64:-}" \
  python3 - <<'PY'
import base64, json, os

definition = {
    "kind": "prompt",
    "model": os.environ["FOUNDRY_AGENT_MODEL"],
    "instructions": os.environ["FOUNDRY_AGENT_PROMPT"],
}
tools_b64 = os.environ.get("FOUNDRY_AGENT_TOOLS_JSON_B64", "")
if tools_b64:
    tools = json.loads(base64.b64decode(tools_b64).decode())
    if tools:
        definition["tools"] = tools

print(json.dumps({"definition": definition}))
PY
)

echo "create-foundry-agent: upserting '${FOUNDRY_AGENT_NAME}' on ${endpoint}"

# Foundry can return 404/409 briefly while a freshly created project
# propagates, so retry rather than failing the apply on a timing artefact.
#
# A 409 on the create call means the agent name already exists (true for
# every re-run after the first apply). That is not a timing artefact --
# switch to adding a new version on the existing agent instead of retrying
# the same create call, which would otherwise conflict forever.
attempt=1
max_attempts=8
mode="create"
while true; do
  if [[ "${mode}" == "create" ]]; then
    url="${endpoint}/agents?api-version=${API_VERSION}"
    body="${create_body}"
  else
    url="${endpoint}/agents/${FOUNDRY_AGENT_NAME}/versions?api-version=${API_VERSION}"
    body="${version_body}"
  fi

  http_status=$(curl -sS -o /tmp/foundry-agent-response.json -w '%{http_code}' \
    -X POST "${url}" \
    -H "Authorization: Bearer ${token}" \
    -H 'Content-Type: application/json' \
    -d "${body}") || http_status=000

  if [[ "${http_status}" == 2* ]]; then
    echo "create-foundry-agent: done (HTTP ${http_status}, ${mode})"
    exit 0
  fi

  if [[ "${mode}" == "create" && "${http_status}" == "409" ]]; then
    echo "create-foundry-agent: agent already exists, adding a new version instead"
    mode="version"
    continue
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
