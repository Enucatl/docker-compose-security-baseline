# Docker Security Program Backlog

This document is intentionally broader than the first Compose-only hardening pass.
Each item can be reviewed and scheduled independently.

## Traefik Docker Socket Proxy

- Why: a read-only Docker socket still exposes high-value daemon metadata and can be risky if Traefik is compromised.
- Benefit: narrows Traefik's Docker API access to the endpoints it needs for service discovery.
- Cost: add and maintain a socket-proxy container and update Traefik's Docker provider endpoint.
- Rollout risk: broken routing if the proxy blocks an endpoint Traefik needs.

## Host Firewall Review

- Why: Compose port bindings publish directly on the host, including several TCP/UDP services that intentionally bypass Traefik.
- Benefit: enforces source allowlists outside Docker and protects accidental future port exposure.
- Cost: maintain nftables/firewalld rules alongside Compose.
- Rollout risk: breaking Unifi adoption, Teamspeak, qBittorrent, i2pd, FreeIPA, Checkmk, or Postgres access.

## Image Digest Pinning

- Why: mutable tags such as `latest` and `main` can change without a Compose diff.
- Benefit: repeatable deploys and controlled update windows.
- Cost: periodic digest refresh and vulnerability review.
- Rollout risk: manual updates become more deliberate and can lag if not scheduled.

## Image Vulnerability Scanning

- Why: pinned or mutable images can contain vulnerable packages.
- Benefit: catches known CVEs before rollout and during periodic review.
- Cost: add Trivy, Docker Scout, or equivalent scanning and a triage process.
- Rollout risk: scanner noise if severity thresholds and ignores are not curated.

## Vault-Backed Secret Rendering

- Why: Compose file secrets are file-backed and do not natively read from Vault.
- Benefit: central secret source of truth while preserving `/run/secrets` runtime mounting.
- Cost: write a preflight render command that reads Vault KV paths into local secret files with strict permissions.
- Rollout risk: services fail to start if Vault is sealed, unreachable, or the render token lacks policy access.

## Project-Specific Secret Wrappers

- Why: several images currently receive secrets as required environment variables or command arguments, including Airflow database/core settings, rclone credentials, cloudflared tunnel tokens, and app `DATABASE_URL` values.
- Benefit: removes more values from `docker inspect` after the low-risk `_FILE` migrations are complete.
- Cost: per-image wrappers or app changes are needed where `_FILE` is not natively supported.
- Rollout risk: wrappers can accidentally bypass an image's original entrypoint behavior.

## Read-Only Root Filesystems

- Why: writable image filesystems allow persistence inside compromised containers.
- Benefit: reduces post-compromise modification paths.
- Cost: identify and mount each service's required writable paths as volumes or tmpfs.
- Rollout risk: applications fail when caches, PID files, lock files, or temp directories were missed.

## Custom AppArmor And Seccomp

- Why: Docker's built-in profiles are general-purpose.
- Benefit: high-value services can get syscall and filesystem access tailored to their actual runtime behavior.
- Cost: profile authoring, audit-mode testing, and ongoing maintenance across image updates.
- Rollout risk: hard-to-debug runtime failures when profiles are too strict.

## Rootless Docker Feasibility

- Why: the daemon remains a privileged host component even with `userns-remap`.
- Benefit: reduces daemon-level privilege in compatible environments.
- Cost: review networking, low ports, storage drivers, IPv6, and services requiring host or privileged modes.
- Rollout risk: iVentoy, low-port publishing, and host-integrated workloads may be incompatible.

## Backup Restore Exercises

- Why: backups are only useful if restores are tested.
- Benefit: validates Duplicati source access under `userns-remap` and confirms recovery steps.
- Cost: scheduled restore drills and temporary storage.
- Rollout risk: low, but restore drills can expose missing data or permission problems that need follow-up.

## Runtime Threat Detection

- Why: static hardening does not reveal all suspicious runtime behavior.
- Benefit: Falco, Tetragon, or similar tooling can alert on shell spawns, sensitive file access, and unexpected network activity.
- Cost: extra CPU/memory, rule tuning, and alert handling.
- Rollout risk: noisy alerts without a tuning period.
