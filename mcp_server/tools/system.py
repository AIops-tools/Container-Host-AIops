"""Host system Docker MCP tools (read-only) + the one-shot host overview."""

from typing import Optional

from container_host_aiops.governance import governed_tool
from container_host_aiops.ops import overview as ov
from container_host_aiops.ops import system as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def overview(target: Optional[str] = None) -> dict:
    """[READ] One-shot host overview: version + container state rollup + disk.

    Call this first to triage a container host before drilling into a specific
    container, image, or volume.

    Args:
        target: Target name from config; omit for the default.
    """
    return ov.host_overview(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def system_info(target: Optional[str] = None) -> dict:
    """[READ] Daemon info: container/image counts, storage driver, kernel, resources.

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.system_info(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def system_version(target: Optional[str] = None) -> dict:
    """[READ] Docker version details (API version, Go version, components).

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.system_version(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def system_df(target: Optional[str] = None) -> dict:
    """[READ] Disk-usage breakdown: images, containers, volumes, build cache.

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.system_df(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def system_events(
    since: int = 3600, event_type: Optional[str] = None, target: Optional[str] = None
) -> dict:
    """[READ] Recent daemon events over the last N seconds, rolled up by type+action.

    Args:
        since: Look-back window in seconds (1..86400, default 3600).
        event_type: Filter to one event type (container/image/volume/network); omit for all.
        target: Target name from config; omit for the default.

    Returns an envelope: {"events": [...], "returned": N, "limit": L,
    "truncated": bool, "total": T}. When "truncated" is true only the most
    recent events fit — narrow the window with a smaller "since".
    """
    return ops.recent_events(_get_connection(target), since, event_type)
