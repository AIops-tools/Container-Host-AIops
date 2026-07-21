"""Smoke + governance tests for container-host-aiops.

Proves: every module imports, the CLI Typer app builds and --help works, the MCP
server exposes the expected tools, EVERY MCP tool carries the harness marker
``_is_governed_tool``, the write tools carry the right risk_level, and the guarded
writes (undo capture of the fetched BEFORE-state, dry-run gating) behave. No real
Docker socket is needed — the connection is a MagicMock or a fake.
"""

import asyncio
import importlib
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

EXPECTED_TOOLS = {
    # system + overview
    "overview", "system_info", "system_version", "system_df", "system_events",
    # containers
    "list_containers", "inspect_container", "container_logs", "container_stats",
    "container_top", "container_restart_summary",
    # images
    "list_images", "inspect_image", "dangling_images", "image_disk_usage",
    # volumes
    "list_volumes", "inspect_volume", "dangling_volumes",
    # networks
    "list_networks", "inspect_network",
    # stacks (portainer) + compose rollup (docker/podman)
    "list_endpoints", "list_stacks", "stack_detail", "list_compose_stacks",
    # podman pods (podman-only)
    "list_pods",
    # flagship analyses
    "restart_loop_rca", "resource_pressure_analysis", "image_and_volume_bloat",
    # writes
    "restart_container", "stop_container", "start_container", "remove_container",
    "prune_images", "prune_volumes", "update_container", "recreate_stack",
}

WRITE_TOOLS = {
    "restart_container", "stop_container", "start_container", "remove_container",
    "prune_images", "prune_volumes", "update_container", "recreate_stack",
}

HIGH_RISK = {"remove_container", "prune_images", "prune_volumes", "recreate_stack"}
MEDIUM_RISK = {"restart_container", "stop_container", "start_container", "update_container"}


@pytest.mark.unit
def test_all_modules_import():
    for name in (
        "container_host_aiops",
        "container_host_aiops.config",
        "container_host_aiops.connection",
        "container_host_aiops.platform",
        "container_host_aiops.doctor",
        "container_host_aiops.secretstore",
        "container_host_aiops.ops.containers",
        "container_host_aiops.ops.images",
        "container_host_aiops.ops.volumes",
        "container_host_aiops.ops.networks",
        "container_host_aiops.ops.system",
        "container_host_aiops.ops.stacks",
        "container_host_aiops.ops.pods",
        "container_host_aiops.ops.analyses",
        "container_host_aiops.ops.writes",
        "container_host_aiops.ops.overview",
        "container_host_aiops.cli",
        "container_host_aiops.cli._root",
        "mcp_server.server",
        "mcp_server._shared",
        "mcp_server.tools.containers",
        "mcp_server.tools.images",
        "mcp_server.tools.volumes",
        "mcp_server.tools.networks",
        "mcp_server.tools.system",
        "mcp_server.tools.stacks",
        "mcp_server.tools.pods",
        "mcp_server.tools.analyses",
        "mcp_server.tools.writes",
    ):
        importlib.import_module(name)


@pytest.mark.unit
def test_version_matches_pyproject():
    """__version__ is single-sourced from package metadata; it must track
    pyproject.toml so a release bump can never ship a stale self-report."""
    import tomllib
    from pathlib import Path

    import container_host_aiops

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text("utf-8"))["project"]["version"]
    assert container_host_aiops.__version__ == expected


@pytest.mark.unit
def test_cli_app_builds_and_help_works():
    from container_host_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in ("container", "image", "volume", "network", "system", "stack",
                "pod", "analyze", "manage", "secret", "init", "overview", "doctor", "mcp"):
        assert sub in result.output


@pytest.mark.unit
def test_cli_leaf_help_triggers_lazy_imports():
    """Recurse into leaf commands so any broken lazy import surfaces."""
    from container_host_aiops.cli import app

    runner = CliRunner()
    for cmd in (
        ["container", "--help"], ["image", "--help"], ["volume", "--help"],
        ["network", "--help"], ["system", "--help"], ["stack", "--help"],
        ["pod", "--help"],
        ["analyze", "--help"], ["manage", "--help"], ["secret", "--help"],
        ["doctor", "--help"], ["overview", "--help"], ["init", "--help"],
        ["container", "list", "--help"], ["container", "logs", "--help"],
        ["container", "stats", "--help"], ["container", "restarts", "--help"],
        ["image", "list", "--help"], ["image", "dangling", "--help"],
        ["volume", "dangling", "--help"], ["network", "inspect", "--help"],
        ["system", "df", "--help"], ["system", "events", "--help"],
        ["stack", "list", "--help"], ["stack", "endpoints", "--help"],
        ["stack", "compose", "--help"], ["pod", "list", "--help"],
        ["analyze", "restart-loop", "--help"], ["analyze", "resource-pressure", "--help"],
        ["analyze", "bloat", "--help"],
        ["manage", "restart", "--help"], ["manage", "stop", "--help"],
        ["manage", "start", "--help"], ["manage", "remove", "--help"],
        ["manage", "prune-images", "--help"], ["manage", "prune-volumes", "--help"],
        ["manage", "update", "--help"], ["manage", "recreate-stack", "--help"],
        ["secret", "list", "--help"], ["secret", "set", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"


@pytest.mark.unit
def test_mcp_list_tools_exposes_expected_tools():
    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


@pytest.mark.unit
def test_every_mcp_tool_is_governed_by_harness():
    """Every registered tool callable must carry the @governed_tool marker."""
    from mcp_server import _shared

    tool_objs = _shared.mcp._tool_manager._tools
    assert EXPECTED_TOOLS <= set(tool_objs), "tool registry incomplete"
    for name, tool in tool_objs.items():
        fn = getattr(tool, "fn", None)
        assert fn is not None, f"{name} has no fn"
        assert getattr(fn, "_is_governed_tool", False), (
            f"{name} is not wrapped with @governed_tool (harness marker missing)"
        )


@pytest.mark.unit
def test_write_tools_have_correct_risk_tiers():
    from mcp_server.tools import writes as w

    for name in HIGH_RISK:
        assert getattr(w, name)._risk_level == "high", name
    for name in MEDIUM_RISK:
        assert getattr(w, name)._risk_level == "medium", name


@pytest.mark.unit
def test_risk_level_agrees_with_read_write_docstring_tag():
    """The two write-markers must never drift apart.

    A tool's ``risk_level`` decides its audit tier and whether it gets dry-run /
    undo handling; its ``[READ]``/``[WRITE]`` docstring tag is what the docs and
    capability tables are built from. If a ``[WRITE]`` were left ``risk_level=low``
    it would be audited as a read and skip the write machinery — this test caught
    16 such mislabels line-wide once, so it is kept even though read-only mode
    (its original motivation) is gone.
    """
    from mcp_server import server

    untagged, mismatched = [], []
    for name, tool in server.mcp._tool_manager._tools.items():
        doc = (tool.fn.__doc__ or "").lstrip()
        if doc.startswith("[READ]"):
            tagged_as_read = True
        elif doc.startswith("[WRITE]"):
            tagged_as_read = False
        else:
            untagged.append(name)
            continue
        if tagged_as_read != (getattr(tool.fn, "_risk_level", "low") == "low"):
            mismatched.append(name)

    assert not untagged, f"tools missing a [READ]/[WRITE] docstring tag: {untagged}"
    assert not mismatched, f"risk_level disagrees with the docstring tag: {mismatched}"


@pytest.mark.unit
def test_update_container_captures_before_state():
    """ops.update_container fetches the container first and records prior limits."""
    from container_host_aiops.ops import writes as ops

    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {
        "Name": "/svc", "HostConfig": {"Memory": 536870912, "NanoCpus": 0},
    }
    conn.docker_post.return_value = {}
    result = ops.update_container(conn, "svc", {"Memory": 999})
    assert result["action"] == "update_container"
    assert result["priorState"] == {"Memory": 536870912}
    conn.docker_post.assert_called_once_with("/containers/svc/update", json={"Memory": 999})


@pytest.mark.unit
def test_update_container_records_undo_via_harness(monkeypatch):
    """update_container through the harness records an inverse (restore prior limits)."""
    import container_host_aiops.governance.undo as undo_mod
    from mcp_server.tools import writes as w

    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {"Name": "/svc", "HostConfig": {"Memory": 536870912}}
    conn.docker_post.return_value = {}
    monkeypatch.setattr(w, "_get_connection", lambda target=None: conn)

    recorded = {}

    class _Store:
        def record(self, *, skill, tool, undo_descriptor, orig_params, effect_verified=True):
            recorded["verified"] = effect_verified
            recorded["descriptor"] = undo_descriptor
            return "undo-7"

    monkeypatch.setattr(undo_mod, "get_undo_store", lambda: _Store())

    result = w.update_container(container_id="svc", resources={"Memory": 999})
    assert "error" not in result
    assert recorded["descriptor"]["tool"] == "update_container"
    # the undo restores the fetched BEFORE value, not a guess
    assert recorded["descriptor"]["params"]["resources"]["Memory"] == 536870912
    assert result.get("_undo_id") == "undo-7"
    # A write that returned normally IS a confirmed change — the unverified
    # flag must be reserved for lost responses, or it means nothing.
    assert recorded["verified"] is True


@pytest.mark.unit
def test_stop_start_undo_pairing(monkeypatch):
    """stop records a start undo, and start records a stop undo (inverse pair)."""
    import container_host_aiops.governance.undo as undo_mod
    from mcp_server.tools import writes as w

    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {"Name": "/svc", "State": {"Running": True}}
    conn.docker_post.return_value = {}
    monkeypatch.setattr(w, "_get_connection", lambda target=None: conn)

    recorded = {}

    class _Store:
        def record(self, *, skill, tool, undo_descriptor, orig_params, effect_verified=True):
            recorded["verified"] = effect_verified
            recorded["d"] = undo_descriptor
            return "u1"

    monkeypatch.setattr(undo_mod, "get_undo_store", lambda: _Store())

    w.stop_container(container_id="svc")
    assert recorded["d"]["tool"] == "start_container"
    assert recorded["d"]["params"]["container_id"] == "svc"

    conn.docker_get.return_value = {"Name": "/svc", "State": {"Running": False}}
    w.start_container(container_id="svc")
    assert recorded["d"]["tool"] == "stop_container"


@pytest.mark.unit
def test_prune_images_dry_run_lists_candidates(monkeypatch):
    """prune_images dry_run lists what would be removed + reclaimable bytes, no post."""
    from mcp_server.tools import writes as w

    conn = MagicMock(name="conn")
    conn.docker_get.return_value = [{"Id": "sha256:x", "Size": 500}]
    monkeypatch.setattr(w, "_get_connection", lambda target=None: conn)

    out = w.prune_images(dangling_only=True, dry_run=True)
    assert out.get("dryRun") is True
    assert out.get("reclaimableBytes") == 500
    conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_dry_run_gates_destructive_cli(monkeypatch):
    """manage remove --dry-run previews without deleting.

    The invariant is "a dry_run MAY read; it must never write" — this preview
    reads so it can run the same guards as the real remove, and routes through
    the governed twin so it lands an audit row like any other call.
    """
    from container_host_aiops.cli import app
    from mcp_server.tools import writes as gov

    monkeypatch.setenv("CONTAINER_HOST_AUDIT_APPROVED_BY", "tester")
    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {"Id": "abc123", "Name": "/web"}
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)

    result = CliRunner().invoke(app, ["manage", "remove", "abc123", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    conn.docker_delete.assert_not_called()  # read yes, write never


@pytest.mark.unit
def test_mcp_write_dry_run_does_not_execute():
    """A write tool's dry_run returns a preview without calling the API."""
    from unittest.mock import patch

    from mcp_server.tools import writes as w

    conn = MagicMock(name="conn")
    with patch.object(w, "_get_connection", lambda target=None: conn):
        out = w.remove_container(container_id="x", dry_run=True)
    assert out.get("dryRun") is True
    conn.docker_delete.assert_not_called()
