#!/usr/bin/env bash
#
# Builds the API and web images and pushes them to the registry created by
# Terraform.
#
#   ./infra/scripts/build-and-push.sh [tag]
#
# The registry name is read from Terraform state, so this must run after a
# successful apply. Run it before setting deploy_images=true.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tf_dir="${repo_root}/infra/terraform"

export PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin"

tag="${1:-${IMAGE_TAG:-v1}}"

registry="$(cd "${tf_dir}" && terraform output -raw container_registry 2>/dev/null || true)"
if [[ -z "${registry}" ]]; then
  echo "build-and-push: could not read container_registry from Terraform state." >&2
  echo "Run ./infra/scripts/deploy.sh apply first." >&2
  exit 1
fi

registry_name="${registry%%.*}"

# Container Apps runs linux/amd64. On an Apple Silicon machine a local build
# must cross-build under QEMU emulation, which is slow and makes `npm ci` in
# the web image die with "Exit handler never called!" (emulated Node exhausts
# the Docker VM). ACR tasks build natively on amd64, so that is the default.
#
#   AIOPS_BUILD_MODE=acr    (default) build in Azure Container Registry
#   AIOPS_BUILD_MODE=local  build locally with docker buildx and push
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
    if [[ "${#build_args[@]}" -gt 0 ]]; then
      az acr build \
        --registry "${registry_name}" \
        --image "${image}:${tag}" \
        --platform "${platform}" \
        --file "${dockerfile}" \
        "${build_args[@]}" \
        "${context}"
    else
      az acr build \
        --registry "${registry_name}" \
        --image "${image}:${tag}" \
        --platform "${platform}" \
        --file "${dockerfile}" \
        "${context}"
    fi
  else
    if [[ "${#build_args[@]}" -gt 0 ]]; then
      docker buildx build \
        --platform "${platform}" \
        --file "${dockerfile}" \
        --tag "${registry}/${image}:${tag}" \
        "${build_args[@]}" \
        --push \
        "${context}"
    else
      docker buildx build \
        --platform "${platform}" \
        --file "${dockerfile}" \
        --tag "${registry}/${image}:${tag}" \
        --push \
        "${context}"
    fi
  fi
}

if [[ "${build_mode}" == "local" ]]; then
  echo "build-and-push: authenticating to ${registry}"
  az acr login --name "${registry_name}"
fi

build_image aiops-api "${repo_root}/Dockerfile" "${repo_root}"
build_image aiops-web "${repo_root}/web/Dockerfile" "${repo_root}/web"

echo
echo "build-and-push: pushed both images with tag '${tag}'."
echo "Deploy them with:"
echo "  ./infra/scripts/deploy.sh apply -var deploy_images=true -var image_tag=${tag}"
