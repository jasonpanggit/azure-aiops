#!/usr/bin/env bash
#
# Sources the service principal from web/.env.local and runs Terraform.
#
#   ./infra/scripts/deploy.sh plan
#   ./infra/scripts/deploy.sh apply
#   ./infra/scripts/deploy.sh output
#
# Credentials are read from web/.env.local (gitignored) and exported into the
# process only; they are never written to a tfvars file.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tf_dir="${repo_root}/infra/terraform"
env_file="${HERMES_ENV_FILE:-${repo_root}/web/.env.local}"

# Homebrew and Docker Desktop are not always on a non-login shell's PATH.
export PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin"

if [[ ! -f "${env_file}" ]]; then
  echo "deploy: ${env_file} not found. Set HERMES_ENV_FILE to override." >&2
  exit 1
fi

read_env() {
  # Tolerates `export FOO=bar`, quotes, and trailing whitespace. Uses awk
  # rather than sed because BSD sed (macOS) lacks the `\+` BRE extension.
  awk -v key="$1" '
    { line = $0
      sub(/^[ \t]*/, "", line)
      sub(/^export[ \t]+/, "", line)
      idx = index(line, "=")
      if (idx == 0) next
      name = substr(line, 1, idx - 1)
      gsub(/[ \t]+$/, "", name)
      if (name != key) next
      value = substr(line, idx + 1)
      sub(/^[ \t]+/, "", value)
      sub(/[ \t\r]+$/, "", value)
      if (value ~ /^".*"$/ || value ~ /^'"'"'.*'"'"'$/)
        value = substr(value, 2, length(value) - 2)
      found = value
    }
    END { if (found != "") print found }
  ' "${env_file}"
}

ARM_SUBSCRIPTION_ID="$(read_env AZURE_SUBSCRIPTION_ID)"
ARM_TENANT_ID="$(read_env AZURE_TENANT_ID)"
ARM_CLIENT_ID="$(read_env AZURE_CLIENT_ID)"
ARM_CLIENT_SECRET="$(read_env AZURE_CLIENT_SECRET)"
ENTRA_WEB_CLIENT_ID="$(read_env NEXT_PUBLIC_ENTRA_CLIENT_ID)"
ENTRA_API_AUDIENCE="$(read_env HERMES_ENTRA_API_AUDIENCE)"
ENTRA_GRANTS_JSON="$(read_env HERMES_ENTRA_GRANTS_JSON)"
# Optional: without it, the deployed API's CVE enrichment hits NVD's
# anonymous rate limit (5 req/30s) and CVE detail lookups fail.
NVD_API_KEY="$(read_env NVD_API_KEY)"

for var in ARM_SUBSCRIPTION_ID ARM_TENANT_ID ARM_CLIENT_ID ARM_CLIENT_SECRET ENTRA_WEB_CLIENT_ID ENTRA_API_AUDIENCE ENTRA_GRANTS_JSON; do
  if [[ -z "${!var}" ]]; then
    echo "deploy: ${var} could not be read from ${env_file}" >&2
    exit 1
  fi
done

export ARM_SUBSCRIPTION_ID ARM_TENANT_ID ARM_CLIENT_ID ARM_CLIENT_SECRET

# The service principal's object ID differs from its application ID, and Fabric
# capacity administration and Key Vault RBAC both need the object ID.
deployer_object_id="${HERMES_DEPLOYER_OBJECT_ID:-}"
if [[ -z "${deployer_object_id}" ]] && command -v az >/dev/null 2>&1; then
  deployer_object_id="$(az ad sp show --id "${ARM_CLIENT_ID}" --query id -o tsv 2>/dev/null || true)"
fi

tf_vars=(
  -var "subscription_id=${ARM_SUBSCRIPTION_ID}"
  -var "tenant_id=${ARM_TENANT_ID}"
  -var "client_id=${ARM_CLIENT_ID}"
  -var "client_secret=${ARM_CLIENT_SECRET}"
  -var "entra_web_client_id=${ENTRA_WEB_CLIENT_ID}"
  -var "entra_api_audience=${ENTRA_API_AUDIENCE}"
  -var "entra_grants_json=${ENTRA_GRANTS_JSON}"
)
if [[ -n "${deployer_object_id}" ]]; then
  tf_vars+=(-var "deployer_object_id=${deployer_object_id}")
fi
if [[ -n "${NVD_API_KEY}" ]]; then
  tf_vars+=(-var "nvd_api_key=${NVD_API_KEY}")
fi

command="${1:-plan}"
shift || true

cd "${tf_dir}"

if [[ ! -d .terraform ]]; then
  terraform init -input=false
fi

case "${command}" in
  plan)
    terraform plan -input=false "${tf_vars[@]}" "$@"
    ;;
  apply)
    terraform apply -input=false "${tf_vars[@]}" "$@"
    ;;
  destroy)
    terraform destroy -input=false "${tf_vars[@]}" "$@"
    ;;
  output)
    # No -var needed: outputs are read from state.
    terraform output "$@"
    ;;
  init|validate|fmt)
    terraform "${command}" "$@"
    ;;
  *)
    echo "deploy: unknown command '${command}'" >&2
    echo "usage: deploy.sh {init|validate|fmt|plan|apply|destroy|output}" >&2
    exit 1
    ;;
esac
