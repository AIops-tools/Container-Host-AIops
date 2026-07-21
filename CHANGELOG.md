# Changelog

## v0.6.0 — 2026-07-21

### Changed (BREAKING)
- **Removed the authorization layer** — read-only mode, the approver gate, and rules.yaml deny are gone. The skill no longer decides read vs write; that is the agent's judgement or the connecting account's permissions. `<PREFIX>_READ_ONLY` now has no effect (a startup warning is logged); `<PREFIX>_AUDIT_APPROVED_BY`/`_RATIONALE` are optional audit annotations.
- The retained guarantee is **unbypassable audit over MCP and CLI alike** — no unaudited entry point. Harness = audit + runaway safety guard + undo + sanitize; `risk_level` is a descriptive audit label, not a gate.

See RELEASE_NOTES.md for tool-specific changes.


## v0.5.0 — 2026-07-20

### Fixed
- **`stop_container` / `remove_container` refuse the Portainer container serving the API.** On a Portainer target every request is proxied through that container, which appears as an ordinary row in the tool's own list — so stopping it killed the API mid-request, and `undo_apply` would have dispatched the inverse through the same dead endpoint.
- Harness: a write whose response is lost is audited `status=unknown`, not `error` — it may have taken effect. Undo tokens gain `effectVerified` (undo.db migrated in place).
- Harness: a dry-run no longer records an undo token, and no longer requires a named approver. Guards now run on the preview path.
- Truncated strings end in an ellipsis instead of being cut silently; error messages are capped at 800 chars, not 300.

See RELEASE_NOTES.md for the full detail.

## v0.3.0 — 2026-07-17

### Added
- **New:** Podman platform + compose-stack awareness (list_pods, list_compose_stacks).
- **Undo executor**: `undo list` / `undo apply <id>` (CLI + MCP) — apply a recorded replayable inverse; the dispatched inverse is re-gated by its own risk tier; single-use, dry-run, double-confirm, both wrapper + inverse audited.

## Unreleased

### Added
- **Podman as a third platform** (alongside docker + portainer). A `podman` target
  connects over the rootful/rootless service socket — autodetected in the order
  `$XDG_RUNTIME_DIR/podman/podman.sock` (rootless), then `/run/podman/podman.sock`
  (rootful); an explicit `socket_path` always overrides. Podman speaks the
  **Docker-compatible** API at the root, so every container/image/volume/network/
  system read, all three flagship analyses (incl. restart-loop RCA), and every
  lifecycle + prune write are reused wholesale through the compat layer. A local
  Podman socket needs **no secret**.
- **`list_pods`** — Podman-only read over the libpod-native endpoint; lists pods
  with per-pod member-container status rollups. Teaching-errors on a docker /
  portainer target (pods do not exist there).
- **`list_compose_stacks`** — groups containers into Compose projects by the
  `com.docker.compose.project` label with a per-stack health rollup
  (healthy / degraded / down). Works on **docker and podman**.
- CLI: new `pod list` and `stack compose` commands; `init` and `doctor` now
  understand podman targets (doctor reports the compat API version + pod count).
- MCP tool count 34 → **36** (28 read, 8 write).

## v0.2.1 — 2026-07-16

### Fixed
- **`secrets.enc` now follows `CONTAINER_HOST_AIOPS_HOME`** (secretstore hardcoded the real
  home directory; config/audit/undo already relocated — found in live verification).
- **Audit fidelity**: failures sanitized into `{"error": ...}` results by the MCP error
  layer are now audited as `status=error` (they previously read as `ok`, hiding failed
  attempts from exception reports), and no undo is recorded for a call that failed.

### Tests
- `doctor` and the `init` wizard are now fully covered (previously ~10–20%); plus a
  regression test for the sanitized-failure audit status.

## v0.2.0 — 2026-07-13

Security-hardening release from a line-wide code review.

### Changed (behavior)
- **Secure by default**: with no `rules.yaml`, high/critical operations now require a
  named approver (`CONTAINER_HOST_AUDIT_APPROVED_BY`). A fresh install no longer allows
  destructive writes unattended; `init` seeds a starter `rules.yaml` you can edit,
  and an operator-authored rules file is honoured as-is.
- `__version__` is now single-sourced from package metadata (the previous release
  self-reported a stale version string).
- Sanitize docs no longer overstate scope: it strips control/format characters and
  truncates; semantic prompt-injection resistance must come from the consuming agent.

### Fixed
- Agent-supplied container/image/volume/stack ids are percent-encoded in Engine/Portainer URL paths (path-traversal hardening, 16 sites).
- `init` TLS verification prompt (Portainer) now defaults to ON.
- Governance docstrings no longer reference a sibling tool.

### Tests
- Governance persistence is now tested against REAL `audit.db`/`undo.db` files
  (write → audit row + inverse undo row with captured prior state).
- The CLI confirmed-write path (dry-run / double-confirm / governed execution) is
  covered end-to-end.
- `pytest-cov` added to the dev dependencies.

## v0.1.1

- Fix: `CONTAINER_HOST_AIOPS_HOME` now also relocates `config.yaml` (was hardcoded to `~/.container-host-aiops`).
- Fix: **CLI writes are now audited + undo-recorded** via the governance path — previously only the MCP tools recorded audit/undo; CLI `manage`/`remediate`/etc. writes now go through the same `@governed_tool` layer (they keep their dry-run + double-confirm). CLI write output is now the governed JSON result. No API/tool changes.


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
