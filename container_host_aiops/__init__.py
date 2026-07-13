"""container-host-aiops — governed Docker + Portainer container-host ops for AI agents.

Standalone and self-contained: the governance harness (audit, token budget,
undo-token recording, graduated risk tiers, prompt-injection sanitize) is
bundled under ``container_host_aiops.governance`` — this package has no external
skill-family dependency. Preview: not yet full-coverage, mock-validated only.
"""

__version__ = "0.1.0"
