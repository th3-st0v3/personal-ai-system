#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
    printf 'error: expected executable Python at %s/.venv/bin/python\n' "$REPO_ROOT" >&2
    exit 1
fi

hours="${PASI_OVERNIGHT_HOURS:-12}"
if [[ "$hours" != "12" && "$hours" != "12.0" ]]; then
    printf 'error: start_pasi_12h.sh is intentionally fixed to a 12-hour automation window; use start_pasi_overnight.sh for another supported duration.\n' >&2
    exit 2
fi

printf '=== PASI 12-HOUR AUTOMATION PREFLIGHT ===\n'
"$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/pasi_setup.py" --check
printf '\n=== STARTING 12-HOUR RUN ===\n'
exec "$SCRIPT_DIR/start_pasi_overnight.sh" --hours 12
