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
#   FOUNDRY_AGENT_VERSION_RECORD tab-separated file the per-agent invocation
#                                appends "<name>\t<contract version>" to
#   FOUNDRY_PROMOTION_RECORD     JSON file recording which specialist version
#                                set is promoted, and the previous one as the
#                                rollback target (default: no record written)
#   FOUNDRY_PARITY_VALIDATOR     path to scripts/validate_specialist_parity.py
#   FOUNDRY_PARITY_PYTHON        interpreter used to run the validator
#   FOUNDRY_REQUIRE_LIVE_PARITY  "1" to treat a BLOCKED live gate as fatal
#                                (default "0": the version set is created but
#                                promotion is held)
#
# Rollout order is create -> validate -> switch:
#
#   1. Every specialist gets a NEW, immutable agent version. Nothing here ever
#      deletes or rewrites a published version, so the previously promoted
#      version -- and with it the legacy planners and the deterministic
#      orchestration mode -- stays selectable for rollback.
#   2. The parity gate runs. Offline parity must pass. Live parity is
#      read-only and reports pass / fail / BLOCKED (not configured).
#   3. Only then is the promotion record written. A parity failure switches
#      nothing; a blocked live gate holds the switch rather than claiming a
#      verification that did not happen.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

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
  version_record="$(mktemp)"
  trap 'rm -f "${version_record}"' EXIT

  while IFS=$'\t' read -r specialist_name specialist_version specialist_model specialist_prompt_b64 specialist_tools_b64; do
    [[ -z "${specialist_name}" ]] && continue
    specialist_prompt=$(printf '%s' "${specialist_prompt_b64}" | python3 -c \
      'import base64,sys; print(base64.b64decode(sys.stdin.read()).decode())')
    FOUNDRY_AGENT_NAME="${specialist_name}" \
    FOUNDRY_AGENT_VERSION="${specialist_version}" \
    FOUNDRY_AGENT_MODEL="${specialist_model:-$FOUNDRY_AGENT_MODEL}" \
    FOUNDRY_AGENT_PROMPT="${specialist_prompt:-$FOUNDRY_AGENT_PROMPT}" \
    FOUNDRY_AGENT_TOOLS_JSON_B64="${specialist_tools_b64}" \
    FOUNDRY_AGENT_VERSION_RECORD="${version_record}" \
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

  # ---------------------------------------------------------------------------
  # Step 2: parity gate. Read-only, and it runs only after every immutable
  # version above already exists -- so a hold leaves the new definitions
  # published but unpromoted, never half-switched.
  # ---------------------------------------------------------------------------
  parity_validator="${FOUNDRY_PARITY_VALIDATOR:-${repo_root}/scripts/validate_specialist_parity.py}"
  parity_python="${FOUNDRY_PARITY_PYTHON:-python3}"
  parity_offline="unavailable"
  parity_live="skipped"

  if [[ -f "${parity_validator}" ]]; then
    if "${parity_python}" "${parity_validator}" --offline >/dev/null; then
      parity_offline="pass"
    else
      echo "create-foundry-agent: offline specialist parity failed; promotion held" >&2
      echo "create-foundry-agent: re-run the validator with --offline for the controlled report" >&2
      exit 1
    fi

    set +e
    "${parity_python}" "${parity_validator}" --live >/dev/null
    live_status=$?
    set -e
    case "${live_status}" in
      0) parity_live="pass" ;;
      3) parity_live="blocked" ;;
      *) parity_live="fail" ;;
    esac
  else
    echo "create-foundry-agent: parity validator not found; promotion held" >&2
  fi

  if [[ "${parity_live}" == "fail" ]]; then
    echo "create-foundry-agent: live specialist parity failed; promotion held" >&2
    exit 1
  fi

  if [[ "${parity_live}" == "blocked" && "${FOUNDRY_REQUIRE_LIVE_PARITY:-0}" == "1" ]]; then
    echo "create-foundry-agent: live specialist parity is BLOCKED and required; promotion held" >&2
    exit 1
  fi

  # ---------------------------------------------------------------------------
  # Step 3: the metadata switch. Writing this record is the only promotion
  # signal; the previously promoted version set is retained verbatim as the
  # rollback target.
  # ---------------------------------------------------------------------------
  promotion="promoted"
  if [[ "${parity_offline}" != "pass" || "${parity_live}" == "blocked" ]]; then
    promotion="held"
  fi

  if [[ -n "${FOUNDRY_PROMOTION_RECORD:-}" ]]; then
    PROMOTION_STATUS="${promotion}" \
    PARITY_OFFLINE="${parity_offline}" \
    PARITY_LIVE="${parity_live}" \
    VERSION_RECORD="${version_record}" \
    RECORD_PATH="${FOUNDRY_PROMOTION_RECORD}" \
    python3 -c '
import json, os, pathlib

record_path = pathlib.Path(os.environ["RECORD_PATH"])
previous = {}
if record_path.exists():
    try:
        previous = json.loads(record_path.read_text(encoding="utf-8"))
    except ValueError:
        previous = {}

agents = []
for line in pathlib.Path(os.environ["VERSION_RECORD"]).read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    name, _, version = line.partition("\t")
    agents.append({"name": name, "version": version})
agents.sort(key=lambda entry: entry["name"])

# Never overwrite a good rollback target with a held rollout: the previously
# promoted set stays the thing to fall back to.
if previous.get("status") == "promoted":
    rollback = previous.get("agents", [])
else:
    rollback = previous.get("rollback_target", [])

record = {
    "status": os.environ["PROMOTION_STATUS"],
    "parity": {
        "offline": os.environ["PARITY_OFFLINE"],
        "live": os.environ["PARITY_LIVE"],
    },
    "agents": agents,
    "agent_count": len(agents),
    "previous_version": previous.get("agents", []),
    "rollback_target": rollback,
}
record_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
'
  fi

  echo "create-foundry-agent: rollout ${promotion} (offline parity ${parity_offline}, live parity ${parity_live})"
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
    # Additive and immutable: the create path publishes the first version, the
    # version path publishes the next one. Neither replaces a published
    # definition, so the prior version stays selectable for rollback.
    if [[ -n "${FOUNDRY_AGENT_VERSION_RECORD:-}" ]]; then
      printf '%s\t%s\n' "${FOUNDRY_AGENT_NAME}" "${FOUNDRY_AGENT_VERSION:-}" \
        >>"${FOUNDRY_AGENT_VERSION_RECORD}"
    fi
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
