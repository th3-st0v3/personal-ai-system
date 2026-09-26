#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

printf '=== PASI FULL REPOSITORY TEST ===\n'
printf 'Canonical gate: scripts/check_all.sh\n'
printf 'Static analysis: Pyright (the engine used by Pylance) over all discovered Python files\n'
printf 'Diagnostics policy: zero errors, warnings, and informational diagnostics\n\n'

bash "$SCRIPT_DIR/check_all.sh"
