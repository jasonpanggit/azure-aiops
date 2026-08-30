#!/bin/sh
set -eu

# Refresh the AIOps semantic graph: discover Azure inventory via the
# registered SPN connection, publish it to the Fabric/OneLake lakehouse, and
# activate the ontology. This is the "aiops agent discovery" entry point.
#
# Credentials are sourced from web/.env.local (the same SPN used by the local
# frontend/API dev loop) rather than requiring them to be exported by hand.

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$repo_root"

if [ -f "$repo_root/web/.env.local" ]; then
  set -a
  . "$repo_root/web/.env.local"
  set +a
else
  echo "error: $repo_root/web/.env.local not found; cannot source SPN credentials" >&2
  exit 1
fi

for var in AZURE_SUBSCRIPTION_ID AZURE_TENANT_ID AZURE_CLIENT_ID AZURE_CLIENT_SECRET; do
  eval "value=\${$var:-}"
  case "$value" in
    "" | "<"*)
      echo "error: $var is not set (or is a placeholder) in web/.env.local" >&2
      exit 1
      ;;
  esac
done

# Ensure `az` is resolvable regardless of the invoking shell's PATH — the
# discovery client shells out to it via AzureCliArgClient.
for az_dir in /opt/homebrew/bin /usr/local/bin; do
  case ":${PATH}:" in
    *":${az_dir}:"*) ;;
    *) [ -x "${az_dir}/az" ] && PATH="${PATH}:${az_dir}" ;;
  esac
done
export PATH

# `activate` (via build_onboarding_service) reads/writes its connection
# registry at config.yaml's storage.output_dir, not AIOPS_HOME. Register the
# SPN connection there so `activate` can find it.
AIOPS_CONNECTION_ROOT="${AIOPS_CONNECTION_ROOT:-$repo_root/live-data}"
AIOPS_LOCAL_CONNECTION_ID="${AIOPS_LOCAL_CONNECTION_ID:-local-spn}"
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}src"

# Register/refresh the SPN connection metadata from env (idempotent).
.venv/bin/aiops-inventory local-spn \
  --home "$AIOPS_CONNECTION_ROOT" \
  --connection-id "$AIOPS_LOCAL_CONNECTION_ID"

# Discover -> publish to Fabric -> activate ontology.
# AIOPS_MCP_COMMAND_JSON lets callers override azure.mcp_command (e.g. to use
# `npx -y @azure/mcp@latest` in environments without a preinstalled `azmcp`
# binary) without editing the checked-in config.yaml.
config_arg="${AIOPS_CONFIG:-config.yaml}"
if [ -n "${AIOPS_MCP_COMMAND_JSON:-}" ]; then
  tmp_config="$(mktemp -t aiops-config.XXXXXX.yaml)"
  trap 'rm -f "$tmp_config"' EXIT
  .venv/bin/python - "$config_arg" "$tmp_config" "$AIOPS_MCP_COMMAND_JSON" "$repo_root" <<'PY'
import sys
import json
import yaml

src, dst, mcp_json, repo_root = sys.argv[1:5]
with open(src) as handle:
    data = yaml.safe_load(handle)
data.setdefault("azure", {})["mcp_command"] = json.loads(mcp_json)
# Re-anchor a relative output_dir to the repo root: the rewritten config is
# written to a tmp directory, and ConnectorConfig.load() resolves relative
# output_dir against the config file's own parent directory.
storage = data.setdefault("storage", {})
output_dir = str(storage.get("output_dir") or "./data")
if not output_dir.startswith(("/", "abfss://", "onelake://")):
    output_dir = str((__import__("pathlib").Path(repo_root) / output_dir).resolve())
storage["output_dir"] = output_dir
with open(dst, "w") as handle:
    yaml.safe_dump(data, handle)
PY
  config_arg="$tmp_config"
fi

exec .venv/bin/aiops-inventory activate \
  --config "$config_arg" \
  --fabric-config "${AIOPS_FABRIC_CONFIG:-fabric.config.yaml}" \
  --connection-id "$AIOPS_LOCAL_CONNECTION_ID" \
  "$@"
