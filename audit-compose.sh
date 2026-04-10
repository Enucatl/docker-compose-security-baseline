#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/opt/docker}"
BASELINE="${ROOT}/compose-security-baseline/hardening.yml"

if [[ ! -f "${BASELINE}" ]]; then
  echo "Missing baseline file: ${BASELINE}" >&2
  exit 1
fi

find "${ROOT}" -mindepth 2 -maxdepth 3 -type f \
  \( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'compose.yml' -o -name 'compose.yaml' \) \
  ! -path '*/site-packages/*' \
  ! -path '*/compose-security-baseline/*' \
  | sort \
  | while read -r compose_file; do
      project_dir="$(dirname "${compose_file}")"
      echo "== ${compose_file#${ROOT}/} =="
      (
        cd "${project_dir}"
        env_args=()
        for env_file in "${ROOT}/.env" "../.env" ".env"; do
          if [[ -f "${env_file}" ]]; then
            env_args+=(--env-file "${env_file}")
          fi
        done
        COMPOSE_ENV_FILES= docker compose "${env_args[@]}" config --quiet
      )
    done
