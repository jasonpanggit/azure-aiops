#!/usr/bin/env bash
#
# Rotate the Exposure cursor-signing key without exposing key material.
#
# Key values move only through mode-0600 temporary files and Key Vault. Logs,
# command output, Terraform values, and process arguments contain names,
# versions, and non-secret key identifiers only.

set -euo pipefail

# Disable inherited xtrace before any key material is created.
[[ $- == *x* ]] && set +x

ACTIVE_SECRET_NAME="exposure-cursor-active"
PREVIOUS_SECRET_NAME="exposure-cursor-previous"
ACTIVE_CONTAINER_SECRET="cursor-active"
PREVIOUS_CONTAINER_SECRET="cursor-previous"
ACTIVE_KEY_ENV="EXPOSURE_CURSOR_ACTIVE_KEY"
PREVIOUS_KEY_ENV="EXPOSURE_CURSOR_PREVIOUS_KEY"
ACTIVE_KID_ENV="EXPOSURE_CURSOR_ACTIVE_KID"
PREVIOUS_KID_ENV="EXPOSURE_CURSOR_PREVIOUS_KID"
DEFAULT_OVERLAP_SECONDS=1800

mode="rotate"
resource_group="${AIOPS_EXPOSURE_RESOURCE_GROUP:-}"
container_app="${AIOPS_EXPOSURE_CONTAINER_APP:-}"
key_vault="${AIOPS_EXPOSURE_KEY_VAULT:-}"
requested_kid=""
overlap_seconds="${AIOPS_EXPOSURE_CURSOR_OVERLAP_SECONDS:-${DEFAULT_OVERLAP_SECONDS}}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
terraform_dir="${repo_root}/infra/terraform"
active_file=""
previous_file=""

usage() {
  printf '%s\n' \
    "Usage: $0 [--dry-run | --status | --rollback] [options]" \
    "" \
    "Modes:" \
    "  --dry-run              Print the redacted rotation plan; call no Azure APIs." \
    "  --status               Print secret versions, kids, and revision metadata only." \
    "  --rollback             Swap active and previous keys and deploy a revision." \
    "" \
    "Options:" \
    "  --resource-group NAME  Container App resource group." \
    "  --app-name NAME        API Container App name." \
    "  --key-vault NAME       Key Vault name." \
    "  --kid KID              Idempotent non-secret identifier for the new key." \
    "  --overlap-seconds N    Overlap before retiring previous (minimum/default: 1800)." \
    "  --help                 Show this help."
}

die() {
  printf 'rotate-exposure-cursor-key: %s\n' "$*" >&2
  exit 1
}

safe_log() {
  printf 'rotate-exposure-cursor-key: %s\n' "$*"
}

cleanup() {
  [[ -z "${active_file}" ]] || rm -f "${active_file}"
  [[ -z "${previous_file}" ]] || rm -f "${previous_file}"
}
trap cleanup EXIT

set_mode() {
  local requested="$1"
  [[ "${mode}" == "rotate" ]] || die "choose only one mode"
  mode="${requested}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      set_mode "dry-run"
      shift
      ;;
    --status)
      set_mode "status"
      shift
      ;;
    --rollback)
      set_mode "rollback"
      shift
      ;;
    --resource-group)
      [[ $# -ge 2 ]] || die "--resource-group requires a value"
      resource_group="$2"
      shift 2
      ;;
    --app-name)
      [[ $# -ge 2 ]] || die "--app-name requires a value"
      container_app="$2"
      shift 2
      ;;
    --key-vault)
      [[ $# -ge 2 ]] || die "--key-vault requires a value"
      key_vault="$2"
      shift 2
      ;;
    --kid)
      [[ $# -ge 2 ]] || die "--kid requires a value"
      requested_kid="$2"
      shift 2
      ;;
    --overlap-seconds)
      [[ $# -ge 2 ]] || die "--overlap-seconds requires a value"
      overlap_seconds="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ "${overlap_seconds}" =~ ^[0-9]+$ ]] || die "overlap seconds must be an integer"
if [[ "${mode}" == "rotate" && "${overlap_seconds}" -lt "${DEFAULT_OVERLAP_SECONDS}" ]]; then
  die "rotation overlap must be at least ${DEFAULT_OVERLAP_SECONDS} seconds"
fi
if [[ -n "${requested_kid}" && ! "${requested_kid}" =~ ^[a-z0-9][a-z0-9._-]{7,63}$ ]]; then
  die "kid must be 8-64 lowercase alphanumeric, dot, underscore, or dash characters"
fi

if [[ "${mode}" == "dry-run" ]]; then
  planned_kid="${requested_kid:-cursor-$(date -u +%Y%m%d%H%M%S)-planned}"
  printf '%s\n' \
    "mode=dry-run" \
    "sanitized=true" \
    "active_key_vault_secret=${ACTIVE_SECRET_NAME}" \
    "previous_key_vault_secret=${PREVIOUS_SECRET_NAME}" \
    "active_container_secret=${ACTIVE_CONTAINER_SECRET}" \
    "previous_container_secret=${PREVIOUS_CONTAINER_SECRET}" \
    "new_active_version=allocated-by-key-vault" \
    "new_active_kid=${planned_kid}" \
    "previous_kid=current-active-kid" \
    "overlap_seconds=${overlap_seconds}" \
    "probe_tokens=new-and-previous" \
    "secret_values=redacted"
  exit 0
fi

for command_name in az python3 terraform; do
  command -v "${command_name}" >/dev/null 2>&1 \
    || die "required command is unavailable: ${command_name}"
done

terraform_output() {
  terraform -chdir="${terraform_dir}" output -raw "$1" 2>/dev/null || true
}

[[ -n "${resource_group}" ]] \
  || resource_group="$(terraform_output resource_group_name)"
[[ -n "${key_vault}" ]] \
  || key_vault="$(terraform_output key_vault_name)"
[[ -n "${resource_group}" ]] || die "resource group is required"
[[ -n "${key_vault}" ]] || die "Key Vault name is required"

if [[ -z "${container_app}" ]]; then
  container_app="$(
    az containerapp list \
      --resource-group "${resource_group}" \
      --query "[?ends_with(name, '-api')].name | [0]" \
      --output tsv \
      --only-show-errors
  )"
fi
[[ -n "${container_app}" ]] || die "API Container App name is required"

identity_id="$(
  az containerapp show \
    --resource-group "${resource_group}" \
    --name "${container_app}" \
    --query "identity.userAssignedIdentities | keys(@)[0]" \
    --output tsv \
    --only-show-errors
)"
[[ -n "${identity_id}" ]] || die "Container App has no user-assigned identity"

vault_uri="$(
  az keyvault show \
    --name "${key_vault}" \
    --query properties.vaultUri \
    --output tsv \
    --only-show-errors
)"
[[ -n "${vault_uri}" ]] || die "Key Vault URI could not be resolved"
vault_uri="${vault_uri%/}"

secret_id() {
  az keyvault secret show \
    --vault-name "${key_vault}" \
    --name "$1" \
    --query id \
    --output tsv \
    --only-show-errors 2>/dev/null || true
}

secret_kid() {
  az keyvault secret show \
    --vault-name "${key_vault}" \
    --name "$1" \
    --query tags.kid \
    --output tsv \
    --only-show-errors 2>/dev/null || true
}

container_env_value() {
  az containerapp show \
    --resource-group "${resource_group}" \
    --name "${container_app}" \
    --query "properties.template.containers[0].env[?name=='$1'].value | [0]" \
    --output tsv \
    --only-show-errors 2>/dev/null || true
}

version_from_id() {
  local id="$1"
  printf '%s\n' "${id##*/}"
}

fallback_kid() {
  local id="$1"
  local version
  version="$(version_from_id "${id}")"
  printf 'kv-%.16s\n' "${version}"
}

show_status() {
  local active_id previous_id active_kid previous_kid deployed_active deployed_previous revision
  active_id="$(secret_id "${ACTIVE_SECRET_NAME}")"
  previous_id="$(secret_id "${PREVIOUS_SECRET_NAME}")"
  active_kid="$(secret_kid "${ACTIVE_SECRET_NAME}")"
  previous_kid="$(secret_kid "${PREVIOUS_SECRET_NAME}")"
  deployed_active="$(container_env_value "${ACTIVE_KID_ENV}")"
  deployed_previous="$(container_env_value "${PREVIOUS_KID_ENV}")"
  revision="$(
    az containerapp revision list \
      --resource-group "${resource_group}" \
      --name "${container_app}" \
      --query "[?properties.active].name | [0]" \
      --output tsv \
      --only-show-errors 2>/dev/null || true
  )"
  printf '%s\n' \
    "mode=status" \
    "sanitized=true" \
    "active_secret=${ACTIVE_SECRET_NAME}" \
    "active_version=${active_id:+$(version_from_id "${active_id}")}" \
    "active_kid=${active_kid:-unprovisioned}" \
    "previous_secret=${PREVIOUS_SECRET_NAME}" \
    "previous_version=${previous_id:+$(version_from_id "${previous_id}")}" \
    "previous_kid=${previous_kid:-unprovisioned}" \
    "deployed_active_kid=${deployed_active:-unprovisioned}" \
    "deployed_previous_kid=${deployed_previous:-unprovisioned}" \
    "active_revision=${revision:-unknown}" \
    "secret_values=redacted"
}

if [[ "${mode}" == "status" ]]; then
  show_status
  exit 0
fi

active_file="$(mktemp "${TMPDIR:-/tmp}/aiops-cursor-active.XXXXXX")"
previous_file="$(mktemp "${TMPDIR:-/tmp}/aiops-cursor-previous.XXXXXX")"
chmod 600 "${active_file}" "${previous_file}"

download_secret() {
  az keyvault secret download \
    --vault-name "${key_vault}" \
    --name "$1" \
    --file "$2" \
    --encoding utf-8 \
    --overwrite \
    --output none \
    --only-show-errors
}

write_secret() {
  local name="$1"
  local file="$2"
  local kid="$3"
  local role="$4"
  az keyvault secret set \
    --vault-name "${key_vault}" \
    --name "${name}" \
    --file "${file}" \
    --encoding utf-8 \
    --content-type "application/vnd.azure-aiops.cursor-hmac-key" \
    --tags "kid=${kid}" "role=${role}" "rotated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --query id \
    --output tsv \
    --only-show-errors
}

configure_container_secrets() {
  az containerapp secret set \
    --resource-group "${resource_group}" \
    --name "${container_app}" \
    --secrets \
      "${ACTIVE_CONTAINER_SECRET}=keyvaultref:${vault_uri}/secrets/${ACTIVE_SECRET_NAME},identityref:${identity_id}" \
      "${PREVIOUS_CONTAINER_SECRET}=keyvaultref:${vault_uri}/secrets/${PREVIOUS_SECRET_NAME},identityref:${identity_id}" \
    --output none \
    --only-show-errors
}

deploy_keyring() {
  local active_kid="$1"
  local previous_kid="$2"
  local suffix="$3"
  configure_container_secrets
  az containerapp update \
    --resource-group "${resource_group}" \
    --name "${container_app}" \
    --revision-suffix "${suffix}" \
    --set-env-vars \
      "${ACTIVE_KEY_ENV}=secretref:${ACTIVE_CONTAINER_SECRET}" \
      "${PREVIOUS_KEY_ENV}=secretref:${PREVIOUS_CONTAINER_SECRET}" \
      "${ACTIVE_KID_ENV}=${active_kid}" \
      "${PREVIOUS_KID_ENV}=${previous_kid}" \
    --output none \
    --only-show-errors
}

verify_dual_keyring() {
  local active_kid="$1"
  local previous_kid="$2"
  local active_path="${3:-${active_file}}"
  local previous_path="${4:-${previous_file}}"
  python3 -c '
import base64
import hashlib
import hmac
import json
import pathlib
import sys

active_path, previous_path, active_kid, previous_kid = sys.argv[1:]
keys = {
    active_kid: pathlib.Path(active_path).read_bytes(),
    previous_kid: pathlib.Path(previous_path).read_bytes(),
}
payload = base64.urlsafe_b64encode(
    json.dumps({"probe": "exposure-cursor-rotation"}, separators=(",", ":")).encode()
).rstrip(b"=")
for kid, key in keys.items():
    signature = hmac.new(key, payload, hashlib.sha256).digest()
    token = kid.encode() + b"." + payload + b"." + base64.urlsafe_b64encode(signature)
    token_kid, token_payload, token_signature = token.split(b".", 2)
    selected = keys[token_kid.decode()]
    expected = hmac.new(selected, token_payload, hashlib.sha256).digest()
    actual = base64.urlsafe_b64decode(token_signature)
    if not hmac.compare_digest(expected, actual):
        raise SystemExit("cursor probe verification failed")
' "${active_path}" "${previous_path}" "${active_kid}" "${previous_kid}"
  safe_log "dual-key probe passed for active_kid=${active_kid} previous_kid=${previous_kid}"
}

if [[ "${mode}" == "rollback" ]]; then
  current_active_id="$(secret_id "${ACTIVE_SECRET_NAME}")"
  current_previous_id="$(secret_id "${PREVIOUS_SECRET_NAME}")"
  [[ -n "${current_active_id}" && -n "${current_previous_id}" ]] \
    || die "rollback requires both active and previous Key Vault secrets"
  current_active_kid="$(secret_kid "${ACTIVE_SECRET_NAME}")"
  current_previous_kid="$(secret_kid "${PREVIOUS_SECRET_NAME}")"
  current_active_kid="${current_active_kid:-$(fallback_kid "${current_active_id}")}"
  current_previous_kid="${current_previous_kid:-$(fallback_kid "${current_previous_id}")}"
  [[ "${current_active_kid}" != "${current_previous_kid}" ]] \
    || die "previous key has already retired; choose an older Key Vault version explicitly"

  download_secret "${ACTIVE_SECRET_NAME}" "${active_file}"
  download_secret "${PREVIOUS_SECRET_NAME}" "${previous_file}"
  rollback_active_id="$(
    write_secret "${ACTIVE_SECRET_NAME}" "${previous_file}" "${current_previous_kid}" "active"
  )"
  rollback_previous_id="$(
    write_secret "${PREVIOUS_SECRET_NAME}" "${active_file}" "${current_active_kid}" "previous"
  )"
  revision_suffix="cursor-rb-$(date -u +%Y%m%d%H%M%S)"
  deploy_keyring "${current_previous_kid}" "${current_active_kid}" "${revision_suffix}"
  verify_dual_keyring \
    "${current_previous_kid}" "${current_active_kid}" \
    "${previous_file}" "${active_file}"
  safe_log \
    "rollback deployed active_version=$(version_from_id "${rollback_active_id}") previous_version=$(version_from_id "${rollback_previous_id}")"
  show_status
  exit 0
fi

current_active_id="$(secret_id "${ACTIVE_SECRET_NAME}")"
current_previous_id="$(secret_id "${PREVIOUS_SECRET_NAME}")"
current_active_kid=""
current_previous_kid=""
if [[ -n "${current_active_id}" ]]; then
  current_active_kid="$(secret_kid "${ACTIVE_SECRET_NAME}")"
  current_active_kid="${current_active_kid:-$(fallback_kid "${current_active_id}")}"
fi
if [[ -n "${current_previous_id}" ]]; then
  current_previous_kid="$(secret_kid "${PREVIOUS_SECRET_NAME}")"
  current_previous_kid="${current_previous_kid:-$(fallback_kid "${current_previous_id}")}"
fi
deployed_active_kid="$(container_env_value "${ACTIVE_KID_ENV}")"
deployed_previous_kid="$(container_env_value "${PREVIOUS_KID_ENV}")"

resume_rotation=false
if [[ -n "${current_active_id}" && -n "${current_previous_id}" ]]; then
  if [[
    "${current_active_kid}" != "${current_previous_kid}"
    && "${deployed_previous_kid}" == "${current_previous_kid}"
  ]]; then
    # Either the new active version has not reached the app yet, or the app is
    # inside the dual-key overlap. Reuse those exact versions instead of
    # creating a third key that would prematurely discard the oldest token.
    resume_rotation=true
  elif [[
    "${current_active_kid}" == "${current_previous_kid}"
    && "${deployed_active_kid}" == "unprovisioned"
  ]]; then
    # Initial Key Vault bootstrap completed but the first app revision did not.
    resume_rotation=true
  fi
fi

if [[ "${resume_rotation}" == "true" ]]; then
  if [[ -n "${requested_kid}" && "${requested_kid}" != "${current_active_kid}" ]]; then
    die "a rotation is already pending or overlapping for kid ${current_active_kid}"
  fi
  new_kid="${current_active_kid}"
  previous_kid="${current_previous_kid}"
  active_version_id="${current_active_id}"
  previous_version_id="${current_previous_id}"
  download_secret "${ACTIVE_SECRET_NAME}" "${active_file}"
  download_secret "${PREVIOUS_SECRET_NAME}" "${previous_file}"
  safe_log "resuming pending or overlapping rotation for kid ${new_kid}"
else
  new_kid="${requested_kid:-cursor-$(date -u +%Y%m%d%H%M%S)-$(python3 -c 'import secrets; print(secrets.token_hex(4))')}"
fi

if [[
  "${resume_rotation}" != "true"
  && -n "${current_active_kid}"
  && "${current_active_kid}" == "${new_kid}"
  && "${deployed_active_kid}" == "${new_kid}"
]]; then
  safe_log "kid ${new_kid} is already active; no key material changed"
  show_status
  exit 0
fi

if [[ "${resume_rotation}" != "true" ]]; then
  python3 -c 'import pathlib,secrets,sys; pathlib.Path(sys.argv[1]).write_text(secrets.token_urlsafe(48), encoding="utf-8")' "${active_file}"

  if [[ -n "${current_active_id}" ]]; then
    download_secret "${ACTIVE_SECRET_NAME}" "${previous_file}"
    previous_kid="${current_active_kid}"
  else
    # Initial provisioning has no older cursor to preserve. Seed both slots
    # with the same key and kid so the Container App can resolve both refs.
    cp "${active_file}" "${previous_file}"
    previous_kid="${new_kid}"
  fi

  previous_version_id="$(
    write_secret "${PREVIOUS_SECRET_NAME}" "${previous_file}" "${previous_kid}" "previous"
  )"
  active_version_id="$(
    write_secret "${ACTIVE_SECRET_NAME}" "${active_file}" "${new_kid}" "active"
  )"
fi
revision_suffix="cursor-$(date -u +%Y%m%d%H%M%S)"
deploy_keyring "${new_kid}" "${previous_kid}" "${revision_suffix}"
verify_dual_keyring "${new_kid}" "${previous_kid}"

safe_log \
  "rotation deployed active_version=$(version_from_id "${active_version_id}") previous_version=$(version_from_id "${previous_version_id}")"
safe_log "retaining previous_kid=${previous_kid} for ${overlap_seconds} seconds"
sleep "${overlap_seconds}"

# Retire the old verification key by making the previous slot equivalent to
# active. Older Key Vault versions remain available for an audited rollback,
# but new revisions no longer accept the retired kid.
retired_previous_id="$(
  write_secret "${PREVIOUS_SECRET_NAME}" "${active_file}" "${new_kid}" "retired"
)"
retire_suffix="cursor-retire-$(date -u +%Y%m%d%H%M%S)"
deploy_keyring "${new_kid}" "${new_kid}" "${retire_suffix}"
safe_log \
  "previous key retired after overlap; replacement_version=$(version_from_id "${retired_previous_id}") active_kid=${new_kid}"
show_status
