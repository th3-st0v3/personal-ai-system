#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# The acceptance script imports the shared preflight module as scripts.*.
# Executing it by absolute path sets sys.path to scripts/, so expose the
# repository root explicitly for the namespace-package import.
export PYTHONPATH="$REPO_ROOT${PYTHONPATH-}"

PYTHON="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "error: expected executable Python at $PYTHON" >&2
    exit 1
fi

exec "$PYTHON" "$REPO_ROOT/scripts/m2_live_acceptance.py" "$@"
