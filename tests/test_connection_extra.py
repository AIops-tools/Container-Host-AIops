"""Connection-layer tests (connection.py) over an injected fake httpx client.

Covers the request pipeline (JSON parse, empty-body → {}, non-JSON → {}), the
teaching-error translation for every status class, transport-error wrapping, the
raw-base verb helpers (get/post/put/delete) and the Docker verb helpers
(docker_post / docker_delete), plus the ConnectionManager session cache. No live
socket is touched — a fake client records the method + path it is handed.
"""

from __future__ import annotations

import httpx
import pytest

from container_host_aiops.config import AppConfig, TargetConfig
from container_host_aiops.connection import (
    ConnectionManager,
    ContainerHostApiError,
    ContainerHostConnection,
)


class _Resp:
    def __init__(self, status=200, payload=None, content=b"{}", raise_json=False):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = "detail-body"
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


class _RecordingClient:
    """Returns a canned response and records the (method, path, kwargs) it saw."""

    def __init__(self, resp=None, error=None):
        self._resp = resp or _Resp()
        self._error = error
        self.calls: list[tuple] = []
        self.closed = False

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if self._error is not None:
            raise self._error
        return self._resp

    def close(self):
        self.closed = True


def _docker_conn(client):
    return ContainerHostConnection(TargetConfig(name="d1"), client=client)


# ── request pipeline / parsing ───────────────────────────────────────────────


@pytest.mark.unit
def test_request_parses_json_object():
    conn = _docker_conn(_RecordingClient(_Resp(200, {"ok": 1}, content=b"{}")))
    assert conn.get("/anything") == {"ok": 1}


@pytest.mark.unit
def test_empty_body_parses_to_empty_dict():
    conn = _docker_conn(_RecordingClient(_Resp(200, content=b"")))
    assert conn.get("/empty") == {}


@pytest.mark.unit
def test_non_json_body_degrades_to_empty_dict():
    conn = _docker_conn(_RecordingClient(_Resp(200, content=b"<html>", raise_json=True)))
    assert conn.get("/html") == {}


# ── teaching-error translation for every status class ────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,needle",
    [
        (401, "authentication/authorization failed"),
        (403, "authentication/authorization failed"),
        (409, "conflict"),
        (400, "validation error"),
        (422, "validation error"),
        (500, "server error"),
        (503, "server error"),
        (418, "api error"),  # generic fallthrough
    ],
)
def test_teaching_error_messages_per_status(status, needle):
    conn = _docker_conn(_RecordingClient(_Resp(status, content=b"boom")))
    with pytest.raises(ContainerHostApiError) as ei:
        conn.get("/x")
    assert needle in str(ei.value).lower()
    assert ei.value.status_code == status
    assert ei.value.path == "/x"


@pytest.mark.unit
def test_transport_error_is_wrapped_with_reachability_hint():
    client = _RecordingClient(error=httpx.ConnectError("refused"))
    conn = _docker_conn(client)
    with pytest.raises(ContainerHostApiError) as ei:
        conn.get("/x")
    msg = str(ei.value).lower()
    assert "could not reach" in msg
    # A unix-socket target names the socket path in the reachability hint.
    assert "socket" in msg


@pytest.mark.unit
def test_transport_error_on_tcp_target_names_api_base():
    target = TargetConfig(name="t", host="10.0.0.9", verify_ssl=False)
    conn = ContainerHostConnection(target, client=_RecordingClient(error=httpx.ReadTimeout("t")))
    with pytest.raises(ContainerHostApiError) as ei:
        conn.get("/x")
    assert "10.0.0.9" in str(ei.value)


# ── verb helpers ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_raw_base_verbs_use_unprefixed_path():
    client = _RecordingClient(_Resp(200, {"v": 1}))
    conn = _docker_conn(client)
    conn.get("/api/a")
    conn.post("/api/b", json={"x": 1})
    conn.put("/api/c")
    conn.delete("/api/d")
    methods = [(m, p) for (m, p, _k) in client.calls]
    assert methods == [
        ("GET", "/api/a"), ("POST", "/api/b"), ("PUT", "/api/c"), ("DELETE", "/api/d"),
    ]


@pytest.mark.unit
def test_docker_post_and_delete_apply_no_prefix_on_direct_docker():
    client = _RecordingClient(_Resp(200))
    conn = _docker_conn(client)
    conn.docker_post("/containers/x/stop", params={"t": "1"})
    conn.docker_delete("/containers/x")
    paths = [p for (_m, p, _k) in client.calls]
    assert paths == ["/containers/x/stop", "/containers/x"]


@pytest.mark.unit
def test_docker_post_prefixed_on_portainer_target():
    target = TargetConfig(name="p1", platform="portainer", host="h", endpoint_id="7")
    client = _RecordingClient(_Resp(200))
    conn = ContainerHostConnection(target, client=client)
    conn.docker_post("/containers/x/stop")
    assert client.calls[0][1] == "/api/endpoints/7/docker/containers/x/stop"


@pytest.mark.unit
def test_libpod_get_raises_on_docker_target():
    conn = _docker_conn(_RecordingClient(_Resp(200)))
    with pytest.raises(ValueError, match="Podman-only"):
        conn.libpod_get("/pods/json")


@pytest.mark.unit
def test_close_delegates_to_client():
    client = _RecordingClient(_Resp(200))
    conn = _docker_conn(client)
    conn.close()
    assert client.closed is True


# ── real client construction (no injected client) ────────────────────────────


@pytest.mark.unit
def test_build_client_for_unix_socket_target():
    # Building the httpx client for a uds target must not attempt to connect.
    conn = ContainerHostConnection(TargetConfig(name="d1"))
    assert conn.target.uses_unix_socket is True
    conn.close()


@pytest.mark.unit
def test_build_client_for_tcp_target():
    conn = ContainerHostConnection(TargetConfig(name="d2", host="127.0.0.1", verify_ssl=False))
    assert conn.target.uses_unix_socket is False
    conn.close()


# ── ConnectionManager session cache ──────────────────────────────────────────


@pytest.mark.unit
def test_connection_manager_caches_and_lists_and_disconnects():
    cfg = AppConfig(targets=(TargetConfig(name="a"), TargetConfig(name="b")))
    mgr = ConnectionManager(cfg)
    assert mgr.list_targets() == ["a", "b"]
    assert mgr.list_connected() == []

    first = mgr.connect()  # default target = a
    again = mgr.connect("a")
    assert first is again  # cached, same session reused
    assert mgr.list_connected() == ["a"]

    named = mgr.connect("b")
    assert named is not first
    assert set(mgr.list_connected()) == {"a", "b"}

    mgr.disconnect("a")
    assert mgr.list_connected() == ["b"]
    mgr.disconnect_all()
    assert mgr.list_connected() == []
    # Disconnecting an unknown target is a no-op.
    mgr.disconnect("nope")


@pytest.mark.unit
def test_connection_manager_from_config_uses_given_config():
    cfg = AppConfig(targets=(TargetConfig(name="only"),))
    mgr = ConnectionManager.from_config(cfg)
    assert mgr.list_targets() == ["only"]
