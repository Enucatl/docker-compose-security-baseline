# Docker Compose Security Baseline

Reusable security building blocks for Docker Compose projects and their image CI.

| Component | Goal |
| --- | --- |
| [Hardening profiles](#hardening-profiles) | Apply consistent least-privilege runtime settings and resource limits to Compose services. |
| [Reusable Docker CI](#reusable-docker-ci-workflow) | Build, publish, sign, and scan Docker images from one shared GitHub Actions workflow. |
| [Trivy AI remediation](#trivy-ai-agentic-remediation) | Turn an enforced, fixable image-vulnerability failure into a tightly scoped remediation pull request. |

The goal is to run all of my homelab containers in significantly hardened environments than is (unfortunately) customary in the docker world, where almost everything runs no limits. 

The three parts tie nicely together, since I aim to build images with 0 HIGH or CRITICAL unfixed CVEs, run them in containers with userns_remap, under a nonprivileged user, dropping all capabilities, and with a read-only filesystem.
Trivy reviews the images weekly, and any new fixable vulnerabilities are patched by pull requests created by a codex agent github action, with human review.

## Hardening profiles

The profiles in [`hardening.yml`](hardening.yml) make the safe runtime posture the default: no Linux capabilities, `no-new-privileges`, a read-only root filesystem, and `restart: unless-stopped`. Size profiles add matched memory and swap limits plus a PID limit, so a service fails under pressure instead of consuming host swap indefinitely.

Profiles use Compose `extends`, which lets multiple Compose files share one baseline. Add only the writable paths and privileges a particular image genuinely needs; a read-only root filesystem commonly needs a project volume or `tmpfs` for its runtime state.

```yaml
services:
  app:
    extends:
      file: /opt/docker/compose-security-baseline/hardening.yml
      service: hardened-small
    image: ghcr.io/your-org/your-app:latest
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=64m
```

## Reusable Docker CI workflow

The reusable [`Docker CI`](.github/workflows/docker-ci.yml) workflow gives Docker repositories one build-and-scan path. It calculates Git-derived Docker image version tags, delegates building, SBOM generation, signing, and optional publishing to Docker's `github-builder` workflow, then scans the checked-out filesystem. When publishing is enabled, it also scans the pushed image, uploads SARIF to GitHub code scanning.

The vulnerability scan can be enforcing or advisory, so a repository can introduce scanning before making it a merge gate.

Create a small wrapper in the consuming repository:

```yaml
name: Docker CI

on:
  push:
    branches: [main]
    tags: ["*"]
  pull_request:

jobs:
  docker:
    uses: Enucatl/docker-compose-security-baseline/.github/workflows/docker-ci.yml@main
    with:
      image_name: ghcr.io/your-org/your-image
      push: ${{ github.event_name != 'pull_request' }}
    secrets: inherit
```

The default tag is derived from the latest reachable Git tag and commit SHA. Repositories with their own versioning can replace it by passing `version` and `meta_tags` together. See the [workflow reference](#reusable-docker-ci-workflow-reference) for all build, scan, and versioning inputs.

## Trivy AI agentic remediation

The optional [`Trivy Remediation`](.github/workflows/trivy-remediation.yml) workflow proposes a minimal fix after the normal Docker CI workflow fails its image-vulnerability policy. It is deliberately a proposal path, not an automatic deployment path, and has strict guardrails:

1. It verifies that the failed run belongs to the same repository, trusted branch, exact commit, and expected source workflow.
2. It gives Codex only a compact report of fixed HIGH and CRITICAL findings, then validates the resulting text-only patch against a narrow path, size, and file-count policy.
3. A separate job applies the validated patch on a new branch and opens a pull request. It never changes `main`, merges, or publishes an image.

Trivy remains the acceptance criterion: the proposed PR must pass the repository's regular Docker CI workflow. If the source failure was not an enforced image-policy failure, the report has no actionable finding, or no safe patch is produced, no PR is opened.

Add this wrapper alongside the Docker CI workflow. `workflows` must exactly match the normal workflow's `name`.

```yaml
name: Trivy remediation

on:
  workflow_run:
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
      source_workflow_name: Docker CI
      trusted_branch: main
      model: deepseek/deepseek-v4.1-flash
      provider_base_url: https://openrouter.ai/api/v1
    secrets:
      model_api_key: ${{ secrets.OPENROUTER_API_KEY }}
```

Use a dedicated, spending-limited provider key. Do not enable the wrapper for untrusted fork/branch code; the example limits remediation to runs whose head repository is the current repository.

# Reference

## Hardening profiles reference

All profiles are Compose services intended for `extends`. `hardened-base` supplies `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `read_only: true`, and `restart: unless-stopped`.

| Profile | Memory / PIDs | Purpose |
| --- | --- | --- |
| `hardened-base` | — | Shared least-privilege runtime settings. |
| `hardened-tiny` | 128 MiB / 64 | Hardened profile for very small services. |
| `hardened-small` | 256 MiB / 128 | Hardened profile for small services. |
| `hardened-medium` | 512 MiB / 192 | Hardened profile for medium services. |
| `hardened-large` | 1 GiB / 256 | Hardened profile for large services. |
| `hardened-xlarge` | 2 GiB / 512 | Hardened profile for extra-large services. |
| `hardened-xxlarge` | 3 GiB / 768 | Hardened profile for the largest services. |
| `limits-small` | 256 MiB / 128 | Resource limits only; no hardening settings. |
| `limits-medium` | 512 MiB / 192 | Resource limits only; no hardening settings. |
| `limits-large` | 1 GiB / 256 | Resource limits only; no hardening settings. |
| `limits-xlarge` | 2 GiB / 512 | Resource limits only; no hardening settings. |
| `limits-xxlarge` | 3 GiB / 768 | Resource limits only; no hardening settings. |
| `postgres` | 512 MiB / 192 | `hardened-medium`, PostgreSQL runtime `tmpfs`, UID/GID `999`, and a `pg_isready` health check. |
| `redis` | 256 MiB / 128 | `hardened-small`, Redis 8, UID/GID `999`, `TZ=Europe/Zurich`, and a `redis-cli ping` health check. |

Every size profile sets `memswap_limit` equal to `mem_limit`. Extend a `limits-*` profile only when the service cannot use the hardened base; otherwise start with its `hardened-*` counterpart. Service-specific writable directories, volumes, ports, users, and environment remain the consuming project's responsibility.

## Reusable Docker CI workflow reference

Call `Enucatl/docker-compose-security-baseline/.github/workflows/docker-ci.yml@main` with `workflow_call`. `image_name` is the only required input.

| Input | Default | Description |
| --- | --- | --- |
| `image_name` | required | Full image name, for example `ghcr.io/org/image`. |
| `version` | empty | Image tag to scan; must be supplied together with `meta_tags`. |
| `meta_tags` | empty | `docker/metadata-action` tag rules; must be supplied together with `version`. |
| `context` | `.` | Docker build context and filesystem-scan path. |
| `dockerfile` | `Dockerfile` | Dockerfile path, passed to `github-builder` as `file`. |
| `platforms` | `linux/amd64` | Target platforms for the image build. |
| `target` | empty | Optional Dockerfile target stage. |
| `build_args` | empty | Build arguments in `github-builder` format. |
| `cache` | `true` | Enable the builder cache. |
| `cache_scope` | empty | Optional cache scope. |
| `set_meta_labels` | `true` | Apply Docker metadata labels. |
| `push` | `false` | Publish the image; also enables image scanning and remediation artifacts. |
| `trivy_severity` | `HIGH,CRITICAL` | Comma-separated Trivy severity threshold. |
| `trivy_skip_dirs` | empty | Comma-separated filesystem paths to exclude from both filesystem scans. |
| `fail_on_image_findings` | `true` | Fail after the image scan finds matching findings; `false` makes it advisory. |
| `fail_on_fs_findings` | `true` | Fail after the filesystem scan finds matching findings; `false` makes it advisory. |

| Secret | Required | Description |
| --- | --- | --- |
| `registry_token` | no | Optional GHCR token. The workflow falls back to the built-in `github.token` for registry authentication. |

The workflow uses the latest Trivy CLI through a commit-pinned `trivy-action`. Filesystem scans check misconfigurations and secrets; image scans check vulnerabilities and secrets, ignore unfixed vulnerabilities, and scan OS and library packages. SARIF is uploaded under `trivy-fs` and, when publishing, `trivy-image`.

On a pushed image, the workflow also uploads these artifacts:

| Artifact | Contents |
| --- | --- |
| `trivy-image-report` | Compact actionable findings, finding markers, and the image-policy result used by remediation. |
| `trivy-image-full-report` | Full Trivy JSON, useful for investigation. |

### Git version action

[`git-version`](.github/actions/git-version/action.yml) is a composite action that produces the default version used by Docker CI. It needs a checkout with tags available.

| Input | Default | Description |
| --- | --- | --- |
| `default_base_tag` | `0.0` | Base tag used when the repository has no reachable Git tag. |

| Output | Description |
| --- | --- |
| `version` | `<base-tag>.<commits-since-base-tag>-g<short-sha>`. |
| `base_tag` | Latest reachable Git tag or `default_base_tag`. |
| `commits_since_tag` | Commits after `base_tag`. |
| `short_sha` | Short SHA of `HEAD`. |

## Trivy AI agentic remediation reference

Call `Enucatl/docker-compose-security-baseline/.github/workflows/trivy-remediation.yml@main` from a `workflow_run` wrapper. The wrapper needs `actions: read`, `contents: write`, and `pull-requests: write` permissions because the final proposal job pushes a branch and opens a PR.

| Input | Default | Description |
| --- | --- | --- |
| `run_id` | required | Numeric ID of the failed source workflow run. |
| `checkout_ref` | required | Full 40-character commit SHA from that run. |
| `source_workflow_name` | required | Exact `name` of the expected Docker CI workflow. |
| `trusted_branch` | repository default branch | Branch the source run must have used. |
| `base_branch` | repository default branch | Base branch for the proposed PR. |
| `report_artifact` | `trivy-image-report` | Name of the remediation-report artifact. |
| `report_path` | `trivy-remediation.json` | Path of the compact report within the artifact. |
| `skill_path` | `.agents/skills/trivy-remediation/SKILL.md` | Repository path given to Codex for its remediation rules. |
| `model` | empty | Model name passed to `openai/codex-action`. |
| `provider_base_url` | empty | Provider base URL; the workflow appends `/responses`. |
| `provider_env_key` | `OPENAI_API_KEY` | Currently declared but not consumed by the workflow. |
| `provider_name` | empty | Currently declared but not consumed by the workflow. |
| `provider_wire_api` | `responses` | Currently declared but not consumed by the workflow. |
| `codex_version` | `latest` | `@openai/codex` version used by the action. |

| Secret | Required | Description |
| --- | --- | --- |
| `model_api_key` | yes | API key passed only to `openai/codex-action`. |

Eligibility requires a failed `push` run from the same repository and trusted branch, with the given SHA, matching workflow name, a live matching report artifact, and an enforced image-policy failure. Duplicate finding markers in an open remediation PR stop another proposal.

The report includes only fixed HIGH or CRITICAL findings and the fields `target`, `type`, `cve`, `package`, `installed`, `fixed`, and `severity`. It is limited to 100 findings and 256 KiB. Codex runs with workspace-only permissions and no GitHub write token. Its patch may contain at most 20 regular text files and 128 KiB; links, special files, nonstandard modes, traversal, workflow/agent paths, and security-policy or Trivy configuration paths are rejected. The remediation instructions also prohibit CVE ignores, weakened scanning, unrelated upgrades, and speculative changes.
