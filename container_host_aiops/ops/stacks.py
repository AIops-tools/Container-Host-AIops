"""Portainer stack + endpoint reads (read-only).

Portainer adds multi-host and stack (Compose/Swarm) management on top of Docker.
These reads answer "what endpoints (managed hosts) does this Portainer know, what
stacks are deployed, and what does one stack look like". They hit the Portainer
management API directly (``/api/...``), not the proxied Docker API, so they
require a ``portainer`` target. All host text is sanitized at the boundary.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.config import PORTAINER
from container_host_aiops.ops._util import clean, clean_list

_MAX_ROWS = 500


def _require_portainer(conn: Any, tool: str) -> None:
    target = getattr(conn, "target", None)
    platform = getattr(target, "platform", None)
    if platform is not None and platform != PORTAINER:
        raise ValueError(
            f"'{tool}' requires a portainer target, but '{getattr(target, 'name', '?')}' "
            f"is a {platform} target. Stacks/endpoints are a Portainer feature."
        )


def list_endpoints(conn: Any) -> dict:
    """[READ] Portainer endpoints (managed hosts): id, name, type, status, url."""
    _require_portainer(conn, "list_endpoints")
    rows = clean_list(conn.get("/api/endpoints"))
    compact = [
        {
            "id": e.get("Id"),
            "name": e.get("Name"),
            "type": e.get("Type"),
            "status": e.get("Status"),
            "url": e.get("URL"),
            "groupId": e.get("GroupId"),
        }
        for e in rows
    ]
    return {"total": len(rows), "endpoints": compact[:_MAX_ROWS]}


def list_stacks(conn: Any) -> dict:
    """[READ] Portainer stacks (Compose/Swarm): id, name, type, endpoint, status."""
    _require_portainer(conn, "list_stacks")
    rows = clean_list(conn.get("/api/stacks"))
    compact = [
        {
            "id": s.get("Id"),
            "name": s.get("Name"),
            "type": s.get("Type"),
            "endpointId": s.get("EndpointId"),
            "status": s.get("Status"),
            "entryPoint": s.get("EntryPoint"),
        }
        for s in rows
    ]
    return {"total": len(rows), "stacks": compact[:_MAX_ROWS]}


def stack_detail(conn: Any, stack_id: str) -> dict:
    """[READ] One Portainer stack in detail (env, entrypoint, resource control)."""
    _require_portainer(conn, "stack_detail")
    return clean(conn.get(f"/api/stacks/{stack_id}"))
