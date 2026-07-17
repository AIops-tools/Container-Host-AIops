"""Podman pod MCP tools (read-only, Podman-only)."""

from typing import Optional

from container_host_aiops.governance import governed_tool
from container_host_aiops.ops import pods as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_pods(target: Optional[str] = None) -> dict:
    """[READ] List Podman pods (Podman-only): id, name, status, member containers.

    A pod groups containers sharing namespaces — a Podman-native concept with no
    Docker equivalent, read over the libpod API. Requires a podman target; on a
    docker/portainer target it returns a teaching error (pods do not exist there).

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.list_pods(_get_connection(target))
