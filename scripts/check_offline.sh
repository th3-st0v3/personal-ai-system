#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash -n scripts/check_offline.sh

run_check() {
    local name="$1"
    shift
    printf "\n==> %s\n" "$name"
    "$@"
}

pruned_dirs=(
    ./.git ./.venv ./venv ./env ./.tox ./.nox ./nox ./node_modules
    ./__pycache__ ./.pytest_cache ./.mypy_cache ./.ruff_cache ./.pyright ./.cache
    ./.next ./.turbo ./.parcel-cache ./.runtime ./runtime ./dist ./build
    ./coverage ./htmlcov ./generated ./artifacts ./tmp ./site-packages ./vendor ./third_party
)
find_expr=(find .)
for dir in "${pruned_dirs[@]}"; do
    find_expr+=( -path "*/${dir#./}" -prune -o )
done
find_expr+=( -type f )
mapfile -d "" PYTHON_TEST_FILES < <("${find_expr[@]}" \( -name "test_*.py" -o -name "*_test.py" \) -print0 | sort -z)
mapfile -d "" JAVASCRIPT_FILES < <("${find_expr[@]}" \( -name "*.js" -o -name "*.mjs" -o -name "*.cjs" \) -print0 | sort -z)

printf "\nOffline validator: %d Python tests, %d JavaScript files\n" "${#PYTHON_TEST_FILES[@]}" "${#JAVASCRIPT_FILES[@]}"
run_check "All discovered Python tests" python -m pytest -q "${PYTHON_TEST_FILES[@]}"
run_check "Python dependency consistency" python -m pip check
run_check "Browser Use compatibility" python -c 'import importlib.metadata; from browser_use import Agent, Browser; version=importlib.metadata.version("browser-use"); assert version=="0.13.10", version; assert Agent is not None and Browser is not None; print(f"browser-use {version}: import compatibility OK")'

for file in "${JAVASCRIPT_FILES[@]}"; do
    node --check "$file"
done
run_check "Native Chromium bridge contract tests" node --test automation/chromium/pasi-chatgpt/test_extension.js
run_check "Frontend contract smoke test" python scripts/frontend_contract_test.py
run_check "Browser/API smoke test" python scripts/ci_web_smoke.py

printf "\nALL OFFLINE VALIDATION PASSED\n"
