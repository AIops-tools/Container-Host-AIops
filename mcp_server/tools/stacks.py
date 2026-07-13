"""Portainer stack + endpoint MCP tools (read-only)."""

from typing import Optional

from container_host_aiops.governance import governed_tool
from container_host_aiops.ops import stacks as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_endpoints(target: Optional[str] = None) -> dict:
    """[READ] Portainer endpoints (managed hosts): id, name, type, status, url.

    Requires a portainer target.

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.list_endpoints(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_stacks(target: Optional[str] = None) -> dict:
    """[READ] Portainer stacks (Compose/Swarm): id, name, type, endpoint, status.

    Requires a portainer target.

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.list_stacks(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def stack_detail(stack_id: str, target: Optional[str] = None) -> dict:
    """[READ] One Portainer stack in detail (env, entrypoint, resource control).

    Requires a portainer target.

    Args:
        stack_id: Portainer stack id.
        target: Target name from config; omit for the default.
    """
    return ops.stack_detail(_get_connection(target), stack_id)
