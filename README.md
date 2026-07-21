<!-- mcp-name: io.github.AIops-tools/container-host-aiops -->

# Container Host AIops

> **Disclaimer**: Community-maintained open-source project. **Not affiliated with, endorsed by, or sponsored by Docker, Inc., Portainer.io, or any container-platform vendor.** "Docker", "Portainer" and all product/trademark names belong to their respective owners. MIT licensed.

Governed AI-ops for **non-orchestrator container hosts** — the **Docker Engine API** (over a local unix socket or a TCP host), **Portainer** (its management API, which also proxies Docker), and **Podman** (a rootful/rootless service socket speaking the Docker-compatible API plus libpod-native endpoints) — with a **built-in governance harness**: a unified audit log over both MCP and CLI, a runaway/budget safety guard, and undo-token recording. It records every operation; it does not decide whether a write is permitted — that is the agent's or the account's call. **Multi-platform by construction**: a registry keyed by `platform` means a per-target `platform` field (`docker` / `portainer` / `podman`) selects the API shape, and another host family could be added later without touching the ops/CLI/MCP layers. Exercised against a live Docker Engine 27.5.1 daemon (doctor, overview, the three flagship analyses, and a governed stop_container with audit + undo recorded); the Portainer and Podman API paths are covered by the mock suite only.

## What it does

Three flagship signature analyses, plus the guarded reads and writes around them:

- **Restart-loop RCA** — inspect containers for restart count + exit code, flag the crash-looping ones (restartCount over threshold, or restarting/dead, or a non-zero exit), and map each to a likely cause + action from the exit code (137 OOM/SIGKILL, 143 SIGTERM, 139 segfault, 127 bad entrypoint, …), with a tail of logs. Every ranking carries its numbers, not a black-box verdict.
- **Resource-pressure analysis** — a one-shot CPU%/memory% sample per running container vs its configured limits, flagging each "near" (≥ 80% of a threshold) or "over", with a recommendation (raise a limit, set a missing memory limit, scale out).
- **Image & volume bloat** — dangling images + dangling volumes + build cache from `system/df`, totalled into prune candidates with reclaimable bytes.

## What works

- **CLI** (`container-host-aiops ...`): `init`, `overview`, `container`, `image`, `volume`, `network`, `system`, `stack`, `pod`, `analyze`, `manage`, `secret`, `doctor`, `mcp`.
- **MCP server** (`container-host-aiops mcp` or `container-host-aiops-mcp`): **38 tools** (29 read, 9 write), every one wrapped with the bundled `@governed_tool` harness.
- **Connection layer**: Docker over a **unix socket** (`httpx.HTTPTransport(uds=...)`) or a TCP host; Portainer over HTTPS with an `X-API-Key` token that also proxies the Docker API of a managed endpoint; Podman over its **rootful/rootless service socket** (autodetected: `$XDG_RUNTIME_DIR/podman/podman.sock` first, then `/run/podman/podman.sock`) speaking the Docker-compat layer (paths reused wholesale) plus libpod-native endpoints. A local Docker/Podman socket needs **no secret** — the socket's file permissions are the boundary.
- **Encrypted credentials**: the Portainer API token lives in an encrypted store `~/.container-host-aiops/secrets.enc` (Fernet + scrypt) — **never plaintext on disk**. Unlock with a master password from `CONTAINER_HOST_AIOPS_MASTER_PASSWORD` (MCP/CI) or an interactive prompt (CLI).
- **Reversibility**: mutating writes fetch the **real before-state first** and record a faithful inverse (`stop`↔`start`; `update_container` restores prior CPU/memory limits). Irreversible ops (`remove_container`, `prune_images`, `prune_volumes`, `recreate_stack`) capture the before-state for audit but declare no undo.
- **Safety**: every state-changing CLI op supports `--dry-run` and requires double confirmation; every write MCP tool takes a `dry_run` preview — and prune previews **list what would be removed + reclaimable bytes** before doing it.

## What this tool does, and does not, decide

It delivers container-host operations — reads and writes — accurately and
efficiently, and records every one of them. It does **not** decide whether a
write is allowed to happen. That is the agent's judgement, or the permission of
the account you connect it with: point it at a Docker socket mounted read-only,
or a Portainer account without write scope, and the writes fail at the server —
the place that actually owns the permission.

So there is no read-only switch, no policy file, no approval gate to configure.
The one thing the tool guarantees is that nothing is silent: **every call, over
MCP and over the CLI alike, lands an audit row** in
`~/.container-host-aiops/audit.db`, and destructive writes still capture their
before-state and record an inverse where one exists.

> Each tool declares a `risk_level`, kept in agreement with its `[READ]`/`[WRITE]`
> documentation tag by a test, and carried into the audit row as a descriptive
> tier — so a reviewer can see at a glance that a row was a high-risk delete. It
> is a label, not a gate.

## Capability matrix (38 MCP tools)

| Domain | Tools | Count | R/W |
|--------|-------|:-----:|:---:|
| **Overview** | `overview` | 1 | read |
| **Containers** | `list_containers`, `inspect_container`, `container_logs`, `container_stats`, `container_top`, `container_restart_summary` | 6 | read |
| **Images** | `list_images`, `inspect_image`, `dangling_images`, `image_disk_usage` | 4 | read |
| **Volumes** | `list_volumes`, `inspect_volume`, `dangling_volumes` | 3 | read |
| **Networks** | `list_networks`, `inspect_network` | 2 | read |
| **System** | `system_info`, `system_version`, `system_df`, `system_events` | 4 | read |
| **Stacks** | `list_endpoints`, `list_stacks`, `stack_detail` (Portainer), `list_compose_stacks` (docker+podman) | 4 | read |
| **Pods (Podman)** | `list_pods` | 1 | read |
| **Analyses (flagship)** | `restart_loop_rca`, `resource_pressure_analysis`, `image_and_volume_bloat` | 3 | read |
| **Writes** | `remove_container`, `prune_images`, `prune_volumes`, `recreate_stack` | 4 | write (high) |
| | `restart_container`, `stop_container`, `start_container`, `update_container` | 4 | write (medium) |

The three analyses accept injected data for offline analysis, or pull live from a configured target. `list_endpoints`/`list_stacks`/`stack_detail` require a `portainer` target; `list_compose_stacks` (Compose project rollup by the `com.docker.compose.project` label, with per-stack health) works on `docker` **or** `podman`; `list_pods` requires a `podman` target (Docker/Portainer have no pod concept).

### Platform support matrix

| Capability | docker | portainer | podman |
|------------|:------:|:---------:|:------:|
| Container / image / volume / network / system reads | ✅ | ✅ (proxied) | ✅ (compat) |
| Flagship analyses (restart-loop RCA, resource pressure, bloat) | ✅ | ✅ | ✅ (compat) |
| Lifecycle + prune writes (stop/start/restart/remove/update/prune) | ✅ | ✅ | ✅ (compat) |
| Compose-stack rollup (`list_compose_stacks`) | ✅ | ✅ (proxied) | ✅ |
| Portainer endpoints / stacks / `recreate_stack` | — | ✅ | — |
| Podman pods (`list_pods`, libpod) | — | — | ✅ |

## Quick start

```bash
uv tool install container-host-aiops          # or: pipx install container-host-aiops
container-host-aiops init                      # wizard: add a Docker/Podman socket or Portainer target
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

Every operation — MCP **and** CLI — passes through the bundled `@governed_tool`
harness. It records; it does not authorize (see above).

- **Audit** — every call (params, result, status, duration, risk tier, and any operator-supplied approver/rationale) is logged to `~/.container-host-aiops/audit.db` (relocatable via `CONTAINER_HOST_AIOPS_HOME`). The CLI writes the same row the MCP path does — there is no unaudited entry point.
- **Runaway guard** — a safety backstop, not an authorization gate: the same call hammered in a tight loop trips a circuit breaker so a stuck agent can't burn unbounded calls/time. Disable with `CONTAINER_HOST_RUNAWAY_MAX=0`; optional hard ceilings via `CONTAINER_HOST_MAX_TOOL_CALLS` / `CONTAINER_HOST_MAX_TOOL_SECONDS`.
- **Undo recording** — reversible writes record an inverse descriptor built from the fetched before-state.
- **Risk tier** — a descriptive label on the audit row derived from `risk_level`; it gates nothing.

## Scope

This is the **container-host** member of the AIops-tools family (governed AI-ops with audit + budget + undo), for **single-host Docker / Portainer / Podman**. It is deliberately **NOT** for a cluster orchestrator, a hypervisor, a storage appliance, a backup product, or OT / industrial edge — those are separate tools/lines.

## Missing a capability?

Coverage is intentionally a curated subset of the Docker Engine + Portainer + Podman (libpod) APIs. Missing a call, or want another container host family? **Open an issue or PR** — contributions welcome.

## Verification status

- **Docker** — exercised against a **live Docker Engine 27.5.1** daemon: `doctor` and
  `overview` connected over the local socket, the `restart-loop` and image/volume
  `bloat` analyses were run against real crash-looping containers and real reclaimable
  data, and a governed `stop_container` wrote a row to the audit DB and recorded a
  working undo descriptor.
- **Portainer and Podman** — **mock-validated only**. Those API paths are modelled from
  each project's public API shape and have not been exercised against a live server.
- The full checklist — what the mock suite guarantees, what the Docker run already
  satisfied, and what a Portainer/Podman run still has to prove — is in
  [docs/VERIFICATION.md](docs/VERIFICATION.md). `container-host-aiops doctor` is the
  fastest live check on any platform.
