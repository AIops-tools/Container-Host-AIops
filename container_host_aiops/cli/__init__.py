"""CLI package for container-host-aiops.

Re-exports ``app`` so the pyproject entry point
``container-host-aiops = "container_host_aiops.cli:app"`` works unchanged.
"""

from container_host_aiops.cli._root import app

__all__ = ["app"]
