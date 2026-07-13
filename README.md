<!-- mcp-name: io.github.AIops-tools/container-host-aiops -->

# Container Host AIops (preview)

> **Disclaimer**: Community-maintained open-source project. **Not affiliated with, endorsed by, or sponsored by Docker, Inc., Portainer.io, or any container-platform vendor.** "Docker", "Portainer" and all product/trademark names belong to their respective owners. MIT licensed.

Governed AI-ops for **non-orchestrator container hosts** — the **Docker Engine API** (over a local unix socket or a TCP host) and **Portainer** (its management API, which also proxies Docker) — with a **built-in governance harness**: unified audit log, policy engine, token/runaway budget guard, undo-token recording, and graduated-autonomy risk tiers. **Multi-platform by construction**: a registry keyed by `platform` means a per-target `platform` field (`docker` / `portainer`) selects the API shape, and another host family could be added later without touching the ops/CLI/MCP layers. **Preview — mock-validated only, not verified against a live Docker daemon or Portainer server.**

## What it does

Three flagship signature analyses, plus the guarded reads and writes around them:

- **Restart-loop RCA** — inspect containers for restart count + exit code, flag the crash-looping ones (restartCount over threshold, or restarting/dead, or a non-zero exit), and map each to a likely cause + action from the exit code (137 OOM/SIGKILL, 143 SIGTERM, 139 segfault, 127 bad entrypoint, …), with a tail of logs. Every ranking carries its numbers, not a black-box verdict.
- **Resource-pressure analysis** — a one-shot CPU%/memory% sample per running container vs its configured limits, flagging each "near" (≥ 80% of a threshold) or "over", with a recommendation (raise a limit, set a missing memory limit, scale out).
- **Image & volume bloat** — dangling images + dangling volumes + build cache from `system/df`, totalled into prune candidates with reclaimable bytes.

## What works

- **CLI** (`container-host-aiops ...`): `init`, `overview`, `container`, `image`, `volume`, `network`, `system`, `stack`, `analyze`, `manage`, `secret`, `doctor`, `mcp`.
- **MCP server** (`container-host-aiops mcp` or `container-host-aiops-mcp`): **34 tools** (26 read, 8 write), every one wrapped with the bundled `@governed_tool` harness.
- **Connection layer**: Docker over a **unix socket** (`httpx.HTTPTransport(uds=...)`) or a TCP host; Portainer over HTTPS with an `X-API-Key` token that also proxies the Docker API of a managed endpoint. A local Docker socket needs **no secret** — the socket's file permissions are the boundary.
- **Encrypted credentials**: the Portainer API token lives in an encrypted store `~/.container-host-aiops/secrets.enc` (Fernet + scrypt) — **never plaintext on disk**. Unlock with a master password from `CONTAINER_HOST_AIOPS_MASTER_PASSWORD` (MCP/CI) or an interactive prompt (CLI).
- **Reversibility**: mutating writes fetch the **real before-state first** and record a faithful inverse (`stop`↔`start`; `update_container` restores prior CPU/memory limits). Irreversible ops (`remove_container`, `prune_images`, `prune_volumes`, `recreate_stack`) capture the before-state for audit but declare no undo.
- **Safety**: every state-changing CLI op supports `--dry-run` and requires double confirmation; every write MCP tool takes a `dry_run` preview — and prune previews **list what would be removed + reclaimable bytes** before doing it.

## Capability matrix (34 MCP tools)

| Domain | Tools | Count | R/W |
|--------|-------|:-----:|:---:|
| **Overview** | `overview` | 1 | read |
| **Containers** | `list_containers`, `inspect_container`, `container_logs`, `container_stats`, `container_top`, `container_restart_summary` | 6 | read |
| **Images** | `list_images`, `inspect_image`, `dangling_images`, `image_disk_usage` | 4 | read |
| **Volumes** | `list_volumes`, `inspect_volume`, `dangling_volumes` | 3 | read |
| **Networks** | `list_networks`, `inspect_network` | 2 | read |
| **System** | `system_info`, `system_version`, `system_df`, `system_events` | 4 | read |
| **Stacks (Portainer)** | `list_endpoints`, `list_stacks`, `stack_detail` | 3 | read |
| **Analyses (flagship)** | `restart_loop_rca`, `resource_pressure_analysis`, `image_and_volume_bloat` | 3 | read |
| **Writes** | `remove_container`, `prune_images`, `prune_volumes`, `recreate_stack` | 4 | write (high) |
| | `restart_container`, `stop_container`, `start_container`, `update_container` | 4 | write (medium) |

The three analyses accept injected data for offline analysis, or pull live from a configured target. Stacks/endpoints require a `portainer` target.

## Quick start

```bash
uv tool install container-host-aiops          # or: pipx install container-host-aiops
container-host-aiops init                      # wizard: add a Docker socket or Portainer target
container-host-aiops doctor                    # verify config, secrets, connectivity
container-host-aiops overview                  # one-shot host health
container-host-aiops analyze restart-loop      # crash-looping containers + cause/action
container-host-aiops container list --running  # running containers
```

Run as an MCP server (stdio):

```bash
export CONTAINER_HOST_AIOPS_MASTER_PASSWORD=...   # only needed for Portainer targets
container-host-aiops-mcp
```

## Governance

Every MCP tool passes through the bundled `@governed_tool` harness:

- **Audit** — every call (params, result, status, duration, risk tier, approver, rationale) is logged to `~/.container-host-aiops/audit.db` (relocatable via `CONTAINER_HOST_AIOPS_HOME`).
- **Budget / runaway guard** — token and call budgets trip a circuit breaker.
- **Risk tiers** — graduated autonomy; high-risk ops (remove / prune / recreate) can require a named approver.
- **Undo recording** — reversible writes record an inverse descriptor built from the fetched before-state.

## Scope

This is the **container-host** member of the AIops-tools family (governed AI-ops with audit + budget + undo + risk tiers), for **single-host Docker / Portainer**. It is deliberately **NOT** for a cluster orchestrator, a hypervisor, a storage appliance, a backup product, or OT / industrial edge — those are separate tools/lines.

## Missing a capability?

Coverage is intentionally a curated subset of the Docker Engine + Portainer APIs. Missing a call, or want another container host family? **Open an issue or PR** — contributions welcome.

## Status

**Preview — mock-validated only, not verified against a live Docker daemon or Portainer server.** The API paths are modelled from the public API shape and need live verification. `container-host-aiops doctor` is the fastest live check.
