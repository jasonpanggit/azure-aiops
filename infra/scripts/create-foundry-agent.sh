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
#   FOUNDRY_AGENT_SPECIALIST_ID  manifest specialist ID for this invocation
#   FOUNDRY_AGENT_VERSION_RECORD tab-separated file the per-agent invocation
#                                appends
#                                "<id>\t<name>\t<actual provider version id>\t<candidate stamp>"
#                                to
#   FOUNDRY_PROMOTION_RECORD     JSON file holding the VALIDATED promotion
#                                mapping Terraform reads on a LATER plan, plus
#                                the previous promoted mapping as the rollback
#                                target (default: no record written)
#   FOUNDRY_CANDIDATE_RECORD     JSON file holding the candidate mapping this
#                                run published (default:
#                                "<promotion record>.candidate")
#   FOUNDRY_SPECIALIST_MANIFEST_DIGEST  digest of the manifest being rolled out
#   FOUNDRY_SPECIALIST_RELEASE   reviewed release stamp for the candidate set
#   FOUNDRY_MODEL_DEPLOYMENT_NAME  real Azure model deployment name, handed to
#                                the live gate so the deployed model can be
#                                checked against it
#   FOUNDRY_PARITY_VALIDATOR     path to scripts/validate_specialist_parity.py
#   FOUNDRY_PARITY_PYTHON        interpreter used to run the validator. Defaults
#                                to the repo's own .venv interpreter when it is
#                                executable, because a bare python3 on a
#                                deployment host may predate 3.11 (no tomllib)
#                                or lack the validator's imports -- which would
#                                otherwise surface only AFTER versions were
#                                already published.
#   FOUNDRY_REQUIRE_LIVE_PARITY  "1" to treat a BLOCKED live gate as fatal
#                                (default "0": the version set is created but
#                                promotion is held)
#
# Rollout order is validate -> create -> validate live -> promote:
#
#   0. The parity validator is probed for availability and offline parity must
#      pass BEFORE anything is published. A validator that cannot run is
#      reported as `validator_unavailable` -- never as a parity mismatch -- and
#      holds promotion. If the same candidate set was already published for
#      this manifest digest and release, it is NOT republished.
#   1. Every specialist gets a NEW, immutable agent version, and the ACTUAL
#      immutable provider version ID returned by Foundry is captured for each.
#      A response without a usable provider version ID fails the run closed.
#      Nothing here ever deletes or rewrites a published version, so the
#      previously promoted version -- and with it the legacy planners and the
#      deterministic orchestration mode -- stays selectable for rollback.
#   2. The live parity gate runs against those EXACT captured provider version
#      IDs (never "the latest version"). It is read-only and reports
#      pass / fail / BLOCKED (not configured).
#   3. Only then is the validated promotion record written, carrying the actual
#      provider IDs and retaining the previously promoted mapping as the
#      rollback target. A parity failure switches nothing; a blocked or
#      unavailable gate leaves the previously validated mapping in place and
#      records the new set as a candidate only.
#
# Terraform reads the promotion record on a LATER plan (see
# var.foundry_specialist_promotion_artifact), so a version created by this
# invocation can never activate in the same unvalidated apply.

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
  manifest_digest="${FOUNDRY_SPECIALIST_MANIFEST_DIGEST:-}"
  release_stamp="${FOUNDRY_SPECIALIST_RELEASE:-}"
  promotion_record="${FOUNDRY_PROMOTION_RECORD:-}"
  candidate_record="${FOUNDRY_CANDIDATE_RECORD:-}"
  if [[ -z "${candidate_record}" && -n "${promotion_record}" ]]; then
    candidate_record="${promotion_record}.candidate"
  fi
  if [[ -z "${candidate_record}" ]]; then
    candidate_record="$(mktemp)"
  fi

  specialist_count=$(FOUNDRY_SPECIALISTS_JSON="$FOUNDRY_SPECIALISTS_JSON" python3 -c '
import json, os
print(len(json.loads(os.environ["FOUNDRY_SPECIALISTS_JSON"])))
')

  # ---------------------------------------------------------------------------
  # Step 0: the validator itself.
  #
  # A bare `python3` on a deployment host may predate 3.11 (no tomllib) or
  # lack the validator's imports. Discovering that AFTER twelve agent versions
  # are published is exactly the failure this default prevents.
  # ---------------------------------------------------------------------------
  if [[ -n "${FOUNDRY_PARITY_PYTHON:-}" ]]; then
    parity_python="${FOUNDRY_PARITY_PYTHON}"
  elif [[ -x "${repo_root}/.venv/bin/python" ]]; then
    parity_python="${repo_root}/.venv/bin/python"
  else
    parity_python="python3"
  fi
  parity_validator="${FOUNDRY_PARITY_VALIDATOR:-${repo_root}/scripts/validate_specialist_parity.py}"

  parity_available=0
  if [[ -f "${parity_validator}" ]]; then
    if "${parity_python}" "${parity_validator}" --selftest >/dev/null 2>&1; then
      parity_available=1
    fi
  fi

  # No validator means no verdict -- not a mismatch. Hold, and do not
  # republish a candidate set that is already published for this exact
  # manifest digest and release: an unverifiable gate must not turn every
  # apply into a fresh round of agent versions.
  if (( parity_available == 0 )); then
    already_published=0
    if [[ -f "${candidate_record}" ]]; then
      CANDIDATE_RECORD="${candidate_record}" \
      EXPECTED_DIGEST="${manifest_digest}" \
      EXPECTED_RELEASE="${release_stamp}" \
      EXPECTED_COUNT="${specialist_count}" \
      python3 -c '
import json, os, sys

try:
    record = json.loads(open(os.environ["CANDIDATE_RECORD"], encoding="utf-8").read())
except (OSError, ValueError):
    sys.exit(1)
agents = record.get("agents") or {}
ok = (
    record.get("manifest_digest", "") == os.environ["EXPECTED_DIGEST"]
    and record.get("release", "") == os.environ["EXPECTED_RELEASE"]
    and len(agents) == int(os.environ["EXPECTED_COUNT"])
    and all(entry.get("provider_version_id") for entry in agents.values())
)
sys.exit(0 if ok else 1)
' && already_published=1 || already_published=0
    fi

    if (( already_published == 1 )); then
      echo "create-foundry-agent: parity validator_unavailable; candidate set for this manifest digest is already published, not republishing" >&2
      echo "create-foundry-agent: rollout held (parity validator_unavailable, live parity skipped)"
      exit 0
    fi

    echo "create-foundry-agent: parity validator_unavailable (interpreter or import failure); parity was NOT evaluated and promotion is held" >&2
  fi

  # ---------------------------------------------------------------------------
  # Step 1: offline parity, before anything is published. Offline parity needs
  # no credentials and no network, so there is no reason to publish first.
  # ---------------------------------------------------------------------------
  parity_offline="unavailable"
  if (( parity_available == 1 )); then
    if "${parity_python}" "${parity_validator}" --offline >/dev/null; then
      parity_offline="pass"
    else
      echo "create-foundry-agent: offline specialist parity did not pass; nothing published, promotion held" >&2
      echo "create-foundry-agent: re-run the validator with --offline for the controlled report" >&2
      exit 1
    fi
  fi

  # ---------------------------------------------------------------------------
  # Step 2: publish the candidate versions and capture the ACTUAL immutable
  # provider version ID Foundry returns for each one.
  # ---------------------------------------------------------------------------
  version_record="$(mktemp)"
  trap 'rm -f "${version_record}"' EXIT

  while IFS=$'\t' read -r specialist_id specialist_name specialist_version specialist_model specialist_prompt_b64 specialist_tools_b64; do
    [[ -z "${specialist_name}" ]] && continue
    specialist_prompt=$(printf '%s' "${specialist_prompt_b64}" | python3 -c \
      'import base64,sys; print(base64.b64decode(sys.stdin.read()).decode())')
    FOUNDRY_AGENT_SPECIALIST_ID="${specialist_id}" \
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
for specialist_id, v in d.items():
    name = v["name"]
    version = v.get("version", "")
    model = v.get("model", "")
    prompt_b64 = base64.b64encode(v.get("prompt", "").encode()).decode()
    tools_b64 = base64.b64encode(json.dumps(v.get("tools", [])).encode()).decode()
    print(f"{specialist_id}\t{name}\t{version}\t{model}\t{prompt_b64}\t{tools_b64}")
')

  # The candidate mapping: specialist ID -> agent name + ACTUAL provider
  # version ID. This is what the live gate validates and, if it passes, what
  # becomes the promoted mapping. It is written before the gate runs so an
  # interrupted run still records exactly what was published.
  CANDIDATE_RECORD="${candidate_record}" \
  VERSION_RECORD="${version_record}" \
  MANIFEST_DIGEST="${manifest_digest}" \
  RELEASE_STAMP="${release_stamp}" \
  python3 -c '
import json, os, pathlib

agents = {}
for line in pathlib.Path(os.environ["VERSION_RECORD"]).read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    specialist_id, name, provider_version_id, candidate_version = (
        line.split("\t") + ["", "", "", ""]
    )[:4]
    agents[specialist_id or name] = {
        "agent_name": name,
        "provider_version_id": provider_version_id,
        "candidate_version": candidate_version,
    }

pathlib.Path(os.environ["CANDIDATE_RECORD"]).write_text(
    json.dumps(
        {
            "status": "candidate",
            "promotion": "held",
            "reason": "not_yet_validated",
            "manifest_digest": os.environ["MANIFEST_DIGEST"],
            "release": os.environ["RELEASE_STAMP"],
            "agent_count": len(agents),
            "agents": agents,
        },
        indent=2,
        sort_keys=True,
    ),
    encoding="utf-8",
)
'

  # ---------------------------------------------------------------------------
  # Step 3: the live gate, pinned to the exact provider version IDs above.
  # Read-only, and it runs only after every immutable version already exists --
  # so a hold leaves the new definitions published but unpromoted, never
  # half-switched.
  # ---------------------------------------------------------------------------
  parity_live="skipped"
  if (( parity_available == 1 )); then
    set +e
    FOUNDRY_CANDIDATE_MAPPING="${candidate_record}" \
      "${parity_python}" "${parity_validator}" --live \
      --candidate-mapping "${candidate_record}" >/dev/null
    live_status=$?
    set -e
    case "${live_status}" in
      0) parity_live="pass" ;;
      3) parity_live="blocked" ;;
      *) parity_live="fail" ;;
    esac
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
  # Step 4: the promotion decision. Writing a "validated" record is the only
  # promotion signal, and Terraform consumes it on a LATER plan. The
  # previously promoted mapping is retained verbatim as the rollback target.
  # ---------------------------------------------------------------------------
  promotion="promoted"
  reason="live_parity_verified"
  if (( parity_available == 0 )); then
    promotion="held"
    reason="validator_unavailable"
  elif [[ "${parity_offline}" != "pass" ]]; then
    promotion="held"
    reason="offline_parity_not_verified"
  elif [[ "${parity_live}" != "pass" ]]; then
    promotion="held"
    reason="live_parity_blocked"
  fi

  if [[ -n "${promotion_record}" ]]; then
    PROMOTION_STATUS="${promotion}" \
    PROMOTION_REASON="${reason}" \
    PARITY_OFFLINE="${parity_offline}" \
    PARITY_LIVE="${parity_live}" \
    CANDIDATE_RECORD="${candidate_record}" \
    MANIFEST_DIGEST="${manifest_digest}" \
    RELEASE_STAMP="${release_stamp}" \
    RECORD_PATH="${promotion_record}" \
    python3 -c '
import json, os, pathlib

promotion_record_path = pathlib.Path(os.environ["RECORD_PATH"])
previous = {}
if promotion_record_path.exists():
    try:
        previous = json.loads(promotion_record_path.read_text(encoding="utf-8"))
    except ValueError:
        previous = {}

candidate = json.loads(
    pathlib.Path(os.environ["CANDIDATE_RECORD"]).read_text(encoding="utf-8")
)
candidate_agents = candidate.get("agents") or {}
previous_agents = previous.get("agents") or {}
promotion = os.environ["PROMOTION_STATUS"]
reason = os.environ["PROMOTION_REASON"]

if promotion == "promoted":
    # The gate passed against these exact provider IDs: they become the
    # activated mapping and the previous one becomes the rollback target.
    agents = candidate_agents
    rollback = previous_agents
    rollback_manifest_digest = previous.get("manifest_digest", "")
    manifest_digest = os.environ["MANIFEST_DIGEST"]
    release = os.environ["RELEASE_STAMP"]
else:
    # A held rollout never moves candidates into the activated position and
    # never destroys the mapping the running revision depends on.
    agents = previous_agents
    rollback = previous.get("rollback_target") or {}
    rollback_manifest_digest = previous.get("rollback_manifest_digest", "")
    manifest_digest = previous.get("manifest_digest", "")
    release = previous.get("release", "")

record = {
    "status": "validated" if agents else "held",
    "promotion": promotion,
    "reason": reason,
    "manifest_digest": manifest_digest,
    "release": release,
    "parity": {
        "offline": os.environ["PARITY_OFFLINE"],
        "live": os.environ["PARITY_LIVE"],
    },
    "agents": agents,
    "agent_count": len(agents),
    "previous_version": previous_agents,
    "rollback_target": rollback,
    "rollback_manifest_digest": rollback_manifest_digest,
    "candidate": {
        "promotion": promotion,
        "reason": reason,
        "manifest_digest": candidate.get("manifest_digest", ""),
        "release": candidate.get("release", ""),
        "agents": candidate_agents,
    },
}
promotion_record_path.write_text(
    json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
)
'
  fi

  echo "create-foundry-agent: rollout ${promotion} (${reason}; offline parity ${parity_offline}, live parity ${parity_live})"
  exit 0
fi

API_VERSION="${FOUNDRY_API_VERSION:-v1}"
endpoint="${FOUNDRY_PROJECT_ENDPOINT%/}"

# Each invocation gets its own response file: a shared /tmp path would race
# under the per-specialist fan-out and could attribute one agent's provider
# version ID to another.
response_file="$(mktemp)"
trap 'rm -f "${response_file}"' EXIT

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

  http_status=$(curl -sS -o "${response_file}" -w '%{http_code}' \
    -X POST "${url}" \
    -H "Authorization: Bearer ${token}" \
    -H 'Content-Type: application/json' \
    -d "${body}") || http_status=000

  if [[ "${http_status}" == 2* ]]; then
    # Additive and immutable: the create path publishes the first version, the
    # version path publishes the next one. Neither replaces a published
    # definition, so the prior version stays selectable for rollback.
    #
    # The ACTUAL immutable provider version ID is whatever the service
    # returned for this version -- never the synthetic
    # "<release>.<contract version>" stamp we asked for. The runtime selects a
    # version by that provider ID, so recording our own label instead would
    # promote something that was never validated. A response that carries no
    # usable provider version ID fails the run closed.
    set +e
    provider_version_id=$(
      RESPONSE_FILE="${response_file}" python3 -c '
import json, os, re, sys

try:
    payload = json.loads(open(os.environ["RESPONSE_FILE"], encoding="utf-8").read())
except (OSError, ValueError):
    sys.exit(2)
if not isinstance(payload, dict):
    sys.exit(2)

# Ordered by specificity: the version resource own identifier first, the
# fully-qualified resource id last.
for key in ("version", "agentVersion", "agent_version", "versionId", "version_id", "id"):
    value = payload.get(key)
    if isinstance(value, str):
        normalized = value.strip()
        if key == "id":
            normalized = normalized.rstrip("/").rsplit("/", 1)[-1]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", normalized):
            print(normalized)
            sys.exit(0)
sys.exit(3)
'
    )
    capture_status=$?
    set -e

    if (( capture_status != 0 )) || [[ -z "${provider_version_id}" ]]; then
      echo "create-foundry-agent: '${FOUNDRY_AGENT_NAME}' was published but the response carried no usable immutable provider version id; failing closed" >&2
      exit 1
    fi

    if [[ -n "${FOUNDRY_AGENT_VERSION_RECORD:-}" ]]; then
      printf '%s\t%s\t%s\t%s\n' \
        "${FOUNDRY_AGENT_SPECIALIST_ID:-}" \
        "${FOUNDRY_AGENT_NAME}" \
        "${provider_version_id}" \
        "${FOUNDRY_AGENT_VERSION:-}" \
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
    cat "${response_file}" >&2 || true
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
