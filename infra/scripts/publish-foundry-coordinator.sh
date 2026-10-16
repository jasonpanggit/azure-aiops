#!/usr/bin/env bash
set -euo pipefail

: "${FOUNDRY_PROJECT_ENDPOINT:?required}"
: "${FOUNDRY_AGENT_NAME:?required}"
: "${FOUNDRY_AGENT_MODEL:?required}"
: "${FOUNDRY_AGENT_PROMPT:?required}"
: "${FOUNDRY_COORDINATOR_RECORD:?required}"
: "${FOUNDRY_SPECIALIST_MANIFEST_DIGEST:?required}"

version_record="$(mktemp)"
trap 'rm -f "${version_record}"' EXIT

FOUNDRY_AGENT_SPECIALIST_ID="operations_copilot" \
FOUNDRY_AGENT_VERSION_RECORD="${version_record}" \
FOUNDRY_SPECIALISTS_JSON="" \
"$(dirname "$0")/create-foundry-agent.sh"

provider_version_id="$(
  awk -F $'\t' '$1 == "operations_copilot" { print $3; exit }' "${version_record}"
)"
if [[ -z "${provider_version_id}" ]]; then
  echo "publish-foundry-coordinator: provider version ID was not captured" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
validator_python="${FOUNDRY_COORDINATOR_PYTHON:-}"
if [[ -z "${validator_python}" && -x "${repo_root}/.venv/bin/python" ]]; then
  validator_python="${repo_root}/.venv/bin/python"
fi
validator_python="${validator_python:-python3}"
if ! "${validator_python}" -c 'import pydantic; from operations.orchestration_contract import CandidatePlan' \
  2>/dev/null; then
  echo "publish-foundry-coordinator: validator interpreter lacks repository dependencies" >&2
  exit 1
fi

PYTHONPATH="${repo_root}/src" \
"${validator_python}" "${repo_root}/scripts/validate_foundry_coordinator.py" \
  --endpoint "${FOUNDRY_PROJECT_ENDPOINT}" \
  --agent-name "${FOUNDRY_AGENT_NAME}" \
  --provider-version-id "${provider_version_id}" \
  --expected-model "${FOUNDRY_AGENT_MODEL}" \
  --manifest-digest "${FOUNDRY_SPECIALIST_MANIFEST_DIGEST}" \
  --rejected-versions-json "${FOUNDRY_COORDINATOR_REJECTED_VERSIONS_JSON:-[\"1\",\"2\",\"3\",\"4\"]}" \
  --out "${FOUNDRY_COORDINATOR_RECORD}"
