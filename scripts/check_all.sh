#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Validate this script before doing any work it controls.
bash -n "$SCRIPT_DIR/check_all.sh"

pull_origin_main() {
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        return 0
    fi

    local branch
    branch="$(git symbolic-ref --quiet --short HEAD || true)"
    if [[ "$branch" != "main" ]]; then
        printf '\n==> Git sync\n'
        printf 'Current branch is %s; skipping automatic origin/main sync.\n' "${branch:-detached HEAD}"
        return 0
    fi

    if ! git remote get-url origin >/dev/null 2>&1; then
        printf '\n==> Git sync\n'
        printf 'No git remote named origin; skipping origin/main sync.\n'
        return 0
    fi

    printf '\n==> Git sync\n'

    if ! git diff --quiet --ignore-submodules -- || ! git diff --cached --quiet --ignore-submodules --; then
        printf 'Working tree is dirty; skipping origin/main sync so local edits are preserved.\n'
        return 0
    fi

    git fetch --prune --tags origin main

    if ! git rev-parse --verify origin/main >/dev/null 2>&1; then
        printf 'Remote branch origin/main not found; skipping sync.\n'
        return 0
    fi

    local head remote
    head="$(git rev-parse --verify HEAD)"
    remote="$(git rev-parse --verify origin/main)"

    if [[ "$head" == "$remote" ]]; then
        printf 'Already synchronized with origin/main.\n'
        return 0
    fi

    if git merge-base --is-ancestor "$head" "$remote"; then
        git pull --ff-only --tags origin main
        return 0
    fi

    if git merge-base --is-ancestor "$remote" "$head"; then
        printf 'Local main is ahead of origin/main; skipping automatic pull.\n'
        return 0
    fi

    printf 'Local main has diverged from origin/main; skipping automatic merge.\n'
}

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
    ./.tox
    ./.nox
    ./nox
    ./node_modules
    ./__pycache__
    ./.pytest_cache
    ./.mypy_cache
    ./.ruff_cache
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
    find_expr+=( -type d -name "${dir#./}" -prune -o )
done
find_expr+=( -type f )
mapfile -d '' PYTHON_FILES < <(
    "${find_expr[@]}" -name '*.py' -print0 | sort -z
)
mapfile -d '' PYTHON_TEST_FILES < <(
    "${find_expr[@]}" \( -name 'test_*.py' -o -name '*_test.py' \) -print0 | sort -z
)
mapfile -d '' JAVASCRIPT_FILES < <(
    "${find_expr[@]}" \( -name '*.js' -o -name '*.mjs' -o -name '*.cjs' \) -print0 | sort -z
)
mapfile -d '' JAVASCRIPT_TEST_FILES < <(
    "${find_expr[@]}" \( -name 'test_*.js' -o -name '*_test.js' -o -name '*.test.js' -o -name '*.spec.js' -o -name 'test_*.mjs' -o -name '*_test.mjs' -o -name '*.test.mjs' -o -name '*.spec.mjs' -o -name 'test_*.cjs' -o -name '*_test.cjs' -o -name '*.test.cjs' -o -name '*.spec.cjs' \) -print0 | sort -z
)
mapfile -d '' SHELL_FILES < <(
    "${find_expr[@]}" -name '*.sh' -print0 | sort -z
)
mapfile -d '' JSON_FILES < <(
    "${find_expr[@]}" -name '*.json' -print0 | sort -z
)

printf '\nDiscovered %d Python source files, %d Python test files, %d JavaScript files, %d JavaScript test suites, %d shell files, %d JSON files\n' \
    "${#PYTHON_FILES[@]}" "${#PYTHON_TEST_FILES[@]}" "${#JAVASCRIPT_FILES[@]}" "${#JAVASCRIPT_TEST_FILES[@]}" "${#SHELL_FILES[@]}" "${#JSON_FILES[@]}"

pull_origin_main

run_check "Beta smoke test" python scripts/smoke_test_beta.py
run_check "All discovered Python tests" python -m pytest -q "${PYTHON_TEST_FILES[@]}"

if ! python -c 'import browser_use' >/dev/null 2>&1; then
    printf '\n==> Browser Use dependency\n'
    python -m pip install -r requirements-browser.txt
fi

run_check "Python dependency consistency" python -m pip check
run_check "Browser Use compatibility" python -c '
import importlib.metadata
from browser_use import Agent, Browser

version = importlib.metadata.version("browser-use")
assert version == "0.13.10", version
assert Agent is not None
assert Browser is not None
print(f"browser-use {version}: import compatibility OK")
'

run_check "Static type check" npx --yes pyright@1.1.411 "${PYTHON_FILES[@]}"
run_check "Markdown lint" npx --yes markdownlint-cli2@0.23.2 '**/*.md' \
    '#node_modules' '#**/.venv/**' '#**/venv/**' '#**/env/**' '#**/.git/**' \
    '#**/.tox/**' '#**/.nox/**' '#**/nox/**' '#**/.pytest_cache/**' '#**/.mypy_cache/**' \
    '#**/.ruff_cache/**' '#**/.pyright/**' '#**/.cache/**' '#**/.next/**' \
    '#**/.turbo/**' '#**/.parcel-cache/**' '#**/.runtime/**' '#**/runtime/**' \
    '#**/dist/**' '#**/build/**' '#**/coverage/**' '#**/htmlcov/**' \
    '#**/generated/**' '#**/artifacts/**' '#**/tmp/**' '#**/site-packages/**' \
    '#**/vendor/**' '#**/third_party/**'

printf '\n==> JavaScript test suites\n'
if ((${#JAVASCRIPT_TEST_FILES[@]})); then
    node --test "${JAVASCRIPT_TEST_FILES[@]}"
else
    printf 'No supported JavaScript test suites discovered.\n'
fi

printf '\n==> JavaScript syntax (non-test files)\n'
declare -A JAVASCRIPT_TEST_SET=()
for file in "${JAVASCRIPT_TEST_FILES[@]}"; do
    JAVASCRIPT_TEST_SET["$file"]=1
done
for file in "${JAVASCRIPT_FILES[@]}"; do
    if [[ -n "${JAVASCRIPT_TEST_SET["$file"]+x}" ]]; then
        continue
    fi
    node --check "$file"
done

printf '\n==> Shell syntax\n'
for file in "${SHELL_FILES[@]}"; do
    bash -n "$file"
done

run_check "JSON syntax" python - "${JSON_FILES[@]}" <<'PY'
import json
import sys
from pathlib import Path

paths = [Path(value) for value in sys.argv[1:] if value]
for path in paths:
    with path.open(encoding="utf-8") as handle:
        json.load(handle)
print(f"validated {len(paths)} JSON files")
PY

run_check "Frontend contract smoke test" python scripts/frontend_contract_test.py
run_check "Browser/API smoke test" python scripts/ci_web_smoke.py

printf '\nALL LOCAL VALIDATION PASSED\n'