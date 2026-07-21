"""Container-host write MCP tools (guarded writes).

The only state-changing tools in the package. Every one is wrapped with the
governance harness (audit — over MCP and the CLI alike) and takes a ``dry_run``
preview. Reversible writes pass an ``undo=`` callback that turns the fetched
before-state into an inverse descriptor the harness records; irreversible ones
(remove, prune, recreate) record none.

Risk levels (a descriptive audit label, not a gate): remove_container /
prune_images / prune_volumes / recreate_stack = high (destructive /
irreversible); restart / stop / start / update_container = medium.
"""

from typing import Any, Optional

from container_host_aiops.governance import governed_tool
from container_host_aiops.ops import writes as ops
from mcp_server._shared import _get_connection, mcp, tool_errors

_SKILL = "container-host-aiops"


# ── undo descriptors (built from the fetched before-state) ──────────────────


def _is_preview(result: Any) -> bool:
    """True when ``result`` is a dry-run preview rather than a performed write.

    A preview changes nothing, so it must record NO undo. Without this check
    ``_stop_undo`` reads a preview's missing ``priorState`` as "it was running"
    (its permissive default) and registers a start_container inverse for a stop
    that never happened — ``undo_apply`` would then perform a REAL start,
    reversing an operation that never occurred. ``_update_undo`` escaped this
    only by accident, because it happens to require a field previews omit.
    """
    return isinstance(result, dict) and result.get("dryRun") is True


def _stop_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    if _is_preview(result):
        return None
    if not isinstance(result, dict) or not (result.get("priorState") or {}).get("running", True):
        return None
    return {
        "tool": "start_container",
        "params": {"container_id": params.get("container_id")},
        "skill": _SKILL,
        "note": "Inverse of stop_container: start the container again.",
    }


def _start_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    if _is_preview(result) or not isinstance(result, dict):
        return None
    return {
        "tool": "stop_container",
        "params": {"container_id": params.get("container_id")},
        "skill": _SKILL,
        "note": "Inverse of start_container: stop the container again.",
    }


def _update_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    if _is_preview(result) or not isinstance(result, dict) or not result.get("priorState"):
        return None
    return {
        "tool": "update_container",
        "params": {"container_id": params.get("container_id"), "resources": result["priorState"]},
        "skill": _SKILL,
        "note": "Inverse of update_container: restore the resource limits captured before.",
    }


# ── tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def restart_container(
    container_id: str, timeout: int = 10, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Restart a container (captures prior state for audit).

    A restart has no meaningful inverse, so no undo is recorded. Pass dry_run=True
    to preview.

    Args:
        container_id: Container id or name.
        timeout: Seconds to wait for graceful stop before killing (default 10).
        dry_run: If True, preview without restarting.
        target: Target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {"dryRun": True, "wouldRestart": {"container_id": container_id}}
    return ops.restart_container(conn, container_id, timeout)


@mcp.tool()
@governed_tool(risk_level="medium", undo=_stop_undo)
@tool_errors("dict")
def stop_container(
    container_id: str, timeout: int = 10, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Stop a running container. Inverse: start it.

    Captures whether it was running so the harness records a start undo. Pass
    dry_run=True to preview.

    Args:
        container_id: Container id or name.
        timeout: Seconds to wait for graceful stop before killing (default 10).
        dry_run: If True, preview without stopping.
        target: Target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        # The preview runs the self-lockout guard too: if the real stop would be
        # refused, the dry-run must say so rather than report wouldStop.
        return {"dryRun": True, "wouldStop": ops.preview_stop_container(conn, container_id)}
    return ops.stop_container(conn, container_id, timeout)


@mcp.tool()
@governed_tool(risk_level="medium", undo=_start_undo)
@tool_errors("dict")
def start_container(
    container_id: str, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Start a stopped container. Inverse: stop it.

    Pass dry_run=True to preview.

    Args:
        container_id: Container id or name.
        dry_run: If True, preview without starting.
        target: Target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {"dryRun": True, "wouldStart": {"container_id": container_id}}
    return ops.start_container(conn, container_id)


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def remove_container(
    container_id: str,
    force: bool = False,
    remove_volumes: bool = False,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=high] Remove a container (captures full inspect first). No undo.

    The complete inspect JSON is captured before deletion for the audit trail;
    there is no clean inverse for a removed container. Pass dry_run=True to preview.

    Args:
        container_id: Container id or name.
        force: Force-remove a running container (SIGKILL).
        remove_volumes: Also remove anonymous volumes attached to it.
        dry_run: If True, preview without removing.
        target: Target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        # The preview runs the self-lockout guard too: if the real remove would
        # be refused, the dry-run must say so rather than report wouldRemove.
        return {
            "dryRun": True,
            "wouldRemove": ops.preview_remove_container(
                conn, container_id, force, remove_volumes
            ),
        }
    return ops.remove_container(conn, container_id, force, remove_volumes)


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def prune_images(
    dangling_only: bool = True, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=high] Prune images (dangling by default). No undo.

    dry_run LISTS the images that would be removed and the reclaimable bytes
    before doing anything.

    Args:
        dangling_only: True (default) prunes only untagged images; False also
            prunes images unused by any container.
        dry_run: If True, list what would be removed + reclaimable bytes.
        target: Target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        preview = ops.preview_prune_images(conn, dangling_only)
        return {"dryRun": True, **preview}
    return ops.prune_images(conn, dangling_only)


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def prune_volumes(dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE][risk=high] Prune unreferenced (dangling) volumes. No undo.

    dry_run LISTS the volumes that would be removed and the reclaimable bytes
    before doing anything.

    Args:
        dry_run: If True, list what would be removed + reclaimable bytes.
        target: Target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        preview = ops.preview_prune_volumes(conn)
        return {"dryRun": True, **preview}
    return ops.prune_volumes(conn)


@mcp.tool()
@governed_tool(risk_level="medium", undo=_update_undo)
@tool_errors("dict")
def update_container(
    container_id: str,
    resources: dict[str, Any],
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Update a container's resource limits, capturing prior limits.

    Captures the current CPU/memory HostConfig limits before the change so the
    harness records an undo (restore the prior limits). Pass dry_run=True to preview.

    Args:
        container_id: Container id or name.
        resources: Resource limits to set — allowed keys: Memory, MemorySwap,
            MemoryReservation, NanoCpus, CpuQuota, CpuPeriod, CpuShares,
            CpusetCpus, CpusetMems (Docker update fields).
        dry_run: If True, preview without changing.
        target: Target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {
            "dryRun": True,
            "wouldUpdate": {"container_id": container_id, "resources": resources},
        }
    return ops.update_container(conn, container_id, resources)


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def recreate_stack(
    stack_id: str,
    endpoint_id: Optional[str] = None,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=high] Redeploy (recreate) a Portainer stack. No undo.

    Captures the stack definition for audit before Portainer recreates it; there
    is no clean inverse for a redeploy. Requires a portainer target. Pass
    dry_run=True to preview.

    Args:
        stack_id: Portainer stack id.
        endpoint_id: Endpoint id the stack runs on; omit to use the stack's own.
        dry_run: If True, preview without recreating.
        target: Target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {"dryRun": True, "wouldRecreate": {"stack_id": stack_id, "endpoint_id": endpoint_id}}
    return ops.recreate_stack(conn, stack_id, endpoint_id)
