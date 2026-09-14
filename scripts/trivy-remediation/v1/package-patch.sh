#!/usr/bin/env bash
set -euo pipefail
out=${1:?output patch required}
mkdir -p "$(dirname -- "$out")"
git add -N -- $(git ls-files --others --exclude-standard) 2>/dev/null || true
"$(dirname -- "$0")/validate-diff.py"
git diff --binary --no-ext-diff HEAD > "$out"
[[ ! -s "$out" ]] && { rm -f "$out"; exit 0; }
PATCH_PATH="$out" "$(dirname -- "$0")/validate-diff.py" "$out"
