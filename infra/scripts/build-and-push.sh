#!/usr/bin/env bash
#
# Builds the API and web images, pushes them to the registry created by
# Terraform, and records the tag as the single source of truth in
# terraform.tfvars.
#
#   ./infra/scripts/build-and-push.sh                 # auto tag, build + push
#   ./infra/scripts/build-and-push.sh my-fix          # explicit tag
#   ./infra/scripts/build-and-push.sh my-fix --deploy # build, push, apply
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

export PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin"

deploy_after=0
tag=""
for arg in "$@"; do
  case "${arg}" in
    --deploy) deploy_after=1 ;;
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

registry="$(cd "${tf_dir}" && terraform output -raw container_registry 2>/dev/null || true)"
if [[ -z "${registry}" ]]; then
  echo "build-and-push: could not read container_registry from Terraform state." >&2
  echo "Run ./infra/scripts/deploy.sh apply first." >&2
  exit 1
fi

registry_name="${registry%%.*}"

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

build_image() {
  local image="$1" dockerfile="$2" context="$3"
  local -a build_args=()
  if [[ "${image}" == "aiops-web" ]]; then
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
    az acr build \
      --registry "${registry_name}" \
      --image "${image}:${tag}" \
      --platform "${platform}" \
      --file "${dockerfile}" \
      ${build_args[@]+"${build_args[@]}"} \
      "${context}"
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
  for image in aiops-api aiops-web mcp-server azure-mcp; do
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
record_tag() {
  if [[ ! -f "${tfvars}" ]]; then
    echo "build-and-push: ${tfvars} not found; skipping tag record." >&2
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  awk -v tag="${tag}" '
    /^[ \t]*image_tag[ \t]*=/ { print "image_tag     = \"" tag "\""; seen = 1; next }
    { print }
    END { if (!seen) print "image_tag     = \"" tag "\"" }
  ' "${tfvars}" >"${tmp}"
  mv "${tmp}" "${tfvars}"
  echo "build-and-push: recorded image_tag = \"${tag}\" in terraform.tfvars"
}

if [[ "${build_mode}" == "local" ]]; then
  echo "build-and-push: authenticating to ${registry}"
  az acr login --name "${registry_name}"
fi

build_image aiops-api "${repo_root}/Dockerfile" "${repo_root}"
build_image aiops-web "${repo_root}/web/Dockerfile" "${repo_root}/web"
build_image mcp-server "${repo_root}/Dockerfile.mcp" "${repo_root}"
build_image azure-mcp "${repo_root}/Dockerfile.azure-mcp" "${repo_root}"

verify_pushed
record_tag

echo
echo "build-and-push: pushed both images with tag '${tag}'."

if [[ "${deploy_after}" -eq 1 ]]; then
  echo "build-and-push: deploying..."
  exec "${repo_root}/infra/scripts/deploy.sh" apply -auto-approve
else
  echo "Deploy them with:"
  echo "  ./infra/scripts/deploy.sh apply"
  echo "(terraform.tfvars already carries deploy_images and the new image_tag)"
fi
