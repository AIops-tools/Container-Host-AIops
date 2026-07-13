"""Container-host writes (guarded).

Every state-changing operation that *can* be reversed reads the host's current
state **before** it changes anything, so the harness records a faithful undo /
audit trail (the before-state is fetched, never guessed):

  * ``stop_container`` ↔ ``start_container`` are inverses.
  * ``update_container`` captures the prior CPU/memory limits so undo restores them.
  * ``remove_container`` captures the full inspect JSON before deleting (for audit;
    there is no clean undo for a removed container).
  * ``prune_images`` / ``prune_volumes`` list what *would* be removed + the
    reclaimable bytes before doing it (the dry-run preview).
  * ``restart_container`` captures the prior running state for audit (a restart has
    no meaningful inverse).

These are the only writes in the tool; each is gated at the MCP layer by the
governance harness (risk tier + audit + undo) and at the CLI layer by dry-run +
double-confirm.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops import images as img
from container_host_aiops.ops import volumes as vol
from container_host_aiops.ops._metrics import host_cpu_limit, host_mem_limit_bytes
from container_host_aiops.ops._util import clean, container_name, human_bytes, short_id

# Resource keys accepted by POST /containers/{id}/update.
_UPDATE_KEYS = (
    "Memory", "MemorySwap", "MemoryReservation", "NanoCpus",
    "CpuQuota", "CpuPeriod", "CpuShares", "CpusetCpus", "CpusetMems",
)


def _inspect_safe(conn: Any, container_id: str) -> dict:
    """Best-effort inspect for before-state capture (never raises)."""
    try:
        info = clean(conn.docker_get(f"/containers/{container_id}/json"))
        return info if isinstance(info, dict) else {}
    except Exception:  # noqa: BLE001 — before-state is advisory for the audit trail
        return {}


def restart_container(conn: Any, container_id: str, timeout: int = 10) -> dict:
    """[WRITE] Restart a container, capturing its prior state. No meaningful inverse."""
    prior = _inspect_safe(conn, container_id)
    state = prior.get("State") or {}
    conn.docker_post(f"/containers/{container_id}/restart", params={"t": str(max(0, int(timeout)))})
    return {
        "action": "restart_container",
        "id": short_id(container_id),
        "name": container_name(prior),
        "priorState": {"running": state.get("Running"), "status": state.get("Status")},
    }


def stop_container(conn: Any, container_id: str, timeout: int = 10) -> dict:
    """[WRITE] Stop a running container. Inverse: start it."""
    prior = _inspect_safe(conn, container_id)
    state = prior.get("State") or {}
    conn.docker_post(f"/containers/{container_id}/stop", params={"t": str(max(0, int(timeout)))})
    return {
        "action": "stop_container",
        "id": short_id(container_id),
        "name": container_name(prior),
        "priorState": {"running": state.get("Running", True)},
    }


def start_container(conn: Any, container_id: str) -> dict:
    """[WRITE] Start a stopped container. Inverse: stop it."""
    prior = _inspect_safe(conn, container_id)
    state = prior.get("State") or {}
    conn.docker_post(f"/containers/{container_id}/start")
    return {
        "action": "start_container",
        "id": short_id(container_id),
        "name": container_name(prior),
        "priorState": {"running": state.get("Running", False)},
    }


def remove_container(
    conn: Any, container_id: str, force: bool = False, remove_volumes: bool = False
) -> dict:
    """[WRITE] Remove a container, capturing its full inspect JSON first. No undo.

    The complete inspect is captured before deletion so the audit trail records
    exactly what was removed (there is no clean inverse for a removed container).
    """
    prior = _inspect_safe(conn, container_id)
    conn.docker_delete(
        f"/containers/{container_id}",
        params={"force": "true" if force else "false", "v": "true" if remove_volumes else "false"},
    )
    return {
        "action": "remove_container",
        "id": short_id(container_id),
        "name": container_name(prior),
        "forced": bool(force),
        "removedVolumes": bool(remove_volumes),
        "priorInspect": prior,
    }


def preview_prune_images(conn: Any, dangling_only: bool = True) -> dict:
    """List images that a prune *would* remove + the reclaimable bytes (no change)."""
    dangling = img.dangling_images(conn)
    if dangling_only:
        return {
            "danglingOnly": True,
            "wouldRemoveCount": dangling.get("danglingCount"),
            "reclaimableBytes": dangling.get("reclaimableBytes"),
            "reclaimableHuman": dangling.get("reclaimableHuman"),
            "images": dangling.get("images"),
        }
    usage = img.image_disk_usage(conn)
    return {
        "danglingOnly": False,
        "reclaimableBytes": usage.get("reclaimableBytes"),
        "reclaimableHuman": usage.get("reclaimableHuman"),
        "note": "Non-dangling prune also removes images unused by any container.",
    }


def prune_images(conn: Any, dangling_only: bool = True) -> dict:
    """[WRITE] Prune images (dangling by default). No undo. High risk."""
    filters = '{"dangling":["true"]}' if dangling_only else '{"dangling":["false"]}'
    result = clean(conn.docker_post("/images/prune", params={"filters": filters}))
    deleted = result.get("ImagesDeleted") or []
    reclaimed = int(result.get("SpaceReclaimed") or 0)
    return {
        "action": "prune_images",
        "danglingOnly": dangling_only,
        "deletedCount": len(deleted),
        "spaceReclaimedBytes": reclaimed,
        "spaceReclaimedHuman": human_bytes(reclaimed),
        "deleted": deleted[:200],
    }


def preview_prune_volumes(conn: Any) -> dict:
    """List volumes that a prune *would* remove + the reclaimable bytes (no change)."""
    dangling = vol.dangling_volumes(conn)
    return {
        "wouldRemoveCount": dangling.get("danglingCount"),
        "reclaimableBytes": dangling.get("reclaimableBytes"),
        "reclaimableHuman": dangling.get("reclaimableHuman"),
        "volumes": dangling.get("volumes"),
    }


def prune_volumes(conn: Any) -> dict:
    """[WRITE] Prune unreferenced (dangling) volumes. No undo. High risk."""
    result = clean(conn.docker_post("/volumes/prune"))
    deleted = result.get("VolumesDeleted") or []
    reclaimed = int(result.get("SpaceReclaimed") or 0)
    return {
        "action": "prune_volumes",
        "deletedCount": len(deleted),
        "spaceReclaimedBytes": reclaimed,
        "spaceReclaimedHuman": human_bytes(reclaimed),
        "deleted": deleted[:200],
    }


def update_container(conn: Any, container_id: str, resources: dict) -> dict:
    """[WRITE] Update a container's resource limits, capturing prior limits.

    Reads the container's current HostConfig CPU/memory limits first so undo can
    restore them; then POSTs the (allow-listed) resource update.
    """
    payload = {k: v for k, v in (resources or {}).items() if k in _UPDATE_KEYS}
    prior_inspect = _inspect_safe(conn, container_id)
    prior_limits = {"Memory": host_mem_limit_bytes(prior_inspect)}
    prior_limits.update(host_cpu_limit(prior_inspect))
    prior = {k: prior_limits.get(k) for k in payload if k in prior_limits}
    conn.docker_post(f"/containers/{container_id}/update", json=payload)
    return {
        "action": "update_container",
        "id": short_id(container_id),
        "name": container_name(prior_inspect),
        "changed": payload,
        "priorState": prior,
    }


def recreate_stack(conn: Any, stack_id: str, endpoint_id: str | None = None) -> dict:
    """[WRITE] Redeploy (recreate) a Portainer stack, capturing the prior stack. No undo.

    Captures the stack's current definition for audit before asking Portainer to
    recreate it; there is no clean inverse for a redeploy.
    """
    try:
        prior = clean(conn.get(f"/api/stacks/{stack_id}"))
    except Exception:  # noqa: BLE001 — before-state is advisory
        prior = {}
    eid = endpoint_id or prior.get("EndpointId")
    params = {"endpointId": str(eid)} if eid else None
    conn.put(f"/api/stacks/{stack_id}/git/redeploy", params=params, json={})
    return {
        "action": "recreate_stack",
        "stackId": stack_id,
        "name": prior.get("Name"),
        "endpointId": eid,
        "priorStack": prior,
    }
