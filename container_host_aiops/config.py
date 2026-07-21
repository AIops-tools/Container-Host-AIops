"""Configuration management for Container Host AIops.

Loads container-host connection targets from a YAML config file. Each target
names its ``platform`` — ``docker`` (the Docker Engine API, spoken directly over
a unix socket or a TCP host), ``portainer`` (the Portainer management API, which
also proxies the Docker Engine API of each managed endpoint), or ``podman`` (a
Podman service socket — rootful ``/run/podman/podman.sock`` or rootless
``$XDG_RUNTIME_DIR/podman/podman.sock``, autodetected — speaking the
Docker-compatible API plus libpod-native endpoints). One config can span many
hosts. See :mod:`container_host_aiops.platform`.

The secret is only meaningful for **Portainer** (its ``X-API-Key`` token). It is
NEVER stored in the config file or in plaintext on disk: it lives in the
encrypted store ``~/.container-host-aiops/secrets.enc`` (see
:mod:`container_host_aiops.secretstore`). A legacy env var
(``CONTAINER_HOST_<TARGET>_TOKEN``) is honoured as a fallback, with a warning
nudging migration to the encrypted store. A direct **Docker** target over a unix
socket needs no secret — the socket's file permissions are the boundary.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from container_host_aiops.governance.paths import ops_home
from container_host_aiops.platform import (
    DEFAULT_DOCKER_SOCKET,
    DEFAULT_DOCKER_TCP_PORT,
    DEFAULT_DOCKER_TLS_PORT,
    DEFAULT_PORTAINER_PORT,
    DOCKER,
    PODMAN,
    PORTAINER,
    default_podman_socket,
    get_platform,
)
from container_host_aiops.secretstore import (
    MasterPasswordError,
    SecretStoreError,
    get_secret,
    has_store,
)

if TYPE_CHECKING:
    from container_host_aiops.platform import Platform

CONFIG_DIR = ops_home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

# Legacy env-var prefix/suffix; also used by the migration helper.
SECRET_ENV_PREFIX = "CONTAINER_HOST_"  # nosec B105 — env-var name, not a secret
SECRET_ENV_SUFFIX = "_TOKEN"  # nosec B105 — env-var name, not a secret

_log = logging.getLogger("container-host-aiops.config")


def _secret_env_key(name: str) -> str:
    """Legacy per-target token env var name, e.g. CONTAINER_HOST_PROD1_TOKEN."""
    return f"{SECRET_ENV_PREFIX}{name.upper().replace('-', '_')}{SECRET_ENV_SUFFIX}"


def _resolve_secret(name: str) -> str:
    """Return a target's token: encrypted store first, then legacy env var."""
    if has_store():
        try:
            return get_secret(name)
        except MasterPasswordError:
            # A wrong or missing master password is NOT "this target has no
            # secret". Falling through resurfaced it as "No API key for target
            # X", sending the operator to add a credential that is already
            # there. MasterPasswordError subclasses SecretStoreError, so the
            # broad catch below would swallow it — re-raise first.
            raise
        except SecretStoreError:
            pass  # no secret stored for this target — try the legacy env var
    legacy = os.environ.get(_secret_env_key(name))
    if legacy:
        _log.warning(
            "Using plaintext env var %s. Migrate to the encrypted store with "
            "'container-host-aiops secret migrate'.",
            _secret_env_key(name),
        )
        return legacy
    raise OSError(
        f"No API token for target '{name}'. Add one with "
        f"'container-host-aiops secret set {name}' (stored encrypted), or run "
        f"'container-host-aiops init'."
    )


@dataclass(frozen=True)
class TargetConfig:
    """A connection target for one container host.

    ``platform`` selects the API family:

      * ``docker`` — the Docker Engine API. With no ``host`` set, the connection
        goes over the local unix socket ``socket_path`` (default
        ``/var/run/docker.sock``); with a ``host`` it uses TCP.
      * ``portainer`` — the Portainer management API at ``host``:``port`` (TLS).
        ``endpoint_id`` names the managed Docker endpoint whose Engine API is
        proxied, so container/image/volume reads work through Portainer too.
      * ``podman`` — a Podman service socket. With no ``host`` set, the connection
        goes over the autodetected rootless/rootful socket (``socket_path`` when
        given); Docker-compat reads/writes reuse the Docker paths, and libpod-only
        reads (pods) use the libpod prefix. Needs no secret (socket permissions).

    The Portainer API token comes from the encrypted secret store, never the
    config file; a direct Docker socket target needs no secret.
    """

    name: str
    platform: str = DOCKER
    socket_path: str = ""
    host: str = ""
    port: int = 0
    base_url: str = ""
    endpoint_id: str = ""
    verify_ssl: bool = True

    def __post_init__(self) -> None:
        # Fail fast on an unknown platform (validated at the trust boundary).
        get_platform(self.platform)
        if not self.host and not self.socket_path:
            if self.platform == DOCKER:
                object.__setattr__(self, "socket_path", DEFAULT_DOCKER_SOCKET)
            elif self.platform == PODMAN:
                # Autodetect the rootless/rootful Podman socket (first existing).
                object.__setattr__(self, "socket_path", default_podman_socket())
        if not self.port:
            if self.platform == PORTAINER:
                object.__setattr__(self, "port", DEFAULT_PORTAINER_PORT)
            elif self.host:
                default = DEFAULT_DOCKER_TLS_PORT if self.verify_ssl else DEFAULT_DOCKER_TCP_PORT
                object.__setattr__(self, "port", default)

    @property
    def platform_obj(self) -> Platform:
        return get_platform(self.platform)

    @property
    def requires_secret(self) -> bool:
        """Only Portainer needs an API token; a Docker socket does not."""
        return self.platform == PORTAINER

    @property
    def secret(self) -> str:
        return _resolve_secret(self.name) if self.requires_secret else ""

    @property
    def uses_unix_socket(self) -> bool:
        return self.platform in (DOCKER, PODMAN) and not self.host and bool(self.socket_path)

    @property
    def api_base(self) -> str:
        """Effective API base URL for the httpx client.

        A unix-socket Docker target uses a dummy ``http://localhost`` base (the
        transport carries the socket path). A TCP Docker target and Portainer
        use a real scheme + host + port.
        """
        if self.base_url:
            return self.base_url
        if self.uses_unix_socket:
            return "http://localhost"
        scheme = "https" if (self.platform == PORTAINER or self.verify_ssl) else "http"
        return f"{scheme}://{self.host}:{self.port}"


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: tuple[TargetConfig, ...] = ()

    def get_target(self, name: str) -> TargetConfig:
        for t in self.targets:
            if t.name == name:
                return t
        available = ", ".join(t.name for t in self.targets) or "(none)"
        raise KeyError(f"Target '{name}' not found. Available: {available}")

    @property
    def default_target(self) -> TargetConfig:
        if not self.targets:
            raise ValueError("No targets configured. Check config.yaml")
        return self.targets[0]


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from YAML; the Portainer token comes from the encrypted store."""
    path = config_path or CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Run 'container-host-aiops init' to set up a Docker or Portainer "
            f"target, or create {CONFIG_FILE} with a 'targets' list."
        )

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    targets = tuple(
        TargetConfig(
            name=t["name"],
            platform=t.get("platform", DOCKER),
            socket_path=t.get("socket_path", ""),
            host=t.get("host", ""),
            port=t.get("port", 0),
            base_url=t.get("base_url", ""),
            endpoint_id=str(t.get("endpoint_id", "")),
            verify_ssl=t.get("verify_ssl", True),
        )
        for t in raw.get("targets", [])
    )

    return AppConfig(targets=targets)
