#!/usr/bin/env bash
set -euo pipefail
patch=${1:?patch required}
PATCH_PATH="$patch" "$(dirname -- "$0")/validate-diff.py" "$patch"
git apply --whitespace=nowarn "$patch"
PATCH_PATH= "$(dirname -- "$0")/validate-diff.py"
[[ -n "$(git status --porcelain)" ]] || { echo "patch made no change" >&2; exit 1; }
