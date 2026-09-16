#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
    # Use the repository's virtual environment automatically when available.
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.venv/bin/activate"
fi

export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

run_check() {
    local name="$1"
    shift
    printf '\n==> %s\n' "$name"
    "$@"
}

trap 'status=$?; printf "\nVALIDATION FAILED (exit %s)\n" "$status" >&2; exit "$status"' ERR

run_check "Beta smoke test" python scripts/smoke_test_beta.py
run_check "Unit tests" python -m unittest discover -s src -p 'test_*.py' -v
run_check "Orchestrator + computer-use tests" python -m pytest -q automation/orchestrator automation/computer_use
run_check "Static type check" npx --yes pyright@latest src scripts automation/orchestrator automation/computer_use
run_check "Markdown lint" npx --yes markdownlint-cli2@latest '**/*.md' '#node_modules' '#**/.venv/**' '#**/venv/**' '#**/env/**'

printf '\n==> Web JavaScript syntax\n'
shopt -s nullglob
web_files=(web/*.js)
for file in "${web_files[@]}"; do
    node --check "$file"
done

printf '\n==> Automation JavaScript syntax\n'
tampermonkey_files=(automation/tampermonkey/*.js)
for file in "${tampermonkey_files[@]}"; do
    node --check "$file"
done

run_check "Frontend contract smoke test" python scripts/frontend_contract_test.py
run_check "Browser/API smoke test" python scripts/ci_web_smoke.py
run_check "Browser Use compatibility" python -c '
import importlib.metadata
from browser_use import Agent, Browser

version = importlib.metadata.version("browser-use")
assert version == "0.13.10", version
assert Agent is not None
assert Browser is not None
print(f"browser-use {version}: import compatibility OK")
'
run_check "Browser integration contract tests" python -m pytest -q automation/computer_use/test_browser_use.py

printf '\nALL LOCAL VALIDATION PASSED\n'
