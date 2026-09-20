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
#                                required by the default client_credentials
#                                authentication mode
#
# Optional:
#   FOUNDRY_AUTH_MODE            "client_credentials" (default) or "azure_cli";
#                                azure_cli uses the current Azure CLI login and
#                                never reads AZURE_CLIENT_SECRET
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
#   FOUNDRY_OPERATIONS_MCP_CONNECTION_ID
#                                exact Terraform-created Operations MCP project
#                                connection resource ID captured in the mapping
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
           FOUNDRY_AGENT_PROMPT; do
  if [[ -z "${!var:-}" ]]; then
    echo "create-foundry-agent: ${var} is required" >&2
    exit 1
  fi
done

auth_mode="${FOUNDRY_AUTH_MODE:-client_credentials}"
case "${auth_mode}" in
  client_credentials)
    for var in AZURE_TENANT_ID AZURE_CLIENT_ID AZURE_CLIENT_SECRET; do
      if [[ -z "${!var:-}" ]]; then
        echo "create-foundry-agent: ${var} is required for client_credentials authentication" >&2
        exit 1
      fi
    done
    ;;
  azure_cli)
    if ! command -v az >/dev/null 2>&1; then
      echo "create-foundry-agent: az is required for azure_cli authentication" >&2
      exit 1
    fi
    ;;
  *)
    echo "create-foundry-agent: unsupported FOUNDRY_AUTH_MODE '${auth_mode}'" >&2
    exit 1
    ;;
esac

# The ontology curator is a security boundary, not a general specialist.  A
# hand-edited Terraform payload must not be able to add a writer/general-query
# tool or silently change its reviewed model before the request reaches
# Foundry.
if [[ "${FOUNDRY_AGENT_SPECIALIST_ID:-}" == "ontology_curator" ]]; then
  if [[ "${FOUNDRY_AGENT_MODEL}" != "${FOUNDRY_EXPECTED_CURATOR_MODEL:-gpt-5.4-mini}" ]]; then
    echo "create-foundry-agent: ontology_curator model mismatch" >&2
    exit 1
  fi
  FOUNDRY_AGENT_TOOLS_JSON_B64="${FOUNDRY_AGENT_TOOLS_JSON_B64:-}" \
  FOUNDRY_EXPECTED_CURATOR_TOOL_NAMES="${FOUNDRY_EXPECTED_CURATOR_TOOL_NAMES:-}" \
  python3 -c '
import base64
import json
import os

expected = [item for item in os.environ["FOUNDRY_EXPECTED_CURATOR_TOOL_NAMES"].split(",") if item]
if len(expected) != 4 or len(set(expected)) != 4:
    raise SystemExit("ontology_curator requires exactly four distinct expected tools")
try:
    definitions = json.loads(
        base64.b64decode(os.environ["FOUNDRY_AGENT_TOOLS_JSON_B64"], validate=True)
    )
except (ValueError, json.JSONDecodeError) as exc:
    raise SystemExit("ontology_curator tool payload is invalid") from exc
if not isinstance(definitions, list) or len(definitions) != 1:
    raise SystemExit("ontology_curator requires exactly one MCP tool definition")
definition = definitions[0]
if not isinstance(definition, dict) or definition.get("type") != "mcp":
    raise SystemExit("ontology_curator accepts only the Operations MCP tool type")
if definition.get("allowed_tools") != expected:
    raise SystemExit("ontology_curator tool allowlist mismatch")
' || exit 1
fi

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

  # A specialist candidate is not publishable unless the governed Operations
  # MCP connection is identified by its exact project-connection resource ID.
  FOUNDRY_OPERATIONS_MCP_CONNECTION_ID="${FOUNDRY_OPERATIONS_MCP_CONNECTION_ID:-}" \
  FOUNDRY_AI_SEARCH_CONNECTION_ID="${FOUNDRY_AI_SEARCH_CONNECTION_ID:-}" \
  FOUNDRY_AI_SEARCH_INDEX_NAME="${FOUNDRY_AI_SEARCH_INDEX_NAME:-}" \
  OPERATIONS_MCP_SERVER_URL="${OPERATIONS_MCP_SERVER_URL:-}" \
  FOUNDRY_SPECIALISTS_JSON="${FOUNDRY_SPECIALISTS_JSON}" \
  python3 -c '
import json, os, re

pattern = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
    r"Microsoft\.CognitiveServices/accounts/[^/]+/projects/[^/]+/"
    r"connections/[^/]+$",
    re.IGNORECASE,
)
operations_connection = os.environ["FOUNDRY_OPERATIONS_MCP_CONNECTION_ID"].strip().rstrip("/")
search_connection = os.environ["FOUNDRY_AI_SEARCH_CONNECTION_ID"].strip().rstrip("/")
operations_url = os.environ["OPERATIONS_MCP_SERVER_URL"].strip().rstrip("/")
search_index = os.environ["FOUNDRY_AI_SEARCH_INDEX_NAME"].strip()
if not pattern.fullmatch(operations_connection):
    raise SystemExit(
        "create-foundry-agent: exact Operations MCP project connection ID is required"
    )
if not pattern.fullmatch(search_connection) or search_connection.casefold() == operations_connection.casefold():
    raise SystemExit(
        "create-foundry-agent: exact distinct Azure AI Search project connection ID is required"
    )
if not operations_url.startswith("https://") or not operations_url.endswith("/operations-mcp"):
    raise SystemExit("create-foundry-agent: exact Operations MCP server URL is required")
if not search_index:
    raise SystemExit("create-foundry-agent: Azure AI Search index name is required")
specialists = json.loads(os.environ["FOUNDRY_SPECIALISTS_JSON"])
if not isinstance(specialists, dict) or len(specialists) != 12:
    raise SystemExit("create-foundry-agent: exact twelve-specialist payload is required")
for specialist_id, specialist in specialists.items():
    tools = specialist.get("tools") if isinstance(specialist, dict) else None
    if not isinstance(tools, list) or len(tools) != 2:
        raise SystemExit(f"create-foundry-agent: {specialist_id} requires exactly Operations MCP and Azure AI Search")
    operations = [tool for tool in tools if isinstance(tool, dict) and tool.get("type") == "mcp"]
    searches = [tool for tool in tools if isinstance(tool, dict) and tool.get("type") == "azure_ai_search"]
    if len(operations) != 1 or len(searches) != 1:
        raise SystemExit(f"create-foundry-agent: {specialist_id} has an unexpected tool definition")
    operation = operations[0]
    if (
        operation.get("server_label") != "operations-mcp"
        or operation.get("server_url", "").rstrip("/") != operations_url
        or operation.get("require_approval") != "never"
        or operation.get("project_connection_id", "").rstrip("/") != operations_connection
        or not isinstance(operation.get("allowed_tools"), list)
    ):
        raise SystemExit(f"create-foundry-agent: {specialist_id} Operations MCP boundary mismatch")
    indexes = (searches[0].get("azure_ai_search") or {}).get("indexes")
    if (
        not isinstance(indexes, list)
        or len(indexes) != 1
        or indexes[0].get("project_connection_id", "").rstrip("/") != search_connection
        or indexes[0].get("index_name") != search_index
        or indexes[0].get("query_type") != "vector_semantic_hybrid"
    ):
        raise SystemExit(f"create-foundry-agent: {specialist_id} Azure AI Search boundary mismatch")
' || exit 1

  if [[ -n "${promotion_record}" && -f "${promotion_record}" ]]; then
    if ! PROMOTION_RECORD="${promotion_record}" python3 -c '
import json, os

with open(os.environ["PROMOTION_RECORD"], encoding="utf-8") as handle:
    payload = json.load(handle)
if not isinstance(payload, dict):
    raise TypeError("promotion artifact must contain a JSON object")
' >/dev/null 2>&1; then
      echo "create-foundry-agent: existing promotion artifact is unreadable; refusing to publish or overwrite it" >&2
      exit 1
    fi
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
coordinator = record.get("coordinator") or {}
ok = (
    record.get("manifest_digest", "") == os.environ["EXPECTED_DIGEST"]
    and record.get("release", "") == os.environ["EXPECTED_RELEASE"]
    and len(agents) == int(os.environ["EXPECTED_COUNT"])
    and all(entry.get("provider_version_id") for entry in agents.values())
    and coordinator.get("provider_version_id")
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

  resume_candidate="${FOUNDRY_RESUME_CANDIDATE:-0}"
  if [[ "${resume_candidate}" == "1" ]]; then
    if [[ ! -f "${candidate_record}" ]]; then
      echo "create-foundry-agent: resume candidate is missing" >&2
      exit 1
    fi
    echo "create-foundry-agent: resuming exact published candidate without provider writes"
  elif [[ "${resume_candidate}" != "0" ]]; then
    echo "create-foundry-agent: FOUNDRY_RESUME_CANDIDATE must be 0 or 1" >&2
    exit 1
  else
  # ---------------------------------------------------------------------------
  # Step 2: publish the candidate versions and capture the ACTUAL immutable
  # provider version ID Foundry returns for each one.
  # ---------------------------------------------------------------------------
  version_record="$(mktemp)"
  trap 'rm -f "${version_record}"' EXIT

  # The shared Operations Copilot narrator is versioned alongside the page
  # specialists. Active and rollback revisions pin it through the same
  # validated artifact rather than resolving its name to "latest".
  FOUNDRY_AGENT_SPECIALIST_ID="operations_copilot" \
  FOUNDRY_AGENT_VERSION="${release_stamp:+${release_stamp}.}coordinator" \
  FOUNDRY_AGENT_VERSION_RECORD="${version_record}" \
  FOUNDRY_SPECIALISTS_JSON="" \
  "$0"

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
  OPERATIONS_CONNECTION_ID="${FOUNDRY_OPERATIONS_MCP_CONNECTION_ID}" \
  SEARCH_CONNECTION_ID="${FOUNDRY_AI_SEARCH_CONNECTION_ID}" \
  SEARCH_INDEX_NAME="${FOUNDRY_AI_SEARCH_INDEX_NAME}" \
  python3 -c '
import json, os, pathlib

agents = {}
coordinator = {}
for line in pathlib.Path(os.environ["VERSION_RECORD"]).read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    specialist_id, name, provider_version_id, candidate_version = (
        line.split("\t") + ["", "", "", ""]
    )[:4]
    entry = {
        "agent_name": name,
        "provider_version_id": provider_version_id,
        "candidate_version": candidate_version,
    }
    if specialist_id == "operations_copilot":
        coordinator = entry
    else:
        agents[specialist_id or name] = entry

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
            "coordinator": coordinator,
            "connections": {
                "operations-mcp": {
                    "project_connection_id": os.environ["OPERATIONS_CONNECTION_ID"],
                },
            },
            "search": {
                "project_connection_id": os.environ["SEARCH_CONNECTION_ID"],
                "index_name": os.environ["SEARCH_INDEX_NAME"],
                "query_type": "vector_semantic_hybrid",
                "cardinality": 1,
            },
        },
        indent=2,
        sort_keys=True,
    ),
    encoding="utf-8",
)
'
  fi

  # Snapshot and normalize the candidate exactly once. Live parity and
  # promotion consume only this private snapshot, never the mutable source
  # path. The original byte digest is checked again after parity.
  candidate_snapshot="$(mktemp "${TMPDIR:-/tmp}/foundry-candidate-snapshot.XXXXXX")"
  chmod 600 "${candidate_snapshot}"
  trap 'rm -f "${version_record:-}" "${candidate_snapshot:-}"' EXIT
  read -r candidate_source_digest candidate_snapshot_digest < <(
    CANDIDATE_RECORD="${candidate_record}" \
    SNAPSHOT_RECORD="${candidate_snapshot}" \
    EXPECTED_DIGEST="${manifest_digest}" \
    EXPECTED_RELEASE="${release_stamp}" \
    EXPECTED_SPECIALISTS="${FOUNDRY_SPECIALISTS_JSON}" \
    EXPECTED_COORDINATOR_NAME="${FOUNDRY_AGENT_NAME}" \
    EXPECTED_OPERATIONS_CONNECTION_ID="${FOUNDRY_OPERATIONS_MCP_CONNECTION_ID}" \
    EXPECTED_SEARCH_CONNECTION_ID="${FOUNDRY_AI_SEARCH_CONNECTION_ID}" \
    EXPECTED_SEARCH_INDEX_NAME="${FOUNDRY_AI_SEARCH_INDEX_NAME}" \
    python3 - <<'PY'
import hashlib
import json
import os
import pathlib
import re

path = pathlib.Path(os.environ["CANDIDATE_RECORD"])
try:
    source_bytes = path.read_bytes()
    candidate = json.loads(source_bytes)
    expected = json.loads(os.environ["EXPECTED_SPECIALISTS"])
except (OSError, ValueError):
    raise SystemExit("create-foundry-agent: candidate is unreadable")
if not isinstance(candidate, dict) or not isinstance(expected, dict):
    raise SystemExit("create-foundry-agent: candidate is malformed")
agents = candidate.get("agents")
coordinator = candidate.get("coordinator")
connections = candidate.get("connections")
if (
    candidate.get("manifest_digest") != os.environ["EXPECTED_DIGEST"]
    or candidate.get("release") != os.environ["EXPECTED_RELEASE"]
    or not isinstance(agents, dict)
    or set(agents) != set(expected)
    or not isinstance(coordinator, dict)
    or set(connections or {}) != {"operations-mcp"}
):
    raise SystemExit("create-foundry-agent: candidate identity mismatch")

agent_names = {
    definition.get("name", "").casefold()
    for definition in expected.values()
    if isinstance(definition, dict)
}
agent_names.add(os.environ["EXPECTED_COORDINATOR_NAME"].casefold())
candidate_stamps = {
    definition.get("version", "").casefold()
    for definition in expected.values()
    if isinstance(definition, dict)
}
candidate_stamps.add((os.environ["EXPECTED_RELEASE"] + ".coordinator").casefold())
provider_id_pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
credential_markers = (
    "access_token",
    "bearer",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
)

def normalized_provider_id(value, expected_agent_name):
    if not isinstance(value, str) or value != value.strip():
        raise SystemExit("create-foundry-agent: candidate provider version id is malformed")
    normalized = value
    if "/" in normalized:
        parts = [part for part in normalized.split("/") if part]
        if (
            len(parts) < 4
            or parts[-4].casefold() != "agents"
            or parts[-3].casefold() != expected_agent_name.casefold()
            or parts[-2].casefold() != "versions"
        ):
            raise SystemExit("create-foundry-agent: unqualified candidate resource id")
        normalized = parts[-1]
    folded = normalized.casefold()
    if (
        not provider_id_pattern.fullmatch(normalized)
        or folded == "latest"
        or folded in agent_names
        or folded in candidate_stamps
        or any(marker in folded for marker in credential_markers)
    ):
        raise SystemExit("create-foundry-agent: candidate provider version id is not immutable")
    return normalized

normalized_provider_identities = []
for specialist_id, definition in expected.items():
    entry = agents.get(specialist_id)
    if (
        not isinstance(entry, dict)
        or entry.get("agent_name") != definition.get("name")
        or entry.get("candidate_version") != definition.get("version")
    ):
        raise SystemExit("create-foundry-agent: candidate specialist mismatch")
    entry["provider_version_id"] = normalized_provider_id(
        entry.get("provider_version_id"),
        definition.get("name", ""),
    )
    normalized_provider_identities.append(
        (
            definition.get("name", "").casefold(),
            entry["provider_version_id"].casefold(),
        )
    )
if (
    coordinator.get("agent_name") != os.environ["EXPECTED_COORDINATOR_NAME"]
    or coordinator.get("candidate_version")
    != os.environ["EXPECTED_RELEASE"] + ".coordinator"
):
    raise SystemExit("create-foundry-agent: candidate coordinator mismatch")
coordinator["provider_version_id"] = normalized_provider_id(
    coordinator.get("provider_version_id"),
    os.environ["EXPECTED_COORDINATOR_NAME"],
)
normalized_provider_identities.append(
    (
        os.environ["EXPECTED_COORDINATOR_NAME"].casefold(),
        coordinator["provider_version_id"].casefold(),
    )
)
if len(normalized_provider_identities) != len(set(normalized_provider_identities)):
    raise SystemExit(
        "create-foundry-agent: candidate agent-qualified provider identities must be unique"
    )
if (
    connections["operations-mcp"].get("project_connection_id", "").rstrip("/")
    != os.environ["EXPECTED_OPERATIONS_CONNECTION_ID"].rstrip("/")
):
    raise SystemExit("create-foundry-agent: candidate Operations MCP connection mismatch")
expected_search = {
    "project_connection_id": os.environ["EXPECTED_SEARCH_CONNECTION_ID"],
    "index_name": os.environ["EXPECTED_SEARCH_INDEX_NAME"],
    "query_type": "vector_semantic_hybrid",
    "cardinality": 1,
}
if candidate.get("search") != expected_search:
    raise SystemExit("create-foundry-agent: candidate Azure AI Search metadata mismatch")
if "azure-mcp" in source_bytes.decode("utf-8").casefold():
    raise SystemExit("create-foundry-agent: candidate contains Azure MCP")
snapshot = json.dumps(candidate, indent=2, sort_keys=True).encode("utf-8") + b"\n"
pathlib.Path(os.environ["SNAPSHOT_RECORD"]).write_bytes(snapshot)
os.chmod(os.environ["SNAPSHOT_RECORD"], 0o400)
print(
    hashlib.sha256(source_bytes).hexdigest(),
    hashlib.sha256(snapshot).hexdigest(),
)
PY
  )

  # ---------------------------------------------------------------------------
  # Step 3: the live gate, pinned to the exact provider version IDs above.
  # Read-only, and it runs only after every immutable version already exists --
  # so a hold leaves the new definitions published but unpromoted, never
  # half-switched.
  # ---------------------------------------------------------------------------
  parity_live="skipped"
  if (( parity_available == 1 )); then
    set +e
    FOUNDRY_CANDIDATE_MAPPING="${candidate_snapshot}" \
      "${parity_python}" "${parity_validator}" --live \
      --candidate-mapping "${candidate_snapshot}" >/dev/null
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

  read -r current_candidate_digest current_snapshot_digest < <(
    CANDIDATE_RECORD="${candidate_record}" \
    SNAPSHOT_RECORD="${candidate_snapshot}" \
    python3 -c '
import hashlib, os, pathlib
print(
    hashlib.sha256(pathlib.Path(os.environ["CANDIDATE_RECORD"]).read_bytes()).hexdigest(),
    hashlib.sha256(pathlib.Path(os.environ["SNAPSHOT_RECORD"]).read_bytes()).hexdigest(),
)
'
  )
  if [[
    "${current_candidate_digest}" != "${candidate_source_digest}" ||
    "${current_snapshot_digest}" != "${candidate_snapshot_digest}"
  ]]; then
    echo "create-foundry-agent: candidate changed during live parity; promotion held" >&2
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
    CANDIDATE_RECORD="${candidate_snapshot}" \
    CANDIDATE_SNAPSHOT_DIGEST="${candidate_snapshot_digest}" \
    MANIFEST_DIGEST="${manifest_digest}" \
    RELEASE_STAMP="${release_stamp}" \
    ROLLBACK_ROTATION="${FOUNDRY_ROLLBACK_ROTATION:-}" \
    RECORD_PATH="${promotion_record}" \
    python3 -c '
import hashlib, json, os, pathlib, tempfile

promotion_record_path = pathlib.Path(os.environ["RECORD_PATH"])
previous = {}
if promotion_record_path.exists():
    previous = json.loads(promotion_record_path.read_text(encoding="utf-8"))

candidate_bytes = pathlib.Path(os.environ["CANDIDATE_RECORD"]).read_bytes()
if hashlib.sha256(candidate_bytes).hexdigest() != os.environ["CANDIDATE_SNAPSHOT_DIGEST"]:
    raise SystemExit("create-foundry-agent: candidate snapshot changed after live parity")
candidate = json.loads(candidate_bytes)
candidate_agents = candidate.get("agents") or {}
candidate_coordinator = candidate.get("coordinator") or {}
candidate_connections = candidate.get("connections") or {}
previous_agents = previous.get("agents") or {}
previous_coordinator = previous.get("coordinator") or {}
previous_connections = previous.get("connections") or {}
promotion = os.environ["PROMOTION_STATUS"]
reason = os.environ["PROMOTION_REASON"]
requested_rotation = os.environ.get("ROLLBACK_ROTATION", "")
previous_rotation = previous.get("rollback_rotation", "")
rotate_rollback = bool(requested_rotation) and requested_rotation != previous_rotation

if promotion == "promoted":
    # The gate passed against these exact provider IDs: they become the
    # activated mapping and the previous one becomes the rollback target.
    agents = candidate_agents
    coordinator = candidate_coordinator
    connections = candidate_connections
    if rotate_rollback or not previous.get("rollback_target"):
        rollback = previous_agents
        rollback_coordinator = previous_coordinator
        rollback_manifest_digest = previous.get("manifest_digest", "")
        rollback_status = previous.get("status", "")
    else:
        rollback = previous.get("rollback_target") or {}
        rollback_coordinator = previous.get("rollback_coordinator") or {}
        rollback_manifest_digest = previous.get("rollback_manifest_digest", "")
        rollback_status = previous.get("rollback_status", "")
    manifest_digest = os.environ["MANIFEST_DIGEST"]
    release = os.environ["RELEASE_STAMP"]
    rollback_rotation = requested_rotation if rotate_rollback else previous_rotation
else:
    # A held rollout never moves candidates into the activated position and
    # never destroys the mapping the running revision depends on.
    agents = previous_agents
    coordinator = previous_coordinator
    connections = previous_connections
    rollback = previous.get("rollback_target") or {}
    rollback_coordinator = previous.get("rollback_coordinator") or {}
    rollback_manifest_digest = previous.get("rollback_manifest_digest", "")
    rollback_status = previous.get("rollback_status", "")
    manifest_digest = previous.get("manifest_digest", "")
    release = previous.get("release", "")
    rollback_rotation = previous_rotation

record = {
    "status": "validated" if agents and coordinator else "held",
    "promotion": promotion,
    "reason": reason,
    "manifest_digest": manifest_digest,
    "release": release,
    "parity": {
        "offline": os.environ["PARITY_OFFLINE"],
        "live": os.environ["PARITY_LIVE"],
    },
    "agents": agents,
    "coordinator": coordinator,
    "connections": connections,
    "agent_count": len(agents),
    "previous_version": previous_agents,
    "rollback_target": rollback,
    "rollback_coordinator": rollback_coordinator,
    "rollback_manifest_digest": rollback_manifest_digest,
    "rollback_status": rollback_status,
    "rollback_rotation": rollback_rotation,
    "candidate": {
        "promotion": promotion,
        "reason": reason,
        "manifest_digest": candidate.get("manifest_digest", ""),
        "release": candidate.get("release", ""),
        "agents": candidate_agents,
        "coordinator": candidate_coordinator,
    },
}
temporary_path = None
try:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=promotion_record_path.parent,
        prefix=f".{promotion_record_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary_path = pathlib.Path(handle.name)
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, promotion_record_path)
finally:
    if temporary_path is not None and temporary_path.exists():
        temporary_path.unlink()
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
auth_header_file="$(mktemp)"
client_secret_file=""
chmod 600 "${auth_header_file}"
cleanup_auth_files() {
  rm -f "${response_file}" "${auth_header_file}"
  if [[ -n "${client_secret_file}" ]]; then
    rm -f "${client_secret_file}"
  fi
}
trap cleanup_auth_files EXIT

# The agent data plane uses its own audience, not the ARM one.
if [[ "${auth_mode}" == "azure_cli" ]]; then
  token=$(az account get-access-token \
    --resource https://ai.azure.com \
    --query accessToken \
    --output tsv)
else
  client_secret_file="$(mktemp)"
  chmod 600 "${client_secret_file}"
  printf '%s' "${AZURE_CLIENT_SECRET}" >"${client_secret_file}"
  token=$(curl -sS --fail-with-body \
    -X POST "https://login.microsoftonline.com/${AZURE_TENANT_ID}/oauth2/v2.0/token" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=client_credentials' \
    --data-urlencode "client_id=${AZURE_CLIENT_ID}" \
    --data-urlencode "client_secret@${client_secret_file}" \
    --data-urlencode 'scope=https://ai.azure.com/.default' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
fi

if [[ -z "${token}" ]]; then
  echo "create-foundry-agent: authentication returned an empty access token" >&2
  exit 1
fi
if [[ "${token}" =~ [[:space:]] ]]; then
  echo "create-foundry-agent: authentication returned an invalid access token" >&2
  exit 1
fi
printf 'Authorization: Bearer %s\n' "${token}" >"${auth_header_file}"

unset token

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
    -H "@${auth_header_file}" \
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
      RESPONSE_FILE="${response_file}" \
      EXPECTED_AGENT_NAME="${FOUNDRY_AGENT_NAME}" \
      python3 -c '
import json, os, re, sys

try:
    payload = json.loads(open(os.environ["RESPONSE_FILE"], encoding="utf-8").read())
except (OSError, ValueError):
    sys.exit(2)
if not isinstance(payload, dict):
    sys.exit(2)

# Ordered by specificity: a first-create response nests the immutable version
# under versions.latest, while an add-version response exposes it directly.
# The top-level id on create is the AGENT identity and must never be treated as
# a provider version.
latest = payload.get("versions", {}).get("latest", {})
candidates = []
if isinstance(latest, dict):
    candidates.extend(
        latest.get(key)
        for key in ("version", "agentVersion", "agent_version", "versionId", "version_id")
    )
    latest_id = latest.get("id")
    if isinstance(latest_id, str) and "/versions/" in latest_id:
        candidates.append(latest_id)
candidates.extend(
    payload.get(key)
    for key in ("version", "agentVersion", "agent_version", "versionId", "version_id")
)
resource_id = payload.get("id")
if isinstance(resource_id, str) and "/versions/" in resource_id:
    candidates.append(resource_id)
for value in candidates:
    if isinstance(value, str):
        normalized = value.strip()
        if "/" in normalized:
            parts = [part for part in normalized.split("/") if part]
            if (
                len(parts) < 4
                or parts[-4].casefold() != "agents"
                or parts[-3].casefold()
                != os.environ["EXPECTED_AGENT_NAME"].casefold()
                or parts[-2].casefold() != "versions"
            ):
                continue
            normalized = parts[-1]
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
