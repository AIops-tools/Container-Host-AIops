"""Stack / compose reads (read-only).

Two flavours of "stack" live here:

  * **Portainer stacks** (``list_endpoints`` / ``list_stacks`` / ``stack_detail``)
    hit the Portainer management API directly (``/api/...``), not the proxied
    Docker API, so they require a ``portainer`` target.
  * **Compose stacks** (``list_compose_stacks``) reconstruct Compose projects from
    the ``com.docker.compose.project`` label that ``docker compose`` **and**
    ``podman compose`` both stamp on every container they create. It groups the
    running containers by that label over the Docker-compat layer, so it works on
    a ``docker`` *or* ``podman`` target with no Portainer required.

All host text is sanitized at the boundary.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.config import PORTAINER
from container_host_aiops.ops._util import _seg, clean, clean_list, container_name, short_id

_MAX_ROWS = 500

# Labels both docker-compose and podman-compose stamp on managed containers.
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


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
    return clean(conn.get(f"/api/stacks/{_seg(stack_id)}"))


def _stack_health(by_state: dict[str, int], total: int) -> str:
    """Roll a compose stack's per-state counts into one health verdict."""
    running = int(by_state.get("running", 0))
    if total == 0:
        return "empty"
    if running == total:
        return "healthy"
    if running == 0:
        return "down"
    return "degraded"


def list_compose_stacks(conn: Any) -> dict:
    """[READ] Group containers into Compose projects with a per-stack health rollup.

    Reconstructs ``docker compose`` / ``podman compose`` projects from the
    ``com.docker.compose.project`` label every managed container carries (works on
    a docker *or* podman target — the Docker-compat layer serves the labels).
    Each stack rolls its containers up by state into a health verdict:
    ``healthy`` (all running), ``degraded`` (some running), or ``down`` (none).
    Containers without the compose label are counted under ``ungrouped``.
    """
    rows = clean_list(conn.docker_get("/containers/json", params={"all": "true"}))
    stacks: dict[str, dict] = {}
    ungrouped = 0
    for r in rows:
        labels = r.get("Labels")
        project = labels.get(COMPOSE_PROJECT_LABEL) if isinstance(labels, dict) else None
        if not project:
            ungrouped += 1
            continue
        state = str(r.get("State") or "unknown").lower()
        entry = stacks.setdefault(
            project,
            {"project": project, "total": 0, "byState": {}, "_services": set(), "containers": []},
        )
        entry["total"] += 1
        entry["byState"][state] = entry["byState"].get(state, 0) + 1
        service = labels.get(COMPOSE_SERVICE_LABEL) if isinstance(labels, dict) else None
        if service:
            entry["_services"].add(str(service))
        if len(entry["containers"]) < _MAX_ROWS:
            entry["containers"].append({
                "id": short_id(r.get("Id")),
                "name": container_name(r),
                "service": service,
                "state": state,
                "status": r.get("Status"),
            })
    compact: list[dict] = []
    for entry in stacks.values():
        services = sorted(entry.pop("_services"))
        entry["services"] = services
        entry["serviceCount"] = len(services)
        entry["health"] = _stack_health(entry["byState"], entry["total"])
        entry["byState"] = dict(
            sorted(entry["byState"].items(), key=lambda kv: kv[1], reverse=True)
        )
        compact.append(entry)
    compact.sort(key=lambda e: e["project"])
    return {
        "totalStacks": len(compact),
        "ungroupedContainers": ungrouped,
        "stacks": compact[:_MAX_ROWS],
        "note": (
            "Advisory read-only rollup: groups containers by the "
            "'com.docker.compose.project' label (docker compose / podman compose). "
            "health = healthy (all running) / degraded (some) / down (none)."
        ),
    }
