# Docker Compose Security Baseline

Shared Docker Compose hardening profiles for the repositories in `/opt/docker`.

The profiles centralize common security defaults such as read-only root filesystems, dropped capabilities, `no-new-privileges`, `restart: unless-stopped`, memory and PID limits, and `memswap_limit` values that match `mem_limit` so containers fail with OOM instead of using swap.

Profiles use Compose `extends` so downstream projects can consume the shared baseline without duplicating hardening blocks in each repository. YAML anchors are useful within a single Compose file, but they are file-local and do not replace this cross-file baseline cleanly.

Hardened profiles mount tmpfs at `/tmp` and `/run` for standard temporary, PID, and lock files while keeping the image filesystem read-only. The `readonly-*` service names remain as compatibility aliases for existing consumers, but new services should use the regular `hardened-*` profiles.

The Redis profile intentionally adds no capabilities. Downstream Redis services should mount a project-local named volume at `/data` so Redis can persist data without needing ownership-changing capabilities:

```yaml
services:
  redis:
    extends:
      file: /opt/docker/compose-security-baseline/hardening.yml
      service: redis
    image: redis:latest
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```
