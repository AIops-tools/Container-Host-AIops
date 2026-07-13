# Security Policy

## Disclaimer

Community-maintained open-source project. **Not affiliated with, endorsed by, or
sponsored by Docker, Inc. or Portainer.io.** Product and trademark names (Docker,
Portainer) belong to their owners. Source is auditable under the MIT license.

## Reporting Vulnerabilities

Report privately via a GitHub Security Advisory on
[github.com/AIops-tools/Container-Host-AIops](https://github.com/AIops-tools/Container-Host-AIops/security/advisories)
or email zhouwei008@gmail.com. Please do not open public issues for security
reports.

## Security Design

### Credential Management
- The only secret is the **Portainer API token**. It lives **encrypted** in
  `~/.container-host-aiops/secrets.enc` (Fernet/AES-128 + scrypt-derived key; chmod
  600), never in `config.yaml` and never in source. The master password is never
  stored — only a per-store random salt and the ciphertext are on disk.
- A **direct Docker socket** target needs no secret at all — the unix socket's
  file permissions are the trust boundary. Treat access to `/var/run/docker.sock`
  as root-equivalent on the host and scope it accordingly.
- A legacy plaintext env var `CONTAINER_HOST_<TARGET_NAME_UPPER>_TOKEN` is still
  honoured as a fallback with a deprecation warning (migrate with
  `container-host-aiops secret migrate`).
- The token is held only in memory and never logged or echoed; it is sent in the
  `X-API-Key` request header at call time. The config file holds only platform,
  socket path / host, port, endpoint id, and TLS settings.

### Governed Operations
Every MCP tool runs through the bundled `@governed_tool` harness
(`container_host_aiops.governance`):
- **Audit** — every call logged to a local SQLite DB under `~/.container-host-aiops/`
  (relocatable via `CONTAINER_HOST_AIOPS_HOME`), agent-attributed, secret-redacted.
- **Token/runaway budget** — hard ceilings (`CONTAINER_HOST_MAX_TOOL_CALLS` /
  `CONTAINER_HOST_MAX_TOOL_SECONDS` — the env-var names the bundled harness reads)
  plus an on-by-default guard that trips a tight poll/retry loop, preventing
  unbounded API consumption.
- **Graduated risk tiers** — `~/.container-host-aiops/rules.yaml` `risk_tiers` gate
  writes by environment/tag; the highest tiers require a recorded approver.
- **Undo-token recording** — reversible writes capture the BEFORE state and
  record an inverse descriptor (e.g. `stop_container`→`start_container`,
  `update_container`→restore prior limits) so the change can be rolled back.

### State-Changing Operations
Destructive writes — `remove_container`, `prune_images`, `prune_volumes`,
`recreate_stack` — are `risk_level=high`, accept a `dry_run` preview (prune
previews **list what would be removed + reclaimable bytes** first), and (under
`risk_tiers`) require a recorded approver (`CONTAINER_HOST_AUDIT_APPROVED_BY` +
`CONTAINER_HOST_AUDIT_RATIONALE` — the env-var names the bundled harness reads).
Lifecycle writes (`restart_container`, `stop_container`, `start_container`,
`update_container`) are `risk_level=medium`; reversible ones capture before-state
and record an undo token. `remove_container` captures the full inspect JSON
before deletion for the audit trail.

### SSL/TLS Verification
`verify_ssl` defaults to true; disable only for a self-signed Portainer / TLS
Docker daemon in a lab. A unix-socket Docker target does not use TLS.

### Prompt-Injection Protection
All host-returned text (container names, image tags, log lines, event text,
volume/network names) is passed through a `sanitize()` truncate +
control-character strip before reaching the agent, bounded in depth and length.

### Network Scope
No webhooks, no telemetry, no outbound calls beyond the configured Docker socket /
TCP host or the Portainer API base URL. No post-install scripts or background
services.

## Static Analysis

```bash
uvx bandit -r container_host_aiops/ mcp_server/
uv run ruff check .
```

## Supported Versions

The latest released version receives security fixes. This is a preview (0.x);
pin a version in production.
