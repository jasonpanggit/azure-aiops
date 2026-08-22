#!/bin/sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
HERMES_LOCAL_SEED=1 exec "$repo_root/scripts/start-api.sh" "$@"
