"""Container-scoped Docker MCP tools (read-only)."""

from typing import Optional

from container_host_aiops.governance import governed_tool
from container_host_aiops.ops import containers as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_containers(all_states: bool = True, target: Optional[str] = None) -> dict:
    """[READ] List containers, bucketed by state, with compact rows.

    Args:
        all_states: True (default) lists all containers; False only running.
        target: Target name from config; omit for the default.
    """
    return ops.list_containers(_get_connection(target), all_states)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def inspect_container(container_id: str, target: Optional[str] = None) -> dict:
    """[READ] Full inspect of one container (config, state, mounts, network).

    Args:
        container_id: Container id or name.
        target: Target name from config; omit for the default.
    """
    return ops.inspect_container(_get_connection(target), container_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def container_logs(
    container_id: str, tail: int = 100, target: Optional[str] = None
) -> dict:
    """[READ] Tail the last N log lines of a container (stdout + stderr).

    Args:
        container_id: Container id or name.
        tail: Number of lines from the end (1..2000, default 100).
        target: Target name from config; omit for the default.
    """
    return ops.container_logs(_get_connection(target), container_id, tail)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def container_stats(container_id: str, target: Optional[str] = None) -> dict:
    """[READ] One-shot CPU%/memory% snapshot for a container (stream=false).

    Args:
        container_id: Container id or name.
        target: Target name from config; omit for the default.
    """
    return ops.container_stats(_get_connection(target), container_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def container_top(container_id: str, target: Optional[str] = None) -> dict:
    """[READ] Processes running inside a container (like docker top).

    Args:
        container_id: Container id or name.
        target: Target name from config; omit for the default.
    """
    return ops.container_top(_get_connection(target), container_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def container_restart_summary(all_states: bool = True, target: Optional[str] = None) -> dict:
    """[READ] Restart-count + exit-code summary across containers, worst-first.

    Args:
        all_states: True (default) inspects all containers; False only running.
        target: Target name from config; omit for the default.
    """
    return ops.restart_summary(_get_connection(target), all_states)
