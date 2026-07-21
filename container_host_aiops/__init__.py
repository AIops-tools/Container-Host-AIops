"""container-host-aiops — governed Docker + Portainer container-host ops for AI agents.

Standalone and self-contained: the governance harness (audit, token budget,
undo-token recording, risk-tier audit labels, output sanitize) is
bundled under ``container_host_aiops.governance`` — this package has no external
skill-family dependency. Preview: not yet full-coverage, mock-validated only.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("container-host-aiops")
except PackageNotFoundError:  # running from an uninstalled source tree
    __version__ = "0.0.0+unknown"
