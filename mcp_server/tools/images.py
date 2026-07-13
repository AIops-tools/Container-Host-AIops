"""Image-scoped Docker MCP tools (read-only)."""

from typing import Optional

from container_host_aiops.governance import governed_tool
from container_host_aiops.ops import images as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_images(all_images: bool = False, target: Optional[str] = None) -> dict:
    """[READ] List images (tags, size, dangling), largest first.

    Args:
        all_images: True includes intermediate layers; default only top-level.
        target: Target name from config; omit for the default.
    """
    return ops.list_images(_get_connection(target), all_images)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def inspect_image(image_id: str, target: Optional[str] = None) -> dict:
    """[READ] Inspect an image plus its build history (layers, sizes, commands).

    Args:
        image_id: Image id or name:tag.
        target: Target name from config; omit for the default.
    """
    return ops.inspect_image(_get_connection(target), image_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def dangling_images(target: Optional[str] = None) -> dict:
    """[READ] Untagged (dangling) images + reclaimable bytes — prune candidates.

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.dangling_images(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def image_disk_usage(target: Optional[str] = None) -> dict:
    """[READ] Image disk usage from system/df (total, shared, reclaimable).

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.image_disk_usage(_get_connection(target))
