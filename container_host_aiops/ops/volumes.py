"""Volume-scoped reads over the Docker Engine API (read-only).

These reads answer "what named volumes exist, what does one look like inspected,
and which volumes are dangling (unreferenced by any container — prune candidates)".
All host text is sanitized at the boundary.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops._util import _seg, clean, clean_list, human_bytes

_MAX_ROWS = 500

# Docker's own marker for a volume it created implicitly for a container
# (`-v /path` with no name). A default `POST /volumes/prune` removes ONLY these;
# named unused volumes need the `all` filter. Detected by label rather than by
# the 64-hex name shape, because the label is what the daemon itself goes by.
ANONYMOUS_LABEL = "com.docker.volume.anonymous"


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

    **Anonymous vs named matters for what a prune actually removes.** Since
    Docker 23.0 ``POST /volumes/prune`` removes only *anonymous* unused volumes
    unless the ``all`` filter is set — so a total over every unreferenced volume
    is NOT what a default prune will reclaim. Each row therefore carries
    ``anonymous`` (Docker's own ``com.docker.volume.anonymous`` label, not a
    name-shape guess), and the totals are split into the anonymous subset and
    the whole set so neither figure has to be inferred.
    """
    df = clean(conn.docker_get("/system/df"))
    volumes = df.get("Volumes") or []
    dangling = []
    reclaimable = 0
    anon_reclaimable = 0
    anon_count = 0
    for v in volumes:
        usage = v.get("UsageData") or {}
        ref_count = _num(usage.get("RefCount"))
        size = max(0, _num(usage.get("Size")))
        if ref_count == 0:
            is_anon = ANONYMOUS_LABEL in (v.get("Labels") or {})
            reclaimable += size
            if is_anon:
                anon_count += 1
                anon_reclaimable += size
            dangling.append({
                "name": v.get("Name"),
                "sizeBytes": size,
                "sizeHuman": human_bytes(size),
                "anonymous": is_anon,
            })
    kept = dangling[:_MAX_ROWS]
    return {
        "danglingCount": len(dangling),
        "reclaimableBytes": reclaimable,
        "reclaimableHuman": human_bytes(reclaimable),
        "anonymousCount": anon_count,
        "anonymousReclaimableBytes": anon_reclaimable,
        "anonymousReclaimableHuman": human_bytes(anon_reclaimable),
        "namedCount": len(dangling) - anon_count,
        "namedReclaimableBytes": reclaimable - anon_reclaimable,
        "volumes": kept,
        "returned": len(kept),
        "limit": _MAX_ROWS,
        "truncated": len(dangling) > _MAX_ROWS,
    }
