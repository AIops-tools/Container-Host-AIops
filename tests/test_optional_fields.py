"""Absent fields come back as null, not as an empty string.

An empty string reads as "this field exists and is empty"; a missing field is a
different fact. The Docker Engine routinely omits keys it has nothing to say
about — a created-but-never-started container has no ``Status``, a dangling
image has no ``RepoTags`` — and collapsing that into ``""`` hides it from the
caller. A smaller local model will confidently invent the difference, and an
empty id string in particular reads as a real, blank identifier.

These tests pin the contract end-to-end: the helpers, the ops normalisers, and
the consumers (the restart-loop log fetch especially) that now see a null.
"""

from __future__ import annotations

import pytest

from container_host_aiops.config import TargetConfig
from container_host_aiops.governance import opt_str
from container_host_aiops.ops import analyses, containers, images, networks
from container_host_aiops.ops._util import container_name, opt, s, short_id


class _Conn:
    def __init__(self, responses, raw=None):
        self._responses = responses
        self._raw = raw or {}
        self.target = TargetConfig(name="t", platform="docker")

    def docker_get(self, path, params=None):
        return self._responses.get(path, {})

    def docker_get_raw(self, path, params=None):
        return self._raw.get(path, b"")


# ── the helper ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_opt_str_distinguishes_absent_from_empty():
    assert opt_str(None) is None, "absent must stay absent"
    assert opt_str("") == "", "a genuinely empty value is not the same as absent"
    assert opt_str("nginx", 64) == "nginx"


@pytest.mark.unit
def test_opt_str_still_sanitizes_and_truncates():
    assert opt_str("a\x00b") == "ab"  # control character stripped
    assert opt_str("abcdef", 3) == "abc"


@pytest.mark.unit
def test_opt_str_accepts_non_string_values():
    assert opt_str(42) == "42"


@pytest.mark.unit
def test_ops_opt_helper_preserves_absence_while_s_still_coerces():
    assert opt(None) is None
    assert s(None) == "", "s() keeps its always-present semantics"


# ── the id helpers ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_short_id_keeps_an_absent_id_absent():
    """A blank id string reads as a real identifier; null does not."""
    assert short_id(None) is None
    assert short_id("") == ""
    assert short_id("0123456789abcdef0123") == "0123456789ab"


@pytest.mark.unit
def test_container_name_is_null_when_nothing_identifies_the_container():
    assert container_name({}) is None
    assert container_name({"Names": ["/web"]}) == "web"
    assert container_name({"Name": "/db"}) == "db"


# ── the ops layer ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_container_row_reports_absent_fields_as_none():
    conn = _Conn({"/containers/json": [{"Id": "abc123def456789"}]})
    row = containers.list_containers(conn)["containers"][0]
    assert row["id"] == "abc123def456"
    assert row["image"] is None
    assert row["status"] is None


@pytest.mark.unit
def test_container_row_never_drops_the_key_itself():
    """Keys are always present; only their value may be null.

    Omitting a key entirely is worse than a null — the consumer cannot tell the
    field was even considered.
    """
    conn = _Conn({"/containers/json": [{}]})
    row = containers.list_containers(conn)["containers"][0]
    for key in ("id", "name", "image", "state", "status", "ports"):
        assert key in row, f"{key} must be present even when Docker omitted it"


@pytest.mark.unit
def test_network_row_with_no_id_is_null_not_blank():
    conn = _Conn({"/networks": [{"Name": "bridge"}]})
    assert networks.list_networks(conn)["networks"][0]["id"] is None


@pytest.mark.unit
def test_image_row_with_no_id_is_null_not_blank():
    conn = _Conn({"/images/json": [{"RepoTags": ["nginx:latest"]}]})
    assert images.list_images(conn)["images"][0]["id"] is None


@pytest.mark.unit
def test_image_id_still_has_the_sha256_prefix_stripped():
    conn = _Conn({"/images/json": [{"Id": "sha256:0123456789abcdef"}]})
    assert images.list_images(conn)["images"][0]["id"] == "0123456789ab"


# ── the consumers ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_restart_data_skips_rows_with_no_id_rather_than_fetching_none():
    """The regression this guards: a null id going down the wire as "None".

    ``pull_restart_data`` fetches logs per container id. A row whose id Docker
    never reported cannot be fetched — skipping it is right; interpolating
    ``None`` into the URL would request a container literally named "None".
    """
    requested: list[str] = []

    class _LogConn(_Conn):
        def docker_get_raw(self, path, params=None):
            requested.append(path)
            return b""

    conn = _LogConn({
        "/containers/json": [{}],  # no Id at all
        "/containers/None/json": {},
    })
    rows, logs = analyses.pull_restart_data(conn)
    assert logs == {}
    assert not any("None" in p for p in requested), "a null id must never be fetched"


# ── truncation announces itself ─────────────────────────────────────────────


@pytest.mark.unit
def test_container_logs_report_truncation_when_history_exceeds_the_tail():
    """Truncation is measured (tail+1 requested), not guessed from a length match."""
    raw = b"\n".join(f"line {i}".encode() for i in range(1, 7))
    conn = _Conn({}, raw={"/containers/abc/logs": raw})
    out = containers.container_logs(conn, "abc", tail=5)
    assert out["returned"] == 5
    assert out["limit"] == 5
    assert out["truncated"] is True, "6 lines available for a tail of 5 is truncated"
    assert out["lines"][-1] == "line 6", "the newest lines are the ones kept"


@pytest.mark.unit
def test_container_logs_are_not_marked_truncated_when_they_fit():
    raw = b"\n".join(f"line {i}".encode() for i in range(1, 4))
    conn = _Conn({}, raw={"/containers/abc/logs": raw})
    out = containers.container_logs(conn, "abc", tail=5)
    assert out["returned"] == 3 and out["truncated"] is False


@pytest.mark.unit
def test_container_logs_ask_docker_for_one_extra_line():
    """Without the +1 the count could never exceed the tail, so nothing would
    ever look truncated — the measurement depends on over-fetching by one."""
    seen: dict = {}

    class _P(_Conn):
        def docker_get_raw(self, path, params=None):
            seen.update(params or {})
            return b""

    conn = _P({})
    containers.container_logs(conn, "abc", tail=100)
    assert seen["tail"] == "101"


@pytest.mark.unit
def test_undo_list_envelope_measures_truncation(monkeypatch):
    from mcp_server.tools import undo as undo_tools

    rows = [
        {
            "undo_id": f"u{i}",
            "ts": "2026-07-18T00:00:00Z",
            "tool": "some_tool",
            "undo_tool": "some_inverse_tool",
            "note": "",
        }
        for i in range(4)
    ]
    captured = {}

    class _Store:
        def list(self, *, status=None, limit=50):
            captured["limit"] = limit
            return rows[:limit]

    monkeypatch.setattr(undo_tools, "get_undo_store", lambda: _Store())
    result = undo_tools.undo_list(limit=3)
    assert captured["limit"] == 4, "one extra row is fetched to measure truncation"
    assert result["returned"] == 3
    assert result["limit"] == 3
    assert result["truncated"] is True
    assert len(result["undos"]) == 3
