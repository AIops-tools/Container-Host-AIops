"""MCP-layer coverage: the shared error/connection plumbing, the write-tool
dry-run + undo descriptors, and the analysis-tool live-pull branches.

Governed tools write real audit/undo rows, so tests that invoke them bind the
harness to a throwaway ``CONTAINER_HOST_AIOPS_HOME`` and stub ``_get_connection``
at the tool-module boundary — no live socket, no real Docker call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import container_host_aiops.governance.audit as audit_mod
import container_host_aiops.governance.policy as policy_mod
import container_host_aiops.governance.undo as undo_mod
from mcp_server import _shared
from mcp_server.tools import writes as gov_writes


@pytest.fixture
def gov_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTAINER_HOST_AIOPS_HOME", str(tmp_path))
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
    yield tmp_path
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()


# ── _shared: error sanitisation + tool_errors shapes ─────────────────────────


@pytest.mark.unit
def test_safe_error_passes_through_known_types():
    msg = _shared._safe_error(ValueError("bad target 'x'"), "t")
    assert "bad target" in msg


@pytest.mark.unit
def test_safe_error_masks_unexpected_types():
    msg = _shared._safe_error(RuntimeError("secret internal detail"), "t")
    assert msg == "RuntimeError: operation failed."
    assert "secret internal detail" not in msg


@pytest.mark.unit
def test_tool_errors_dict_shape():
    @_shared.tool_errors("dict")
    def boom() -> dict:
        raise ValueError("nope")

    out = boom()
    assert out["error"]
    assert "doctor" in out["hint"].lower()


@pytest.mark.unit
def test_tool_errors_list_shape():
    @_shared.tool_errors("list")
    def boom() -> list:
        raise ValueError("nope")

    out = boom()
    assert isinstance(out, list)
    assert out[0]["error"]


@pytest.mark.unit
def test_tool_errors_str_shape():
    @_shared.tool_errors("str")
    def boom() -> str:
        raise ValueError("nope")

    out = boom()
    assert out.startswith("Error:")


@pytest.mark.unit
def test_get_connection_lazily_builds_manager_from_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("targets:\n  - name: local\n    platform: docker\n")
    monkeypatch.setenv("CONTAINER_HOST_AIOPS_CONFIG", str(cfg_file))
    monkeypatch.setattr(_shared, "_conn_mgr", None)
    conn = _shared._get_connection()
    assert conn.target.name == "local"
    conn.close()


# ── write tools: undo descriptors (pure) ─────────────────────────────────────


@pytest.mark.unit
def test_stop_undo_emits_start_inverse_when_was_running():
    undo = gov_writes._stop_undo(
        {"container_id": "abc"}, {"priorState": {"running": True}}
    )
    assert undo["tool"] == "start_container"
    assert undo["params"] == {"container_id": "abc"}


@pytest.mark.unit
def test_stop_undo_returns_none_when_not_running_or_bad_result():
    assert gov_writes._stop_undo({"container_id": "a"}, {"priorState": {"running": False}}) is None
    assert gov_writes._stop_undo({"container_id": "a"}, "not-a-dict") is None


@pytest.mark.unit
def test_start_undo_emits_stop_inverse():
    undo = gov_writes._start_undo({"container_id": "abc"}, {"ok": 1})
    assert undo["tool"] == "stop_container"
    assert undo["params"] == {"container_id": "abc"}
    assert gov_writes._start_undo({"container_id": "a"}, None) is None


@pytest.mark.unit
def test_update_undo_restores_prior_limits():
    undo = gov_writes._update_undo(
        {"container_id": "abc"}, {"priorState": {"Memory": 1000}}
    )
    assert undo["tool"] == "update_container"
    assert undo["params"] == {"container_id": "abc", "resources": {"Memory": 1000}}
    assert gov_writes._update_undo({"container_id": "a"}, {"priorState": {}}) is None


# ── write tools: dry-run previews go through governance, fire no API call ─────


@pytest.mark.unit
def test_stop_container_dry_run_previews_without_calling(gov_home, monkeypatch):
    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov_writes, "_get_connection", lambda target=None: conn)
    out = gov_writes.stop_container(container_id="abc", dry_run=True)
    assert out["dryRun"] is True
    assert out["wouldStop"] == {"container_id": "abc"}
    conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_remove_container_dry_run_reports_flags(gov_home, monkeypatch):
    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov_writes, "_get_connection", lambda target=None: conn)
    out = gov_writes.remove_container(container_id="abc", force=True, dry_run=True)
    assert out["dryRun"] is True
    assert out["wouldRemove"]["force"] is True
    conn.docker_delete.assert_not_called()


@pytest.mark.unit
def test_prune_images_dry_run_lists_reclaimable(gov_home, monkeypatch):
    conn = MagicMock(name="conn")
    conn.docker_get.return_value = [{"Id": "sha256:a", "Size": 700}]
    monkeypatch.setattr(gov_writes, "_get_connection", lambda target=None: conn)
    out = gov_writes.prune_images(dry_run=True)
    assert out["dryRun"] is True
    assert out["reclaimableBytes"] == 700
    conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_prune_volumes_dry_run_lists_reclaimable(gov_home, monkeypatch):
    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {
        "Volumes": [{"Name": "v", "UsageData": {"RefCount": 0, "Size": 250}}]
    }
    monkeypatch.setattr(gov_writes, "_get_connection", lambda target=None: conn)
    out = gov_writes.prune_volumes(dry_run=True)
    assert out["dryRun"] is True
    assert out["reclaimableBytes"] == 250


@pytest.mark.unit
def test_update_container_dry_run_previews(gov_home, monkeypatch):
    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov_writes, "_get_connection", lambda target=None: conn)
    out = gov_writes.update_container(
        container_id="abc", resources={"Memory": 2000}, dry_run=True
    )
    assert out["dryRun"] is True
    assert out["wouldUpdate"]["resources"] == {"Memory": 2000}
    conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_restart_container_dry_run_previews(gov_home, monkeypatch):
    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov_writes, "_get_connection", lambda target=None: conn)
    out = gov_writes.restart_container(container_id="abc", dry_run=True)
    assert out["dryRun"] is True
    conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_start_container_dry_run_previews(gov_home, monkeypatch):
    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov_writes, "_get_connection", lambda target=None: conn)
    out = gov_writes.start_container(container_id="abc", dry_run=True)
    assert out["dryRun"] is True
    conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_recreate_stack_dry_run_previews(gov_home, monkeypatch):
    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov_writes, "_get_connection", lambda target=None: conn)
    out = gov_writes.recreate_stack(stack_id="3", dry_run=True)
    assert out["dryRun"] is True
    assert out["wouldRecreate"]["stack_id"] == "3"


# ── analysis tools: live-pull branches (containers/samples omitted) ──────────


@pytest.mark.unit
def test_restart_loop_rca_pulls_live_when_no_containers(gov_home, monkeypatch):
    from mcp_server.tools import analyses as gov

    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    rows = [{"id": "a", "name": "loopy", "state": "restarting",
             "restartCount": 5, "exitCode": 137, "oomKilled": True}]
    monkeypatch.setattr(gov.ops, "pull_restart_data", lambda c: (rows, {"a": ["boom"]}))
    out = gov.restart_loop_rca()
    assert out["loopingCount"] == 1
    assert "memory" in out["looping"][0]["cause"].lower()


@pytest.mark.unit
def test_resource_pressure_pulls_live_when_no_samples(gov_home, monkeypatch):
    from mcp_server.tools import analyses as gov

    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    samples = [{"id": "a", "name": "hot", "cpuPercent": 95.0, "memPercent": 30.0,
                "memUsageBytes": 3, "memLimitBytes": 10}]
    monkeypatch.setattr(gov.ops, "pull_resource_pressure", lambda c: samples)
    out = gov.resource_pressure_analysis()
    assert out["overThresholdCount"] == 1
    assert out["ranked"][0]["name"] == "hot"


@pytest.mark.unit
def test_image_and_volume_bloat_pulls_live_when_no_payloads(gov_home, monkeypatch):
    from mcp_server.tools import analyses as gov

    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    monkeypatch.setattr(gov.ops, "pull_bloat", lambda c: {"totalReclaimableBytes": 42})
    out = gov.image_and_volume_bloat()
    assert out["totalReclaimableBytes"] == 42


@pytest.mark.unit
def test_image_and_volume_bloat_pure_when_payloads_given(gov_home, monkeypatch):
    from mcp_server.tools import analyses as gov

    monkeypatch.setattr(gov, "_get_connection",
                        lambda target=None: pytest.fail("must not pull"))
    out = gov.image_and_volume_bloat(
        dangling_images={"danglingCount": 1, "reclaimableBytes": 100},
        dangling_volumes={"danglingCount": 0, "reclaimableBytes": 0},
        df={"buildCache": {"count": 0, "totalBytes": 0}},
    )
    assert out["totalReclaimableBytes"] == 100


# ── image read tools: thin governed wrappers over ops ────────────────────────


@pytest.mark.unit
def test_image_read_tools_delegate_to_ops(gov_home, monkeypatch):
    from mcp_server.tools import images as gov

    conn = MagicMock(name="conn")
    conn.docker_get.return_value = [{"Id": "sha256:a", "RepoTags": ["app:1"], "Size": 100}]
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    out = gov.list_images()
    assert out["total"] == 1

    conn.docker_get.return_value = {"Volumes": []}  # for dangling path via /system/df
    conn.docker_get.return_value = {
        "Images": [{"Size": 500, "SharedSize": 100, "Containers": 0}]
    }
    usage = gov.image_disk_usage()
    assert usage["reclaimableBytes"] == 400
