"""Network-scoped Docker MCP tools (read-only)."""

from typing import Optional

from container_host_aiops.governance import governed_tool
from container_host_aiops.ops import networks as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_networks(target: Optional[str] = None) -> dict:
    """[READ] List Docker networks, bucketed by driver.

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.list_networks(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def inspect_network(network_id: str, target: Optional[str] = None) -> dict:
    """[READ] Inspect one network (driver, IPAM subnet/gateway, attached containers).

    Args:
        network_id: Network id or name.
        target: Target name from config; omit for the default.
    """
    return ops.inspect_network(_get_connection(target), network_id)
