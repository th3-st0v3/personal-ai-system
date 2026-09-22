#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${PASI_REPOSITORY:-th3-st0v3/personal-ai-system}"
RUNNER_ROOT="${PASI_RUNNER_ROOT:-$HOME/.pasi/actions-runner}"
RUNNER_TOKEN="${PASI_RUNNER_TOKEN:-}"
RUNNER_LABELS="${PASI_RUNNER_LABELS:-pasi-desktop,pasi-wsl,pasi-capabilities-v1}"
RUNNER_NAME="${PASI_RUNNER_NAME:-pasi-wsl-runner}"

if [[ -z "$RUNNER_TOKEN" ]]; then
  echo 'PASI_RUNNER_TOKEN is required. Generate the short-lived token in GitHub Settings → Actions → Runners.' >&2
  exit 2
fi

command -v curl >/dev/null || { echo 'curl is required' >&2; exit 2; }
command -v tar >/dev/null || { echo 'tar is required' >&2; exit 2; }

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
TAG="$(python -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])' <<<"$RELEASE_JSON")"
VERSION="${TAG#v}"
ARCHIVE="actions-runner-${VERSION}-${PLATFORM}-${ARCH_NAME}.tar.gz"
URL="https://github.com/actions/runner/releases/download/${TAG}/${ARCHIVE}"

echo "Downloading GitHub Actions runner $VERSION for $PLATFORM/$ARCH_NAME..."
curl -fsSL "$URL" -o "$ARCHIVE"
tar -xzf "$ARCHIVE"
rm -f "$ARCHIVE"

chmod +x config.sh run.sh
./config.sh --unattended --url "https://github.com/$REPOSITORY" --token "$RUNNER_TOKEN" --name "$RUNNER_NAME" --labels "$RUNNER_LABELS" --work _work --replace

if [[ -x ./svc.sh ]] && command -v systemctl >/dev/null 2>&1 && systemctl is-system-running >/dev/null 2>&1; then
  sudo ./svc.sh install
  sudo ./svc.sh start
  echo 'GitHub Actions runner service installed and started.'
else
  echo 'Runner registered successfully. WSL does not expose an active system service manager here; use ./run.sh from this directory for a persistent headless runner.'
fi

echo "Runner root: $RUNNER_ROOT"
echo "Runner name: $RUNNER_NAME"
echo "Labels: $RUNNER_LABELS"
echo 'Registration token was not persisted by this script.'