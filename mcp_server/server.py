"""MCP server wrapping container-host-aiops operations (stdio transport).

Thin adapter layer: each ``@mcp.tool()`` function (in ``mcp_server/tools/``)
delegates to the ``container_host_aiops`` ops package and is wrapped with the
container-host-aiops ``@governed_tool`` harness (audit / budget / undo / risk-tier).

Standalone, self-governed container-host operations (preview) over the Docker
Engine API and Portainer: container / image / volume / network / system reads,
three flagship analyses, and governed lifecycle + prune writes.

Source: https://github.com/AIops-tools/Container-Host-AIops
License: MIT
"""

import logging

from mcp_server._shared import _safe_error, mcp, tool_errors

# Importing the tool modules registers every @mcp.tool() onto the shared
# `mcp` instance. Order does not matter; each module is self-contained.
from mcp_server.tools import (  # noqa: F401 — side effects
    analyses,
    containers,
    images,
    networks,
    pods,
    stacks,
    system,
    undo,
    volumes,
    writes,
)

__all__ = ["mcp", "main", "_safe_error", "tool_errors"]


def main() -> None:
    """Run the MCP server over stdio."""
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")
