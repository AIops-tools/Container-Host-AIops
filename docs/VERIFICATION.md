# Live verification — Docker / Portainer / Podman

`container-host-aiops` speaks to three platforms behind one server. Their verification
status is **not the same**, and this document keeps them honest:

| Platform | Status |
|----------|--------|
| **Docker Engine** | ✅ **Live-verified** against Docker Engine **27.5.1** (see §"Docker: already satisfied") |
| **Portainer** | ⬜ Mock-validated only — API paths modelled from the public API shape |
| **Podman** (Docker-compat + libpod) | ⬜ Mock-validated only |

It is deliberately checklist-shaped so results are reproducible and auditable — not a
subjective "seems fine".

## What the mock suite already guarantees (all platforms)

- Every module imports; the CLI builds; **all 38 MCP tools** carry the `@governed_tool`
  harness marker (`tests/test_smoke.py`, which also asserts the tool count and that
  `__version__` matches `pyproject.toml`).
- The three flagship analyses (`restart_loop_rca`, `resource_pressure_analysis`,
  `image_and_volume_bloat`) are unit-tested against synthetic telemetry: exit-code →
  cause mapping is exercised per code (137/143/139/127/…), thresholds fire where they
  should, findings cite the measured number, and partial/missing fields do not crash.
- The **platform registry** resolves each tool name to the correct Docker, Portainer,
  and Podman request shape (including the Portainer `/api/endpoints/{id}/docker/...`
  proxy and the libpod prefix for pods).
- Reversible writes record a faithful **inverse** undo descriptor built from a fetched
  before-state (`stop_container` → start; `update_container` → the *prior* limits), and
  write tools carry the right risk tier.
- Governance persistence is tested against a real on-disk SQLite audit DB: calls land as
  rows over both the MCP and CLI paths, failures record `status=error` and no undo, and a
  lost-response write records `status=unknown`. The harness authorizes nothing — there is
  no read-only, deny-rule, or approver gate to test.

What the mocks cannot guarantee: that the concrete API paths, field names, and error
shapes match a real daemon or server. Docker has now been checked against a real one;
Portainer and Podman have not.

## Docker: already satisfied

Run against a **live Docker Engine 27.5.1** daemon over the local socket
(`~/.docker/run/docker.sock`). What was actually exercised:

- [x] **Connectivity** — `container-host-aiops doctor` green against the real daemon
      (socket reachable, version query returned).
- [x] **Host reads** — `container-host-aiops overview` returned the real platform
      version and live container counts by state.
- [x] **restart-loop RCA** — run against the machine's genuinely crash-looping
      containers; the analysis found them and mapped the real exit codes to causes.
- [x] **image & volume bloat** — reported real reclaimable space (~2 GiB) matching the
      host's actual dangling images/volumes.
- [x] **A governed write end-to-end** — MCP `stop_container` actually stopped the
      container, wrote an audit row to `~/.container-host-aiops/audit.db`, and recorded
      a usable undo descriptor.

That is a real closed governance loop on the Docker path: connect → analyse → write →
audit → undo. It is **not** a claim about Portainer or Podman, and it did not cover
every Docker tool — the gaps below are still open on Docker too.

### Still open on Docker

- [ ] `manage prune-images` / `prune-volumes` for real (dry-run preview vs what actually
      gets removed, and the reclaimed bytes matching `system df` afterwards).
- [ ] `update_container` against a live container, then `undo apply` restoring the
      **prior** limits (the mocks prove the descriptor; a live run proves the replay).
- [ ] `remove_container --force` on a running container, confirming it runs (no gate)
      and lands an audit row tagged `risk_tier=review`.
- [ ] `system_events` streaming/paging behaviour on a busy host.
- [ ] The runaway budget guard tripping on a tight poll loop against a real socket.

## Prerequisites for the remaining platforms

Use a **throwaway host** with **throwaway containers** you are willing to stop, restart,
reconfigure, and delete. Never run this checklist against containers carrying data you
need — §"Reclaim disk" removes volumes irreversibly.

**Portainer** — run Portainer CE in a container against a test endpoint; create an API
token under *My account → Access tokens*, then:

```bash
uv tool install container-host-aiops
container-host-aiops init                  # stores the Portainer token encrypted
container-host-aiops secret set <target>   # or add one later
```

**Podman** — enable the service socket (`systemctl --user enable --now podman.socket`
for rootless, or the rootful equivalent). No secret is needed for a local socket.

Record the exact versions you tested (e.g. "Portainer CE 2.21", "Podman 5.3") — a tick is
only meaningful with the build it was ticked against.

## Verification checklist (Portainer / Podman)

### 1. Connectivity
- [ ] `container-host-aiops doctor` → green: config parsed, secret store unlocks (Portainer),
      and a real version query returns from the server.
- [ ] `container-host-aiops system version` / `system info` → match what the platform's
      own CLI/UI reports.

### 2. Reads return real, well-shaped data
- [ ] `container-host-aiops container list` → the real containers with correct state;
      `--running` filters correctly.
- [ ] `container-host-aiops container inspect <id>` → exit code, restart policy, and
      resource limits match the platform's own inspect output.
- [ ] `container-host-aiops container logs <id> --tail 200` → real log lines, correct count.
- [ ] `container-host-aiops container stats <id>` / `container top <id>` → live numbers
      and real processes.
- [ ] `container-host-aiops image list` / `volume list` / `network list` → match the host.
- [ ] `container-host-aiops system df` → totals match the platform's own disk-usage report.
- [ ] **Portainer**: `stack endpoints`, `stack list`, `stack detail <id>`, `stack compose <id>`
      return the real endpoints/stacks and the actual compose source.
- [ ] **Podman**: `pod list` returns real pods via the libpod endpoint (this path has no
      Docker equivalent, so the mocks are weakest here).

### 3. The analyses are right, not just non-crashing
- [ ] Start a container that exits 137 (hit its memory limit) with `restart: always`;
      `analyze restart-loop` flags it and names OOM as the cause.
- [ ] Start one that exits 127 (bad entrypoint); the RCA names the entrypoint, not OOM.
- [ ] `analyze resource-pressure --cpu 50 --mem 50` against a deliberately loaded
      container → the measured percentage matches `container stats`.
- [ ] `analyze bloat` reclaimable bytes agree with `system df` and with a real prune.

### 4. A reversible write + its undo
- [ ] `container-host-aiops manage stop <id> --dry-run` → prints the call, container keeps
      running (confirm on the host).
- [ ] `container-host-aiops manage stop <id>` → it actually stops, the result carries an
      `_undo_id`, and a row lands in `~/.container-host-aiops/audit.db`.
- [ ] `container-host-aiops undo list` shows it; `undo apply <id>` starts it again.
- [ ] `container-host-aiops manage update <id> '{"Memory": 536870912}'` then `undo apply`
      → the **prior** memory limit is restored (proves the undo captured the real
      before-state rather than guessing a default).

### 5. Irreversible writes behave as declared
- [ ] `manage prune-images --dry-run` lists exactly what the real prune then removes,
      and the reclaimed bytes match.
- [ ] `manage prune-volumes` and `manage remove --force` record **no** undo and are
      tagged high risk in the audit row.
- [ ] **Portainer**: `manage recreate-stack <id> --dry-run` then for real → the stack is
      redeployed from its stored definition and the containers come back.

### 6. Audit is unbypassable — both entry points
- [ ] Run a write over MCP and the same write over the CLI; confirm **both** land a row
      in `audit.db`, and that `CONTAINER_HOST_AUDIT_APPROVED_BY` / `_RATIONALE`, when set,
      appear on the row (recorded, never required).
- [ ] A tight poll loop trips the runaway budget guard rather than hammering the socket.
- [ ] A failed call (nonexistent container id) is audited `status=error` with no undo.

### 7. Cleanup
- [ ] Restart everything you stopped, restore every limit you changed, remove the
      throwaway containers/images/volumes you created.
- [ ] `container-host-aiops overview` matches the baseline you captured before starting.
- [ ] Skim `~/.container-host-aiops/audit.db` — every write is there with the right tier.

## Criteria to consider a platform live-verified

For a given platform, all of the following must hold:

1. Every box in sections 1–7 is ticked against that platform, with the exact build
   recorded (e.g. "Portainer CE 2.21", "Podman 5.3").
2. Every API-path or field-shape mismatch found is **fixed and covered by a regression
   test**, so the mock suite would now catch it.
3. Section 4 (write + undo replay) passed — recording an undo descriptor is not the same
   as the undo actually working, and this line has shipped bad undo pairs before.
4. The run is written up in the release notes / product-line memory with the date and
   package version, matching how the line records its other live-verified tools.

Docker meets criterion 1 only for the subset listed under "Docker: already satisfied";
finish "Still open on Docker" before calling the Docker path fully covered.

## Notes for maintainers

- `container-host-aiops doctor` is the single fastest live entry point on every platform.
- Podman's **libpod-native** endpoints (pods) and Portainer's **endpoint-proxy** paths
  are where the two remaining platforms diverge most from Docker — weight the run there.
- Add each platform's result to the product-line verification ledger once green, so the
  central "verification debt" list stays accurate.
