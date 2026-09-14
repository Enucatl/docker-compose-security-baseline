#!/usr/bin/env bash
set -euo pipefail

required=(RUN_ID CHECKOUT_REF SOURCE_WORKFLOW_NAME TRUSTED_BRANCH REPORT_ARTIFACT REPORT_PATH)
for name in "${required[@]}"; do [[ -n "${!name:-}" ]] || { echo "$name is required" >&2; exit 1; }; done
[[ "$RUN_ID" =~ ^[0-9]+$ ]] || { echo "run_id must be numeric" >&2; exit 1; }
[[ "$CHECKOUT_REF" =~ ^[0-9a-fA-F]{40}$ ]] || { echo "checkout_ref must be a commit SHA" >&2; exit 1; }
[[ "$REPORT_ARTIFACT" != */* && "$REPORT_ARTIFACT" != .* ]] || { echo "invalid artifact name" >&2; exit 1; }
case "${REPORT_PATH#./}" in ""|/*|..|../*|*/../*|*\\*) echo "invalid report path" >&2; exit 1;; esac

api() { gh api -H 'Accept: application/vnd.github+json' "$1"; }
run_json=$(api "repos/${CURRENT_REPOSITORY}/actions/runs/${RUN_ID}")
jq -e --arg repo "$CURRENT_REPOSITORY" --arg workflow "$SOURCE_WORKFLOW_NAME" --arg branch "$TRUSTED_BRANCH" --arg sha "$CHECKOUT_REF" '
  .repository.full_name == $repo and .id == ('$RUN_ID') and .event == "push" and
  .name == $workflow and .head_branch == $branch and .head_sha == $sha and
  .conclusion == "failure" and .head_repository.full_name == $repo
' <<<"$run_json" >/dev/null

artifacts=$(api "repos/${CURRENT_REPOSITORY}/actions/runs/${RUN_ID}/artifacts?per_page=100")
jq -e --arg name "$REPORT_ARTIFACT" 'any(.artifacts[]?; .name == $name and .workflow_run.id == ('$RUN_ID') and .expired == false)' <<<"$artifacts" >/dev/null
printf 'eligible=true\n'
