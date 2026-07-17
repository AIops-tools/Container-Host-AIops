"""Connection management for container hosts (Docker Engine API / Portainer).

A single :class:`ContainerHostConnection` speaks the protocol of its target's
platform:

  * **Docker** — the Docker Engine API. Over a **unix socket** the httpx client
    uses ``httpx.HTTPTransport(uds=...)`` against a dummy ``http://localhost``
    base; over TCP it uses the real ``host:port``. Docker list endpoints
    (``/containers/json`` …) return bare JSON arrays; inspect endpoints return
    objects; ``/containers/{id}/logs`` returns a raw (optionally multiplexed)
    byte stream.
  * **Portainer** — the Portainer management API with an ``X-API-Key`` header.
    Portainer also *proxies* the Docker Engine API of each managed endpoint under
    ``/api/endpoints/{id}/docker/...``; the ``docker_*`` methods prepend that
    prefix automatically so the same container/image/volume reads work through
    Portainer.
  * **Podman** — a Podman service socket. Its Docker-compatible endpoints live at
    the root (unprefixed), so the ``docker_*`` helpers reuse the Docker paths
    unchanged; ``libpod_get`` reaches the Podman-only libpod endpoints (pods) via
    the platform's libpod prefix.

The ``docker_*`` helpers apply the platform's Docker path prefix; the plain
``get``/``post`` helpers hit the raw base (used for the Portainer management API).
All non-2xx responses are translated centrally into ``ContainerHostApiError``
with a teaching message.

The httpx client is injectable for tests: pass ``client=`` to substitute a mock
implementing ``request`` / ``close``. No live Docker socket is needed in tests.
"""

from __future__ import annotations

from typing import Any

import httpx

from container_host_aiops.config import AppConfig, TargetConfig, load_config

_TIMEOUT = 30.0


class ContainerHostApiError(Exception):
    """A Docker/Portainer call failed; carries a teaching message + status code."""

    def __init__(self, message: str, *, status_code: int | None = None, path: str = "") -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(message)


def _teaching_message(status: int, path: str, body: str, label: str) -> str:
    """Map a non-2xx status to an actionable, teaching error message."""
    snippet = body[:200].strip()
    if status in (401, 403):
        return (
            f"Authentication/authorization failed ({status}) on {label} {path}. "
            f"For Portainer check the X-API-Key token and the user's access to the "
            f"endpoint; for a Docker socket check the socket's file permissions. {snippet}"
        )
    if status == 404:
        return (
            f"Resource not found (404) on {label} {path}. The container/image/volume "
            f"id or name may be stale — list the collection first. {snippet}"
        )
    if status == 409:
        return (
            f"Conflict (409) on {label} {path}. The resource is in a state that "
            f"blocks this operation (e.g. removing a running container without "
            f"force, or a name already in use). {snippet}"
        )
    if status in (400, 422):
        return (
            f"Validation error ({status}) on {label} {path}. The host rejected the "
            f"request body — check required fields and value formats. {snippet}"
        )
    if status in (500, 502, 503, 504):
        return (
            f"{label} server error ({status}) on {path}. The host may be busy; "
            f"retry shortly. {snippet}"
        )
    return f"{label} API error ({status}) on {path}. {snippet}"


class ContainerHostConnection:
    """A single session against one container host (Docker daemon or Portainer)."""

    def __init__(self, target: TargetConfig, client: Any | None = None) -> None:
        self._target = target
        self._client = client or self._build_client(target)

    @staticmethod
    def _build_client(target: TargetConfig) -> httpx.Client:
        headers = target.platform_obj.auth_headers(target.secret)
        if target.uses_unix_socket:
            transport = httpx.HTTPTransport(uds=target.socket_path)
            return httpx.Client(
                base_url=target.api_base, transport=transport,
                timeout=_TIMEOUT, headers=headers,
            )
        return httpx.Client(
            base_url=target.api_base, verify=target.verify_ssl,
            timeout=_TIMEOUT, headers=headers,
        )

    @property
    def target(self) -> TargetConfig:
        return self._target

    def _docker_prefix(self) -> str:
        return self._target.platform_obj.docker_prefix(self._target.endpoint_id)

    # ── raw transport ─────────────────────────────────────────────────────
    def _raw_request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Issue a request and return the raw response, translating transport errors."""
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            where = (
                f"unix socket {self._target.socket_path}"
                if self._target.uses_unix_socket
                else self._target.api_base
            )
            raise ContainerHostApiError(
                f"Could not reach {self._target.platform_obj.label} at {where} "
                f"({method} {path}): {exc}. Check the socket path / host and that "
                f"the API is reachable.",
                path=path,
            ) from exc

    def _raise_for_status(self, resp: Any, path: str) -> None:
        if not (200 <= resp.status_code < 300):
            raise ContainerHostApiError(
                _teaching_message(
                    resp.status_code, path, getattr(resp, "text", ""),
                    self._target.platform_obj.label,
                ),
                status_code=resp.status_code,
                path=path,
            )

    @staticmethod
    def _parse(resp: Any) -> Any:
        if not getattr(resp, "content", b""):
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Issue a request against the raw base and return parsed JSON."""
        resp = self._raw_request(method, path, **kwargs)
        self._raise_for_status(resp, path)
        return self._parse(resp)

    def request_raw(self, method: str, path: str, **kwargs: Any) -> bytes:
        """Issue a request against the raw base and return the response bytes."""
        resp = self._raw_request(method, path, **kwargs)
        self._raise_for_status(resp, path)
        return getattr(resp, "content", b"") or b""

    # ── raw base helpers (Portainer management API) ──────────────────────
    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    # ── Docker Engine API helpers (prefixed for a proxying platform) ─────
    def docker_get(self, path: str, params: dict | None = None) -> Any:
        return self.request("GET", self._docker_prefix() + path, params=params)

    def docker_get_raw(self, path: str, params: dict | None = None) -> bytes:
        return self.request_raw("GET", self._docker_prefix() + path, params=params)

    def docker_post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", self._docker_prefix() + path, **kwargs)

    def docker_delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", self._docker_prefix() + path, **kwargs)

    # ── libpod-native helpers (Podman-only endpoints, e.g. pods) ─────────
    def libpod_get(self, path: str, params: dict | None = None) -> Any:
        """GET a libpod-native endpoint (raises for a non-Podman target)."""
        return self.request("GET", self._target.platform_obj.libpod_path(path), params=params)

    def close(self) -> None:
        self._client.close()


class ConnectionManager:
    """Manages connections to multiple container-host targets with session reuse."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._connections: dict[str, ContainerHostConnection] = {}

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        cfg = config or load_config()
        return cls(cfg)

    def connect(self, target_name: str | None = None) -> ContainerHostConnection:
        """Connect to a target by name, or the default target."""
        target = (
            self._config.get_target(target_name)
            if target_name
            else self._config.default_target
        )
        cached = self._connections.get(target.name)
        if cached is not None:
            return cached
        conn = ContainerHostConnection(target)
        self._connections[target.name] = conn
        return conn

    def disconnect(self, target_name: str) -> None:
        conn = self._connections.pop(target_name, None)
        if conn is not None:
            conn.close()

    def disconnect_all(self) -> None:
        for name in list(self._connections):
            self.disconnect(name)

    def list_targets(self) -> list[str]:
        return [t.name for t in self._config.targets]

    def list_connected(self) -> list[str]:
        return list(self._connections.keys())
