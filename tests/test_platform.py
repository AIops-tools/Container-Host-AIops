"""Platform registry + connection wiring (Docker uds/tcp, Portainer) + config."""

import pytest

from container_host_aiops.config import TargetConfig
from container_host_aiops.connection import ContainerHostApiError, ContainerHostConnection
from container_host_aiops.platform import (
    DOCKER,
    LIBPOD_PREFIX,
    PODMAN,
    PORTAINER,
    default_podman_socket,
    get_platform,
    platform_names,
    podman_socket_candidates,
)


@pytest.mark.unit
def test_docker_and_portainer_registered():
    assert DOCKER in platform_names()
    assert PORTAINER in platform_names()
    assert get_platform(DOCKER).label == "Docker Engine API"
    assert get_platform(PORTAINER).label == "Portainer API"


@pytest.mark.unit
def test_unknown_platform_raises_with_registered_names():
    with pytest.raises(ValueError, match="docker"):
        get_platform("kubernetes")


@pytest.mark.unit
def test_portainer_auth_header_and_docker_prefix():
    p = get_platform(PORTAINER)
    assert p.auth_headers("TOK")["X-API-Key"] == "TOK"
    assert p.docker_prefix("2") == "/api/endpoints/2/docker"
    with pytest.raises(ValueError, match="endpoint_id"):
        p.docker_prefix("")


@pytest.mark.unit
def test_docker_platform_no_auth_and_empty_prefix():
    p = get_platform(DOCKER)
    assert "X-API-Key" not in p.auth_headers("ignored")
    assert p.docker_prefix() == ""


# ── podman platform ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_podman_registered_with_label():
    assert PODMAN in platform_names()
    assert "Podman" in get_platform(PODMAN).label


@pytest.mark.unit
def test_podman_reuses_docker_compat_layer_no_auth_no_prefix():
    """Podman's compat endpoints sit at the root — same as Docker, so the
    docker_* path templates are reused wholesale (empty prefix, no auth)."""
    p = get_platform(PODMAN)
    assert p.proxies_docker is False
    assert p.docker_prefix() == ""
    assert "X-API-Key" not in p.auth_headers("ignored")


@pytest.mark.unit
def test_podman_supports_libpod_and_prefixes_native_path():
    p = get_platform(PODMAN)
    assert p.supports_libpod is True
    assert p.libpod_path("/pods/json") == f"{LIBPOD_PREFIX}/pods/json"


@pytest.mark.unit
def test_libpod_path_raises_on_docker_and_portainer():
    for name in (DOCKER, PORTAINER):
        p = get_platform(name)
        assert p.supports_libpod is False
        with pytest.raises(ValueError, match="Podman-only"):
            p.libpod_path("/pods/json")


@pytest.mark.unit
def test_podman_socket_autodetection_order_prefers_rootless(monkeypatch, tmp_path):
    """With XDG_RUNTIME_DIR set, the rootless socket is probed before rootful."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    candidates = podman_socket_candidates()
    assert candidates[0] == str(tmp_path / "podman/podman.sock")
    assert candidates[-1] == "/run/podman/podman.sock"


@pytest.mark.unit
def test_default_podman_socket_returns_existing_rootless(monkeypatch, tmp_path):
    sock = tmp_path / "podman" / "podman.sock"
    sock.parent.mkdir(parents=True)
    sock.write_text("")  # stand-in for the socket file
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert default_podman_socket() == str(sock)


@pytest.mark.unit
def test_default_podman_socket_falls_back_to_rootful(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert default_podman_socket() == "/run/podman/podman.sock"


@pytest.mark.unit
def test_podman_target_defaults_to_autodetected_socket(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    t = TargetConfig(name="pod1", platform="podman")
    assert t.platform == "podman"
    assert t.uses_unix_socket is True
    assert t.socket_path == "/run/podman/podman.sock"
    assert t.api_base == "http://localhost"
    assert t.requires_secret is False


@pytest.mark.unit
def test_podman_tcp_target_builds_host_base():
    t = TargetConfig(name="pod2", platform="podman", host="10.0.0.9", verify_ssl=False)
    assert t.uses_unix_socket is False
    assert t.api_base == "http://10.0.0.9:2375"


@pytest.mark.unit
def test_podman_libpod_get_prepends_libpod_prefix():
    target = TargetConfig(name="pod1", platform="podman")
    seen = {}

    class _Client:
        def request(self, method, path, **k):
            seen["path"] = path
            return _Resp(200, [{"Id": "pod-a"}], content=b"[]")

        def close(self):
            pass

    conn = ContainerHostConnection(target, client=_Client())
    conn.libpod_get("/pods/json")
    assert seen["path"] == f"{LIBPOD_PREFIX}/pods/json"


@pytest.mark.unit
def test_podman_docker_get_uses_root_path_no_prefix():
    """A compat read on a podman target hits the unprefixed Docker path."""
    target = TargetConfig(name="pod1", platform="podman")
    seen = {}

    class _Client:
        def request(self, method, path, **k):
            seen["path"] = path
            return _Resp(200, [{"Id": "c1"}], content=b"[]")

        def close(self):
            pass

    conn = ContainerHostConnection(target, client=_Client())
    conn.docker_get("/containers/json")
    assert seen["path"] == "/containers/json"


@pytest.mark.unit
def test_docker_target_defaults_to_unix_socket():
    t = TargetConfig(name="d1")
    assert t.platform == "docker"
    assert t.uses_unix_socket is True
    assert t.socket_path == "/var/run/docker.sock"
    assert t.api_base == "http://localhost"
    assert t.requires_secret is False
    assert t.secret == ""


@pytest.mark.unit
def test_docker_tcp_target_builds_host_base():
    t = TargetConfig(name="d2", host="10.0.0.5", verify_ssl=False)
    assert t.uses_unix_socket is False
    assert t.api_base == "http://10.0.0.5:2375"


@pytest.mark.unit
def test_portainer_target_requires_secret_and_https():
    t = TargetConfig(name="p1", platform="portainer", host="portainer.local", endpoint_id="1")
    assert t.requires_secret is True
    assert t.port == 9443
    assert t.api_base == "https://portainer.local:9443"


@pytest.mark.unit
def test_target_config_rejects_unknown_platform():
    with pytest.raises(ValueError):
        TargetConfig(name="x", platform="nope")


class _Resp:
    def __init__(self, status, payload=None, content=b"{}", body=b""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = "body"
        self._body = body

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.mark.unit
def test_docker_get_returns_json_and_translates_errors():
    target = TargetConfig(name="d1")

    class _Client:
        def request(self, method, path, **k):
            if path == "/containers/nope/json":
                return _Resp(404, content=b"x")
            return _Resp(200, [{"Id": "abc", "State": "running"}], content=b"[]")

        def close(self):
            pass

    conn = ContainerHostConnection(target, client=_Client())
    assert conn.docker_get("/containers/json")[0]["Id"] == "abc"
    with pytest.raises(ContainerHostApiError) as ei:
        conn.docker_get("/containers/nope/json")
    assert ei.value.status_code == 404
    assert "not found" in str(ei.value).lower()


@pytest.mark.unit
def test_portainer_docker_get_prepends_proxy_prefix():
    target = TargetConfig(name="p1", platform="portainer", host="h", endpoint_id="7")
    seen = {}

    class _Client:
        def request(self, method, path, **k):
            seen["path"] = path
            return _Resp(200, [{"Id": "z"}], content=b"[]")

        def close(self):
            pass

    conn = ContainerHostConnection(target, client=_Client())
    conn.docker_get("/containers/json")
    assert seen["path"] == "/api/endpoints/7/docker/containers/json"


@pytest.mark.unit
def test_request_raw_returns_bytes():
    target = TargetConfig(name="d1")

    class _Client:
        def request(self, method, path, **k):
            return _Resp(200, content=b"hello-bytes", body=b"hello-bytes")

        def close(self):
            pass

    # content is what request_raw returns
    conn = ContainerHostConnection(target, client=_Client())
    resp_bytes = conn.docker_get_raw("/containers/x/logs")
    assert resp_bytes == b"hello-bytes"


# ── URL-encoding of agent-supplied path segments ─────────────────────────────


@pytest.mark.unit
def test_path_traversal_ids_are_url_encoded():
    """An id carrying ``../`` must not reach the HTTP client as a raw path
    traversal — agent-supplied segments are URL-encoded before interpolation."""
    from unittest.mock import MagicMock

    from container_host_aiops.ops import writes as ops

    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {}
    ops.stop_container(conn, "../images/prune")
    path = conn.docker_post.call_args.args[0]
    assert "../" not in path and path.startswith("/containers/")

    conn2 = MagicMock(name="conn2")
    conn2.get.return_value = {}
    ops.recreate_stack(conn2, "../../endpoints/1", endpoint_id="9")
    path = conn2.put.call_args.args[0]
    assert "../" not in path and path.startswith("/api/stacks/")
