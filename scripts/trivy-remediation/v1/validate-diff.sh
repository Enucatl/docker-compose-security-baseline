#!/usr/bin/env bash
set -euo pipefail

max_files=20 max_bytes=131072
paths=$(git diff --name-only --diff-filter=ACDMRTUXB HEAD -- .; git ls-files --others --exclude-standard)
mapfile -t files < <(printf '%s\n' "$paths" | sed '/^$/d' | sort -u)
(( ${#files[@]} <= max_files )) || { echo "patch changes too many files" >&2; exit 1; }
for path in "${files[@]}"; do
  [[ "$path" != /* && "$path" != *'..'* && "$path" != .github/* && "$path" != .agents/* ]] || { echo "prohibited path: $path" >&2; exit 1; }
  case "$path" in .git*|*trivy*config*|*trivy*ignore*|*security-policy*|*SECURITY*|*security.yml|*security.yaml) echo "prohibited path: $path" >&2; exit 1;; esac
  [[ -L "$path" ]] && { echo "symlink is not allowed: $path" >&2; exit 1; }
  file_type=$(stat -c '%F' -- "$path")
  [[ "$file_type" == "regular file" ]] || { echo "special file is not allowed: $path" >&2; exit 1; }
  [[ $(stat -c '%h' -- "$path") -eq 1 ]] || { echo "hard link is not allowed: $path" >&2; exit 1; }
  mode=$(stat -c '%a' -- "$path"); [[ "$mode" == 644 || "$mode" == 755 ]] || { echo "invalid mode: $path" >&2; exit 1; }
done
patch=${PATCH_PATH:-${1:-}}
if [[ -n "$patch" ]]; then
  [[ -s "$patch" ]] || { echo "empty patch" >&2; exit 1; }
  (( $(wc -c < "$patch") <= max_bytes )) || { echo "patch is too large" >&2; exit 1; }
  mapfile -t patch_paths < <(sed -n 's/^diff --git a\/\(.*\) b\/.*$/\1/p' "$patch")
  (( ${#patch_paths[@]} <= max_files )) || { echo "patch changes too many files" >&2; exit 1; }
  for path in "${patch_paths[@]}"; do
    [[ "$path" != /* && "$path" != *'..'* && "$path" != .github/* && "$path" != .agents/* ]] || { echo "prohibited patch path: $path" >&2; exit 1; }
    case "$path" in .git*|*trivy*config*|*trivy*ignore*|*security-policy*|*SECURITY*|*security.yml|*security.yaml) echo "prohibited patch path: $path" >&2; exit 1;; esac
  done
  ! grep -Eq '^(new|old) file mode (120000|160000)' "$patch" || { echo "symlink or submodule mode denied" >&2; exit 1; }
fi
