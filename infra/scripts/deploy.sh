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
AGENT_ORCHESTRATION_MODE="${AIOPS_AGENT_ORCHESTRATION_MODE:-$(read_env AIOPS_AGENT_ORCHESTRATION_MODE)}"

for var in ARM_SUBSCRIPTION_ID ARM_TENANT_ID ARM_CLIENT_ID ARM_CLIENT_SECRET ENTRA_WEB_CLIENT_ID ENTRA_API_AUDIENCE ENTRA_GRANTS_JSON; do
  if [[ -z "${!var}" ]]; then
    echo "deploy: ${var} could not be read from ${env_file}" >&2
    exit 1
  fi
done

export ARM_SUBSCRIPTION_ID ARM_TENANT_ID ARM_CLIENT_ID ARM_CLIENT_SECRET
export TF_VAR_subscription_id="${ARM_SUBSCRIPTION_ID}"
export TF_VAR_tenant_id="${ARM_TENANT_ID}"
export TF_VAR_client_id="${ARM_CLIENT_ID}"
export TF_VAR_client_secret="${ARM_CLIENT_SECRET}"
export TF_VAR_entra_web_client_id="${ENTRA_WEB_CLIENT_ID}"
export TF_VAR_entra_api_audience="${ENTRA_API_AUDIENCE}"
export TF_VAR_entra_grants_json="${ENTRA_GRANTS_JSON}"

# The service principal's object ID differs from its application ID, and Fabric
# capacity administration and Key Vault RBAC both need the object ID.
deployer_object_id="${AIOPS_DEPLOYER_OBJECT_ID:-}"
if [[ -z "${deployer_object_id}" ]] && command -v az >/dev/null 2>&1; then
  deployer_object_id="$(az ad sp show --id "${ARM_CLIENT_ID}" --query id -o tsv 2>/dev/null || true)"
fi

if [[ -n "${APIM_PUBLISHER_EMAIL}" ]]; then
  export TF_VAR_apim_publisher_email="${APIM_PUBLISHER_EMAIL}"
fi
if [[ -n "${APIM_NAME}" ]]; then
  export TF_VAR_apim_name="${APIM_NAME}"
fi
if [[ -n "${FOUNDRY_MODEL_CAPACITY}" ]]; then
  export TF_VAR_foundry_model_capacity="${FOUNDRY_MODEL_CAPACITY}"
fi
export TF_VAR_agent_orchestration_mode="${AGENT_ORCHESTRATION_MODE:-maf}"
if [[ -n "${deployer_object_id}" ]]; then
  export TF_VAR_deployer_object_id="${deployer_object_id}"
fi
if [[ -n "${NVD_API_KEY}" ]]; then
  export TF_VAR_nvd_api_key="${NVD_API_KEY}"
fi

command="${1:-plan}"
shift || true
api_authorization_release="${AIOPS_API_AUTHORIZATION_RELEASE:-0}"

validate_api_authorization_environment() {
  local name

  while IFS= read -r name; do
    case "${name}" in
      TF_CLI_ARGS|TF_CLI_ARGS_*)
        if [[ -n "${!name:-}" ]]; then
          echo "deploy: API authorization release rejects non-empty ${name}." >&2
          return 1
        fi
        ;;
    esac
  done < <(compgen -e)
}

validate_api_authorization_target() {
  local args=("$@")
  local target="" target_count=0 i

  for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[i]}" in
      -target|--target)
        target="${args[i + 1]:-}"
        if [[ -z "${target}" ]]; then
          echo "deploy: ${args[i]} requires a resource address." >&2
          return 1
        fi
        target_count=$((target_count + 1))
        i=$((i + 1))
        ;;
      -target=*|--target=*)
        target="${args[i]#*=}"
        if [[ -z "${target}" ]]; then
          echo "deploy: ${args[i]%%=*} requires a resource address." >&2
          return 1
        fi
        target_count=$((target_count + 1))
        ;;
    esac
  done

  if [[ "${target_count}" -ne 1 || "${target}" != "azurerm_container_app.api" ]]; then
    echo "deploy: API authorization release requires exactly one Terraform target: azurerm_container_app.api." >&2
    return 1
  fi
}

api_compatibility_args() {
  local args=("$@")
  local i

  API_COMPATIBILITY_ARGS=()
  for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[i]}" in
      -var)
        if [[ "${args[i + 1]:-}" == copilot_rollout_mode=* ]]; then
          i=$((i + 1))
          continue
        fi
        API_COMPATIBILITY_ARGS+=("${args[i]}")
        if [[ -n "${args[i + 1]:-}" ]]; then
          API_COMPATIBILITY_ARGS+=("${args[i + 1]}")
          i=$((i + 1))
        fi
        ;;
      -var=copilot_rollout_mode=*)
        ;;
      *)
        API_COMPATIBILITY_ARGS+=("${args[i]}")
        ;;
    esac
  done
  API_COMPATIBILITY_ARGS+=("-var=copilot_rollout_mode=compatibility")
}

api_digest_args() {
  local digest="$1"
  shift
  local args=("$@")
  local i

  API_DIGEST_ARGS=()
  for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[i]}" in
      -var)
        if [[ "${args[i + 1]:-}" == api_image_digest=* ]]; then
          i=$((i + 1))
          continue
        fi
        API_DIGEST_ARGS+=("${args[i]}")
        if [[ -n "${args[i + 1]:-}" ]]; then
          API_DIGEST_ARGS+=("${args[i + 1]}")
          i=$((i + 1))
        fi
        ;;
      -var=api_image_digest=*)
        ;;
      *)
        API_DIGEST_ARGS+=("${args[i]}")
        ;;
    esac
  done
  API_DIGEST_ARGS+=("-var=api_image_digest=${digest}")
}

apply_api_compatibility_hold() {
  api_compatibility_args "$@"
  terraform apply -input=false "${API_COMPATIBILITY_ARGS[@]}"
}

restore_and_verify_api_compatibility() {
  local expected_image="$1"
  shift
  if ! apply_api_compatibility_hold "$@" ||
    ! validate_running_api_revision compatibility 0 "${expected_image}"; then
    echo "deploy: automatic compatibility hold could not be verified; keep promotion blocked and intervene immediately." >&2
    return 1
  fi
}

# Pointing Container Apps at a tag that was never pushed produces a revision
# stuck in ActivationFailed with MANIFEST_UNKNOWN, so verify the images exist
# before Terraform rewrites the container image.
verify_images_exist() {
  local args=("$@")
  local deploy_images="" image_tag="" i

  if [[ "${api_authorization_release}" == "1" ]]; then
    local api_digest
    api_digest="$(
      awk -F'=' '/^[ \t]*api_image_digest[ \t]*=/ {gsub(/[ \t"]/,"",$2); print $2}' \
        "${tf_dir}/terraform.tfvars" | tail -1
    )"
    if [[ ! "${api_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
      echo "deploy: API authorization release requires an immutable api_image_digest." >&2
      exit 1
    fi
    return 0
  fi

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
  for repo in aiops-api aiops-web mcp-server azure-mcp; do
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

if [[ "${api_authorization_release}" == "1" ]]; then
  validate_api_authorization_environment
  case "${command}" in
    plan|apply) validate_api_authorization_target "$@" ;;
  esac
fi

cd "${tf_dir}"

artifact_dir="${AIOPS_DEPLOY_ARTIFACT_DIR:-${TMPDIR:-/tmp}/aiops-deploy}"
capture_apim_snapshot() {
  [[ "${AIOPS_CAPTURE_APIM_SNAPSHOT:-true}" == "true" ]] || return 0
  command -v az >/dev/null 2>&1 || return 0
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

validate_running_api_revision() {
  command -v az >/dev/null 2>&1 || return 1
  local expected_mode="$1" expected_percentage="$2" expected="${3:-}"
  local rg app attempt actual_image="" actual_mode="" actual_percentage=""
  local authorization_manifest authorized_target authorized_subscription
  local authorized_rg authorized_app expected_resource_id actual_resource_id
  local normalized_arm_subscription normalized_authorized_subscription
  local normalized_expected_resource_id normalized_actual_resource_id
  if [[ -z "${expected}" ]]; then
    expected="$(terraform output -raw api_image 2>/dev/null || true)"
  fi
  rg="$(terraform output -raw resource_group_name 2>/dev/null || true)"
  app="$(terraform output -raw api_app_name 2>/dev/null || true)"
  if [[ ! "${expected}" =~ @sha256:[0-9a-f]{64}$ ]] ||
    [[ -z "${rg}" || -z "${app}" ]]; then
    echo "deploy: external API digest validation lacks immutable expected image or target." >&2
    return 1
  fi

  authorization_manifest="${repo_root}/src/operations/copilot_canary_authorization.v1.json"
  authorized_target="$(
    python3 - "${authorization_manifest}" <<'PY' 2>/dev/null
import json
import sys

with open(sys.argv[1], encoding="utf-8") as manifest_file:
    target = json.load(manifest_file)["deployment_target"]
print(
    target["subscription_id"],
    target["resource_group"],
    target["app"],
    sep="\t",
)
PY
  )" || true
  IFS=$'\t' read -r authorized_subscription authorized_rg authorized_app \
    <<<"${authorized_target}"
  normalized_arm_subscription="$(
    printf '%s' "${ARM_SUBSCRIPTION_ID}" | tr '[:upper:]' '[:lower:]'
  )"
  normalized_authorized_subscription="$(
    printf '%s' "${authorized_subscription}" | tr '[:upper:]' '[:lower:]'
  )"
  if [[ -z "${authorized_subscription}" ]] ||
    [[ -z "${authorized_rg}" ]] ||
    [[ -z "${authorized_app}" ]] ||
    [[ "${normalized_arm_subscription}" != "${normalized_authorized_subscription}" ]]; then
    echo "deploy: platform admission denied; authorized API target could not be bound to ARM_SUBSCRIPTION_ID." >&2
    return 1
  fi

  expected_resource_id="/subscriptions/${authorized_subscription}/resourceGroups/${authorized_rg}/providers/Microsoft.App/containerApps/${authorized_app}"
  actual_resource_id="$(
    az containerapp show --subscription "${ARM_SUBSCRIPTION_ID}" \
      --resource-group "${rg}" --name "${app}" --query id --output tsv \
      2>/dev/null || true
  )"
  normalized_expected_resource_id="$(
    printf '%s' "${expected_resource_id}" | tr '[:upper:]' '[:lower:]'
  )"
  normalized_actual_resource_id="$(
    printf '%s' "${actual_resource_id}" | tr '[:upper:]' '[:lower:]'
  )"
  if [[ -z "${actual_resource_id}" ]] ||
    [[ "${normalized_actual_resource_id}" != "${normalized_expected_resource_id}" ]]; then
    echo "deploy: platform admission denied; resolved API resource ID does not match the authorized subscription, resource group, and app." >&2
    return 1
  fi

  for attempt in $(seq 1 20); do
    actual_image=""
    actual_mode=""
    actual_percentage=""
    read -r actual_image actual_mode actual_percentage < <(
      az containerapp revision list --subscription "${ARM_SUBSCRIPTION_ID}" \
        --resource-group "${rg}" --name "${app}" --output json 2>/dev/null |
        python3 -c '
import json
import sys

revisions = json.load(sys.stdin)
active = next(
    (
        revision
        for revision in revisions
        if revision.get("properties", {}).get("active")
        and revision.get("properties", {}).get("healthState") == "Healthy"
    ),
    {},
)
container = (
    active.get("properties", {})
    .get("template", {})
    .get("containers", [{}])[0]
)
environment = {
    item.get("name"): item.get("value", "")
    for item in container.get("env", [])
}
print(
    container.get("image", ""),
    environment.get("AIOPS_COPILOT_ROLLOUT_MODE", ""),
    environment.get("AIOPS_COPILOT_CANARY_PERCENTAGE", ""),
    sep="\t",
)
' 2>/dev/null || true
    ) || true
    if [[ "${actual_image}" == "${expected}" ]] &&
      [[ "${actual_mode}" == "${expected_mode}" ]] &&
      [[ "${actual_percentage}" == "${expected_percentage}" ]]; then
      break
    fi
    sleep 15
  done
  if [[ "${actual_image}" != "${expected}" ]] ||
    [[ "${actual_mode}" != "${expected_mode}" ]] ||
    [[ "${actual_percentage}" != "${expected_percentage}" ]]; then
    echo "deploy: platform admission denied; active healthy API revision does not match ${expected}, mode ${expected_mode}, percentage ${expected_percentage}." >&2
    return 1
  fi
  echo "deploy: platform admission confirmed active API image ${expected}, mode ${expected_mode}, percentage ${expected_percentage}."
}

apply_api_authorization_release() {
  local args=("$@")
  local rollout_json requested_mode requested_percentage applied_api_image
  local captured_api_image captured_api_digest applied_api_digest
  local bound_args=()

  echo "deploy: staging immutable API digest in compatibility mode (zero canonical canary)..."
  if ! apply_api_compatibility_hold "${args[@]}"; then
    echo "deploy: compatibility staging failed; restoring the compatibility hold." >&2
    restore_and_verify_api_compatibility "" "${args[@]}" || true
    return 1
  fi
  captured_api_image="$(terraform output -raw api_image 2>/dev/null || true)"
  captured_api_digest="${captured_api_image##*@}"
  if [[ "${captured_api_image}" != *"@${captured_api_digest}" ]] ||
    [[ ! "${captured_api_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "deploy: compatibility staging did not expose an immutable API digest; holding compatibility." >&2
    restore_and_verify_api_compatibility "" "${args[@]}" || true
    return 1
  fi
  api_digest_args "${captured_api_digest}" "${args[@]}"
  bound_args=("${API_DIGEST_ARGS[@]}")
  if ! validate_running_api_revision compatibility 0 "${captured_api_image}"; then
    echo "deploy: staged digest validation failed; holding compatibility." >&2
    restore_and_verify_api_compatibility "${captured_api_image}" "${bound_args[@]}" || true
    return 1
  fi

  echo "deploy: staged digest ${captured_api_digest} admitted; applying the requested API canary..."
  if ! terraform apply -input=false "${bound_args[@]}"; then
    echo "deploy: canary apply failed; restoring compatibility hold." >&2
    restore_and_verify_api_compatibility "${captured_api_image}" "${bound_args[@]}" || true
    return 1
  fi

  applied_api_image="$(terraform output -raw api_image 2>/dev/null || true)"
  rollout_json="$(terraform output -json copilot_provider_environment 2>/dev/null || true)"
  requested_mode="$(
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("AIOPS_COPILOT_ROLLOUT_MODE", ""))' \
      <<<"${rollout_json}" 2>/dev/null || true
  )"
  requested_percentage="$(
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("AIOPS_COPILOT_CANARY_PERCENTAGE", ""))' \
      <<<"${rollout_json}" 2>/dev/null || true
  )"
  applied_api_digest="$(
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("AIOPS_API_IMAGE_DIGEST", ""))' \
      <<<"${rollout_json}" 2>/dev/null || true
  )"
  if [[ "${requested_mode}" != "canary" ]] ||
    [[ ! "${requested_percentage}" =~ ^([1-9]|10)$ ]] ||
    [[ "${applied_api_image}" != "${captured_api_image}" ]] ||
    [[ "${applied_api_digest}" != "${captured_api_digest}" ]] ||
    ! validate_running_api_revision \
      "${requested_mode}" "${requested_percentage}" "${captured_api_image}"; then
    echo "deploy: canary activation validation failed; restoring compatibility hold." >&2
    restore_and_verify_api_compatibility "${captured_api_image}" "${bound_args[@]}" || true
    return 1
  fi
}

publish_governed_remediation_catalog() {
  local python="${AIOPS_PYTHON:-${repo_root}/.venv/bin/python}"
  local fabric_config="${AIOPS_FABRIC_CONFIG:-${repo_root}/fabric.config.yaml}"

  if [[ ! -x "${python}" ]]; then
    echo "deploy: Python runtime not found at ${python}; cannot publish governed remediation catalog" >&2
    exit 1
  fi
  if [[ ! -f "${fabric_config}" ]]; then
    echo "deploy: Fabric config not found at ${fabric_config}" >&2
    exit 1
  fi

  # fabric.config.yaml names AZURE_CLIENT_SECRET as its credential source.
  # Keep the value process-local; neither the CLI nor deployment artifacts
  # serialize it.
  export AZURE_CLIENT_SECRET="${ARM_CLIENT_SECRET}"
  echo
  echo "deploy: publishing governed remediation catalog..."
  PYTHONPATH="${repo_root}/src${PYTHONPATH:+:${PYTHONPATH}}" \
    "${python}" -m onboarding.cli fabric \
      "Publish governed remediation catalog" \
      --config "${fabric_config}"
}

if [[ ! -d .terraform ]]; then
  terraform init -input=false
fi

case "${command}" in
  plan)
    terraform plan -input=false "$@"
    ;;
  apply)
    verify_images_exist "$@"
    if [[ "${api_authorization_release}" != "1" ]]; then
      capture_apim_snapshot
    fi
    if [[ "${api_authorization_release}" == "1" ]]; then
      apply_api_authorization_release "$@"
    else
      terraform apply -input=false "$@"
      publish_governed_remediation_catalog
      report_running_images
    fi
    ;;
  destroy)
    terraform destroy -input=false "$@"
    ;;
  import)
    # Adopts a resource that already exists in Azure/Fabric into state, so a
    # subsequent apply updates it instead of recreating it.
    terraform import -input=false "$@"
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
