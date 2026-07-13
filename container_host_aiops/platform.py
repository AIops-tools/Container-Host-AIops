"""Platform descriptors — the container hosts container-host-aiops speaks to.

container-host-aiops is multi-platform by construction. A registry maps a
*platform name* to a :class:`Platform` descriptor that captures everything the
connection layer needs to talk to that host: how it authenticates, and — for a
management plane that *proxies* the Docker Engine API — the path prefix under
which the raw Docker endpoints live.

v0.1 registers two platforms:

  * **docker** — the Docker Engine API spoken directly, over a local unix socket
    (``/var/run/docker.sock``) or a TCP host. No auth header (the socket's file
    permissions are the boundary); TLS for a remote daemon.
  * **portainer** — the Portainer management API (``X-API-Key`` header), which
    also *proxies* the Docker Engine API of each managed endpoint under
    ``/api/endpoints/{id}/docker/...``. So the same container/image/volume reads
    work against a Portainer-managed host by prefixing the Docker path.

Additional container hosts (e.g. a Podman socket) can ``register`` their own
descriptor later without touching the ops / CLI / MCP layers — a registry keyed
by ``platform`` name, so adding a host family is a new descriptor, not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass

from container_host_aiops.governance import sanitize

# ─── registered platform names ──────────────────────────────────────────────
DOCKER = "docker"
PORTAINER = "portainer"
PLATFORMS = (DOCKER, PORTAINER)

# Sensible defaults per platform.
DEFAULT_DOCKER_SOCKET = "/var/run/docker.sock"
DEFAULT_DOCKER_TCP_PORT = 2375
DEFAULT_DOCKER_TLS_PORT = 2376
DEFAULT_PORTAINER_PORT = 9443

# Bounds for the response normaliser (defensive against a hostile host).
_MAX_STR = 512
_MAX_DEPTH = 8


def _sanitize_obj(obj: object, depth: int = 0) -> object:
    """Recursively fold host-returned JSON into injection-safe values.

    Every string leaf passes through ``sanitize`` (bounded length); numbers,
    booleans and ``None`` pass through unchanged. Depth is capped so a
    pathological nesting cannot exhaust the stack.
    """
    if depth > _MAX_DEPTH:
        return None
    if isinstance(obj, dict):
        return {str(k): _sanitize_obj(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_obj(v, depth + 1) for v in obj]
    if isinstance(obj, str):
        return sanitize(obj, _MAX_STR)
    return obj


@dataclass(frozen=True)
class Platform:
    """A container host's API shape: auth + Docker-path prefixing + normaliser."""

    name: str
    label: str
    proxies_docker: bool  # True when Docker endpoints live under a proxy prefix.

    def auth_headers(self, secret: str) -> dict[str, str]:
        """Build the request headers that authenticate to this platform.

        Portainer authenticates every request with an ``X-API-Key`` header.
        Docker over a unix socket / plain TCP needs no header (the socket's file
        permissions, or mTLS handled by the transport, are the boundary).
        """
        headers = {"Accept": "application/json"}
        if self.name == PORTAINER and secret:
            headers["X-API-Key"] = secret
        return headers

    def docker_prefix(self, endpoint_id: str = "") -> str:
        """Path prefix under which the raw Docker Engine API is reachable.

        Empty for a direct Docker daemon; for Portainer the Docker API of a
        managed endpoint is proxied at ``/api/endpoints/{id}/docker``.
        """
        if self.proxies_docker:
            eid = str(endpoint_id or "").strip()
            if not eid:
                raise ValueError(
                    "Portainer target needs an endpoint_id to reach the Docker "
                    "API (set 'endpoint_id' on the target, or list endpoints)."
                )
            return f"/api/endpoints/{eid}/docker"
        return ""

    def normalise(self, payload: object) -> object:
        """Return an injection-safe copy of a raw response payload."""
        return _sanitize_obj(payload)


# ─── registry ───────────────────────────────────────────────────────────────
_REGISTRY: dict[str, Platform] = {}


def register(platform: Platform) -> None:
    """Register a platform descriptor under its name (idempotent overwrite)."""
    _REGISTRY[platform.name] = platform


def get_platform(name: str) -> Platform:
    """Return the descriptor for ``name`` or raise with the registered names."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(
            f"Unknown platform '{name}'. Registered platforms: {available}."
        ) from exc


def platform_names() -> tuple[str, ...]:
    """All registered platform names (sorted)."""
    return tuple(sorted(_REGISTRY))


register(Platform(name=DOCKER, label="Docker Engine API", proxies_docker=False))
register(Platform(name=PORTAINER, label="Portainer API", proxies_docker=True))


__all__ = [
    "DOCKER",
    "PORTAINER",
    "PLATFORMS",
    "DEFAULT_DOCKER_SOCKET",
    "DEFAULT_DOCKER_TCP_PORT",
    "DEFAULT_DOCKER_TLS_PORT",
    "DEFAULT_PORTAINER_PORT",
    "Platform",
    "register",
    "get_platform",
    "platform_names",
]
