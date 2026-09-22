#!/usr/bin/env bash
set -Eeuo pipefail

RUNNER_ROOT="${PASI_RUNNER_ROOT:-$HOME/.pasi/actions-runner}"
RUNNER_PID_FILE="${PASI_RUNNER_PID_FILE:-$HOME/.pasi/actions-runner/runner.pid}"
RUNNER_LOG="${PASI_RUNNER_LOG:-$HOME/.pasi/actions-runner/runner.log}"

cd "$RUNNER_ROOT"

configured=0
[[ -f .runner ]] && configured=1
active=0
pid=""
if [[ -f "$RUNNER_PID_FILE" ]]; then
  pid="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    active=1
  fi
fi

service_units=""
if command -v systemctl >/dev/null 2>&1; then
  service_units="$(systemctl list-unit-files 'actions.runner.*' --no-legend 2>/dev/null | awk '{print $1}' || true)"
fi

printf 'configured=%s
' "$configured"
printf 'pid=%s
' "${pid:-<none>}"
printf 'active=%s
' "$active"
printf 'systemd_services=%s
' "${service_units:-<none>}"
printf 'runner_log=%s
' "$RUNNER_LOG"

if (( active == 1 )); then
  printf 'PASI_ACTIONS_RUNNER: READY
'
  exit 0
fi

if [[ -n "$service_units" ]] && command -v systemctl >/dev/null 2>&1; then
  while IFS= read -r service; do
    [[ -n "$service" ]] || continue
    if systemctl is-active --quiet "$service" 2>/dev/null; then
      printf 'PASI_ACTIONS_RUNNER: READY (systemd: %s)
' "$service"
      exit 0
    fi
  done <<< "$service_units"
fi

printf 'PASI_ACTIONS_RUNNER: NOT ACTIVE
' >&2
printf 'Start it with: bash scripts/start_pasi_actions_runner.sh
' >&2
exit 1
