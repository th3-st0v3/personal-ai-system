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

# Discover working-tree validation targets while excluding dependency,
# generated, cache, and runtime directories. This automatically covers new
# source, test, and JavaScript files without requiring script edits.
pruned_dirs=(
    ./.git
    ./.venv
    ./venv
    ./env
    ./node_modules
    ./__pycache__
    ./.pytest_cache
    ./.mypy_cache
    ./.pyright
    ./.cache
    ./.next
    ./.turbo
    ./.parcel-cache
    ./.runtime
    ./runtime
    ./dist
    ./build
    ./coverage
    ./htmlcov
    ./generated
    ./artifacts
    ./tmp
    ./site-packages
    ./vendor
    ./third_party
)

find_expr=(find .)
for dir in "${pruned_dirs[@]}"; do
    find_expr+=( -path "$dir" -prune -o )
done
find_expr+=( -type f )

mapfile -d '' PYTHON_FILES < <(
    "${find_expr[@]}" -name '*.py' -print0 | sort -z
)
mapfile -d '' PYTHON_TEST_FILES < <(
    "${find_expr[@]}" \( -name 'test_*.py' -o -name '*_test.py' \) -print0 | sort -z
)
mapfile -d '' SRC_NON_LEGACY_PYTHON_TEST_FILES < <(
    "${find_expr[@]}" \( -name 'test_*.py' -o -name '*_test.py' \) \
        -path './src/*' ! -name 'test_*.py' -print0 | sort -z
)
mapfile -d '' NON_SRC_PYTHON_TEST_FILES < <(
    "${find_expr[@]}" \( -name 'test_*.py' -o -name '*_test.py' \) \
        ! -path './src/*' -print0 | sort -z
)
mapfile -d '' JAVASCRIPT_FILES < <(
    "${find_expr[@]}" \( -name '*.js' -o -name '*.mjs' -o -name '*.cjs' \) -print0 | sort -z
)

printf '\nDiscovered %d Python source files, %d Python test files, %d JavaScript files\n' \
    "${#PYTHON_FILES[@]}" "${#PYTHON_TEST_FILES[@]}" "${#JAVASCRIPT_FILES[@]}"

run_check "Beta smoke test" python scripts/smoke_test_beta.py
run_check "Unit tests" python -m unittest discover -s src -p 'test_*.py' -v

if ((${#SRC_NON_LEGACY_PYTHON_TEST_FILES[@]})); then
    run_check "Discovered src Python tests outside unittest discovery" \
        python -m pytest -q "${SRC_NON_LEGACY_PYTHON_TEST_FILES[@]}"
fi

if ! python -c 'import browser_use' >/dev/null 2>&1; then
    printf '\n==> Browser Use dependency\n'
    python -m pip install -r requirements-browser.txt
fi

run_check "Browser Use compatibility" python -c '
import importlib.metadata
from browser_use import Agent, Browser

version = importlib.metadata.version("browser-use")
assert version == "0.13.10", version
assert Agent is not None
assert Browser is not None
print(f"browser-use {version}: import compatibility OK")
'

if ((${#NON_SRC_PYTHON_TEST_FILES[@]})); then
    run_check "All discovered non-src Python tests" \
        python -m pytest -q "${NON_SRC_PYTHON_TEST_FILES[@]}"
fi

run_check "Static type check" npx --yes pyright@latest "${PYTHON_FILES[@]}"
run_check "Markdown lint" npx --yes markdownlint-cli2@latest '**/*.md' \
    '#node_modules' '#**/.venv/**' '#**/venv/**' '#**/env/**' '#**/.git/**' \
    '#**/.pytest_cache/**' '#**/.mypy_cache/**' '#**/.pyright/**' '#**/.cache/**' \
    '#**/.next/**' '#**/.turbo/**' '#**/.parcel-cache/**' '#**/.runtime/**' \
    '#**/runtime/**' '#**/dist/**' '#**/build/**' '#**/coverage/**' '#**/htmlcov/**' \
    '#**/generated/**' '#**/artifacts/**' '#**/tmp/**' '#**/site-packages/**' \
    '#**/vendor/**' '#**/third_party/**'

printf '\n==> JavaScript syntax\n'
for file in "${JAVASCRIPT_FILES[@]}"; do
    node --check "$file"
done

run_check "Frontend contract smoke test" python scripts/frontend_contract_test.py
run_check "Browser/API smoke test" python scripts/ci_web_smoke.py

printf '\nALL LOCAL VALIDATION PASSED\n'
