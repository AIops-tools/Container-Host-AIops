# container-host-aiops setup & security guide

> Preview / mock-only — not yet validated against a live Docker daemon or
> Portainer server. `container-host-aiops doctor` is the fastest live check.

## 1. Install

```bash
uv tool install container-host-aiops     # or: pipx install container-host-aiops
```

## 2. What you need

- **Docker (unix socket)** — read/write access to the Docker socket (default
  `/var/run/docker.sock`). No secret is stored; the socket's file permissions are
  the trust boundary. Treat socket access as **root-equivalent** on the host.
- **Docker (TCP)** — a host + port (2375 plain, 2376 TLS). Enable TLS in
  production; a plain TCP daemon is unauthenticated.
- **Portainer** — the Portainer host + HTTPS port (default 9443), an **API token**
  (Portainer → My account → Access tokens), and the **endpoint id** of the managed
  Docker environment you want to read/manage (list them with `stack endpoints`).

## 3. Onboard (interactive)

```bash
container-host-aiops init
```

The wizard asks, per target, for the **platform** (`docker` / `portainer`):

- **docker** — connect over a **unix socket** (path, default `/var/run/docker.sock`)
  or a **TCP host** (host + optional TLS). No secret.
- **portainer** — host, HTTPS port, managed **endpoint id**, TLS verification, and
  the **API token** (stored encrypted). A master password (used to encrypt
  `secrets.enc`) is prompted the first time a Portainer token is stored.

Non-secret connection details go to `~/.container-host-aiops/config.yaml`; a
Portainer token goes to `~/.container-host-aiops/secrets.enc` (encrypted).

### Manual config (`~/.container-host-aiops/config.yaml`)

```yaml
targets:
  - name: local
    platform: docker
    socket_path: /var/run/docker.sock

  - name: remote-tcp
    platform: docker
    host: 10.0.0.5
    port: 2376
    verify_ssl: true

  - name: portainer1
    platform: portainer
    host: portainer.lan
    port: 9443
    endpoint_id: "1"
    verify_ssl: false        # true in production
```

Then store the Portainer token (encrypted):

```bash
container-host-aiops secret set portainer1
container-host-aiops doctor
```

## 4. Credentials & security

- Only **Portainer** needs a secret. Its API token is **never** written to disk in
  plaintext — it lives encrypted in `~/.container-host-aiops/secrets.enc` (Fernet /
  AES-128 + a scrypt-derived key; chmod 600). The master password is never stored.
- The master password is resolved from `CONTAINER_HOST_AIOPS_MASTER_PASSWORD`
  (non-interactive / MCP / CI) or an interactive prompt (CLI on a TTY).
- A legacy plaintext env var `CONTAINER_HOST_<TARGET_NAME_UPPER>_TOKEN` is honoured
  as a fallback with a deprecation warning (migrate with `secret migrate`).
- The token is sent in the `X-API-Key` header at request time and held only in
  memory; secrets are never logged or echoed.
- `verify_ssl` defaults to true; disable only for a self-signed Portainer / TLS
  Docker daemon in a lab. A unix-socket Docker target does not use TLS.

## 5. Governance

Every MCP tool runs through the bundled `@governed_tool` harness:

- **Audit** — all calls logged to `~/.container-host-aiops/audit.db` (relocatable via
  `CONTAINER_HOST_AIOPS_HOME`), agent-attributed, secret-redacted.
- **Budget / runaway guard** — token/call ceilings + a tight-loop breaker.
- **Risk tiers** — high-risk ops (`remove_container`, `prune_images`,
  `prune_volumes`, `recreate_stack`) can require a recorded approver
  (`CONTAINER_HOST_AUDIT_APPROVED_BY` + `CONTAINER_HOST_AUDIT_RATIONALE` — the env-var names
  the bundled harness reads).
- **Undo recording** — reversible writes capture the before-state and record an
  inverse (`stop`→`start`, `update_container`→restore prior limits).

## 6. Verify

```bash
container-host-aiops doctor            # Docker: GET /version · Portainer: GET /api/endpoints
container-host-aiops overview          # one-shot host health
```

## Missing a capability?

Coverage is a curated subset of the Docker Engine + Portainer APIs. Missing a call
or want another container host family? **Open an issue or PR** — contributions
welcome.
