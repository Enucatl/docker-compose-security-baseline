# Postgres Memory Investigation

## Summary

This investigation measured the memory impact of the shared Postgres low-memory profile introduced in commit `5798cca` (`Add Postgres low-memory profile`).

The key question was simple: how much RAM does the new configuration actually save, both at idle and under a small connection load?

The short answer:

- The optimized profile saves about `10 MiB` of container memory in this setup.
- Under a 7-connection load, the savings were about `9.9 MiB`.
- Docker's own memory reporting showed the same trend, with the optimized container staying lower in both idle and loaded states.

## What Was Tested

Two Postgres 18 containers were compared:

- Baseline: plain `postgres:18` with default server settings.
- Optimized: `postgres:18` started with the shared baseline config file mounted and passed as `config_file=/etc/postgresql/postgres-low-memory.conf`.

Both containers were run with the same outer container memory limit:

- `--memory 512m`
- `--memory-swap 512m`

The optimized configuration came from [postgres-low-memory.conf](/opt/docker/compose-security-baseline/postgres-low-memory.conf).

That file applies the generated `postgres:18` default config first, then overrides only the low-memory settings:

- `max_connections = 10`
- `shared_buffers = 16MB`
- `work_mem = 1MB`
- `maintenance_work_mem = 16MB`
- `temp_buffers = 1MB`
- `wal_buffers = 1MB`
- `autovacuum_max_workers = 1`

## What Was Tried

I ran several benchmark attempts before getting the final measurement.

### First attempt

I initially tried to launch the Postgres containers using the same Compose-style assumptions as the repository profile, but the Postgres 18 image requires a different data-volume layout.

The image produced this error:

- the database data mount must be at `/var/lib/postgresql`
- a mount at `/var/lib/postgresql/data` is treated as incompatible with the Postgres 18 layout

That was corrected by mounting the volume at `/var/lib/postgresql` instead.

### Second attempt

I also hit a command construction issue when starting the optimized container. The image name and the command override were passed in the wrong order, so the container entrypoint received `postgres:18` as an argument instead of as the image name.

That was corrected by using the proper Docker argument order:

1. options
2. image
3. command

### Third attempt

I tried to measure the optimized server with 10 client sessions plus a monitoring query. That exposed a real operational boundary rather than a scripting bug:

- the optimized profile sets `max_connections = 10`
- 10 test clients plus one monitoring connection exceeded that ceiling
- the server began returning `FATAL: sorry, too many clients already`

To keep the comparison fair and avoid measuring refusal behavior instead of memory use, I reduced the active load to 7 client sessions. That left room for the monitoring query and stayed below the configured connection limit.

## How Memory Was Checked

I measured memory in two ways.

### 1. cgroup memory

For each container, I read:

- `/sys/fs/cgroup/memory.current`

This gives the container's cgroup memory usage directly.

### 2. Docker stats

I also sampled:

- `docker stats --no-stream --format '{{.MemUsage}}' <container>`

That reports Docker's own view of the container memory usage.

The two measurements were taken:

- after startup, before any client sessions were opened
- again after the 7 client sessions were active

## How the Benchmark Was Run

The benchmark procedure was:

1. Create a private Docker network for the test.
2. Start the baseline container with a clean data volume.
3. Wait for Postgres to accept connections.
4. Record idle memory.
5. Start 7 client containers, each running:

   - `psql -c 'select pg_sleep(60)'`

6. Wait until 7 client backends were visible in `pg_stat_activity`.
7. Record loaded memory.
8. Repeat the same flow for the optimized container.

The connection-count query was:

```sql
select count(*)
from pg_stat_activity
where backend_type = 'client backend'
  and datname = 'postgres'
  and pid <> pg_backend_pid();
```

## Implementation Notes

The shared Postgres profile is wired in [hardening.yml](/opt/docker/compose-security-baseline/hardening.yml).

The `postgres` service:

- extends the shared hardened profile
- uses `postgres:18`
- mounts [postgres-low-memory.conf](/opt/docker/compose-security-baseline/postgres-low-memory.conf)
- starts Postgres with:

  - `postgres -c config_file=/etc/postgresql/postgres-low-memory.conf`

The configuration file itself starts by including the image's generated default config:

```conf
include = '/var/lib/postgresql/18/docker/postgresql.conf'
```

Then it applies only the low-memory overrides.

That design matters because it keeps the tuning centralized in this repository instead of duplicating copied settings in every downstream Compose file.

## Results

### Configuration observed

- Baseline:
  - `shared_buffers = 128MB`
  - `max_connections = 100`
- Optimized:
  - `shared_buffers = 16MB`
  - `max_connections = 10`

### Memory measurements

| Case | cgroup idle | cgroup loaded | Docker stats idle | Docker stats loaded |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 65.3 MiB | 76.1 MiB | 26.11MiB / 512MiB | 36.93MiB / 512MiB |
| Optimized | 55.3 MiB | 66.1 MiB | 16.15MiB / 512MiB | 26.95MiB / 512MiB |

### Savings

| Comparison | Savings |
| --- | ---: |
| Idle cgroup memory | 10.0 MiB |
| Loaded cgroup memory | 9.9 MiB |

## Interpretation

The memory reduction is real, but it is not large in absolute terms.

Most of the observed savings came from reducing the Postgres process footprint itself, not from the outer container limits. The container cap stayed fixed at 512 MiB in both cases.

The low-memory profile also changes behavior beyond memory:

- `max_connections` drops from 100 to 10
- that makes the container much less tolerant of concurrent client bursts
- the profile is appropriate only when the downstream service is expected to stay within that tighter connection envelope

## Notes And Caveats

- The optimized configuration was tested with 7 active client sessions, not 10, because the profile's `max_connections=10` left no room for the monitoring query.
- The report compares the same image version and the same outer memory cap in both cases.
- Docker's `stats` output and cgroup memory were both recorded. They differ numerically, but both show the same direction and roughly the same magnitude of improvement.

