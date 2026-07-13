"""Platform registry + connection wiring (Docker uds/tcp, Portainer) + config."""

import pytest

from container_host_aiops.config import TargetConfig
from container_host_aiops.connection import ContainerHostApiError, ContainerHostConnection
from container_host_aiops.platform import (
    DOCKER,
    PORTAINER,
    get_platform,
    platform_names,
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
        get_platform("podman")


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
