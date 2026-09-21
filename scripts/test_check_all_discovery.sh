#!/usr/bin/env bash
# Regression test for the check_all.sh file-discovery block.
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC="${1:-$HERE/../scripts/check_all.sh}"

bash -n "$SRC"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
cd "$T"

mkdir -p src tests node_modules/x .venv/lib .runtime/a pkg/node_modules/y build vendor/z
touch src/a.py tests/test_a.py tests/b_test.py pkg/keep.py pkg/keep.js pkg/test_keep.js \
      node_modules/x/n.py .venv/lib/v.py .runtime/a/r.py pkg/node_modules/y/p.py \
      pkg/node_modules/y/p.js build/b.py vendor/z/v.py

pruned_dirs=(./node_modules ./.venv ./.runtime ./build ./vendor)

# Reproduce the discovery expression exactly as check_all.sh.
find_expr=(find .)
for dir in "${pruned_dirs[@]}"; do
    find_expr+=( -type d -name "${dir#./}" -prune -o )
done
find_expr+=( -type f )

py="$("${find_expr[@]}" -name "*.py" -print0 | sort -z | tr "\0" " ")"
tests="$("${find_expr[@]}" \( -name "test_*.py" -o -name "*_test.py" \) -print0 | sort -z | tr "\0" " ")"
js="$("${find_expr[@]}" \( -name "*.js" -o -name "*.mjs" -o -name "*.cjs" \) -print0 | sort -z | tr "\0" " ")"
js_tests="$("${find_expr[@]}" \( -name "test_*.js" -o -name "*_test.js" -o -name "*.test.js" -o -name "*.spec.js" \) -print0 | sort -z | tr "\0" " ")"

[[ "$py" == "./pkg/keep.py ./src/a.py ./tests/b_test.py ./tests/test_a.py " ]] || { echo "FAIL py: $py"; exit 1; }
[[ "$tests" == "./tests/b_test.py ./tests/test_a.py " ]] || { echo "FAIL tests: $tests"; exit 1; }
[[ "$js" == "./pkg/keep.js ./pkg/test_keep.js " ]] || { echo "FAIL js: $js"; exit 1; }
[[ "$js_tests" == "./pkg/test_keep.js " ]] || { echo "FAIL js_tests: $js_tests"; exit 1; }
echo "check_all discovery: PASS"
