#!/usr/bin/env bash
set -u -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.venv/bin/activate"
fi

export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

FAILURES=()

run_check() {
    local name="$1"
    shift
    printf '\n==> %s\n' "$name"
    if "$@"; then
        printf 'PASS: %s\n' "$name"
    else
        printf 'FAIL: %s\n' "$name" >&2
        FAILURES+=( "$name" )
    fi
}

run_shell_syntax() {
    local failed=0 file
    while IFS= read -r -d '' file; do
        if ! bash -n "$file"; then
            failed=1
        fi
    done < <(find . -type d \( -name .git -o -name .venv -o -name node_modules -o -name .runtime -o -name dist -o -name build -o -name coverage -o -name generated -o -name artifacts -o -name tmp \) -prune -o -type f -name '*.sh' -print0)
    return "$failed"
}

run_json_syntax() {
    python - <<'PY'
import json
from pathlib import Path

pruned = {".git", ".venv", "node_modules", ".runtime", "dist", "build", "coverage", "generated", "artifacts", "tmp"}
paths = [p for p in Path(".").rglob("*.json") if not any(part in pruned for part in p.parts)]
for path in paths:
    with path.open(encoding="utf-8") as handle:
        json.load(handle)
print(f"validated {len(paths)} JSON files")
PY
}

mapfile -d '' PYTHON_TEST_FILES < <(
    find . \
        -type d \( -name .git -o -name .venv -o -name node_modules -o -name .runtime -o -name dist -o -name build -o -name coverage -o -name generated -o -name artifacts -o -name tmp \) -prune -o \
        -type f \( -name 'test_*.py' -o -name '*_test.py' \) -print0 | sort -z
)
mapfile -d '' JAVASCRIPT_TEST_FILES < <(
    find . \
        -type d \( -name .git -o -name .venv -o -name node_modules -o -name .runtime -o -name dist -o -name build -o -name coverage -o -name generated -o -name artifacts -o -name tmp \) -prune -o \
        -type f \( -name 'test_*.js' -o -name '*_test.js' -o -name '*.test.js' -o -name '*.spec.js' -o -name 'test_*.mjs' -o -name '*_test.mjs' -o -name '*.test.mjs' -o -name '*.spec.mjs' -o -name 'test_*.cjs' -o -name '*_test.cjs' -o -name '*.test.cjs' -o -name '*.spec.cjs' \) -print0 | sort -z
)

printf 'Fast validation discovered %d Python test files and %d JavaScript test suites.\n' "${#PYTHON_TEST_FILES[@]}" "${#JAVASCRIPT_TEST_FILES[@]}"

if ((${#PYTHON_TEST_FILES[@]})); then
    run_check "Python unit and contract tests" python -m pytest -q "${PYTHON_TEST_FILES[@]}" --durations=15
else
    printf 'No Python test files discovered.\n'
    FAILURES+=( "Python unit and contract tests (none discovered)" )
fi

if ((${#JAVASCRIPT_TEST_FILES[@]})); then
    run_check "JavaScript unit and fixture tests" node --test "${JAVASCRIPT_TEST_FILES[@]}"
else
    printf 'No JavaScript test suites discovered.\n'
fi

run_check "Shell syntax" run_shell_syntax
run_check "JSON syntax" run_json_syntax

printf '\n==> Fast validation summary\n'
if ((${#FAILURES[@]})); then
    printf 'Failed checks:\n' >&2
    printf ' - %s\n' "${FAILURES[@]}" >&2
    exit 1
fi

printf 'ALL FAST VALIDATION PASSED\n'
