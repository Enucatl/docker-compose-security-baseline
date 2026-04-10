# Docker Compose Security Baseline

Shared Docker Compose hardening profiles for the repositories in `/opt/docker`.

The profiles centralize common security defaults such as dropped capabilities, `no-new-privileges`, memory and PID limits, and `memswap_limit` values that match `mem_limit` so containers fail with OOM instead of using swap.
