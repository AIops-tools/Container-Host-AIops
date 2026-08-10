# Changelog

## v0.10.0 — 2026-08-10

### Fixed
- **An undetermined outcome no longer exits as a plain failure.** A write whose response was lost carries *both* `error` and `outcomeUnknown`, and the harness deliberately judges unknown first when writing the audit row — the change may have taken effect, so a blind retry could apply it twice. The CLI guard judged `error` first, so the audit said "may have taken effect" while the exit status told a script it had not happened. The two layers now agree (exit 2, not 1), and a test pins the ordering so it cannot silently flip back.
- **The CLI reported a refused or failed governed write as a success.** 1 write call site (`undo apply`) printed the governed twin's payload and exited **0** whatever it said — and `@tool_errors` flattens every refusal, guard rejection and upstream failure into `{"error": ...}` rather than raising, so nothing downstream of a `&&` chain or a CI step could tell a blocked write from a landed one. The dry-run path already exited non-zero, which made the asymmetry worse: the preview was stricter than the write it previews. Results now route through a `checked()` helper — exit 1 on an error payload, exit 2 on an undetermined outcome, unchanged on success. This defect class had been fixed repo-by-repo several times and kept coming back; an audit across the whole line found it live in **18 of the 24 tools at once (87 call sites)**, so each tool now carries an invariant test that fails if any future CLI command prints a governed result without checking it.

## v0.9.0 — 2026-08-10

### Fixed
- **`prune_volumes`'s preview described a different call than the one it previews.** Since Docker 23.0 a default `POST /volumes/prune` removes only **anonymous** unused volumes, but the preview counted every unreferenced volume: on a real host it promised **7 volumes / 7.1 MiB** where the prune then removed **4 / 65.3 KiB**, leaving the named volumes in place while reporting success — so an operator reclaiming disk got ~0.9% of what was advertised. The preview is now scoped by the same flag as the call, and the named-but-unused space it will not touch is reported separately (`alsoUnusedNamedCount` / `alsoUnusedNamedBytes`) instead of being folded into the promise. The `image_and_volume_bloat` RCA no longer credits a default `prune_volumes()` with space only `all_unused=True` can reclaim. Two unit tests had encoded the defect as the spec and were corrected.
- **`system_events` no longer reads as full coverage of a window it cannot cover.** Docker's event buffer is bounded and in-memory, so on a busy host `--since 300` and `--since 7200` return the identical events while `truncated` stays false (this tool's own row limit cut nothing). The response now carries `requestedFromTime`, `oldestEventTime` and `coveredSeconds`, making a 7200-second request answered by 51 seconds of events visible. Idle host and evicted buffer cannot be distinguished from here, so both bounds are reported rather than one guessed verdict.

### Added
- **`prune_volumes(all_unused=True)` / `manage prune-volumes --all`** — mirrors `docker volume prune -a` to also remove NAMED unused volumes, matching the existing `prune-images --all` shape. The default stays Docker's safer anonymous-only behaviour.
- `dangling_volumes` now reports the anonymous/named split (`anonymousCount`, `anonymousReclaimableBytes`, `namedCount`, `namedReclaimableBytes`) and a per-row `anonymous` flag taken from Docker's own `com.docker.volume.anonymous` label rather than a name-shape guess, plus the standard truncation envelope (`returned`/`limit`/`truncated`).

## v0.8.0 — 2026-08-03

### Fixed
- **The image-prune preview no longer promises space it cannot free.** `reclaimableBytes` summed each dangling image's total `Size`, which includes the base layers a still-tagged image holds too — on a real Docker 29.1.3 the preview offered 11.0 MiB where the prune freed 1.6 KiB. It now subtracts `SharedSize`, read from an **unfiltered** listing (Docker computes sharing against the images it returns, so a dangling-only listing reports `SharedSize: 0` for everything and the subtraction would do nothing), and the result is labelled `reclaimableIsUpperBound` — layers still held by a container or the build cache survive the prune, so the exact figure is only known afterwards from `spaceReclaimedBytes`.
- **One pruned image is reported as one.** Docker's prune response carries an entry per *action*, so removing a single image yields both `Untagged` and `Deleted` for the same id and `deletedCount` said 2.
- **The CLI exited 0 for a refused or failed write.** `manage` printed the governed twin's `{"error": ...}` payload and returned success, so nothing reading the exit status could tell a refusal from a completed write — while the `--dry-run` path already exited 1, making the preview stricter than the write it previews. Every `manage` result now goes through `checked()`: error → exit 1, undetermined → exit 2. Caught live against a real Portainer 2.39.5 by asking it to stop the Portainer container it proxies through (the self-lockout guard refused correctly; the exit code said otherwise). Same class already fixed in proxmox-, xcpng-, veeam- and truenas-aiops.
- **`undo apply` replays against the target the original write ran on.** It dispatched the inverse against whatever target the *caller* named — in practice the config's first entry — while the write's own target sat unused in the undo record. On a multi-target config the inverse therefore ran against the wrong host; it only looks harmless because the resource usually is not there, but two hosts holding the same name and the inverse **succeeds on the wrong one, silently**. An explicitly named target still wins. Line-wide: all 24 copies had the identical defect. Caught live in container-host-aiops, where a stop recorded against a Podman target replayed against a Portainer one.

## v0.7.0 — 2026-08-02

### Changed (BREAKING)
- **Requires MCP SDK 2.0** (`mcp[cli]>=2.0,<3.0`). `mcp.server.fastmcp` no longer exists in 2.0; the server is now built with `MCPServer` and reports its package version in the stdio handshake.

### Fixed
- **`undo apply` works from the CLI.** Every write tool is imported lazily inside its own CLI command, so a CLI-driven undo ran in a process where the inverse tool was never registered and failed with "inverse tool is not registered" — for every write tool. Only the MCP entry point, which imports the whole server, worked. Found while live-verifying against a real cluster.
- **An undetermined outcome is audited `unknown`, not `ok`.** The harness only classified a result as undetermined when the payload *also* carried an `error` key, so a write that looked successful but had not been confirmed was recorded as a success.


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

## v0.7.0 — 2026-08-02

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
