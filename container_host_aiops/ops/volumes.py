"""Volume-scoped reads over the Docker Engine API (read-only).

These reads answer "what named volumes exist, what does one look like inspected,
and which volumes are dangling (unreferenced by any container — prune candidates)".
All host text is sanitized at the boundary.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops._util import _seg, clean, clean_list, human_bytes

_MAX_ROWS = 500


def _num(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def list_volumes(conn: Any) -> dict:
    """[READ] List named volumes (name, driver, mountpoint, scope)."""
    data = clean(conn.docker_get("/volumes"))
    rows = clean_list(data.get("Volumes") if isinstance(data, dict) else data)
    compact = [
        {
            "name": v.get("Name"),
            "driver": v.get("Driver"),
            "mountpoint": v.get("Mountpoint"),
            "scope": v.get("Scope"),
            "labels": v.get("Labels"),
        }
        for v in rows
    ]
    return {"total": len(rows), "volumes": compact[:_MAX_ROWS]}


def inspect_volume(conn: Any, name: str) -> dict:
    """[READ] Inspect one named volume (driver, mountpoint, options, usage)."""
    return clean(conn.docker_get(f"/volumes/{_seg(name)}"))


def dangling_volumes(conn: Any) -> dict:
    """[READ] Dangling volumes — unreferenced by any container (prune candidates).

    Reads ``/system/df`` for the per-volume ref-count and size, then lists those
    with zero references and totals the reclaimable bytes.
    """
    df = clean(conn.docker_get("/system/df"))
    volumes = df.get("Volumes") or []
    dangling = []
    reclaimable = 0
    for v in volumes:
        usage = v.get("UsageData") or {}
        ref_count = _num(usage.get("RefCount"))
        size = _num(usage.get("Size"))
        if ref_count == 0:
            reclaimable += max(0, size)
            dangling.append({
                "name": v.get("Name"),
                "sizeBytes": max(0, size),
                "sizeHuman": human_bytes(max(0, size)),
            })
    return {
        "danglingCount": len(dangling),
        "reclaimableBytes": reclaimable,
        "reclaimableHuman": human_bytes(reclaimable),
        "volumes": dangling[:_MAX_ROWS],
    }
