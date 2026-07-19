"""Flagship signature analyses over container-host telemetry (pure analysis).

These are the differentiators — transparent heuristics, every flag reported with
its numbers so an operator can see *why* something was ranked, never a black-box
verdict:

  1. ``restart_loop_rca`` — find crash-looping containers (high restart count +
     exit code + a tail of logs) and map each to a likely cause + action.
  2. ``resource_pressure_analysis`` — containers near or over their CPU / memory
     limits (live stats vs configured HostConfig limits) with a recommendation.
  3. ``image_and_volume_bloat`` — dangling images + dangling volumes + build
     cache from system/df, totalled into prune candidates with reclaimable bytes.

All three are pure functions (no I/O): pass them the telemetry (from the reads in
the other ops modules, or injected) and they return the analysis. The live pulls
that feed them live under the ``pull_*`` helpers.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops import containers as cont
from container_host_aiops.ops import images as img
from container_host_aiops.ops import system as sysops
from container_host_aiops.ops import volumes as vol
from container_host_aiops.ops._util import human_bytes, short_id

MAX_ROWS = 100

# ── 1. restart-loop RCA ─────────────────────────────────────────────────────
DEFAULT_RESTART_THRESHOLD = 3
_LOOPING_STATES = {"restarting", "dead"}


def _classify_exit(exit_code: Any, oom_killed: bool) -> dict:
    """Map a container exit code (+ OOM flag) to a likely cause + action."""
    if oom_killed:
        return {
            "cause": "Out of memory — the kernel OOM-killed the container.",
            "action": "Raise the memory limit (update_container) or fix the leak; "
            "check memPercent in resource_pressure_analysis.",
        }
    try:
        code = int(exit_code)
    except (TypeError, ValueError):
        code = None
    mapping = {
        0: ("Clean exit but still restarting — likely a restart policy on a "
            "short-lived process.", "Check the restart policy and whether the "
            "process is meant to be long-running."),
        1: ("Application error (generic non-zero exit).", "Read the log tail; fix "
            "the app config/dependency it is failing on."),
        2: ("Application error / misuse (exit 2).", "Read the log tail; check "
            "command-line args and config."),
        125: ("Docker run itself failed (exit 125).", "Check the container's "
              "create options (mounts, ports, devices)."),
        126: ("Container command not executable (exit 126).", "Fix the entrypoint "
              "file permissions or shebang."),
        127: ("Container command not found (exit 127).", "Fix the entrypoint/CMD "
              "path — the binary is missing in the image."),
        137: ("Killed with SIGKILL (exit 137) — often OOM or a forced kill.",
              "Check memory limits and whether something is killing it."),
        139: ("Segmentation fault (exit 139 / SIGSEGV).", "The process crashed — "
              "check the app version / native deps."),
        143: ("Terminated with SIGTERM (exit 143) — a graceful stop.",
              "Usually external; confirm nothing is stopping it in a loop."),
    }
    cause, action = mapping.get(
        code, (f"Non-zero exit (code {code}).", "Read the log tail and address the error.")
    )
    return {"cause": cause, "action": action}


def restart_loop_rca(
    containers: list[dict],
    logs_by_id: dict[str, list[str]] | None = None,
    restart_threshold: int = DEFAULT_RESTART_THRESHOLD,
) -> dict:
    """[READ] Rank crash-looping containers and map each to a cause + action.

    Pure analysis over ``containers`` rows (from ``pull_restart_data`` or
    injected) — each {id, name, state, restartCount, exitCode, oomKilled, error}.
    A container is "looping" when its restart count is at/above ``restart_threshold``,
    its state is restarting/dead, or it exited non-zero. Ranks worst-first by
    restart count, attaches a likely cause + action, and a tail of logs when
    provided in ``logs_by_id``. Every ranking carries its numbers.
    """
    logs_by_id = logs_by_id or {}
    ranked: list[dict] = []
    for c in containers or []:
        restart_count = int(c.get("restartCount") or 0)
        exit_code = c.get("exitCode")
        oom = bool(c.get("oomKilled"))
        state = str(c.get("state") or "").lower()
        nonzero_exit = isinstance(exit_code, int) and exit_code != 0
        looping = (
            restart_count >= restart_threshold or state in _LOOPING_STATES or nonzero_exit or oom
        )
        if not looping:
            continue
        cid = short_id(c.get("id"))
        entry = {
            "id": cid,
            "name": c.get("name"),
            "state": state,
            "restartCount": restart_count,
            "exitCode": exit_code,
            "oomKilled": oom,
            "error": c.get("error") or "",
            "logsTail": (logs_by_id.get(str(c.get("id"))) or logs_by_id.get(cid) or [])[-20:],
        }
        entry.update(_classify_exit(exit_code, oom))
        ranked.append(entry)

    ranked.sort(key=lambda e: e["restartCount"], reverse=True)
    return {
        "containersEvaluated": len(containers or []),
        "loopingCount": len(ranked),
        "restartThreshold": restart_threshold,
        "looping": ranked[:MAX_ROWS],
        "note": (
            "Advisory read-only heuristic: 'looping' = restartCount >= threshold, "
            "or state restarting/dead, or a non-zero exit. Ranked by restart count."
        ),
    }


def pull_restart_data(conn: Any, tail: int = 20) -> tuple[list[dict], dict[str, list[str]]]:
    """[READ] Live restart rows + log tails for the flapping containers."""
    summary = cont.restart_summary(conn, all_states=True)
    rows = summary.get("containers", [])
    logs_by_id: dict[str, list[str]] = {}
    for r in rows:
        # A row whose id the Engine never reported is null now, not "" — it
        # cannot be fetched (the id would go down the wire as "None"), so skip.
        if r.get("id") is None:
            continue
        if int(r.get("restartCount") or 0) > 0 or (
            isinstance(r.get("exitCode"), int) and r["exitCode"] != 0
        ):
            try:
                logs_by_id[r["id"]] = cont.container_logs(conn, r["id"], tail=tail).get("lines", [])
            except Exception:  # noqa: BLE001 — log tail is advisory
                continue
    return rows, logs_by_id


# ── 2. resource-pressure analysis ───────────────────────────────────────────
DEFAULT_CPU_PCT = 80.0
DEFAULT_MEM_PCT = 80.0
_NEAR_FACTOR = 0.8  # "near" = at/above 80%% of the threshold


def _pressure_recommendation(
    cpu: float, mem: float, cpu_thr: float, mem_thr: float, mem_limited: bool
) -> dict:
    over_cpu = cpu >= cpu_thr
    over_mem = mem >= mem_thr
    if over_mem and not mem_limited:
        return {
            "cause": "High memory use with no memory limit set.",
            "action": "Set a memory limit (update_container) so a leak can't take "
            "the host down; investigate the working set.",
        }
    if over_cpu and over_mem:
        return {
            "cause": "Both CPU and memory near/over their limits.",
            "action": "Scale out or raise limits (update_container); profile the "
            "workload for a hot path.",
        }
    if over_mem:
        return {
            "cause": "Memory near/over its limit — OOM risk.",
            "action": "Raise the memory limit (update_container) or reduce the "
            "working set before it is OOM-killed.",
        }
    if over_cpu:
        return {
            "cause": "CPU near/over its limit — throttling likely.",
            "action": "Raise the CPU limit (update_container) or scale out; check "
            "for a busy loop.",
        }
    return {"cause": "Within thresholds.", "action": "No action needed."}


def resource_pressure_analysis(
    samples: list[dict],
    cpu_threshold: float = DEFAULT_CPU_PCT,
    mem_threshold: float = DEFAULT_MEM_PCT,
) -> dict:
    """[READ] Rank containers by CPU/memory pressure vs their limits.

    Pure analysis over ``samples`` (from ``pull_resource_pressure`` or injected) —
    each {id, name, cpuPercent, memPercent, memUsageBytes, memLimitBytes}. Flags
    each container "near" (>= 80%% of a threshold) or "over" (>= threshold) and
    attaches a recommendation. Ranks worst-first by the higher of CPU/mem pressure.
    """
    ranked: list[dict] = []
    for smp in samples or []:
        cpu = float(smp.get("cpuPercent") or 0.0)
        mem = float(smp.get("memPercent") or 0.0)
        mem_limit = int(smp.get("memLimitBytes") or 0)
        mem_limited = mem_limit > 0
        near = cpu >= cpu_threshold * _NEAR_FACTOR or mem >= mem_threshold * _NEAR_FACTOR
        over = cpu >= cpu_threshold or mem >= mem_threshold
        entry = {
            "id": short_id(smp.get("id")),
            "name": smp.get("name"),
            "cpuPercent": round(cpu, 2),
            "memPercent": round(mem, 2),
            "memUsageBytes": int(smp.get("memUsageBytes") or 0),
            "memLimitBytes": mem_limit,
            "memLimited": mem_limited,
            "near": near,
            "over": over,
            "_score": max(cpu, mem),
        }
        entry.update(
            _pressure_recommendation(cpu, mem, cpu_threshold, mem_threshold, mem_limited)
        )
        ranked.append(entry)

    ranked.sort(key=lambda e: e["_score"], reverse=True)
    for e in ranked:
        e.pop("_score", None)
    over_rows = [e for e in ranked if e["over"]]
    return {
        "containersEvaluated": len(ranked),
        "overThresholdCount": len(over_rows),
        "thresholds": {"cpuPct": cpu_threshold, "memPct": mem_threshold},
        "ranked": ranked[:MAX_ROWS],
        "note": (
            "Advisory read-only heuristic: 'near' >= 80%% of a threshold, 'over' "
            ">= the threshold; ranked by the higher of CPU%% / mem%%."
        ),
    }


def pull_resource_pressure(conn: Any) -> list[dict]:
    """[READ] Live CPU/mem samples for running containers (stats + limits)."""
    listing = cont.list_containers(conn, all_states=False)
    samples: list[dict] = []
    for c in listing.get("containers", []):
        try:
            samples.append(cont.container_stats(conn, c["id"]))
        except Exception:  # noqa: BLE001 — one bad container must not fail the pull
            continue
    return samples


# ── 3. image & volume bloat ─────────────────────────────────────────────────


def image_and_volume_bloat(
    dangling_images: dict,
    dangling_volumes: dict,
    df: dict | None = None,
) -> dict:
    """[READ] Total dangling images + volumes + build cache into prune candidates.

    Pure analysis over the three read payloads (from ``pull_bloat`` or injected):
    ``dangling_images`` / ``dangling_volumes`` (each {reclaimableBytes, ...}) and
    an optional ``system_df`` for build-cache reclaimable. Returns each candidate
    with its reclaimable bytes and a grand total.
    """
    df = df or {}
    img_bytes = int((dangling_images or {}).get("reclaimableBytes") or 0)
    vol_bytes = int((dangling_volumes or {}).get("reclaimableBytes") or 0)
    build_cache = df.get("buildCache") or {}
    cache_bytes = int(build_cache.get("totalBytes") or 0)

    candidates = [
        {
            "kind": "dangling-images",
            "count": int((dangling_images or {}).get("danglingCount") or 0),
            "reclaimableBytes": img_bytes,
            "reclaimableHuman": human_bytes(img_bytes),
            "action": "prune_images(dangling_only=True)",
        },
        {
            "kind": "dangling-volumes",
            "count": int((dangling_volumes or {}).get("danglingCount") or 0),
            "reclaimableBytes": vol_bytes,
            "reclaimableHuman": human_bytes(vol_bytes),
            "action": "prune_volumes()",
        },
        {
            "kind": "build-cache",
            "count": int(build_cache.get("count") or 0),
            "reclaimableBytes": cache_bytes,
            "reclaimableHuman": human_bytes(cache_bytes),
            "action": "docker builder prune (not automated here)",
        },
    ]
    candidates.sort(key=lambda c: c["reclaimableBytes"], reverse=True)
    total = img_bytes + vol_bytes + cache_bytes
    return {
        "totalReclaimableBytes": total,
        "totalReclaimableHuman": human_bytes(total),
        "candidates": candidates,
        "note": (
            "Advisory read-only heuristic: sums dangling images + dangling volumes "
            "+ build cache. Review candidates before pruning (prune is risk=high)."
        ),
    }


def pull_bloat(conn: Any) -> dict:
    """[READ] Live dangling images + volumes + df for image_and_volume_bloat."""
    return image_and_volume_bloat(
        img.dangling_images(conn),
        vol.dangling_volumes(conn),
        sysops.system_df(conn),
    )
