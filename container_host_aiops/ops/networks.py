"""Network-scoped reads over the Docker Engine API (read-only).

These reads answer "what Docker networks exist (bridge/host/overlay/…) and what
does one look like inspected (driver, subnet/gateway, attached containers)". All
host text is sanitized at the boundary.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops._util import clean, clean_list

_MAX_ROWS = 500


def list_networks(conn: Any) -> dict:
    """[READ] List Docker networks (name, driver, scope, id)."""
    rows = clean_list(conn.docker_get("/networks"))
    by_driver: dict[str, int] = {}
    compact: list[dict] = []
    for r in rows:
        driver = str(r.get("Driver") or "unknown")
        by_driver[driver] = by_driver.get(driver, 0) + 1
        compact.append({
            "id": str(r.get("Id", ""))[:12],
            "name": r.get("Name"),
            "driver": driver,
            "scope": r.get("Scope"),
            "internal": r.get("Internal"),
        })
    return {
        "total": len(rows),
        "byDriver": dict(sorted(by_driver.items(), key=lambda kv: kv[1], reverse=True)),
        "networks": compact[:_MAX_ROWS],
    }


def inspect_network(conn: Any, network_id: str) -> dict:
    """[READ] Inspect one network (driver, IPAM subnet/gateway, attached containers)."""
    info = clean(conn.docker_get(f"/networks/{network_id}"))
    ipam = (info.get("IPAM") or {}).get("Config") or []
    containers = info.get("Containers") or {}
    return {
        "id": str(info.get("Id", ""))[:12],
        "name": info.get("Name"),
        "driver": info.get("Driver"),
        "scope": info.get("Scope"),
        "internal": info.get("Internal"),
        "ipam": ipam,
        "attachedCount": len(containers) if isinstance(containers, dict) else 0,
        "containers": containers,
    }
