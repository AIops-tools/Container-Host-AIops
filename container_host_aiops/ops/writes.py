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

``stop_container`` / ``remove_container`` additionally refuse to act on the
Portainer container a Portainer target speaks *through* — see ``SelfLockout``.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops import images as img
from container_host_aiops.ops import volumes as vol
from container_host_aiops.ops._metrics import host_cpu_limit, host_mem_limit_bytes
from container_host_aiops.ops._util import _seg, clean, container_name, human_bytes, short_id
from container_host_aiops.platform import PORTAINER

# Resource keys accepted by POST /containers/{id}/update.
_UPDATE_KEYS = (
    "Memory", "MemorySwap", "MemoryReservation", "NanoCpus",
    "CpuQuota", "CpuPeriod", "CpuShares", "CpusetCpus", "CpusetMems",
)


def _inspect_safe(conn: Any, container_id: str) -> dict:
    """Best-effort inspect for before-state capture (never raises)."""
    try:
        info = clean(conn.docker_get(f"/containers/{_seg(container_id)}/json"))
        return info if isinstance(info, dict) else {}
    except Exception:  # noqa: BLE001 — before-state is advisory for the audit trail
        return {}


# ── self-lockout guard (the Portainer control plane) ────────────────────────
#
# A Portainer target proxies EVERY request through the Portainer container
# itself (``/api/endpoints/{id}/docker/...``, see ``Platform.docker_prefix``),
# and that container is returned as an ordinary row in this tool's own
# ``list_containers``. Stopping it kills the API mid-request; the inverse
# ``start_container`` would then be dispatched through ``_get_connection`` to
# the very endpoint that just died, so the undo token sits in undo.db
# permanently unapplicable. ``remove_container`` has no undo at all.

# Images that ARE the Portainer control plane (repository path, tag stripped).
_PORTAINER_IMAGES = ("portainer/portainer-ce", "portainer/portainer-ee", "portainer/agent")


class SelfLockout(ValueError):  # noqa: N818 — teaching error, reads as a statement
    """Refused: the operation would destroy the API endpoint this tool speaks through."""


def _image_repo(ref: str) -> str:
    """Repository path of an image reference, tag and digest stripped.

    ``portainer/portainer-ce:2.19.4`` and ``docker.io/portainer/portainer-ce``
    both fold to a path ending in ``portainer/portainer-ce``. Only the final
    segment can carry a tag, so a registry port (``host:5000/repo``) survives.
    """
    head, sep, tail = ref.split("@", 1)[0].rpartition("/")
    return f"{head}{sep}{tail.split(':', 1)[0]}"


def _image_refs(info: dict) -> list[str]:
    """Image references on a container, from either an inspect or a list row."""
    refs: list[str] = []
    config = info.get("Config")
    if isinstance(config, dict) and config.get("Image"):
        refs.append(str(config["Image"]))
    if info.get("Image"):
        refs.append(str(info["Image"]))
    return refs


def _published_ports(info: dict) -> set[int]:
    """Host ports a container publishes, from either an inspect or a list row."""
    ports: set[int] = set()
    net = info.get("NetworkSettings")
    bindings = net.get("Ports") if isinstance(net, dict) else None
    if not isinstance(bindings, dict):
        host_cfg = info.get("HostConfig")
        bindings = host_cfg.get("PortBindings") if isinstance(host_cfg, dict) else None
    if isinstance(bindings, dict):
        for binds in bindings.values():
            for bind in binds or []:
                port = str(bind.get("HostPort") or "") if isinstance(bind, dict) else ""
                if port.isdigit():
                    ports.add(int(port))
    row_ports = info.get("Ports")  # list-row shape: [{"PublicPort": 9443, ...}]
    if isinstance(row_ports, list):
        for entry in row_ports:
            public = entry.get("PublicPort") if isinstance(entry, dict) else None
            if isinstance(public, int):
                ports.add(public)
    return ports


def _control_plane_reason(conn: Any, info: dict) -> str:
    """Why ``info`` is the Portainer container this connection speaks through, or "".

    FAILS OPEN — returns "" (meaning "not the control plane, proceed") whenever
    the answer cannot be established: a non-Portainer platform, a target that
    carries no port, or an empty inspect (the inspect call failed). An unknown
    container must never be assumed to be the API.

    The returned reason is deliberately BOUNDED — it names the known image that
    matched rather than echoing the container's (arbitrarily long) image ref, so
    the refusal message cannot be pushed past the 300-char error cap by a long
    registry path. The full inspect still reaches the audit trail.
    """
    target = getattr(conn, "target", None)
    if getattr(target, "platform", "") != PORTAINER or not isinstance(info, dict) or not info:
        return ""
    for ref in _image_refs(info):
        repo = _image_repo(ref)
        for known in _PORTAINER_IMAGES:
            if repo == known or repo.endswith(f"/{known}"):
                return f"it runs {known}"
    port = getattr(target, "port", 0)
    if port and port in _published_ports(info):
        return f"it publishes port {port}, this target's own port"
    return ""


def _refuse_self_lockout(conn: Any, container_id: str, info: dict, verb: str, cost: str) -> None:
    """Raise ``SelfLockout`` when ``container_id`` is this target's Portainer API.

    Keep ``cost`` short. ``mcp_server._shared._safe_error`` truncates a
    passed-through ValueError at ``_ERROR_MAX`` and the remedy sentence comes
    last, so an over-long ``cost`` truncates away the instruction the caller
    needs. These messages are held to 300 characters, well inside the current
    cap, so the tail survives even if the cap is lowered again;
    ``test_refusal_messages_survive_the_300_char_cap`` pins it.
    """
    reason = _control_plane_reason(conn, info)
    if not reason:
        return
    raise SelfLockout(
        f"Refusing to {verb} container '{container_id}': {reason} — this target proxies "
        f"every request through it. {cost} Manage Portainer from a 'docker' target on "
        f"the host's own socket."
    )


#: Refusal cost strings. Named once so the real write and its dry-run preview
#: quote IDENTICAL text — a preview that worded the refusal differently would
#: read as a different problem. Kept short so the remedy sentence survives the
#: error cap (see _refuse_self_lockout).
_STOP_COST = (
    "The stop kills the API mid-request, and the start_container undo would route "
    "through the same dead endpoint."
)
_REMOVE_COST = (
    "Removing it destroys this target's API for good, and a removed container has "
    "no undo at all."
)


def preview_stop_container(conn: Any, container_id: str) -> dict:
    """Guarded dry-run preview for :func:`stop_container` — reads only, changes nothing.

    Runs the SAME self-lockout check as the real stop, on the same fetched
    inspect and with the same fail-open semantics, so the preview can never
    promise a stop the real call would refuse — nor refuse one it would allow.
    A dry-run whose honest answer is "this would be refused" has to say so:
    otherwise the caller sees a green preview, then a refusal, and a smaller
    model reads that refusal as transient and retries.
    """
    _refuse_self_lockout(
        conn, container_id, _inspect_safe(conn, container_id), "stop", _STOP_COST
    )
    return {"container_id": container_id}


def preview_remove_container(
    conn: Any, container_id: str, force: bool = False, remove_volumes: bool = False
) -> dict:
    """Guarded dry-run preview for :func:`remove_container` — reads only.

    Same self-lockout check, same fetched inspect, same fail-open semantics as
    the real remove, so preview and write always agree on whether it is allowed.
    """
    _refuse_self_lockout(
        conn, container_id, _inspect_safe(conn, container_id), "remove", _REMOVE_COST
    )
    return {"container_id": container_id, "force": bool(force),
            "remove_volumes": bool(remove_volumes)}


def restart_container(conn: Any, container_id: str, timeout: int = 10) -> dict:
    """[WRITE] Restart a container, capturing its prior state. No meaningful inverse."""
    prior = _inspect_safe(conn, container_id)
    state = prior.get("State") or {}
    conn.docker_post(
        f"/containers/{_seg(container_id)}/restart", params={"t": str(max(0, int(timeout)))}
    )
    return {
        "action": "restart_container",
        "id": short_id(container_id),
        "name": container_name(prior),
        "priorState": {"running": state.get("Running"), "status": state.get("Status")},
    }


def stop_container(conn: Any, container_id: str, timeout: int = 10) -> dict:
    """[WRITE] Stop a running container. Inverse: start it.

    **Refuses to stop the Portainer container a Portainer target proxies
    through.** Stopping it kills the API mid-request, and the start_container
    undo would be dispatched through that same dead endpoint — an operation that
    destroys its own reversibility. Fails open: a non-Portainer target, or an
    inspect that did not come back, is never assumed to be the API.
    """
    prior = _inspect_safe(conn, container_id)
    _refuse_self_lockout(conn, container_id, prior, "stop", _STOP_COST)
    state = prior.get("State") or {}
    conn.docker_post(
        f"/containers/{_seg(container_id)}/stop", params={"t": str(max(0, int(timeout)))}
    )
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
    conn.docker_post(f"/containers/{_seg(container_id)}/start")
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

    **Refuses to remove the Portainer container a Portainer target proxies
    through** — it is the API, and unlike a stop there is no undo to fail later.
    Fails open exactly as ``stop_container`` does.
    """
    prior = _inspect_safe(conn, container_id)
    _refuse_self_lockout(conn, container_id, prior, "remove", _REMOVE_COST)
    conn.docker_delete(
        f"/containers/{_seg(container_id)}",
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
    conn.docker_post(f"/containers/{_seg(container_id)}/update", json=payload)
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
        prior = clean(conn.get(f"/api/stacks/{_seg(stack_id)}"))
    except Exception:  # noqa: BLE001 — before-state is advisory
        prior = {}
    eid = endpoint_id or prior.get("EndpointId")
    params = {"endpointId": str(eid)} if eid else None
    conn.put(f"/api/stacks/{_seg(stack_id)}/git/redeploy", params=params, json={})
    return {
        "action": "recreate_stack",
        "stackId": stack_id,
        "name": prior.get("Name"),
        "endpointId": eid,
        "priorStack": prior,
    }
