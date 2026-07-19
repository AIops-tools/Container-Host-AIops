"""Host system reads over the Docker Engine API (read-only).

These reads answer "what is this daemon (version, kernel, container/image counts),
how is disk broken down across images/containers/volumes/build-cache, and what has
happened recently (events)". All host text is sanitized at the boundary.
"""

from __future__ import annotations

import json
from typing import Any

from container_host_aiops.ops._util import clean, clean_list, human_bytes

_MAX_ROWS = 500


def _num(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def system_info(conn: Any) -> dict:
    """[READ] Daemon info: container/image counts, driver, kernel, resources."""
    info = clean(conn.docker_get("/info"))
    return {
        "name": info.get("Name"),
        "serverVersion": info.get("ServerVersion"),
        "containers": info.get("Containers"),
        "containersRunning": info.get("ContainersRunning"),
        "containersPaused": info.get("ContainersPaused"),
        "containersStopped": info.get("ContainersStopped"),
        "images": info.get("Images"),
        "storageDriver": info.get("Driver"),
        "cgroupVersion": info.get("CgroupVersion"),
        "kernelVersion": info.get("KernelVersion"),
        "operatingSystem": info.get("OperatingSystem"),
        "architecture": info.get("Architecture"),
        "ncpu": info.get("NCPU"),
        "memTotalBytes": info.get("MemTotal"),
        "memTotalHuman": human_bytes(info.get("MemTotal")),
        "warnings": info.get("Warnings"),
    }


def system_version(conn: Any) -> dict:
    """[READ] Docker version details (API version, Go version, components)."""
    v = clean(conn.docker_get("/version"))
    return {
        "version": v.get("Version"),
        "apiVersion": v.get("ApiVersion"),
        "minApiVersion": v.get("MinAPIVersion"),
        "goVersion": v.get("GoVersion"),
        "os": v.get("Os"),
        "arch": v.get("Arch"),
        "kernelVersion": v.get("KernelVersion"),
        "components": [
            {"name": c.get("Name"), "version": c.get("Version")}
            for c in (v.get("Components") or [])
        ],
    }


def system_df(conn: Any) -> dict:
    """[READ] Disk-usage breakdown across images, containers, volumes, build cache."""
    df = clean(conn.docker_get("/system/df"))
    images = df.get("Images") or []
    containers = df.get("Containers") or []
    volumes = df.get("Volumes") or []
    build_cache = df.get("BuildCache") or []

    def _sum(items: list, key: str) -> int:
        return sum(_num(i.get(key)) for i in items)

    vol_size = sum(_num((v.get("UsageData") or {}).get("Size")) for v in volumes)
    layers = _num(df.get("LayersSize"))
    return {
        "images": {
            "count": len(images),
            "totalBytes": _sum(images, "Size"),
            "totalHuman": human_bytes(_sum(images, "Size")),
        },
        "containers": {
            "count": len(containers),
            "sizeRwBytes": _sum(containers, "SizeRw"),
            "sizeRwHuman": human_bytes(_sum(containers, "SizeRw")),
        },
        "volumes": {
            "count": len(volumes),
            "totalBytes": vol_size,
            "totalHuman": human_bytes(vol_size),
        },
        "buildCache": {
            "count": len(build_cache),
            "totalBytes": _sum(build_cache, "Size"),
            "totalHuman": human_bytes(_sum(build_cache, "Size")),
        },
        "layersSizeBytes": layers,
        "layersSizeHuman": human_bytes(layers),
    }


def recent_events(conn: Any, since: int = 3600, event_type: str | None = None) -> dict:
    """[READ] Recent daemon events over the last ``since`` seconds.

    Docker's ``/events`` streams; with an ``until`` bound it returns a finite
    newline-delimited JSON body of the events in the window. Parsed and rolled up
    by (type, action).
    """
    import time

    since = max(1, min(int(since), 86400))
    now = int(time.time())
    params: dict[str, Any] = {"since": str(now - since), "until": str(now)}
    if event_type:
        params["filters"] = json.dumps({"type": [event_type]})
    raw = conn.docker_get_raw("/events", params=params)
    events = _parse_ndjson(raw)
    rollup: dict[str, int] = {}
    compact: list[dict] = []
    for e in events:
        etype = str(e.get("Type") or e.get("status") or "unknown")
        action = str(e.get("Action") or "")
        key = f"{etype}:{action}" if action else etype
        rollup[key] = rollup.get(key, 0) + 1
        actor = e.get("Actor") or {}
        compact.append({
            "type": etype,
            "action": action,
            "id": str(e.get("id") or actor.get("ID") or "")[:12],
            "time": e.get("time"),
        })
    kept = compact[-_MAX_ROWS:]
    return {
        "windowSeconds": since,
        "total": len(events),
        "byTypeAction": dict(sorted(rollup.items(), key=lambda kv: kv[1], reverse=True)),
        "events": [_clean_event(x) for x in kept],
        "returned": len(kept),
        "limit": _MAX_ROWS,
        # Measured against the full parsed event stream, not guessed: when true,
        # only the most recent _MAX_ROWS events are in "events" — narrow the
        # window with a smaller "since" to see the rest.
        "truncated": len(compact) > _MAX_ROWS,
    }


def _clean_event(event: dict) -> dict:
    return clean_list([event])[0] if event else {}


def _parse_ndjson(raw: Any) -> list[dict]:
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8", "replace")
    else:
        text = str(raw or "")
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out
