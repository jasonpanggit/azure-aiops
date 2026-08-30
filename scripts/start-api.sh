#!/bin/sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$repo_root"

# Reuse the local frontend configuration for the API process. The file is
# ignored by Git and may contain the local SPN environment reference.
if [ -f "$repo_root/web/.env.local" ]; then
  set -a
  . "$repo_root/web/.env.local"
  set +a
fi

if [ -z "${AIOPS_API_AUTH:-}" ]; then
  AIOPS_API_AUTH=token
fi
if [ -z "${AIOPS_API_TOKENS:-}" ]; then
  AIOPS_API_TOKENS="{\"${AIOPS_DEV_TOKEN:-local-dev-token-1234}\":{\"subject\":\"local\",\"grants\":[{\"role\":\"admin\"}]}}"
fi
if [ -z "${AIOPS_API_CORS_ORIGINS:-}" ]; then
  AIOPS_API_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
fi

AIOPS_LOCAL_SEED="${AIOPS_LOCAL_SEED:-0}"
case "$AIOPS_LOCAL_SEED" in
  0|false|False|no|No)
    AIOPS_RUNTIME_MODE="${AIOPS_RUNTIME_MODE:-production}"
    ;;
  *)
    AIOPS_RUNTIME_MODE=demo
    AIOPS_HOME="${AIOPS_HOME:-$repo_root/.aiops-local}"
    AIOPS_LOCAL_FIXTURE="${AIOPS_LOCAL_FIXTURE:-tests/fixtures/mock_arg_responses.json}"
    AIOPS_LOCAL_CONNECTION_ID="${AIOPS_LOCAL_CONNECTION_ID:-local-spn}"
    AIOPS_LOCAL_AUTO_SYNC="${AIOPS_LOCAL_AUTO_SYNC:-1}"
    ;;
esac

# Ensure `az` (Azure CLI) is resolvable regardless of the invoking shell's
# PATH — connection sync shells out to it via AzureCliArgClient, and a
# non-login shell (cron, some IDE terminals, CI) may not include Homebrew's
# bin directories by default.
for az_dir in /opt/homebrew/bin /usr/local/bin; do
  case ":${PATH}:" in
    *":${az_dir}:"*) ;;
    *) [ -x "${az_dir}/az" ] && PATH="${PATH}:${az_dir}" ;;
  esac
done

export AIOPS_API_AUTH AIOPS_API_TOKENS AIOPS_API_CORS_ORIGINS AIOPS_HOME AIOPS_RUNTIME_MODE PATH
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}src"

case "$AIOPS_LOCAL_SEED" in
  0|false|False|no|No) ;;
  *)
    if [ -n "${AZURE_SUBSCRIPTION_ID:-}" ] && [ -n "${AZURE_TENANT_ID:-}" ] && [ -n "${AZURE_CLIENT_ID:-}" ] && [ -n "${AZURE_CLIENT_SECRET:-}" ] \
      && [ "${AZURE_SUBSCRIPTION_ID#<}" = "$AZURE_SUBSCRIPTION_ID" ] \
      && [ "${AZURE_TENANT_ID#<}" = "$AZURE_TENANT_ID" ] \
      && [ "${AZURE_CLIENT_ID#<}" = "$AZURE_CLIENT_ID" ] \
      && [ "${AZURE_CLIENT_SECRET#<}" = "$AZURE_CLIENT_SECRET" ]; then
      case "$AIOPS_LOCAL_AUTO_SYNC" in
        0|false|False|no|No)
          .venv/bin/aiops-inventory local-spn --home "$AIOPS_HOME" --connection-id "$AIOPS_LOCAL_CONNECTION_ID" >/dev/null
          ;;
        *)
          .venv/bin/aiops-inventory local-spn --home "$AIOPS_HOME" --connection-id "$AIOPS_LOCAL_CONNECTION_ID" --sync >/dev/null
          ;;
      esac
    else
      .venv/bin/aiops-inventory local --home "$AIOPS_HOME" --fixture "$AIOPS_LOCAL_FIXTURE" >/dev/null
    fi
    ;;
esac

exec .venv/bin/uvicorn api.app:create_app \
  --factory \
  --host "${AIOPS_API_HOST:-127.0.0.1}" \
  --port "${AIOPS_API_PORT:-8080}" \
  --reload \
  --reload-dir src \
  --reload-dir scripts \
  "$@"
