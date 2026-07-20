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
    # No name is recoverable from an empty prior inspect. That is reported as
    # null, not "" — an empty string reads as a container genuinely named "".
    assert out["name"] is None
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


# ── self-lockout guard: the Portainer container the target speaks through ────
#
# A Portainer target proxies every request through the Portainer container, which
# is also an ordinary row in this tool's container list. Stopping it kills the
# API mid-request and strands the start_container undo; removing it has no undo
# at all. These tests pin that the guard is EXACT (an ordinary container on the
# same Portainer target still stops) and FAILS OPEN (unknown is never "it is me").


def _portainer_conn(inspect, port=9443):
    """A conn whose target is a Portainer platform on ``port``."""
    conn = _conn(inspect=inspect)
    conn.target.platform = "portainer"
    conn.target.port = port
    return conn


@pytest.mark.unit
def test_stop_refuses_the_portainer_container_by_image():
    conn = _portainer_conn(
        {"Name": "/portainer", "Config": {"Image": "portainer/portainer-ce:2.19"}}
    )
    with pytest.raises(writes.SelfLockout) as exc:
        writes.stop_container(conn, "portainer")
    # The reason names the KNOWN image matched, not the container's own ref, so
    # a long registry path cannot push the remedy past the 300-char error cap.
    assert "portainer/portainer-ce" in str(exc.value)
    conn.docker_post.assert_not_called()  # refused BEFORE the API call


@pytest.mark.unit
def test_stop_refuses_the_portainer_container_by_published_port():
    # Untagged/renamed image, but it publishes the port this target connects to.
    inspect = {"Name": "/mgmt", "Config": {"Image": "internal/mgmt:1"},
               "NetworkSettings": {"Ports": {"9443/tcp": [{"HostPort": "9443"}]}}}
    conn = _portainer_conn(inspect, port=9443)
    with pytest.raises(writes.SelfLockout):
        writes.stop_container(conn, "mgmt")
    conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_remove_refuses_the_portainer_agent_container():
    conn = _portainer_conn({"Name": "/agent", "Config": {"Image": "portainer/agent"}})
    with pytest.raises(writes.SelfLockout):
        writes.remove_container(conn, "agent", force=True)
    conn.docker_delete.assert_not_called()


@pytest.mark.unit
def test_guard_is_exact_ordinary_container_on_portainer_target_still_stops():
    # Proves the guard discriminates: same Portainer target, different container.
    inspect = {"Name": "/web", "Config": {"Image": "nginx:1.27"}, "State": {"Running": True},
               "NetworkSettings": {"Ports": {"80/tcp": [{"HostPort": "8080"}]}}}
    conn = _portainer_conn(inspect, port=9443)
    out = writes.stop_container(conn, "web")
    assert out["action"] == "stop_container"
    conn.docker_post.assert_called_once()
    assert conn.docker_post.call_args.args[0] == "/containers/web/stop"


@pytest.mark.unit
def test_guard_is_exact_ordinary_container_on_portainer_target_still_removes():
    conn = _portainer_conn({"Name": "/web", "Config": {"Image": "nginx:1.27"}})
    out = writes.remove_container(conn, "web")
    assert out["action"] == "remove_container"
    conn.docker_delete.assert_called_once()


@pytest.mark.unit
def test_guard_fails_open_on_a_plain_docker_target():
    # Same image, but a direct Docker socket target is NOT proxied through it.
    conn = _conn(inspect={"Name": "/portainer", "Config": {"Image": "portainer/portainer-ce"}})
    conn.target.platform = "docker"
    conn.target.port = 9443
    out = writes.stop_container(conn, "portainer")
    assert out["action"] == "stop_container"
    conn.docker_post.assert_called_once()


@pytest.mark.unit
def test_guard_fails_open_when_the_inspect_call_fails():
    # Identity unknowable → proceed. An unknown container is never assumed to be
    # the API; refusing on an empty inspect would block every write whenever the
    # inspect endpoint hiccups.
    conn = MagicMock(name="conn")
    conn.docker_get.side_effect = RuntimeError("socket gone")
    conn.docker_post.return_value = {}
    conn.target.platform = "portainer"
    conn.target.port = 9443
    out = writes.stop_container(conn, "portainer")
    assert out["action"] == "stop_container"
    conn.docker_post.assert_called_once()


@pytest.mark.unit
def test_guard_fails_open_when_target_carries_no_port():
    conn = _portainer_conn({"Name": "/x", "Config": {"Image": "internal/mgmt"},
                            "NetworkSettings": {"Ports": {"9443/tcp": [{"HostPort": "9443"}]}}},
                           port=0)
    out = writes.stop_container(conn, "x")
    assert out["action"] == "stop_container"


@pytest.mark.unit
def test_image_repo_strips_tag_and_digest_but_keeps_registry_port():
    assert writes._image_repo("portainer/portainer-ce:2.19.4") == "portainer/portainer-ce"
    assert writes._image_repo("portainer/portainer-ce@sha256:ab") == "portainer/portainer-ce"
    assert writes._image_repo("reg.local:5000/portainer/portainer-ee") == (
        "reg.local:5000/portainer/portainer-ee"
    )


@pytest.mark.unit
def test_guard_reads_list_row_port_shape_too():
    # /containers/json rows carry PublicPort ints rather than a bindings dict.
    conn = _portainer_conn({"Names": ["/mgmt"], "Image": "internal/mgmt",
                            "Ports": [{"PrivatePort": 9443, "PublicPort": 9443}]})
    with pytest.raises(writes.SelfLockout):
        writes.remove_container(conn, "mgmt")


@pytest.mark.unit
def test_refusal_messages_survive_the_300_char_cap():
    """The remedy sentence must reach the caller.

    ``mcp_server._shared._safe_error`` passes a ValueError through but sanitizes
    it to 300 characters, and the "use a docker target instead" instruction is
    the LAST thing in the message. If a cost string grows, the teaching tail is
    what gets cut — silently. A long registry path must not do it either.
    """
    long_ref = "registry.internal.example.com:5000/vendor/portainer/portainer-ee:2.19.4-alpine"
    for verb, call in (
        ("stop", lambda c: writes.stop_container(c, "portainer")),
        ("remove", lambda c: writes.remove_container(c, "portainer")),
    ):
        conn = _portainer_conn({"Name": "/portainer", "Config": {"Image": long_ref}})
        with pytest.raises(writes.SelfLockout) as exc:
            call(conn)
        msg = str(exc.value)
        assert len(msg) <= 300, f"{verb} refusal is {len(msg)} chars; tail will be truncated"
        assert msg.rstrip().endswith("socket."), f"{verb} refusal lost its remedy sentence"


# ── dry-run must tell the truth about a refusal ─────────────────────────────
#
# A preview that reports wouldStop for a call the guard will then refuse is the
# preview being WRONG, not merely incomplete — and it is the weak-model trap
# this line designs against: green preview → refusal → the model reads the
# refusal as transient and retries. Fail-open semantics are identical on both
# paths, so a dry-run can never refuse what the real call would allow.


@pytest.mark.unit
def test_dry_run_stop_refuses_the_portainer_container():
    conn = _portainer_conn({"Name": "/portainer", "Config": {"Image": "portainer/portainer-ce"}})
    with pytest.raises(writes.SelfLockout):
        writes.preview_stop_container(conn, "portainer")
    conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_dry_run_remove_refuses_the_portainer_container():
    conn = _portainer_conn({"Name": "/portainer", "Config": {"Image": "portainer/portainer-ee"}})
    with pytest.raises(writes.SelfLockout):
        writes.preview_remove_container(conn, "portainer", force=True)
    conn.docker_delete.assert_not_called()


@pytest.mark.unit
def test_dry_run_stop_is_exact_non_self_target_still_previews():
    conn = _portainer_conn({"Name": "/web", "Config": {"Image": "nginx:1.27"}})
    assert writes.preview_stop_container(conn, "web") == {"container_id": "web"}
    conn.docker_post.assert_not_called()  # a preview writes nothing either way


@pytest.mark.unit
def test_dry_run_remove_is_exact_non_self_target_still_previews():
    conn = _portainer_conn({"Name": "/web", "Config": {"Image": "nginx:1.27"}})
    out = writes.preview_remove_container(conn, "web", force=True, remove_volumes=True)
    assert out == {"container_id": "web", "force": True, "remove_volumes": True}
    conn.docker_delete.assert_not_called()


@pytest.mark.unit
def test_dry_run_fails_open_exactly_like_the_real_call():
    # Inspect fails → identity unknown → preview proceeds, matching stop_container.
    conn = MagicMock(name="conn")
    conn.docker_get.side_effect = RuntimeError("socket gone")
    conn.target.platform = "portainer"
    conn.target.port = 9443
    assert writes.preview_stop_container(conn, "portainer") == {"container_id": "portainer"}
    assert writes.preview_remove_container(conn, "portainer")["container_id"] == "portainer"
