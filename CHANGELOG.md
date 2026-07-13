# Changelog

All notable changes to container-host-aiops are documented here. This project adheres
to [Semantic Versioning](https://semver.org/).

## [0.1.0] — preview

Initial preview release: governed AI-ops for **non-orchestrator container hosts**
across the **Docker Engine API** (unix socket or TCP) and **Portainer** (its
management API, which also proxies Docker), with a bundled governance harness. One
config can span many hosts; a per-target `platform` field selects the API shape.
**Mock-validated only — not yet verified against a live Docker daemon or Portainer
server.**

### Added

- **34 MCP tools** (26 read, 8 write), every one wrapped with the bundled
  `@governed_tool` harness (audit, policy, token/runaway budget, undo,
  risk-tiers):
  - **Overview** — `overview` (one-shot host health: version + container state
    rollup + disk headline).
  - **Containers (read)** — `list_containers`, `inspect_container`,
    `container_logs` (tail N), `container_stats` (CPU%/mem%), `container_top`,
    `container_restart_summary`.
  - **Images (read)** — `list_images`, `inspect_image` (with history/layers),
    `dangling_images`, `image_disk_usage`.
  - **Volumes (read)** — `list_volumes`, `inspect_volume`, `dangling_volumes`.
  - **Networks (read)** — `list_networks`, `inspect_network`.
  - **System (read)** — `system_info`, `system_version`, `system_df`,
    `system_events`.
  - **Stacks (Portainer, read)** — `list_endpoints`, `list_stacks`,
    `stack_detail`.
  - **Flagship analyses (read)** — `restart_loop_rca` (crash-looping containers +
    cause/action from exit code + log tail), `resource_pressure_analysis`
    (CPU/memory vs limits + recommendation), `image_and_volume_bloat` (dangling
    images + volumes + build cache → prune candidates with reclaimable bytes).
  - **Writes** — `restart_container` (med), `stop_container` (med, undo→start),
    `start_container` (med, undo→stop), `update_container` (med, undo restores
    prior CPU/memory limits), `remove_container` (**high**, captures full inspect
    first), `prune_images` (**high**, dry-run lists candidates), `prune_volumes`
    (**high**, dry-run lists candidates), `recreate_stack` (**high**, Portainer).
- **Connection layer** — Docker over a unix socket (`httpx.HTTPTransport(uds=...)`)
  or a TCP host; Portainer over HTTPS with an `X-API-Key` token that also proxies
  the Docker API of a managed endpoint (`/api/endpoints/{id}/docker/...`).
- **Encrypted secret store** — the Portainer API token is stored encrypted in
  `~/.container-host-aiops/secrets.enc` (Fernet + scrypt); never plaintext on disk.
  A direct Docker socket needs no secret. Legacy `CONTAINER_HOST_<TARGET>_TOKEN`
  env var honoured as a fallback.
- **CLI** (`container-host-aiops`) — `init` platform-picking wizard, `overview`,
  `container`, `image`, `volume`, `network`, `system`, `stack`, `analyze`,
  `manage` (guarded writes with `--dry-run` + double-confirm), `secret`
  management, and a platform-aware `doctor`.

### Known limitations

- Preview / mock-only: the Docker Engine + Portainer API responses are mocked and
  need live verification against a real daemon / server. `container-host-aiops
  doctor` is the fastest live check.
- Single-host focus by design: cluster orchestrators, hypervisors, storage
  appliances, and backup products are out of scope (separate AIops-tools).
