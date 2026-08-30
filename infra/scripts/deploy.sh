#!/usr/bin/env bash
#
# Sources the service principal from web/.env.local and runs Terraform.
#
#   ./infra/scripts/deploy.sh plan
#   ./infra/scripts/deploy.sh apply
#   ./infra/scripts/deploy.sh output
#   AIOPS_DEPLOY_ARTIFACT_DIR=/secure/path ./infra/scripts/deploy.sh apply
#
# Credentials are read from web/.env.local (gitignored) and exported into the
# process only; they are never written to a tfvars file.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tf_dir="${repo_root}/infra/terraform"
env_file="${AIOPS_ENV_FILE:-${repo_root}/web/.env.local}"

# Homebrew and Docker Desktop are not always on a non-login shell's PATH.
export PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin"

if [[ ! -f "${env_file}" ]]; then
  echo "deploy: ${env_file} not found. Set AIOPS_ENV_FILE to override." >&2
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
ENTRA_API_AUDIENCE="$(read_env AIOPS_ENTRA_API_AUDIENCE)"
ENTRA_GRANTS_JSON="$(read_env AIOPS_ENTRA_GRANTS_JSON)"
# Optional: without it, the deployed API's CVE enrichment hits NVD's
# anonymous rate limit (5 req/30s) and CVE detail lookups fail.
NVD_API_KEY="$(read_env NVD_API_KEY)"
APIM_PUBLISHER_EMAIL="${AIOPS_APIM_PUBLISHER_EMAIL:-$(read_env AIOPS_APIM_PUBLISHER_EMAIL)}"
APIM_NAME="${AIOPS_APIM_NAME:-$(read_env AIOPS_APIM_NAME)}"
FOUNDRY_MODEL_CAPACITY="${AIOPS_FOUNDRY_MODEL_CAPACITY:-$(read_env AIOPS_FOUNDRY_MODEL_CAPACITY)}"

for var in ARM_SUBSCRIPTION_ID ARM_TENANT_ID ARM_CLIENT_ID ARM_CLIENT_SECRET ENTRA_WEB_CLIENT_ID ENTRA_API_AUDIENCE ENTRA_GRANTS_JSON; do
  if [[ -z "${!var}" ]]; then
    echo "deploy: ${var} could not be read from ${env_file}" >&2
    exit 1
  fi
done

export ARM_SUBSCRIPTION_ID ARM_TENANT_ID ARM_CLIENT_ID ARM_CLIENT_SECRET

# The service principal's object ID differs from its application ID, and Fabric
# capacity administration and Key Vault RBAC both need the object ID.
deployer_object_id="${AIOPS_DEPLOYER_OBJECT_ID:-}"
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
if [[ -n "${APIM_PUBLISHER_EMAIL}" ]]; then
  tf_vars+=(-var "apim_publisher_email=${APIM_PUBLISHER_EMAIL}")
fi
if [[ -n "${APIM_NAME}" ]]; then
  tf_vars+=(-var "apim_name=${APIM_NAME}")
fi
if [[ -n "${FOUNDRY_MODEL_CAPACITY}" ]]; then
  tf_vars+=(-var "foundry_model_capacity=${FOUNDRY_MODEL_CAPACITY}")
fi
if [[ -n "${deployer_object_id}" ]]; then
  tf_vars+=(-var "deployer_object_id=${deployer_object_id}")
fi
if [[ -n "${NVD_API_KEY}" ]]; then
  tf_vars+=(-var "nvd_api_key=${NVD_API_KEY}")
fi

command="${1:-plan}"
shift || true

# Pointing Container Apps at a tag that was never pushed produces a revision
# stuck in ActivationFailed with MANIFEST_UNKNOWN, so verify the images exist
# before Terraform rewrites the container image.
verify_images_exist() {
  local args=("$@")
  local deploy_images="" image_tag="" i

  for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[i]}" in
      -var) case "${args[i + 1]:-}" in
              deploy_images=*) deploy_images="${args[i + 1]#deploy_images=}" ;;
              image_tag=*) image_tag="${args[i + 1]#image_tag=}" ;;
            esac ;;
      -var=deploy_images=*) deploy_images="${args[i]#-var=deploy_images=}" ;;
      -var=image_tag=*) image_tag="${args[i]#-var=image_tag=}" ;;
    esac
  done

  # CLI flags win, but terraform.tfvars is the normal source of truth (it is
  # written by build-and-push.sh). Without this fallback a plain `apply` did
  # no verification at all, so a stale or half-pushed tag sailed through.
  local tfvars="${tf_dir}/terraform.tfvars"
  if [[ -f "${tfvars}" ]]; then
    [[ -n "${deploy_images}" ]] || deploy_images="$(
      awk -F'=' '/^[ \t]*deploy_images[ \t]*=/ {gsub(/[ \t"]/,"",$2); print $2}' "${tfvars}" | tail -1)"
    [[ -n "${image_tag}" ]] || image_tag="$(
      awk -F'=' '/^[ \t]*image_tag[ \t]*=/ {gsub(/[ \t"]/,"",$2); print $2}' "${tfvars}" | tail -1)"
  fi

  [[ "${deploy_images}" == "true" && -n "${image_tag}" ]] || return 0
  command -v az >/dev/null 2>&1 || return 0

  local registry
  registry="$(cd "${tf_dir}" && terraform output -raw container_registry 2>/dev/null || true)"
  [[ -n "${registry}" ]] || return 0

  local repo missing=()
  for repo in aiops-api aiops-web; do
    if ! az acr repository show \
      --name "${registry%%.*}" \
      --image "${repo}:${image_tag}" >/dev/null 2>&1; then
      missing+=("${repo}:${image_tag}")
    fi
  done

  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "deploy: image(s) not found in ${registry}: ${missing[*]}" >&2
    echo "deploy: build them first with" >&2
    echo "  ./infra/scripts/build-and-push.sh ${image_tag}" >&2
    exit 1
  fi
}

cd "${tf_dir}"

artifact_dir="${AIOPS_DEPLOY_ARTIFACT_DIR:-${TMPDIR:-/tmp}/aiops-deploy}"
capture_apim_snapshot() {
  [[ "${AIOPS_CAPTURE_APIM_SNAPSHOT:-true}" == "true" ]] || return 0
  command -v az >/dev/null 2>&1 || return 0
  local enabled
  enabled="$(printf '%s\n' "${tf_vars[@]}" | grep -c 'enable_apim=true' || true)"
  [[ "${enabled}" -gt 0 ]] || return 0

  local rg apim api snapshot_dir
  rg="$(terraform output -raw resource_group_name 2>/dev/null || true)"
  apim="${AIOPS_APIM_NAME:-aiops-dev-apim}"
  api="${AIOPS_APIM_API_NAME:-aiops-dev-mcp}"
  [[ -n "${rg}" && -n "${apim}" && -n "${api}" ]] || return 0
  az apim show --resource-group "${rg}" --name "${apim}" >/dev/null 2>&1 || return 0
  snapshot_dir="${artifact_dir}/apim/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "${snapshot_dir}"
  umask 077
  printf '%s\n' "resource_group=${rg}" "apim_name=${apim}" \
    "api_name=${api}" "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    >"${snapshot_dir}/metadata.txt"
  az apim api show --resource-group "${rg}" --service-name "${apim}" \
    --api-id "${api}" --output json >"${snapshot_dir}/api.json" 2>/dev/null || true
  az apim api policy show --resource-group "${rg}" --service-name "${apim}" \
    --api-id "${api}" --format rawxml >"${snapshot_dir}/api-policy.xml" 2>/dev/null || true
  az apim api operation policy show --resource-group "${rg}" --service-name "${apim}" \
    --api-id "${api}" --operation-id mcp --format rawxml \
    >"${snapshot_dir}/operation-policy.xml" 2>/dev/null || true
  printf '%s\n' "${snapshot_dir}"
}

# Terraform can report success while the Container Apps revision still serves
# the previous image (a failed revision rollout does not fail the apply), so
# confirm what is actually running matches the tag that was just deployed.
report_running_images() {
  command -v az >/dev/null 2>&1 || return 0
  local tfvars="${tf_dir}/terraform.tfvars" expected rg
  [[ -f "${tfvars}" ]] || return 0
  expected="$(awk -F'=' '/^[ \t]*image_tag[ \t]*=/ {gsub(/[ \t"]/,"",$2); print $2}' "${tfvars}" | tail -1)"
  [[ -n "${expected}" ]] || return 0
  rg="$(terraform output -raw resource_group_name 2>/dev/null || true)"
  [[ -n "${rg}" ]] || return 0

  echo
  echo "deploy: waiting for revisions to serve ${expected}..."

  # A Container Apps rollout takes roughly a minute to activate, so poll
  # rather than reading once -- checking immediately after apply would report
  # drift on every single successful deploy.
  local attempt drift=1 report=""
  for attempt in $(seq 1 20); do
    drift=0
    report=""
    while IFS=$'\t' read -r name image; do
      [[ -n "${name}" ]] || continue
      if [[ "${image}" == *":${expected}" ]]; then
        report+="  ok    ${name} -> ${image##*/}"$'\n'
      else
        report+="  DRIFT ${name} -> ${image##*/}"$'\n'
        drift=1
      fi
    done < <(az containerapp list -g "${rg}" \
      --query "[].[name,properties.template.containers[0].image]" -o tsv 2>/dev/null)

    [[ "${drift}" -eq 0 ]] && break
    sleep 15
  done

  printf '%s' "${report}"

  if [[ "${drift}" -eq 1 ]]; then
    echo "deploy: a revision is not serving ${expected} after 5m; check status with" >&2
    echo "  az containerapp revision list -g ${rg} -n <app> -o table" >&2
    return 1
  fi
  echo "deploy: all apps serving ${expected}."
}

if [[ ! -d .terraform ]]; then
  terraform init -input=false
fi

case "${command}" in
  plan)
    terraform plan -input=false "${tf_vars[@]}" "$@"
    ;;
  apply)
    verify_images_exist "$@"
    capture_apim_snapshot
    terraform apply -input=false "${tf_vars[@]}" "$@"
    report_running_images
    ;;
  destroy)
    terraform destroy -input=false "${tf_vars[@]}" "$@"
    ;;
  import)
    # Adopts a resource that already exists in Azure/Fabric into state, so a
    # subsequent apply updates it instead of recreating it.
    terraform import -input=false "${tf_vars[@]}" "$@"
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
    echo "usage: deploy.sh {init|validate|fmt|plan|apply|import|destroy|output}" >&2
    exit 1
    ;;
esac
