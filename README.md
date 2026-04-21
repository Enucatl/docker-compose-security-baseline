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

The `codex_pipeline.py` helper writes confirmed findings to `validated/` and sends invalid or unverifiable reports to `rejected/`. Only the files in `validated/` are used when generating `validated/fix_plan.md`, which keeps the remediation plan focused on security issues that were actually verified.

## Reusable Docker CI workflow

This repository exports `.github/workflows/docker-ci.yml` as a reusable GitHub workflow.

This repository also self-consumes that workflow as an integration check through `.github/workflows/self-test-docker-ci.yml`. Pull requests build the repo's minimal Debian example image and run the filesystem scan without publishing. Pushes to `main` and tag pushes publish the same image to GHCR and then run the published-image scan.

Consume it from another repo with a small wrapper workflow:

```yaml
name: Docker CI

on:
  push:
    branches: [main]
    tags: ["*"]
  pull_request:

jobs:
  docker:
    uses: your-org/compose-security-baseline/.github/workflows/docker-ci.yml@main
    with:
      image_name: ghcr.io/your-org/your-image
      context: .
      platforms: linux/amd64
      push: ${{ github.event_name != 'pull_request' }}
    secrets: inherit
```

The reusable workflow computes Docker metadata tags, delegates the build to Docker's `docker/github-builder` reusable workflow, always runs the Trivy filesystem scan, and runs the Trivy image scan when the image was pushed.

`docker/github-builder` owns the build, publish, SBOM, and signing path. The reusable workflow keeps the existing git-derived tag computation, always scans the checked-out filesystem locally, and scans the published image at `${image_name}:${version}` only when `push: true`.

The self-test image is intentionally minimal: the repo root `Dockerfile` starts from `debian:13-slim` and its default command prints `hello world`. Its publish target shape is `ghcr.io/<owner>/<repo>`, using the repository path normalized to lowercase before passing it into the reusable workflow.

The wrapper exposes the common `github-builder` Dockerfile build inputs so callers can tune builds without forking the workflow: `context`, `dockerfile`, `platforms`, `target`, `build_args`, `cache`, `cache_scope`, and `set_meta_labels`. Defaults stay conservative, with `platforms: linux/amd64`, `cache: true`, and `set_meta_labels: true`.

`fail_on_fs_findings` and `fail_on_image_findings` control whether each Trivy scan fails the workflow. Setting `fail_on_image_findings: false` makes published-image findings advisory: the image is still pushed, findings are uploaded as SARIF, and the workflow stays green.
