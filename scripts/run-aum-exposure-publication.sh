#!/usr/bin/env bash
# Ensure the dedicated E8 workload profile exists, run one guarded fresh AUM
# Exposure publication via scripts/recover_aum_exposure_publication.py, then
# tear the profile back down if this script is the one that created it.
#
# Every historically successful publication execution ran on a dedicated
# 8 vCPU / 64Gi profile. The Consumption default (4 vCPU / 8Gi) is not
# sufficient and reliably fails. This wrapper removes the need to
# provision/remove that profile by hand each time.
set -euo pipefail

RESOURCE_GROUP="${AIOPS_PUBLICATION_RESOURCE_GROUP:-aiops-dev-rg}"
ENV_NAME="${AIOPS_PUBLICATION_ENV:-aiops-dev-cae}"
JOB_NAME="${AIOPS_PUBLICATION_JOB:-aiops-dev-exposure-publication}"
PROFILE_NAME="${AIOPS_PUBLICATION_WORKLOAD_PROFILE:-publication-e8}"
PROFILE_TYPE="${AIOPS_PUBLICATION_WORKLOAD_PROFILE_TYPE:-E8}"
PROFILE_MIN_NODES="${AIOPS_PUBLICATION_WORKLOAD_PROFILE_MIN:-0}"
PROFILE_MAX_NODES="${AIOPS_PUBLICATION_WORKLOAD_PROFILE_MAX:-1}"
TARGET_CPU="${AIOPS_PUBLICATION_TARGET_CPU:-8}"
TARGET_MEMORY="${AIOPS_PUBLICATION_TARGET_MEMORY:-64Gi}"
TARGET_TIMEOUT="${AIOPS_PUBLICATION_TARGET_TIMEOUT:-14400}"
TOKEN_RESOURCE="${AIOPS_API_TOKEN_RESOURCE:-api://306c1437-0e7d-43bd-940b-79b878166331}"
KEEP_PROFILE=0
SUBSCRIPTION=""
IMAGE=""
API_BASE_URL=""
SUBSCRIPTION_SCOPE=""
EVIDENCE_DIR=""

usage() {
  cat <<'EOF'
Usage: run-aum-exposure-publication.sh --image IMAGE --api-base-url URL --subscription-scope SUB [options]

Required:
  --image IMAGE               Immutable image ref (tag or digest) for the publication run
  --api-base-url URL          Exposure API base URL used for post-run facet validation
  --subscription-scope SUB    Subscription id passed to the Exposure API for scoping

Options:
  --subscription SUB          Azure subscription id (default: AZURE_SUBSCRIPTION_ID env or current az context)
  --resource-group NAME       Resource group (default: aiops-dev-rg)
  --env NAME                  Container Apps environment (default: aiops-dev-cae)
  --job NAME                  Container Apps Job (default: aiops-dev-exposure-publication)
  --profile-name NAME         Dedicated workload profile name (default: publication-e8)
  --profile-type TYPE         Dedicated workload profile SKU (default: E8)
  --target-cpu N              Target CPU for the publication run (default: 8)
  --target-memory Gi          Target memory for the publication run (default: 64Gi)
  --target-timeout SECONDS    Target replica timeout (default: 14400)
  --evidence-dir PATH         Evidence directory (default: timestamped under /tmp)
  --keep-profile               Do not remove the workload profile after the run,
                               even if this script created it
  -h, --help                   Show this help

Environment variables:
  AIOPS_PUBLICATION_RESOURCE_GROUP, AIOPS_PUBLICATION_ENV, AIOPS_PUBLICATION_JOB,
  AIOPS_PUBLICATION_WORKLOAD_PROFILE, AIOPS_PUBLICATION_WORKLOAD_PROFILE_TYPE,
  AIOPS_PUBLICATION_WORKLOAD_PROFILE_MIN, AIOPS_PUBLICATION_WORKLOAD_PROFILE_MAX,
  AIOPS_PUBLICATION_TARGET_CPU, AIOPS_PUBLICATION_TARGET_MEMORY,
  AIOPS_PUBLICATION_TARGET_TIMEOUT, AIOPS_API_TOKEN_RESOURCE
EOF
}

while (($#)); do
  case "$1" in
    --image) IMAGE="${2:?missing value for --image}"; shift 2 ;;
    --api-base-url) API_BASE_URL="${2:?missing value for --api-base-url}"; shift 2 ;;
    --subscription-scope) SUBSCRIPTION_SCOPE="${2:?missing value for --subscription-scope}"; shift 2 ;;
    --subscription) SUBSCRIPTION="${2:?missing value for --subscription}"; shift 2 ;;
    --resource-group) RESOURCE_GROUP="${2:?missing value for --resource-group}"; shift 2 ;;
    --env) ENV_NAME="${2:?missing value for --env}"; shift 2 ;;
    --job) JOB_NAME="${2:?missing value for --job}"; shift 2 ;;
    --profile-name) PROFILE_NAME="${2:?missing value for --profile-name}"; shift 2 ;;
    --profile-type) PROFILE_TYPE="${2:?missing value for --profile-type}"; shift 2 ;;
    --target-cpu) TARGET_CPU="${2:?missing value for --target-cpu}"; shift 2 ;;
    --target-memory) TARGET_MEMORY="${2:?missing value for --target-memory}"; shift 2 ;;
    --target-timeout) TARGET_TIMEOUT="${2:?missing value for --target-timeout}"; shift 2 ;;
    --evidence-dir) EVIDENCE_DIR="${2:?missing value for --evidence-dir}"; shift 2 ;;
    --keep-profile) KEEP_PROFILE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$IMAGE" || -z "$API_BASE_URL" || -z "$SUBSCRIPTION_SCOPE" ]]; then
  echo "error: --image, --api-base-url, and --subscription-scope are required" >&2
  usage >&2
  exit 2
fi

if [[ -z "$SUBSCRIPTION" ]]; then
  SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"
fi

if [[ -z "$EVIDENCE_DIR" ]]; then
  EVIDENCE_DIR="/tmp/aum-publication-recovery-$(date -u +%Y%m%dT%H%M%SZ)"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

profile_exists() {
  az containerapp env workload-profile list \
    --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" \
    --query "[?name=='${PROFILE_NAME}'] | length(@)" -o tsv
}

CREATED_PROFILE=0
if [[ "$(profile_exists)" == "0" ]]; then
  echo "Provisioning dedicated workload profile '$PROFILE_NAME' ($PROFILE_TYPE, min=$PROFILE_MIN_NODES, max=$PROFILE_MAX_NODES)..."
  az containerapp env workload-profile add \
    --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" \
    --workload-profile-name "$PROFILE_NAME" \
    --workload-profile-type "$PROFILE_TYPE" \
    --min-nodes "$PROFILE_MIN_NODES" \
    --max-nodes "$PROFILE_MAX_NODES" \
    --only-show-errors -o none
  CREATED_PROFILE=1
else
  echo "Workload profile '$PROFILE_NAME' already exists; leaving it as-is."
fi

cleanup() {
  if [[ "$CREATED_PROFILE" == "1" && "$KEEP_PROFILE" == "0" ]]; then
    echo "Removing workload profile '$PROFILE_NAME' (provisioned by this run)..."
    az containerapp env workload-profile delete \
      --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" \
      --workload-profile-name "$PROFILE_NAME" \
      --only-show-errors -o none || echo "warning: failed to remove workload profile '$PROFILE_NAME'; remove it manually." >&2
  fi
}
trap cleanup EXIT

export AIOPS_API_TOKEN
AIOPS_API_TOKEN="$(az account get-access-token --resource "$TOKEN_RESOURCE" --query accessToken -o tsv)"

mkdir -p "$EVIDENCE_DIR"
echo "Evidence dir: $EVIDENCE_DIR"

python3 "$SCRIPT_DIR/recover_aum_exposure_publication.py" \
  --subscription "$SUBSCRIPTION" \
  --resource-group "$RESOURCE_GROUP" \
  --job-name "$JOB_NAME" \
  --image "$IMAGE" \
  --target-workload-profile "$PROFILE_NAME" \
  --target-cpu "$TARGET_CPU" \
  --target-memory "$TARGET_MEMORY" \
  --target-timeout "$TARGET_TIMEOUT" \
  --api-base-url "$API_BASE_URL" \
  --subscription-scope "$SUBSCRIPTION_SCOPE" \
  --evidence-dir "$EVIDENCE_DIR"
