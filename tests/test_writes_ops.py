"""Write-path ops tests (ops/writes.py) — pure, over a mocked connection.

Each guarded write reads the host's before-state through the connection, fires
the correct Docker Engine / libpod endpoint with the right args, and returns a
descriptor carrying the captured prior state for the audit / undo trail. A
``MagicMock`` connection stands in for a live Docker socket: every assertion pins
the exact path + params the write POSTs/DELETEs, so a wrong endpoint or a lost
before-state fails the test.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from container_host_aiops.ops import writes


def _conn(inspect=None, post=None, get=None):
    conn = MagicMock(name="conn")
    conn.docker_get.return_value = inspect if inspect is not None else {}
    conn.docker_post.return_value = post if post is not None else {}
    conn.docker_delete.return_value = {}
    if get is not None:
        conn.get.return_value = get
    return conn


@pytest.mark.unit
def test_restart_container_captures_prior_and_posts_restart():
    conn = _conn(inspect={"Name": "/web", "State": {"Running": True, "Status": "running"}})
    out = writes.restart_container(conn, "web", timeout=5)
    assert out["action"] == "restart_container"
    assert out["name"] == "web"
    assert out["priorState"] == {"running": True, "status": "running"}
    conn.docker_post.assert_called_once()
    assert conn.docker_post.call_args.args[0] == "/containers/web/restart"
    assert conn.docker_post.call_args.kwargs["params"] == {"t": "5"}


@pytest.mark.unit
def test_restart_negative_timeout_is_clamped_to_zero():
    conn = _conn(inspect={"Name": "/x", "State": {}})
    writes.restart_container(conn, "x", timeout=-9)
    assert conn.docker_post.call_args.kwargs["params"] == {"t": "0"}


@pytest.mark.unit
def test_stop_container_defaults_running_true_when_unknown():
    # No State in inspect → priorState.running defaults to True (was running).
    conn = _conn(inspect={"Name": "/db"})
    out = writes.stop_container(conn, "db")
    assert out["action"] == "stop_container"
    assert out["priorState"] == {"running": True}
    assert conn.docker_post.call_args.args[0] == "/containers/db/stop"


@pytest.mark.unit
def test_start_container_captures_prior_running_false():
    conn = _conn(inspect={"Name": "/db", "State": {"Running": False}})
    out = writes.start_container(conn, "db")
    assert out["action"] == "start_container"
    assert out["priorState"] == {"running": False}
    assert conn.docker_post.call_args.args[0] == "/containers/db/start"


@pytest.mark.unit
def test_inspect_before_state_is_best_effort_and_never_raises():
    # An inspect that blows up must degrade to an empty prior, not propagate.
    conn = MagicMock(name="conn")
    conn.docker_get.side_effect = RuntimeError("socket gone")
    conn.docker_post.return_value = {}
    out = writes.stop_container(conn, "ghost")
    assert out["priorState"] == {"running": True}  # default when prior unknown
    assert out["name"] == ""  # empty prior inspect → no name recoverable
    assert out["id"] == "ghost"  # id still echoed for the audit trail
    conn.docker_post.assert_called_once()  # the stop still fired


@pytest.mark.unit
def test_remove_container_captures_full_inspect_and_passes_force_flags():
    inspect = {"Id": "abc", "Name": "/gone", "State": {"Running": False}}
    conn = _conn(inspect=inspect)
    out = writes.remove_container(conn, "gone", force=True, remove_volumes=True)
    assert out["action"] == "remove_container"
    assert out["forced"] is True
    assert out["removedVolumes"] is True
    assert out["priorInspect"] == inspect
    conn.docker_delete.assert_called_once()
    assert conn.docker_delete.call_args.args[0] == "/containers/gone"
    assert conn.docker_delete.call_args.kwargs["params"] == {"force": "true", "v": "true"}


@pytest.mark.unit
def test_remove_container_default_flags_are_false_strings():
    conn = _conn(inspect={"Name": "/c"})
    writes.remove_container(conn, "c")
    assert conn.docker_delete.call_args.kwargs["params"] == {"force": "false", "v": "false"}


@pytest.mark.unit
def test_preview_prune_images_dangling_only_lists_candidates():
    conn = _conn(inspect={
        "/images/json": None,
    })
    # dangling_images reads /images/json with the dangling filter.
    conn.docker_get.return_value = [{"Id": "sha256:aa", "Size": 400}]
    out = writes.preview_prune_images(conn, dangling_only=True)
    assert out["danglingOnly"] is True
    assert out["wouldRemoveCount"] == 1
    assert out["reclaimableBytes"] == 400


@pytest.mark.unit
def test_preview_prune_images_non_dangling_uses_disk_usage():
    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {
        "Images": [{"Size": 1000, "SharedSize": 200, "Containers": 0}],
    }
    out = writes.preview_prune_images(conn, dangling_only=False)
    assert out["danglingOnly"] is False
    assert out["reclaimableBytes"] == 800
    assert "Non-dangling prune" in out["note"]


@pytest.mark.unit
def test_prune_images_reports_deleted_and_reclaimed():
    conn = MagicMock(name="conn")
    conn.docker_post.return_value = {
        "ImagesDeleted": [{"Deleted": "sha256:a"}, {"Deleted": "sha256:b"}],
        "SpaceReclaimed": 2048,
    }
    out = writes.prune_images(conn, dangling_only=True)
    assert out["action"] == "prune_images"
    assert out["deletedCount"] == 2
    assert out["spaceReclaimedBytes"] == 2048
    # The dangling filter is passed to /images/prune.
    assert conn.docker_post.call_args.args[0] == "/images/prune"
    assert conn.docker_post.call_args.kwargs["params"] == {"filters": '{"dangling":["true"]}'}


@pytest.mark.unit
def test_prune_images_non_dangling_filter():
    conn = MagicMock(name="conn")
    conn.docker_post.return_value = {}
    writes.prune_images(conn, dangling_only=False)
    assert conn.docker_post.call_args.kwargs["params"] == {"filters": '{"dangling":["false"]}'}


@pytest.mark.unit
def test_preview_prune_volumes_lists_dangling():
    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {
        "Volumes": [{"Name": "v1", "UsageData": {"RefCount": 0, "Size": 300}}],
    }
    out = writes.preview_prune_volumes(conn)
    assert out["wouldRemoveCount"] == 1
    assert out["reclaimableBytes"] == 300


@pytest.mark.unit
def test_prune_volumes_reports_deleted_and_reclaimed():
    conn = MagicMock(name="conn")
    conn.docker_post.return_value = {"VolumesDeleted": ["v1", "v2"], "SpaceReclaimed": 512}
    out = writes.prune_volumes(conn)
    assert out["action"] == "prune_volumes"
    assert out["deletedCount"] == 2
    assert out["spaceReclaimedBytes"] == 512
    assert conn.docker_post.call_args.args[0] == "/volumes/prune"


@pytest.mark.unit
def test_update_container_allowlists_keys_and_captures_prior_limits():
    inspect = {
        "Name": "/svc",
        "HostConfig": {"Memory": 1000, "NanoCpus": 2_000_000_000},
    }
    conn = _conn(inspect=inspect)
    # A disallowed key (Privileged) must be dropped; allowed keys kept.
    out = writes.update_container(
        conn, "svc", {"Memory": 2000, "NanoCpus": 4_000_000_000, "Privileged": True}
    )
    assert out["action"] == "update_container"
    assert out["changed"] == {"Memory": 2000, "NanoCpus": 4_000_000_000}
    assert "Privileged" not in out["changed"]
    # priorState restores the captured before-limits for undo.
    assert out["priorState"] == {"Memory": 1000, "NanoCpus": 2_000_000_000}
    assert conn.docker_post.call_args.args[0] == "/containers/svc/update"
    assert conn.docker_post.call_args.kwargs["json"] == {
        "Memory": 2000, "NanoCpus": 4_000_000_000,
    }


@pytest.mark.unit
def test_update_container_empty_resources_posts_empty_payload():
    conn = _conn(inspect={"Name": "/svc", "HostConfig": {}})
    out = writes.update_container(conn, "svc", {})
    assert out["changed"] == {}
    assert out["priorState"] == {}


@pytest.mark.unit
def test_recreate_stack_captures_prior_and_redeploys_with_endpoint():
    conn = MagicMock(name="conn")
    conn.get.return_value = {"Id": 3, "Name": "web", "EndpointId": 5}
    conn.put.return_value = {}
    out = writes.recreate_stack(conn, "3")
    assert out["action"] == "recreate_stack"
    assert out["name"] == "web"
    assert out["endpointId"] == 5  # inferred from the prior stack
    assert out["priorStack"]["Name"] == "web"
    assert conn.put.call_args.args[0] == "/api/stacks/3/git/redeploy"
    assert conn.put.call_args.kwargs["params"] == {"endpointId": "5"}


@pytest.mark.unit
def test_recreate_stack_prior_fetch_failure_degrades_to_empty():
    conn = MagicMock(name="conn")
    conn.get.side_effect = RuntimeError("no such stack")
    conn.put.return_value = {}
    out = writes.recreate_stack(conn, "9", endpoint_id="2")
    assert out["priorStack"] == {}
    assert out["endpointId"] == "2"  # explicit override survives a missing prior
    assert out["name"] is None
    assert conn.put.call_args.kwargs["params"] == {"endpointId": "2"}


@pytest.mark.unit
def test_recreate_stack_no_endpoint_sends_no_params():
    conn = MagicMock(name="conn")
    conn.get.return_value = {"Id": 1, "Name": "x"}  # no EndpointId anywhere
    conn.put.return_value = {}
    out = writes.recreate_stack(conn, "1")
    assert out["endpointId"] is None
    assert conn.put.call_args.kwargs["params"] is None
