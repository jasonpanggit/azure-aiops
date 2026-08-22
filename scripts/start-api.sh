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

if [ -z "${HERMES_API_AUTH:-}" ]; then
  HERMES_API_AUTH=token
fi
if [ -z "${HERMES_API_TOKENS:-}" ]; then
  HERMES_API_TOKENS="{\"${HERMES_DEV_TOKEN:-local-dev-token-1234}\":{\"subject\":\"local\",\"grants\":[{\"role\":\"admin\"}]}}"
fi
if [ -z "${HERMES_API_CORS_ORIGINS:-}" ]; then
  HERMES_API_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
fi

HERMES_LOCAL_SEED="${HERMES_LOCAL_SEED:-0}"
case "$HERMES_LOCAL_SEED" in
  0|false|False|no|No)
    HERMES_RUNTIME_MODE="${HERMES_RUNTIME_MODE:-production}"
    if [ -z "${HERMES_DATABASE_URL:-}" ]; then
      HERMES_DATABASE_URL="postgresql://hermes:hermes@127.0.0.1:5432/hermes"
    fi
    ;;
  *)
    HERMES_RUNTIME_MODE=demo
    HERMES_HOME="${HERMES_HOME:-$repo_root/.hermes-local}"
    HERMES_LOCAL_FIXTURE="${HERMES_LOCAL_FIXTURE:-tests/fixtures/mock_arg_responses.json}"
    HERMES_LOCAL_CONNECTION_ID="${HERMES_LOCAL_CONNECTION_ID:-local-spn}"
    HERMES_LOCAL_AUTO_SYNC="${HERMES_LOCAL_AUTO_SYNC:-1}"
    unset HERMES_DATABASE_URL
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

export HERMES_API_AUTH HERMES_API_TOKENS HERMES_API_CORS_ORIGINS HERMES_HOME HERMES_RUNTIME_MODE PATH
if [ -n "${HERMES_DATABASE_URL:-}" ]; then
  export HERMES_DATABASE_URL
fi
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}src"

case "$HERMES_LOCAL_SEED" in
  0|false|False|no|No) ;;
  *)
    if [ -n "${AZURE_SUBSCRIPTION_ID:-}" ] && [ -n "${AZURE_TENANT_ID:-}" ] && [ -n "${AZURE_CLIENT_ID:-}" ] && [ -n "${AZURE_CLIENT_SECRET:-}" ] \
      && [ "${AZURE_SUBSCRIPTION_ID#<}" = "$AZURE_SUBSCRIPTION_ID" ] \
      && [ "${AZURE_TENANT_ID#<}" = "$AZURE_TENANT_ID" ] \
      && [ "${AZURE_CLIENT_ID#<}" = "$AZURE_CLIENT_ID" ] \
      && [ "${AZURE_CLIENT_SECRET#<}" = "$AZURE_CLIENT_SECRET" ]; then
      case "$HERMES_LOCAL_AUTO_SYNC" in
        0|false|False|no|No)
          .venv/bin/hermes-arg local-spn --home "$HERMES_HOME" --connection-id "$HERMES_LOCAL_CONNECTION_ID" >/dev/null
          ;;
        *)
          .venv/bin/hermes-arg local-spn --home "$HERMES_HOME" --connection-id "$HERMES_LOCAL_CONNECTION_ID" --sync >/dev/null
          ;;
      esac
    else
      .venv/bin/hermes-arg local --home "$HERMES_HOME" --fixture "$HERMES_LOCAL_FIXTURE" >/dev/null
    fi
    ;;
esac

exec .venv/bin/uvicorn api.app:create_app \
  --factory \
  --host "${HERMES_API_HOST:-127.0.0.1}" \
  --port "${HERMES_API_PORT:-8080}" \
  --reload \
  --reload-dir src \
  --reload-dir scripts \
  "$@"
