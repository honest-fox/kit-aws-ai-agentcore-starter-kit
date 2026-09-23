#!/usr/bin/env bash
#
# Kit evaluation — run the golden set against a deployed agent.
#
#   ./scripts/eval.sh              full suite against your deployed stack
#   ./scripts/eval.sh --validate   offline dataset check, no AWS needed
#   ./scripts/eval.sh --no-judge   deterministic assertions only
#
# Exits 0 if the quality gate passed, 1 if it failed, 2 on a configuration
# or dataset error.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/evals"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install it: https://docs.astral.sh/uv/" >&2
  exit 2
fi

uv sync --quiet --extra dev
exec uv run python -m harness.cli "$@"
