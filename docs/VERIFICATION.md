# Live verification — Docker / Portainer / Podman

`container-host-aiops` speaks to three platforms behind one server. Their verification
status is **not the same**, and this document keeps them honest:

| Platform | Status |
|----------|--------|
| **Docker Engine** | ✅ **Live-verified** against Docker Engine **27.5.1** (see §"Docker: already satisfied") |
| **Portainer** | ✅ **Live-verified** against Portainer **2.39.5** (see §"Portainer and Podman") |
| **Podman** (Docker-compat + libpod) | ✅ **Live-verified** against Podman **4.9.3** (see §"Portainer and Podman") |

It is deliberately checklist-shaped so results are reproducible and auditable — not a
subjective "seems fine".

## 🔴 Portainer and Podman (2026-08-03): two real bugs, one of them line-wide

The two platforms the Docker round never touched. Portainer **2.39.5** managing
the host's own Docker endpoint, and rootful Podman **4.9.3** over
`/run/podman/podman.sock`, both driven through the real governed CLI.

### Reads: correct on both, cross-checked against ground truth

Portainer proxies the Docker Engine API, and its answers matched `docker` on the
host exactly — server version 29.1.3, two running containers, five images.
Podman's `system info`, `container list`, `image list`, `volume list` and
`network list` all returned real data; `pod list` was re-run against a **real**
two-container pod rather than being accepted as an empty list.

### Bug 1 — the CLI exited 0 for a refused write

Asking Portainer to stop the Portainer container it proxies through is exactly
the self-lockout case the guard exists for, and the guard fired with a genuinely
useful message. **The CLI still exited 0.** It printed the governed twin's
`{"error": ...}` payload and returned success, so nothing reading the exit status
could distinguish a refusal from a completed write — a 404 on a nonexistent
container behaved the same way. The `--dry-run` path already exited 1, which made
it worse: the preview was stricter than the write it previews.

Every `manage` result now passes through `checked()`. Same defect class already
fixed in proxmox-, xcpng-, veeam- and truenas-aiops; this repo was never swept.

### Bug 2 — `undo apply` replayed against the wrong host (line-wide)

Stopping a Podman container and then running `undo apply` **without** naming a
target sent `start_container` to the *Portainer* target and 404'd. The undo
record carries the original call's target in `orig_params`; the replay never read
it, using whatever target the caller named — in practice the config's first
entry.

The 404 is the lucky case. Two hosts with a container named `web` — the common
case in any fleet — and the inverse **succeeds on the wrong machine**, silently.
All 24 copies of `undo_apply` across the line had the identical shape and none
consulted `orig_params`, so the fix went line-wide.

### The governed loop, closed on both platforms

- Portainer: `manage stop` → the host reports `exited` → `undo apply` →
  `start_container`, `effectVerified: true` → the host reports `running`. Audit
  rows for the write, the undo and the refused attempt (`error`).
- Podman: the same loop over the Docker-compat socket, and the undo now routes
  itself to the podman target.

### Lab recipe

Portainer needs its admin bootstrapped with the **`X-Setup-Token`** printed in
the container log (grep for `setup_token=`, not the Chisel fingerprint that
also looks like a token), then `POST /api/endpoints` with
`EndpointCreationType=1` for the local Docker socket, then an API key from
`POST /api/users/1/tokens`. Podman needs `systemctl enable --now podman.socket`;
the socket is root-owned, and a workstation reaches it with
`ssh -L /local.sock:/run/podman/podman.sock` — delete any stale local socket
path **before** starting the tunnel, not after.


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

- [x] ✅ `manage prune-images` for real — **done 2026-08-03, and comparing the
      preview against what actually happened found two defects** (both fixed):
      the preview promised 11.0 MiB where the prune freed 1.6 KiB, because it
      summed each image's total size including layers a still-tagged image holds;
      and one pruned image was counted as two, because Docker's response carries
      an entry per action (`Untagged` **and** `Deleted` for the same id).
      `prune-volumes` was closed the same way on 2026-08-04 (below).
- [x] ✅ `update_container` against a live container, then `undo apply` — **done
      2026-08-03**: `{"Memory":536870912}` applied to a running container (host
      confirmed 536870912), `priorState` captured the real prior 268435456, and
      `undo apply` restored it — confirmed on the host, not from the payload.
- [x] ✅ `remove_container --force` on a **running** container — **done
      2026-08-03**: it ran with no gate, the container was gone from the host,
      and `priorInspect` held the full pre-removal inspect. No undo token is
      recorded, which is correct — a removal has no inverse.
- [x] ✅ `manage prune-volumes` for real — **done 2026-08-04, and the same
      preview-vs-outcome comparison found a defect** (fixed): the preview
      promised **7 volumes / 7.1 MiB** where the prune then removed **4 volumes
      / 65.3 KiB**. Cause: since Docker 23.0 a default `POST /volumes/prune`
      removes only **anonymous** unused volumes, but the preview counted every
      unreferenced volume. The named unused volumes (`v_dangling1`,
      `v_dangling2`) survived while the tool reported success — an operator
      reclaiming space got ~0.9% of what was promised, and the bloat RCA
      recommended `prune_volumes()` for space it could not reclaim. Fixed by
      giving preview and prune a shared `all_unused` flag (mirroring
      `docker volume prune -a`, defaulting to Docker's safer default) and
      reporting the named-but-unused space separately as `alsoUnusedNamed*`.
      Anonymous volumes are identified by Docker's own
      `com.docker.volume.anonymous` label, not by the 64-hex name shape.
      **Re-verified live, preview against outcome, word for word**: default
      preview 1 volume / 0 B → prune removed 1 / 0 B; `--all` preview
      7,340,032 B → prune reclaimed exactly 7,340,032 B, with the referenced
      volume left untouched. Two unit tests had encoded the defect as the spec
      (a *named* unused volume asserted to be a default-prune candidate) and
      were corrected.
- [x] ✅ `system_events` on a busy host — **done 2026-08-04**. Counts match the
      Engine API exactly (256 = 256 over an identical window; an earlier
      mismatch was my own sloppier `--since 300s --until 0s` ground truth, not a
      tool defect). **What the run did surface**: Docker's event buffer is
      bounded and in-memory, so asking for 300s and for 7200s returned the
      *identical* 228 events — while `truncated` stayed false, since this tool's
      own 500-row limit had cut nothing. A caller would read that as full
      coverage of the requested window. The response now also carries
      `requestedFromTime`, `oldestEventTime` and `coveredSeconds`, so a 7200s
      request answered by 51 seconds of events is visible. The two cases (idle
      host vs evicted buffer) genuinely cannot be told apart from here, so both
      bounds are reported rather than one guessed verdict.
- [x] ✅ The runaway budget guard on a tight poll loop against a real socket —
      **done 2026-08-04**: it tripped on exactly the 25th identical call
      (`CONTAINER_HOST_RUNAWAY_MAX` default) with an actionable message, and the
      stopped call was audited as `budget_exceeded` rather than as a success.
      **Scope note:** the guard is per-process by design (its threat model is an
      agent stuck looping inside one session), so a shell loop that spawns a
      fresh CLI process per iteration does not trip it — 30 consecutive CLI
      invocations ran without tripping. That is the documented behaviour, not a
      defect, but worth knowing before relying on it as a rate limit.

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
