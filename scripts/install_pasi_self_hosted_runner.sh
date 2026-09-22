#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${PASI_REPOSITORY:-th3-st0v3/personal-ai-system}"
RUNNER_ROOT="${PASI_RUNNER_ROOT:-$HOME/.pasi/actions-runner}"
RUNNER_TOKEN="${PASI_RUNNER_TOKEN:-}"
RUNNER_LABELS="${PASI_RUNNER_LABELS:-pasi-desktop,pasi-wsl,pasi-capabilities-v1}"
RUNNER_NAME="${PASI_RUNNER_NAME:-pasi-wsl-runner}"

command -v curl >/dev/null || { echo 'curl is required' >&2; exit 2; }
command -v tar >/dev/null || { echo 'tar is required' >&2; exit 2; }
command -v python3 >/dev/null || { echo 'python3 is required' >&2; exit 2; }

if [[ -z "$RUNNER_TOKEN" ]] && command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo 'Using authenticated gh CLI to request a short-lived runner registration token.'
  RUNNER_TOKEN="$(gh api --method POST "repos/${REPOSITORY}/actions/runners/registration-token" --jq .token)"
fi

if [[ -z "$RUNNER_TOKEN" ]]; then
  echo 'PASI_RUNNER_TOKEN is required unless authenticated gh CLI is available.' >&2
  echo 'Generate a short-lived token in GitHub Settings → Actions → Runners, or run gh auth login first.' >&2
  exit 2
fi

mkdir -p "$RUNNER_ROOT"
cd "$RUNNER_ROOT"

if [[ -f .runner ]]; then
  echo "A GitHub Actions runner is already configured at $RUNNER_ROOT."
  echo 'Refusing to overwrite an existing registration.'
  exit 3
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ARCH_NAME='x64' ;;
  aarch64|arm64) ARCH_NAME='arm64' ;;
  *) echo "Unsupported runner architecture: $ARCH" >&2; exit 2 ;;
esac

PLATFORM='linux'
RELEASE_JSON="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
TAG="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])' <<<"$RELEASE_JSON")"
VERSION="${TAG#v}"
ARCHIVE="actions-runner-${VERSION}-${PLATFORM}-${ARCH_NAME}.tar.gz"
URL="https://github.com/actions/runner/releases/download/${TAG}/${ARCHIVE}"

echo "Downloading GitHub Actions runner $VERSION for $PLATFORM/$ARCH_NAME..."
curl -fsSL "$URL" -o "$ARCHIVE"
tar -xzf "$ARCHIVE"
rm -f "$ARCHIVE"

chmod +x config.sh run.sh
./config.sh --unattended --url "https://github.com/$REPOSITORY" --token "$RUNNER_TOKEN" --name "$RUNNER_NAME" --labels "$RUNNER_LABELS" --work _work --replace

unset RUNNER_TOKEN RELEASE_JSON TAG VERSION ARCHIVE URL

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh auth setup-git >/dev/null
fi

if [[ -x ./svc.sh ]] && command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  if sudo -n ./svc.sh install >/dev/null 2>&1; then
    sudo ./svc.sh start
    echo 'GitHub Actions runner service installed and started.'
  else
    echo 'Runner registered. Automatic service installation requires passwordless sudo; run sudo ./svc.sh install && sudo ./svc.sh start for a persistent runner.'
  fi
else
  echo 'Runner registered successfully. Start ./run.sh from this directory for a persistent headless runner.'
fi

echo "Runner root: $RUNNER_ROOT"
echo "Runner name: $RUNNER_NAME"
echo "Labels: $RUNNER_LABELS"
echo 'The short-lived registration token was not persisted by this script.'
