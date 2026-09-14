# Docker Compose Security Baseline

Shared Docker Compose hardening profiles for the repositories in `/opt/docker`.

The profiles centralize common security defaults such as read-only root filesystems, dropped capabilities, `no-new-privileges`, `restart: unless-stopped`, memory and PID limits, and `memswap_limit` values that match `mem_limit` so containers fail with OOM instead of using swap.

Profiles use Compose `extends` so downstream projects can consume the shared baseline without duplicating hardening blocks in each repository. YAML anchors are useful within a single Compose file, but they are file-local and do not replace this cross-file baseline cleanly.

Hardened profiles keep the image filesystem read-only and drop capabilities by default. Services that need writable temp or runtime directories should declare their own `tmpfs` mounts explicitly. The `readonly-*` service names remain as compatibility aliases for existing consumers, but new services should use the regular `hardened-*` profiles.

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

## Reusable Docker CI workflow

This repository exports `.github/workflows/docker-ci.yml` as a reusable GitHub workflow.

This repository also self-consumes that workflow as an integration check through `.github/workflows/self-test-docker-ci.yml`. The example uses the same fully qualified reusable-workflow reference external repositories would use. Pull requests build the repo's minimal Debian example image and run the filesystem scan without publishing. Pushes to `main` and tag pushes publish the same image to GHCR and then run the published-image scan. For this repository's self-test only, Trivy findings stay advisory so SARIF still uploads without blocking the example workflow.

The repository also exports `.github/actions/git-version` as a composite action for repos that need the same git-derived version string in their own jobs before calling the reusable workflow, for example to pass `CARGO_PACKAGE_VERSION` as a Docker build arg.

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

Callers can pass `trivy_skip_dirs` as a comma-separated list when the filesystem scan should ignore vendored or generated directories that are not part of the maintained project surface.

Callers that need to publish forked upstream images or otherwise keep a repo-specific versioning scheme can override the default git-derived tags by passing both `version` and `meta_tags` together. If omitted, the reusable workflow keeps its built-in git-derived version calculation and tag policy.

`fail_on_fs_findings` and `fail_on_image_findings` control whether each Trivy scan fails the workflow. Setting `fail_on_image_findings: false` makes published-image findings advisory: the image is still pushed, findings are uploaded as SARIF, and the workflow stays green.

## Opt-in Trivy remediation

When `push: true`, the normal workflow continues to produce the existing table output and SARIF files, and now also writes `trivy-image.json`. The SARIF result feeds GitHub code scanning; the JSON result is machine-readable input for remediation. Both the JSON report and an image-policy result marker are uploaded as the stable `trivy-image-report` artifact, including when the enforced image scan fails.

Remediation is opt-in. A consuming repository adds a small `workflow_run` wrapper that calls the reusable workflow after its normal Docker CI workflow completes unsuccessfully:

```yaml
name: Trivy remediation

on:
  workflow_run:
    # This must match the `name` of the consuming repository's normal Docker CI workflow.
    workflows: [Docker CI]
    types: [completed]

jobs:
  remediate:
    if: ${{ github.event.workflow_run.conclusion == 'failure' && github.event.workflow_run.head_repository.full_name == github.repository }}
    permissions:
      actions: read
      contents: write
      pull-requests: write
    uses: Enucatl/docker-compose-security-baseline/.github/workflows/trivy-remediation.yml@main
    with:
      run_id: ${{ github.event.workflow_run.id }}
      checkout_ref: ${{ github.event.workflow_run.head_sha }}
      model: deepseek/deepseek-v4.1-flash
      provider_base_url: https://openrouter.ai/api/v1
      provider_env_key: OPENROUTER_API_KEY
      report_artifact: trivy-image-report
      report_path: trivy-image.json
      # Set profile instead when the selected Codex profile is available to the runner.
      # profile: remediation-provider
    secrets:
      model_api_key: ${{ secrets.OPENROUTER_API_KEY }}
```

The consumer must store the model-provider API key as `OPENROUTER_API_KEY` (or pass a different secret through `model_api_key`). The reusable workflow passes the selected `model`, optional Codex `profile`, provider base URL, provider API-key environment-variable name, and wire API to Codex CLI; it does not implement an LLM client or require OpenRouter/DeepSeek. For another provider, change those inputs and the secret. `codex_version` can be pinned to a supported `@openai/codex` npm version instead of its `latest` default.

The remediation workflow downloads the failed run's report, invokes `codex exec` with the repository's `.agents/skills/trivy-remediation/SKILL.md`, and never gives that process a GitHub write token. A separate proposal job applies the resulting diff, pushes a `codex/trivy-remediation/...` branch, and opens a pull request; it does not merge, publish, or modify `main` directly. The pull request must pass the consuming repository's normal build and Trivy workflow again. Trivy remains the acceptance criterion.

If the failed run was not an enforced image-policy failure, the report is missing/invalid, no fixed version exists, or Codex cannot produce a meaningful safe diff, no pull request is opened. The skill prohibits CVE ignores, weakened scan policy, unrelated upgrades, and speculative architectural changes.

The example limits remediation to branches in the consuming repository. That keeps the provider key away from fork-originated workflow code; fork pull requests should be remediated through their normal review process.

The self-test in this repository intentionally does not invoke Codex. End-to-end remediation testing requires a provider API key and a deliberately vulnerable image with a known fixed HIGH/CRITICAL finding; this repository validates the workflow and shell paths statically instead.
