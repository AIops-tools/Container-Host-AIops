"""Platform descriptors — the container hosts container-host-aiops speaks to.

container-host-aiops is multi-platform by construction. A registry maps a
*platform name* to a :class:`Platform` descriptor that captures everything the
connection layer needs to talk to that host: how it authenticates, and — for a
management plane that *proxies* the Docker Engine API — the path prefix under
which the raw Docker endpoints live.

The registry currently registers three platforms:

  * **docker** — the Docker Engine API spoken directly, over a local unix socket
    (``/var/run/docker.sock``) or a TCP host. No auth header (the socket's file
    permissions are the boundary); TLS for a remote daemon.
  * **portainer** — the Portainer management API (``X-API-Key`` header), which
    also *proxies* the Docker Engine API of each managed endpoint under
    ``/api/endpoints/{id}/docker/...``. So the same container/image/volume reads
    work against a Portainer-managed host by prefixing the Docker path.
  * **podman** — a Podman service socket (rootful ``/run/podman/podman.sock`` or
    rootless ``$XDG_RUNTIME_DIR/podman/podman.sock``). Podman exposes **two**
    HTTP APIs on the same socket: a **Docker-compatible** compat layer (the same
    unversioned ``/containers/json`` … paths Docker serves, so every Docker read /
    write and RCA is reused wholesale) *plus* **libpod-native** endpoints under
    ``/v4.x.y/libpod/...`` that add Podman-only objects — most notably **pods**,
    which Docker has no concept of. ``proxies_docker`` is False (the compat paths
    live at the root, exactly like Docker); ``libpod_prefix`` carries the
    libpod path prefix used only where a native endpoint adds value.

Additional container hosts can ``register`` their own descriptor later without
touching the ops / CLI / MCP layers — a registry keyed by ``platform`` name, so
adding a host family is a new descriptor, not a rewrite.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from container_host_aiops.governance import sanitize

# ─── registered platform names ──────────────────────────────────────────────
DOCKER = "docker"
PORTAINER = "portainer"
PODMAN = "podman"
PLATFORMS = (DOCKER, PORTAINER, PODMAN)

# Sensible defaults per platform.
DEFAULT_DOCKER_SOCKET = "/var/run/docker.sock"
DEFAULT_DOCKER_TCP_PORT = 2375
DEFAULT_DOCKER_TLS_PORT = 2376
DEFAULT_PORTAINER_PORT = 9443

# Podman service sockets, in the order autodetection prefers them (see
# ``default_podman_socket``). Rootful is the system-wide socket; the rootless
# socket lives under the user's XDG runtime dir.
DEFAULT_PODMAN_ROOTFUL_SOCKET = "/run/podman/podman.sock"
_PODMAN_ROOTLESS_RELATIVE = "podman/podman.sock"  # under $XDG_RUNTIME_DIR
# libpod-native endpoints (pods, etc.) live under this prefix; the compat
# (Docker-shaped) endpoints stay at the root and reuse the Docker path templates.
LIBPOD_PREFIX = "/v4.0.0/libpod"


def podman_socket_candidates() -> tuple[str, ...]:
    """Podman socket paths to probe, most-preferred first (autodetection order).

    Order (documented): a **rootless** socket under ``$XDG_RUNTIME_DIR`` first
    (a non-root operator's own Podman service is the common case), then the
    **rootful** system socket. An explicit ``socket_path`` in the target config
    always overrides this probing.
    """
    candidates: list[str] = []
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        candidates.append(str(Path(xdg) / _PODMAN_ROOTLESS_RELATIVE))
    candidates.append(DEFAULT_PODMAN_ROOTFUL_SOCKET)
    return tuple(candidates)


def default_podman_socket() -> str:
    """First existing Podman socket from :func:`podman_socket_candidates`.

    Falls back to the rootful path when none of the candidates exist yet, so the
    target config always carries a concrete, sane default string to show/edit.
    """
    for path in podman_socket_candidates():
        try:
            if Path(path).exists():
                return path
        except OSError:
            continue
    return DEFAULT_PODMAN_ROOTFUL_SOCKET

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
    libpod_prefix: str = ""  # non-empty only for a platform exposing libpod-native endpoints.

    @property
    def supports_libpod(self) -> bool:
        """True when this platform serves libpod-native endpoints (Podman pods, …)."""
        return bool(self.libpod_prefix)

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
            return f"/api/endpoints/{quote(eid, safe='')}/docker"
        return ""

    def libpod_path(self, path: str) -> str:
        """Prefix ``path`` with the libpod-native endpoint prefix for this platform.

        Only Podman exposes libpod-native endpoints (e.g. ``/pods/json``); on
        Docker / Portainer this raises a teaching error so a pod read against a
        Docker-family target fails with an explanation rather than a 404.
        """
        if not self.supports_libpod:
            raise ValueError(
                f"'{self.name}' does not expose libpod-native endpoints. Pods are a "
                f"Podman-only feature — target a 'podman' host to list pods."
            )
        return f"{self.libpod_prefix}{path}"

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
register(
    Platform(
        name=PODMAN,
        label="Podman (libpod + Docker-compat API)",
        proxies_docker=False,
        libpod_prefix=LIBPOD_PREFIX,
    )
)


__all__ = [
    "DOCKER",
    "PORTAINER",
    "PODMAN",
    "PLATFORMS",
    "DEFAULT_DOCKER_SOCKET",
    "DEFAULT_DOCKER_TCP_PORT",
    "DEFAULT_DOCKER_TLS_PORT",
    "DEFAULT_PORTAINER_PORT",
    "DEFAULT_PODMAN_ROOTFUL_SOCKET",
    "LIBPOD_PREFIX",
    "podman_socket_candidates",
    "default_podman_socket",
    "Platform",
    "register",
    "get_platform",
    "platform_names",
]
