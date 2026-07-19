"""Container-scoped reads over the Docker Engine API (read-only).

Containers are the core object. These reads answer "what containers exist (all or
just running), what does one look like inspected, what is it logging, how much
CPU/memory is it using right now, what processes are inside it, and which ones
keep restarting or exited non-zero". All host text is sanitized at the boundary.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops import _metrics
from container_host_aiops.ops._util import _seg, clean, clean_list, container_name, short_id

_MAX_ROWS = 500


def list_containers(conn: Any, all_states: bool = True) -> dict:
    """[READ] List containers (all states by default, or only running).

    Buckets by state (running/exited/created/paused/…) and returns compact rows.
    """
    params = {"all": "true" if all_states else "false"}
    rows = clean_list(conn.docker_get("/containers/json", params=params))
    by_state: dict[str, int] = {}
    compact: list[dict] = []
    for r in rows:
        state = str(r.get("State") or "unknown").lower()
        by_state[state] = by_state.get(state, 0) + 1
        compact.append({
            "id": short_id(r.get("Id")),
            "name": container_name(r),
            "image": r.get("Image"),
            "state": state,
            "status": r.get("Status"),
            "ports": r.get("Ports"),
        })
    return {
        "total": len(rows),
        "allStates": all_states,
        "byState": dict(sorted(by_state.items(), key=lambda kv: kv[1], reverse=True)),
        "containers": compact[:_MAX_ROWS],
    }


def inspect_container(conn: Any, container_id: str) -> dict:
    """[READ] Full inspect of one container (id/name, config, state, mounts, network)."""
    return clean(conn.docker_get(f"/containers/{_seg(container_id)}/json"))


def container_logs(conn: Any, container_id: str, tail: int = 100) -> dict:
    """[READ] Tail the last ``tail`` log lines of a container (stdout + stderr).

    Docker returns a multiplexed byte stream for non-TTY containers (each frame
    prefixed by an 8-byte header); this demultiplexes best-effort into text.

    Returns a truncation envelope::

        {"lines": [...], "returned": 100, "limit": 100, "truncated": true, ...}

    Container logs are the single most likely read to be cut off — the tail
    window is almost always smaller than the container's history — and a bare
    list cannot say "there is more". The consumer would have to infer it from
    the length happening to equal the limit, and a smaller local model faced
    with a long result tends to report that nothing came back at all. One extra
    line is requested from Docker so ``truncated`` is *measured* rather than
    guessed from a length coincidence.
    """
    tail = max(1, min(int(tail), 2000))
    raw = conn.docker_get_raw(
        f"/containers/{_seg(container_id)}/logs",
        # tail + 1: if Docker can give us one more line than asked for, there is
        # older history beyond the window and the read is genuinely truncated.
        params={"stdout": "true", "stderr": "true", "tail": str(tail + 1),
                "timestamps": "false"},
    )
    text = _demux_stream(raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode())
    lines = [ln for ln in text.splitlines() if ln.strip()]
    truncated = len(lines) > tail
    kept = lines[-tail:]
    return {
        "id": short_id(container_id),
        "tail": tail,
        "lines": [_clip(ln) for ln in kept],
        "returned": len(kept),
        "limit": tail,
        "truncated": truncated,
    }


def container_stats(conn: Any, container_id: str) -> dict:
    """[READ] One-shot CPU%%/memory%% snapshot for a container (stream=false).

    Percentages are computed from Docker's raw counters with the same formula
    ``docker stats`` uses, so the numbers are explainable.
    """
    stats = clean(
        conn.docker_get(f"/containers/{_seg(container_id)}/stats", params={"stream": "false"})
    )
    used, limit = _metrics.mem_usage_and_limit(stats)
    return {
        "id": short_id(container_id),
        "name": container_name(stats),
        "cpuPercent": _metrics.cpu_percent(stats),
        "memUsageBytes": int(used),
        "memLimitBytes": int(limit),
        "memPercent": _metrics.mem_percent(stats),
    }


def container_top(conn: Any, container_id: str) -> dict:
    """[READ] Processes running inside a container (like ``docker top``)."""
    data = clean(conn.docker_get(f"/containers/{_seg(container_id)}/top"))
    titles = data.get("Titles") or []
    processes = data.get("Processes") or []
    return {
        "id": short_id(container_id),
        "titles": titles,
        "processCount": len(processes),
        "processes": processes[:_MAX_ROWS],
    }


def restart_summary(conn: Any, all_states: bool = True) -> dict:
    """[READ] Restart-count and exit-code summary across containers.

    Inspects each container to read ``State.RestartCount`` and ``State.ExitCode``
    (the list endpoint omits them) and returns rows worst-first by restart count.
    """
    params = {"all": "true" if all_states else "false"}
    listing = clean_list(conn.docker_get("/containers/json", params=params))
    rows: list[dict] = []
    for c in listing:
        cid = c.get("Id")
        try:
            info = clean(conn.docker_get(f"/containers/{_seg(cid)}/json"))
        except Exception:  # noqa: BLE001 — one bad container must not fail the summary
            continue
        state = info.get("State") or {}
        rows.append({
            "id": short_id(cid),
            "name": container_name(info),
            "state": str(state.get("Status") or "").lower(),
            "restartCount": int(state.get("RestartCount") or 0),
            "exitCode": state.get("ExitCode"),
            "oomKilled": bool(state.get("OOMKilled")),
            "error": state.get("Error") or "",
        })
    rows.sort(key=lambda r: r["restartCount"], reverse=True)
    flapping = [r for r in rows if r["restartCount"] > 0]
    return {
        "total": len(rows),
        "withRestarts": len(flapping),
        "containers": rows[:_MAX_ROWS],
    }


# ── helpers ──────────────────────────────────────────────────────────────────

_MAX_LINE = 2000


def _clip(line: str) -> str:
    return line if len(line) <= _MAX_LINE else line[:_MAX_LINE] + "…"


def _demux_stream(raw: bytes) -> str:
    """Best-effort demultiplex of a Docker log byte stream into text.

    Non-TTY logs frame each chunk as ``[stream(1) 0 0 0 size(4 BE)] payload``.
    TTY logs are raw. Detect the framing heuristically; fall back to a lenient
    UTF-8 decode when the bytes do not look framed.
    """
    if not raw:
        return ""
    out: list[str] = []
    i = 0
    n = len(raw)
    framed = False
    while i + 8 <= n:
        stream_type = raw[i]
        if stream_type not in (0, 1, 2) or raw[i + 1] != 0 or raw[i + 2] != 0 or raw[i + 3] != 0:
            break
        size = int.from_bytes(raw[i + 4 : i + 8], "big")
        if size < 0 or i + 8 + size > n:
            break
        payload = raw[i + 8 : i + 8 + size]
        out.append(payload.decode("utf-8", "replace"))
        i += 8 + size
        framed = True
    if framed and i >= n:
        return "".join(out)
    return raw.decode("utf-8", "replace")
