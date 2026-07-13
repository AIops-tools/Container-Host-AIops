# Container Host AIops v0.1.0 — preview

Governed AI-ops for **non-orchestrator container hosts** across the **Docker
Engine API** (unix socket or TCP) and **Portainer** (its management API, which
also proxies Docker) for AI agents, with a built-in governance harness (audit,
policy, token/runaway budget, undo-token recording, graduated risk tiers) and an
encrypted credential store. Standalone — no external skill-family dependency. One
config can span many hosts; a per-target `platform` field selects the API shape.

> **Preview / mock-only.** All behaviour is validated against mocked Docker /
> Portainer responses; it has not been run against a live daemon or server. The
> fastest live check is `container-host-aiops doctor`.

## Highlights

- **34 MCP tools** (26 read, 8 write), every one wrapped with `@governed_tool`.
  - **Overview** — `overview` (host version + container state rollup + disk).
  - **Containers** — `list_containers`, `inspect_container`, `container_logs`,
    `container_stats`, `container_top`, `container_restart_summary`.
  - **Images** — `list_images`, `inspect_image`, `dangling_images`,
    `image_disk_usage`.
  - **Volumes / Networks** — `list_volumes`, `inspect_volume`, `dangling_volumes`;
    `list_networks`, `inspect_network`.
  - **System** — `system_info`, `system_version`, `system_df`, `system_events`.
  - **Stacks (Portainer)** — `list_endpoints`, `list_stacks`, `stack_detail`.
  - **Writes** — `restart_container`, `stop_container`/`start_container`,
    `update_container`, `remove_container`, `prune_images`/`prune_volumes`,
    `recreate_stack`.
- **Three flagship analyses** — `restart_loop_rca` (crash-looping containers +
  cause/action from exit code + log tail), `resource_pressure_analysis` (CPU/memory
  vs limits + recommendation), `image_and_volume_bloat` (prune candidates +
  reclaimable bytes). Each accepts injected data for offline analysis or pulls live.
- **Connection layer** — Docker over a unix socket (`httpx.HTTPTransport(uds=...)`)
  or a TCP host; Portainer over HTTPS with an `X-API-Key` token that proxies the
  Docker API of a managed endpoint. A local Docker socket needs no secret.
- **Encrypted secret store** (`~/.container-host-aiops/secrets.enc`, Fernet + scrypt)
  — the Portainer API token, never plaintext on disk; legacy
  `CONTAINER_HOST_<TARGET>_TOKEN` env fallback.
- **Guarded writes** — destructive ops (`remove_container`, `prune_images`,
  `prune_volumes`, `recreate_stack`) require dry-run + double-confirm; prune
  previews list what would be removed + reclaimable bytes first. Reversible writes
  capture before-state and record an inverse undo descriptor.
- **CLI** with an `init` platform-picking wizard, `secret` management, and a
  platform-aware `doctor`.

## Install

```bash
uv tool install container-host-aiops
container-host-aiops init       # pick platform (docker/portainer) + connect
container-host-aiops doctor
```

## Caveats

- Preview / mock-only: the Docker Engine + Portainer API responses are mocked and
  need live verification.
- Single-host focus by design: cluster orchestrators, hypervisors, storage
  appliances, and backup products are out of scope (separate AIops-tools).
