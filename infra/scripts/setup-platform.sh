#!/usr/bin/env bash
# Bash entry point for the existing Terraform-backed platform setup.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "setup: uv is required; install uv and run 'uv sync --locked --extra api --extra test' in the platform checkout." >&2
  exit 127
fi

if [[ ! -x "${repo_root}/.venv/bin/python" ]]; then
  echo "setup: dependencies are not prepared; run 'uv sync --locked --extra api --extra test' in ${repo_root}." >&2
  exit 1
fi

cd -- "${repo_root}"
exec uv run --no-sync python "${repo_root}/infra/scripts/setup-platform.py" "$@"
