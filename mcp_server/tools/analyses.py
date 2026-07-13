"""Flagship container-host analysis MCP tools (read-only)."""

from typing import Any, Optional

from container_host_aiops.governance import governed_tool
from container_host_aiops.ops import analyses as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def restart_loop_rca(
    restart_threshold: int = 3,
    containers: Optional[list[dict[str, Any]]] = None,
    logs_by_id: Optional[dict[str, list[str]]] = None,
    target: Optional[str] = None,
) -> dict:
    """[READ] Find crash-looping containers and map each to a cause + action.

    The flagship restart RCA: inspects containers for restart count + exit code,
    flags the crash-looping ones (restartCount >= threshold, or restarting/dead,
    or a non-zero exit), attaches a likely cause + recommended action from the
    exit code (137 OOM/SIGKILL, 143 SIGTERM, 139 segfault, 127 bad entrypoint, …),
    and a tail of logs. Every ranking carries its numbers. Pass 'containers' for
    pure analysis, or a target to pull live.

    Args:
        restart_threshold: Restart count at/above which a container is looping (default 3).
        containers: Injected rows {id, name, state, restartCount, exitCode,
            oomKilled, error}; skips live collection.
        logs_by_id: Optional {containerId: [logLine, ...]} log tails to attach.
        target: Target name from config; omit for the default.
    """
    if containers is None:
        conn = _get_connection(target)
        containers, pulled_logs = ops.pull_restart_data(conn)
        logs_by_id = logs_by_id or pulled_logs
    return ops.restart_loop_rca(containers, logs_by_id, restart_threshold)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def resource_pressure_analysis(
    cpu_threshold: float = 80.0,
    mem_threshold: float = 80.0,
    samples: Optional[list[dict[str, Any]]] = None,
    target: Optional[str] = None,
) -> dict:
    """[READ] Rank containers by CPU/memory pressure vs their limits + recommend.

    Pulls a one-shot CPU%/mem% sample for each running container (or uses injected
    'samples'), flags each 'near' (>= 80% of a threshold) or 'over' (>= threshold),
    and attaches a recommendation (raise a limit, set a missing memory limit, scale
    out). Ranks worst-first by the higher of CPU%/mem%. Every row carries its numbers.

    Args:
        cpu_threshold: CPU% at/above which a container is over pressure (default 80).
        mem_threshold: Memory% at/above which a container is over pressure (default 80).
        samples: Injected rows {id, name, cpuPercent, memPercent, memUsageBytes,
            memLimitBytes}; skips live collection.
        target: Target name from config; omit for the default.
    """
    if samples is None:
        samples = ops.pull_resource_pressure(_get_connection(target))
    return ops.resource_pressure_analysis(samples, cpu_threshold, mem_threshold)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def image_and_volume_bloat(
    dangling_images: Optional[dict[str, Any]] = None,
    dangling_volumes: Optional[dict[str, Any]] = None,
    df: Optional[dict[str, Any]] = None,
    target: Optional[str] = None,
) -> dict:
    """[READ] Total dangling images + volumes + build cache into prune candidates.

    Sums dangling images, dangling volumes, and build cache (from system/df) into
    reclaimable-byte prune candidates, largest first. Pass the three read payloads
    for pure analysis, or a target to pull live.

    Args:
        dangling_images: Injected {danglingCount, reclaimableBytes, ...}; skips live.
        dangling_volumes: Injected {danglingCount, reclaimableBytes, ...}; skips live.
        df: Injected system/df summary {buildCache:{count, totalBytes}, ...}.
        target: Target name from config; omit for the default.
    """
    if dangling_images is None and dangling_volumes is None and df is None:
        return ops.pull_bloat(_get_connection(target))
    return ops.image_and_volume_bloat(dangling_images or {}, dangling_volumes or {}, df or {})
