#!/usr/bin/env bash
#
# Builds the API and web images, pushes them to the registry created by
# Terraform, and records the tag as the single source of truth in
# terraform.tfvars.
#
#   ./infra/scripts/build-and-push.sh                 # auto tag, build + push
#   ./infra/scripts/build-and-push.sh my-fix          # explicit tag
#   ./infra/scripts/build-and-push.sh my-fix --deploy # build, push, apply
#   ./infra/scripts/build-and-push.sh my-fix --api-authorization-release
#   ./infra/scripts/build-and-push.sh my-fix --default-promotion
#
# The registry name is read from Terraform state, so this must run after a
# successful apply.
#
# Both images are always built under the same tag and both are verified to
# exist in the registry afterwards. A tag where only one image landed is a
# hard error -- that is what previously let the api and web apps drift onto
# different builds of the same commit.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tf_dir="${repo_root}/infra/terraform"
tfvars="${tf_dir}/terraform.tfvars"
env_file="${AIOPS_ENV_FILE:-${repo_root}/web/.env.local}"

export PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin"

read_env() {
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

# These values are public browser configuration, not secrets. Resolve them from
# the same env file as deploy.sh so a normal image build needs no manual exports.
if [[ -f "${env_file}" ]]; then
  for name in NEXT_PUBLIC_ENTRA_CLIENT_ID NEXT_PUBLIC_ENTRA_TENANT_ID NEXT_PUBLIC_ENTRA_API_SCOPE; do
    if [[ -z "${!name:-}" ]]; then
      printf -v "${name}" '%s' "$(read_env "${name}")"
      export "${name}"
    fi
  done
fi

deploy_after=0
authorization_release=0
default_promotion=0
tag=""
for arg in "$@"; do
  case "${arg}" in
    --deploy) deploy_after=1 ;;
    --api-authorization-release) authorization_release=1 ;;
    --default-promotion)
      authorization_release=1
      default_promotion=1
      ;;
    -*) echo "build-and-push: unknown flag ${arg}" >&2; exit 2 ;;
    *) if [[ -z "${tag}" ]]; then tag="${arg}"; else
         echo "build-and-push: unexpected argument ${arg}" >&2; exit 2
       fi ;;
  esac
done

# A generated tag is preferred over a hand-typed one: it is always unique, so
# Container Apps sees a new image reference and rolls a fresh revision instead
# of silently reusing a cached layer under a reused tag.
if [[ -z "${tag}" ]]; then
  tag="${IMAGE_TAG:-}"
fi
if [[ -z "${tag}" ]]; then
  slug="$(cd "${repo_root}" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo build)"
  slug="$(printf '%s' "${slug}" | tr -c 'a-zA-Z0-9._-' '-' | cut -c1-40)"
  tag="${slug}-$(date -u +%Y%m%d-%H%M%S)"
fi
if [[ ! "${tag}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "build-and-push: invalid image tag ${tag}" >&2
  exit 2
fi

registry="$(cd "${tf_dir}" && terraform output -raw container_registry 2>/dev/null || true)"
if [[ -z "${registry}" ]]; then
  echo "build-and-push: could not read container_registry from Terraform state." >&2
  echo "Run ./infra/scripts/deploy.sh apply first." >&2
  exit 1
fi

registry_name="${registry%%.*}"

# API tags are immutable release identities. Never resume or overwrite a prior
# API build, because recording that tag would bind its old digest to this
# invocation's source revision.
if [[ "${authorization_release}" -eq 1 ]] && az acr repository show \
  --name "${registry_name}" \
  --image "aiops-api:${tag}" >/dev/null 2>&1; then
  echo "build-and-push: refusing to reuse existing API tag aiops-api:${tag}." >&2
  exit 1
fi

# Container Apps runs linux/amd64. On an Apple Silicon machine a local build
# must cross-build; without Rosetta that falls back to QEMU emulation, which
# is slow and makes `npm ci` in the web image die with "Exit handler never
# called!" (emulated Node exhausts the Docker VM). ACR tasks build natively
# on amd64, so that is the default.
#
#   AIOPS_BUILD_MODE=acr    (default) build in Azure Container Registry
#   AIOPS_BUILD_MODE=local  build locally with docker buildx and push
#
# For local mode see infra/scripts/README-local-builds.md -- it needs Rosetta
# enabled and a Docker VM with >=12 GB RAM to beat ACR.
platform="linux/amd64"
build_mode="${AIOPS_BUILD_MODE:-acr}"
acr_context=""
source_revision="$(git -C "${repo_root}" rev-parse HEAD)"
default_base_digest=""
canary_base_image=""

if [[ "${default_promotion}" -eq 1 ]]; then
  IFS=$'\t' read -r source_revision default_base_digest < <(
    python3 - "${repo_root}/src/operations/copilot_default_authorization.v1.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as manifest_file:
    lineage = json.load(manifest_file)["promotion_lineage"]
print(lineage["base_source_revision"], lineage["base_image_digest"], sep="\t")
PY
  )
  if [[ ! "${source_revision}" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]] ||
    [[ ! "${default_base_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "build-and-push: default promotion manifest has invalid base lineage." >&2
    exit 1
  fi
  canary_base_image="${registry}/aiops-api@${default_base_digest}"
  if ! az acr repository show \
    --name "${registry_name}" \
    --image "aiops-api@${default_base_digest}" >/dev/null 2>&1; then
    echo "build-and-push: canary base image ${canary_base_image} does not exist." >&2
    exit 1
  fi
fi

prepare_acr_context() {
  [[ "${build_mode}" == "acr" ]] || return 0
  # Azure CLI archives the source tree before ACR sees .dockerignore. A live
  # Git fsmonitor socket is not a tar-compatible file and can abort that
  # upload. Build from an immutable archive of HEAD instead: this also keeps
  # ignored credentials, local evidence, and unrelated working-tree files out
  # of the remote build context.
  acr_context="${repo_root}/.acr-build-context.$$"
  rm -rf "${acr_context}"
  mkdir -p "${acr_context}"
  git -C "${repo_root}" archive HEAD | tar -x -C "${acr_context}"
  trap '[[ -z "${acr_context}" ]] || rm -rf "${acr_context}"' EXIT
}

build_image() {
  local image="$1" dockerfile="$2" context="$3"
  local -a build_args=()

  # Recheck API immutability at the build boundary to close races after the
  # early fail-fast check. Force rebuild never permits overwriting an API tag.
  if az acr repository show \
    --name "${registry_name}" \
    --image "${image}:${tag}" >/dev/null 2>&1; then
    if [[ "${image}" == "aiops-api" ]]; then
      echo "build-and-push: refusing to reuse existing API tag aiops-api:${tag}." >&2
      return 1
    fi
    if [[ "${AIOPS_FORCE_REBUILD:-0}" != "1" ]]; then
      echo "build-and-push: reusing ${registry}/${image}:${tag}"
      return 0
    fi
  fi

  if [[ "${image}" == "aiops-api" ]]; then
    if [[ "${default_promotion}" -eq 1 ]]; then
      build_args=(
        --build-arg "AIOPS_CANARY_BASE_IMAGE=${canary_base_image}"
      )
    elif [[ "${build_mode}" == "local" ]] &&
      [[ -n "$(git -C "${repo_root}" status --porcelain --untracked-files=all)" ]]; then
      echo "build-and-push: local API builds require a clean worktree so baked source revision is exact." >&2
      return 1
    else
      build_args=(
        --build-arg "AIOPS_SOURCE_REVISION=${source_revision}"
      )
    fi
  elif [[ "${image}" == "aiops-web" ]]; then
    : "${NEXT_PUBLIC_ENTRA_CLIENT_ID:?Set NEXT_PUBLIC_ENTRA_CLIENT_ID}"
    : "${NEXT_PUBLIC_ENTRA_TENANT_ID:?Set NEXT_PUBLIC_ENTRA_TENANT_ID}"
    : "${NEXT_PUBLIC_ENTRA_API_SCOPE:?Set NEXT_PUBLIC_ENTRA_API_SCOPE}"
    build_args=(
      --build-arg "NEXT_PUBLIC_ENTRA_CLIENT_ID=${NEXT_PUBLIC_ENTRA_CLIENT_ID}"
      --build-arg "NEXT_PUBLIC_ENTRA_TENANT_ID=${NEXT_PUBLIC_ENTRA_TENANT_ID}"
      --build-arg "NEXT_PUBLIC_ENTRA_API_SCOPE=${NEXT_PUBLIC_ENTRA_API_SCOPE}"
    )
  fi

  echo "build-and-push: building ${registry}/${image}:${tag} (${build_mode})"
  if [[ "${build_mode}" == "acr" ]]; then
    local build_context dockerfile_arg
    if [[ "${context}" == "${repo_root}" ]]; then
      build_context="${acr_context}"
      dockerfile_arg="${dockerfile#"${repo_root}/"}"
    elif [[ "${context}" == "${repo_root}/"* ]]; then
      build_context="${acr_context}/${context#"${repo_root}/"}"
      dockerfile_arg="${dockerfile#"${context}/"}"
    else
      echo "build-and-push: ACR context must be inside ${repo_root}" >&2
      return 1
    fi
    (
      cd "${build_context}"
      az acr build \
        --registry "${registry_name}" \
        --image "${image}:${tag}" \
        --platform "${platform}" \
        --file "${dockerfile_arg}" \
        ${build_args[@]+"${build_args[@]}"} \
        .
    )
  else
    # --cache-from/--cache-to against the registry means an incremental local
    # build reuses layers from the last push instead of rebuilding the whole
    # dependency stage every time.
    docker buildx build \
      --platform "${platform}" \
      --file "${dockerfile}" \
      --tag "${registry}/${image}:${tag}" \
      --cache-from "type=registry,ref=${registry}/${image}:buildcache" \
      --cache-to "type=registry,ref=${registry}/${image}:buildcache,mode=max" \
      ${build_args[@]+"${build_args[@]}"} \
      --push \
      "${context}"
  fi
}

# Pointing Container Apps at a half-pushed tag produces a revision stuck in
# ActivationFailed with MANIFEST_UNKNOWN, so confirm all images landed.
verify_pushed() {
  local image missing=()
  for image in "$@"; do
    if ! az acr repository show \
      --name "${registry_name}" \
      --image "${image}:${tag}" >/dev/null 2>&1; then
      missing+=("${image}:${tag}")
    fi
  done
  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "build-and-push: image(s) missing from ${registry} after build: ${missing[*]}" >&2
    echo "build-and-push: NOT updating terraform.tfvars -- the tag is incomplete." >&2
    exit 1
  fi
}

# terraform.tfvars is the source of truth Terraform reads on a plain apply.
# Writing it here is what stops the deployed revision from drifting behind
# the newest pushed tag.
resolve_api_digest() {
  local resolved_tag resolved_digest
  IFS=$'\t' read -r resolved_tag resolved_digest < <(
    az acr repository show-tags \
      --name "${registry_name}" \
      --repository "aiops-api" \
      --detail \
      --query "[?name=='${tag}'] | [0].[name,digest]" \
      --output tsv
  )
  if [[ "${resolved_tag}" != "${tag}" ]]; then
    echo "build-and-push: resolved API manifest does not correspond to aiops-api:${tag}." >&2
    exit 1
  fi
  if [[ ! "${resolved_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "build-and-push: resolved API manifest digest is malformed." >&2
    exit 1
  fi
  printf '%s\n' "${resolved_digest}"
}

record_authorization_release() {
  local api_digest="$1" base_digest="${2:-}"
  if [[ ! -f "${tfvars}" ]]; then
    echo "build-and-push: ${tfvars} not found; cannot record immutable release." >&2
    if [[ "${deploy_after}" -eq 1 ]]; then
      exit 1
    fi
    return 0
  fi
  local tmp="${tfvars}.tmp.$$"
  if ! awk -v digest="${api_digest}" -v revision="${source_revision}" -v base_digest="${base_digest}" '
    /^[ \t]*api_image_digest[ \t]*=/ { print "api_image_digest = \"" digest "\""; seen_digest = 1; next }
    /^[ \t]*deployment_source_revision[ \t]*=/ { print "deployment_source_revision = \"" revision "\""; seen_revision = 1; next }
    /^[ \t]*copilot_default_base_image_digest[ \t]*=/ { print "copilot_default_base_image_digest = \"" base_digest "\""; seen_base = 1; next }
    { print }
    END { if (!seen_digest) print "api_image_digest = \"" digest "\"" }
    END { if (!seen_revision) print "deployment_source_revision = \"" revision "\"" }
    END { if (!seen_base) print "copilot_default_base_image_digest = \"" base_digest "\"" }
  ' "${tfvars}" >"${tmp}"; then
    rm -f "${tmp}"
    return 1
  fi
  mv "${tmp}" "${tfvars}"
  echo "build-and-push: atomically recorded API digest=${api_digest}, deployment_source_revision=${source_revision}, and default base digest=${base_digest:-none}"
}

record_application_release() {
  local api_digest="$1"
  if [[ ! -f "${tfvars}" ]]; then
    echo "build-and-push: ${tfvars} not found; cannot record application release." >&2
    if [[ "${deploy_after}" -eq 1 ]]; then
      exit 1
    fi
    return 0
  fi
  local tmp="${tfvars}.tmp.$$"
  if ! awk -v tag="${tag}" -v digest="${api_digest}" -v revision="${source_revision}" '
    /^[ \t]*image_tag[ \t]*=/ { print "image_tag     = \"" tag "\""; seen = 1; next }
    /^[ \t]*api_image_digest[ \t]*=/ { print "api_image_digest = \"" digest "\""; seen_digest = 1; next }
    /^[ \t]*deployment_source_revision[ \t]*=/ { print "deployment_source_revision = \"" revision "\""; seen_revision = 1; next }
    /^[ \t]*copilot_default_base_image_digest[ \t]*=/ { print "copilot_default_base_image_digest = \"\""; seen_base = 1; next }
    { print }
    END { if (!seen) print "image_tag     = \"" tag "\"" }
    END { if (!seen_digest) print "api_image_digest = \"" digest "\"" }
    END { if (!seen_revision) print "deployment_source_revision = \"" revision "\"" }
    END { if (!seen_base) print "copilot_default_base_image_digest = \"\"" }
  ' "${tfvars}" >"${tmp}"; then
    rm -f "${tmp}"
    return 1
  fi
  mv "${tmp}" "${tfvars}"
  echo "build-and-push: atomically recorded image_tag=${tag}, API digest=${api_digest}, and deployment_source_revision=${source_revision}"
}

if [[ "${build_mode}" == "local" ]]; then
  echo "build-and-push: authenticating to ${registry}"
  az acr login --name "${registry_name}"
fi

prepare_acr_context

if [[ "${authorization_release}" -eq 1 ]]; then
  # This release gate authorizes API code only. Existing Operations MCP
  # endpoint/catalog/connection identity may be consumed by the API, but MCP
  # container images are neither built nor validated nor changed by this path.
  reviewed_root="${repo_root}"
  if [[ "${build_mode}" == "acr" ]]; then
    reviewed_root="${acr_context}"
  fi
  PYTHONPATH="${reviewed_root}/src" python3 -m operations.reviewed_tree \
    --root "${reviewed_root}" \
    --manifest "${reviewed_root}/src/operations/copilot_canary_authorization.v1.json" \
    >/dev/null
  PYTHONPATH="${reviewed_root}/src" python3 -m operations.reviewed_tree \
    --root "${reviewed_root}" \
    --manifest "${reviewed_root}/src/operations/copilot_default_authorization.v1.json" \
    >/dev/null
  api_dockerfile="${repo_root}/Dockerfile"
  if [[ "${default_promotion}" -eq 1 ]]; then
    api_dockerfile="${repo_root}/Dockerfile.default-promotion"
  fi
  build_image aiops-api "${api_dockerfile}" "${repo_root}"
  verify_pushed aiops-api
  api_digest="$(resolve_api_digest)"
  record_authorization_release "${api_digest}" "${default_base_digest}"
  echo
  echo "build-and-push: pushed API authorization release '${tag}'."
else
  build_image aiops-api "${repo_root}/Dockerfile" "${repo_root}"
  build_image aiops-web "${repo_root}/web/Dockerfile" "${repo_root}/web"
  build_image mcp-server "${repo_root}/Dockerfile.mcp" "${repo_root}"
  build_image azure-mcp "${repo_root}/Dockerfile.azure-mcp" "${repo_root}"
  verify_pushed aiops-api aiops-web mcp-server azure-mcp
  api_digest="$(resolve_api_digest)"
  record_application_release "${api_digest}"
  echo
  echo "build-and-push: pushed application images with tag '${tag}'."
fi

if [[ "${deploy_after}" -eq 1 ]]; then
  echo "build-and-push: deploying..."
  if [[ "${authorization_release}" -eq 1 ]]; then
    export AIOPS_API_AUTHORIZATION_RELEASE=1
    exec "${repo_root}/infra/scripts/deploy.sh" apply \
      -target=azurerm_container_app.api \
      -auto-approve
  fi
  exec "${repo_root}/infra/scripts/deploy.sh" apply -auto-approve
else
  echo "Deploy them with:"
  if [[ "${authorization_release}" -eq 1 ]]; then
    echo "  AIOPS_API_AUTHORIZATION_RELEASE=1 ./infra/scripts/deploy.sh apply -target=azurerm_container_app.api"
    echo "(terraform.tfvars carries only the immutable API digest and source revision)"
  else
    echo "  ./infra/scripts/deploy.sh apply"
    echo "(terraform.tfvars carries deploy_images, the new image_tag, immutable API digest, and source revision)"
  fi
fi
