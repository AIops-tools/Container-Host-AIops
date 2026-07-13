"""Volume-scoped Docker MCP tools (read-only)."""

from typing import Optional

from container_host_aiops.governance import governed_tool
from container_host_aiops.ops import volumes as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_volumes(target: Optional[str] = None) -> dict:
    """[READ] List named volumes (name, driver, mountpoint, scope).

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.list_volumes(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def inspect_volume(name: str, target: Optional[str] = None) -> dict:
    """[READ] Inspect one named volume (driver, mountpoint, options, usage).

    Args:
        name: Volume name.
        target: Target name from config; omit for the default.
    """
    return ops.inspect_volume(_get_connection(target), name)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def dangling_volumes(target: Optional[str] = None) -> dict:
    """[READ] Dangling volumes (unreferenced) + reclaimable bytes — prune candidates.

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.dangling_volumes(_get_connection(target))
