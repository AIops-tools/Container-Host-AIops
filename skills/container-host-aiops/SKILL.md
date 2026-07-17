---
name: container-host-aiops
description: >
  Use this skill whenever the user needs to operate a single container host through the Docker Engine API, Portainer, or Podman — a one-shot host overview; container reads (list/inspect, logs tail, CPU/memory stats, top processes, restart summary); image reads (list, inspect with history, dangling, disk usage); volume reads (list, inspect, dangling); network reads (list, inspect); system reads (info, version, df disk-usage, recent events); Portainer stacks + endpoints; Compose-project rollups (list_compose_stacks, docker+podman); Podman pods (list_pods, podman-only); three flagship analyses — restart-loop RCA (crash-looping containers + cause/action), resource-pressure analysis (CPU/memory vs limits), and image & volume bloat (prune candidates + reclaimable bytes); and eight guarded writes (restart/stop/start/remove a container, prune images/volumes, update resource limits, recreate a Portainer stack).
  Always use this skill for "Docker host overview", "which containers are crash-looping", "restart loop", "why does this container keep restarting", "container CPU/memory usage", "docker logs", "which containers are near their limits", "resource pressure", "dangling images/volumes", "reclaim disk", "prune images", "stop/start/restart a container", "update a container's memory limit", "Portainer stacks", "compose stacks", "Podman pods" when the context is a Docker, Portainer, or Podman container host.
  Do NOT use when the target is a cluster orchestrator, a hypervisor, a storage appliance, a backup product, network device config, or OT/industrial equipment — route those to the appropriate other AIops-tools skill. This is for NON-orchestrator container hosts.
  Preview — governed Docker/Portainer/Podman container-host operations with a built-in governance harness (audit, policy, token budget, undo, risk-tiers). Mock-validated only, not verified against a live Docker daemon, Portainer, or Podman server.
installer:
  kind: uv
  package: container-host-aiops
argument-hint: "[container/image/volume id or describe your container-host task]"
allowed-tools:
  - Bash
metadata: {"openclaw":{"requires":{"env":["CONTAINER_HOST_AIOPS_CONFIG"],"bins":["container-host-aiops"],"config":["~/.container-host-aiops/config.yaml"]},"optional":{"env":["CONTAINER_HOST_AIOPS_MASTER_PASSWORD"]},"primaryEnv":"CONTAINER_HOST_AIOPS_CONFIG","homepage":"https://github.com/AIops-tools/Container-Host-AIops","emoji":"🐳","os":["macos","linux"]}}
compatibility: >
  Standalone, self-governed Docker + Portainer + Podman container-host operations (preview). The governance harness (audit, policy, token/runaway budget, undo, risk-tiers) is bundled in the package — no external skill-family dependency. Multi-platform by construction (a platform registry); a per-target 'platform' field (docker / portainer / podman) selects the API shape.
  All write operations are audited to a local SQLite DB under ~/.container-host-aiops/ (relocatable via CONTAINER_HOST_AIOPS_HOME).
  Connection: a Docker target speaks the Docker Engine API over a local unix socket (httpx uds transport, default /var/run/docker.sock — treat socket access as root-equivalent) or a TCP host; a Portainer target speaks the Portainer management API over HTTPS with an X-API-Key token, and also proxies the Docker API of a managed endpoint at /api/endpoints/{id}/docker/...; a Podman target speaks over the rootful/rootless service socket (autodetected: $XDG_RUNTIME_DIR/podman/podman.sock, then /run/podman/podman.sock), reusing the Docker-compat paths at the root plus libpod-native endpoints (pods) under the libpod prefix.
  Credentials: only Portainer needs a secret — its API token is stored ENCRYPTED in ~/.container-host-aiops/secrets.enc (Fernet/AES-128 + scrypt-derived key) — never plaintext on disk. A local Docker or Podman socket needs no secret. Run 'container-host-aiops init' to onboard, or 'container-host-aiops secret set <target>' to add a Portainer token. The store is unlocked by a master password from CONTAINER_HOST_AIOPS_MASTER_PASSWORD (non-interactive/MCP/CI) or an interactive prompt (CLI on a TTY). A legacy plaintext env var CONTAINER_HOST_<TARGET_NAME_UPPER>_TOKEN is still honoured as a fallback with a deprecation warning (migrate with 'container-host-aiops secret migrate'). The token is sent in the X-API-Key header at request time and held only in memory; secrets are never logged or echoed.
  State-changing operations require double confirmation at the CLI layer and support --dry-run. All write tools pass through the @governed_tool decorator (pre-check + budget guard + audit + risk-tier gate) and take a dry_run preview. Prune previews list what would be removed + reclaimable bytes before doing it. Mutating/reversible writes fetch the real before-state first and record a faithful inverse undo descriptor (stop→start, update_container→restore prior limits); irreversible ops (remove, prune, recreate) record only the before-state.
  Webhooks: none — no outbound network calls beyond the configured Docker socket / TCP host or the Portainer API base URL.
  SSL: verify_ssl defaults to true; disable only for a self-signed Portainer / TLS Docker daemon. A unix-socket Docker target does not use TLS.
  Transitive dependencies: httpx (HTTP client) and the MCP SDK. No post-install scripts or background services.
  PREVIEW: mock-validated only; the Docker Engine + Portainer + Podman (libpod) API paths are modelled from the public API shape and need live verification. Community-maintained; not affiliated with or endorsed by Docker/Portainer/Podman — trademarks belong to their owners.
---

# Container Host AIops (preview)

> **Disclaimer**: Community-maintained open-source project, **not affiliated with, endorsed by, or sponsored by Docker, Inc., Portainer.io, or any container-platform vendor.** Product and trademark names belong to their owners. Source at [github.com/AIops-tools/Container-Host-AIops](https://github.com/AIops-tools/Container-Host-AIops) under the MIT license.

Governed Docker + Portainer + Podman container-host operations — **36 MCP tools**, every one wrapped with the bundled `@governed_tool` harness: a local unified audit log under `~/.container-host-aiops/`, policy engine, token/runaway budget guard, undo-token recording, and graduated-autonomy risk tiers. A Docker target speaks the Docker Engine API over a unix socket or TCP; a Portainer target speaks the Portainer API (and proxies Docker); a Podman target speaks over its rootful/rootless socket (Docker-compat + libpod). The Portainer API token is stored **encrypted** (`~/.container-host-aiops/secrets.enc`, Fernet + scrypt) — never plaintext on disk; a local Docker/Podman socket needs no secret.

> **Standalone**: the governance harness is bundled in the package (`container_host_aiops.governance`) — container-host-aiops has no external skill-family dependency. **Preview / mock-only**: not yet validated against a live Docker daemon or Portainer server.

## What This Skill Does

| Domain | Tools | Count | Read or Write |
|--------|-------|:-----:|:-------------:|
| **Overview** | one-shot host health | 1 | 1 read |
| **Containers** | list/inspect, logs, stats, top, restart summary | 6 | 6 read |
| **Images** | list, inspect (+history), dangling, disk usage | 4 | 4 read |
| **Volumes** | list, inspect, dangling | 3 | 3 read |
| **Networks** | list, inspect | 2 | 2 read |
| **System** | info, version, df, events | 4 | 4 read |
| **Stacks** | endpoints, stacks, stack detail (Portainer), compose-stack rollup (docker+podman) | 4 | 4 read |
| **Pods (Podman)** | list pods (libpod) | 1 | 1 read |
| **Analyses (flagship)** | restart-loop RCA, resource pressure, image/volume bloat | 3 | 3 read |
| **Writes** | remove container, prune images, prune volumes, recreate stack | 4 | 4 write (high) |
| | restart, stop, start, update container | 4 | 4 write (medium) |

The three analyses accept injected data for offline analysis, or pull live from a configured target. Portainer endpoints/stacks require a `portainer` target; `list_compose_stacks` works on docker or podman; `list_pods` requires a `podman` target.

## Quick Install

```bash
uv tool install container-host-aiops
container-host-aiops init       # interactive wizard: Docker/Podman socket or Portainer target
container-host-aiops doctor
```

## When to Use This Skill

- Triage a host (`overview`): version + container state rollup + disk headline
- Find crash-looping containers (`analyze restart-loop` / `restart_loop_rca`): ranked by restart count with a likely cause and action from the exit code, plus a log tail
- Spot resource pressure (`analyze resource-pressure` / `resource_pressure_analysis`): CPU%/mem% vs each container's limits, worst first, with a recommendation
- Reclaim disk (`analyze bloat` / `image_and_volume_bloat`): dangling images + volumes + build cache as prune candidates with reclaimable bytes
- List/inspect containers, images, volumes, networks; tail logs; read stats/top
- Restart/stop/start a container, update its resource limits (reversible), remove a container, prune images/volumes, or recreate a Portainer stack — all with dry-run + double-confirm

**Do NOT use when** the target is a cluster orchestrator, a hypervisor, a storage appliance, a backup product, network device config, or OT/industrial equipment.

## Related Skills — Skill Routing

| If the user wants… | Use |
|--------------------|-----|
| Docker / Portainer single-host container ops | **container-host-aiops** (this skill) |
| A cluster orchestrator's workloads/rollouts | a cluster ops skill |
| Hypervisor VM lifecycle (power, snapshot, migrate) | a hypervisor ops skill |
| OT / industrial edge (Modbus, OPC-UA, PLC) | the industrial-aiops line |

## Common Workflows

### Diagnose a crash-looping container

1. `container-host-aiops analyze restart-loop` → containers ranked by restart count, each with a likely cause (137 OOM/SIGKILL, 143 SIGTERM, 139 segfault, 127 bad entrypoint, …), an action, and a log tail
2. Drill with `container-host-aiops container logs <id> --tail 200` and `container inspect <id>`
3. If it is memory pressure, cross-check `analyze resource-pressure`; raise the limit with `manage update <id> '{"Memory": 1073741824}'` (dry-run first)

### Reclaim disk safely

1. `container-host-aiops analyze bloat` → prune candidates with reclaimable bytes
2. `container-host-aiops manage prune-images --dry-run` → list exactly what would be removed
3. Re-run without `--dry-run` (double-confirm) — a high-risk op; `prune-volumes` similarly

### Offline analysis (no live host)

Pass data straight to the analysis tools — `restart_loop_rca(containers=[...])`, `resource_pressure_analysis(samples=[...])`, or `image_and_volume_bloat(dangling_images=..., dangling_volumes=..., df=...)` — to analyse an exported dataset without connecting to a host.

## Governance & Safety

- Every tool is audited to `~/.container-host-aiops/audit.db` (relocatable via `CONTAINER_HOST_AIOPS_HOME`).
- High-risk ops (remove / prune / recreate) can require a named approver: set `CONTAINER_HOST_AUDIT_APPROVED_BY` and `CONTAINER_HOST_AUDIT_RATIONALE` (the env-var names the bundled harness reads).
- **Secure by default (v0.2.0+)**: with no `~/.container-host-aiops/rules.yaml`, high/critical operations are denied unless `CONTAINER_HOST_AUDIT_APPROVED_BY` names an approver (set `CONTAINER_HOST_AUDIT_RATIONALE` too). `container-host-aiops init` seeds a starter rules.yaml; an operator-authored rules file is honoured as-is.
- Writes support `--dry-run` / `dry_run=True` and double confirmation at the CLI; prune previews list what would be removed + reclaimable bytes.
- Mutating/reversible writes fetch the real before-state and record an inverse descriptor (stop→start, update_container→restore prior limits); irreversible ops record only the before-state.

## References

- `references/capabilities.md` — full tool + field reference
- `references/cli-reference.md` — CLI command reference
- `references/setup-guide.md` — onboarding, credentials, and connectivity
