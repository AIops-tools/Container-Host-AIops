"""CLI confirmed-write path — past dry-run, through governance, onto disk.

The CLI write commands delegate real execution to the ``@governed_tool``
functions in ``mcp_server.tools.writes``. These tests drive ``manage stop``
PAST the dry-run branch and the double-confirm prompts and assert the call
really went through the governed path (audit row on disk) — the regression
test for the "CLI writes were unaudited" line-wide fix.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import container_host_aiops.governance.audit as audit_mod
import container_host_aiops.governance.policy as policy_mod
import container_host_aiops.governance.undo as undo_mod


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


@pytest.fixture
def docker_conn(monkeypatch):
    """A fake Docker connection wired into the governed write module."""
    from mcp_server.tools import writes as gov

    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {"Id": "abc123", "Name": "/web", "State": {"Running": True}}
    conn.docker_post.return_value = {}
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    return conn


def _audit_tools(db_path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT tool FROM audit_log ORDER BY id")]
    finally:
        conn.close()


@pytest.mark.unit
def test_cli_manage_stop_dry_run_reads_and_audits_but_never_writes(gov_home, docker_conn):
    """A dry_run MAY read; it must never write.

    The older "dry_run does zero I/O" assumption was never a stated rule and is
    wrong on its face: a preview that cannot read cannot answer "would this be
    refused?", which is the most valuable thing a preview can say. So the read
    is expected, the audit row is expected (MCP previews were always audited —
    the CLI silently not auditing was the outlier), and only the MUTATING call
    is forbidden.
    """
    from container_host_aiops.cli import app

    result = CliRunner().invoke(app, ["manage", "stop", "abc123", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output  # human banner preserved, not raw JSON
    docker_conn.docker_post.assert_not_called()  # no POST
    docker_conn.docker_delete.assert_not_called()  # no DELETE
    docker_conn.docker_get.assert_called()  # it DID read, to run the guard
    assert _audit_tools(gov_home / "audit.db") == ["stop_container"]


@pytest.mark.unit
def test_cli_manage_stop_dry_run_records_no_undo_token(gov_home, docker_conn):
    """A preview changed nothing, so there is nothing to reverse.

    A phantom undo token is not inert: undo_apply would dispatch a REAL
    start_container for a stop that never happened.
    """
    import sqlite3

    from container_host_aiops.cli import app

    CliRunner().invoke(app, ["manage", "stop", "abc123", "--dry-run"])
    if (gov_home / "undo.db").exists():
        rows = sqlite3.connect(gov_home / "undo.db").execute(
            "SELECT undo_tool FROM undo_log"
        ).fetchall()
        assert rows == [], f"dry-run registered a phantom undo: {rows}"


@pytest.mark.unit
def test_cli_manage_stop_dry_run_on_portainer_self_refuses_nonzero(gov_home, monkeypatch):
    """A refused preview must teach and exit non-zero, like a refused real write."""
    from container_host_aiops.cli import app
    from mcp_server.tools import writes as gov

    conn = MagicMock(name="conn")
    conn.docker_get.return_value = {"Name": "/portainer",
                                    "Config": {"Image": "portainer/portainer-ce"}}
    conn.target.platform = "portainer"
    conn.target.port = 9443
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)

    result = CliRunner().invoke(app, ["manage", "stop", "portainer", "--dry-run"])
    assert result.exit_code == 1
    assert "Refusing to stop" in result.output
    assert "DRY-RUN" not in result.output  # no green banner for a refusal
    conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_cli_manage_stop_confirmed_goes_through_governance(gov_home, docker_conn):
    """Confirmed CLI write must execute via the governed twin: the API call
    fires AND an audit row lands in audit.db (this is what the reroute fix
    bought)."""
    from container_host_aiops.cli import app

    result = CliRunner().invoke(app, ["manage", "stop", "abc123"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    docker_conn.docker_post.assert_called_once()
    assert _audit_tools(gov_home / "audit.db") == ["stop_container"]


@pytest.mark.unit
def test_cli_manage_stop_aborts_without_double_confirm(gov_home, docker_conn):
    from container_host_aiops.cli import app

    result = CliRunner().invoke(app, ["manage", "stop", "abc123"], input="y\nn\n")
    assert result.exit_code != 0
    docker_conn.docker_post.assert_not_called()
    assert not (gov_home / "audit.db").exists()


@pytest.mark.unit
def test_cli_manage_remove_dry_run_reads_and_audits_but_never_writes(
    gov_home, docker_conn, monkeypatch
):
    """Same invariant on the high-risk twin: MAY read, MUST NOT write. It runs
    through the governed twin, so the preview lands an audit row like any call."""
    from container_host_aiops.cli import app

    result = CliRunner().invoke(
        app, ["manage", "remove", "abc123", "--force", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    assert "force" in result.output  # banner filled from the returned dict
    docker_conn.docker_delete.assert_not_called()
    docker_conn.docker_post.assert_not_called()
    docker_conn.docker_get.assert_called()
    assert _audit_tools(gov_home / "audit.db") == ["remove_container"]


@pytest.mark.unit
def test_cli_high_risk_runs_without_an_approver_and_audits(gov_home, docker_conn, monkeypatch):
    """The skill authorizes nothing. A high-risk CLI write with no approver set
    runs (past the double-confirm) and lands an audit row — whether it *should*
    run is the operator's / account's call, made when they chose to run it."""
    from container_host_aiops.cli import app

    monkeypatch.delenv("CONTAINER_HOST_AUDIT_APPROVED_BY", raising=False)
    result = CliRunner().invoke(app, ["manage", "remove", "abc123"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    docker_conn.docker_delete.assert_called_once()
    assert _audit_tools(gov_home / "audit.db") == ["remove_container"]


@pytest.mark.unit
def test_cli_high_risk_dry_run_previews_and_mutates_nothing(gov_home, docker_conn):
    """A high-risk preview runs, reads, and mutates nothing — no gate stands
    between the operator and finding out what a delete would do."""
    from container_host_aiops.cli import app

    result = CliRunner().invoke(app, ["manage", "remove", "abc123", "--dry-run"])
    assert result.exit_code == 0
    docker_conn.docker_delete.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "tool"),
    [
        (["manage", "restart", "abc123", "--dry-run"], "restart_container"),
        (["manage", "start", "abc123", "--dry-run"], "start_container"),
        (["manage", "update", "abc123", '{"Memory":536870912}', "--dry-run"],
         "update_container"),
    ],
)
def test_cli_manage_dry_run_is_audited_but_never_writes(gov_home, docker_conn, argv, tool):
    """The remaining manage previews now route through the governed twin too.

    Before this, each of these printed a hand-written banner and returned without
    ever entering governance: no audit row, and no way for a guard to refuse. The
    surviving rule is the same one ``stop``/``remove`` already state — a preview
    may read, but it must never issue a mutating call — plus the audit row that
    proves the preview actually went through the harness.
    """
    from container_host_aiops.cli import app

    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output  # human banner preserved, not raw JSON
    docker_conn.docker_post.assert_not_called()
    docker_conn.docker_delete.assert_not_called()
    assert _audit_tools(gov_home / "audit.db") == [tool]


@pytest.mark.unit
def test_cli_manage_update_dry_run_banner_carries_the_resolved_resources(gov_home, docker_conn):
    """The banner is now filled from the governed dict, not a hand-written guess."""
    from container_host_aiops.cli import app

    result = CliRunner().invoke(
        app, ["manage", "update", "abc123", '{"Memory":536870912}', "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "536870912" in result.output
    docker_conn.docker_post.assert_not_called()


@pytest.mark.unit
def test_cli_manage_recreate_stack_dry_run_is_audited_but_never_writes(gov_home, monkeypatch):
    """recreate-stack rides the Portainer transport, so the forbidden verbs differ.
    The preview runs through the governed twin: it reads, it audits, it does not
    mutate."""
    from container_host_aiops.cli import app
    from mcp_server.tools import writes as gov

    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    monkeypatch.delenv("CONTAINER_HOST_AUDIT_APPROVED_BY", raising=False)

    result = CliRunner().invoke(app, ["manage", "recreate-stack", "s1", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    conn.put.assert_not_called()
    conn.post.assert_not_called()
    conn.delete.assert_not_called()
    assert _audit_tools(gov_home / "audit.db") == ["recreate_stack"]


@pytest.mark.unit
def test_cli_manage_restart_dry_run_previews_and_audits(gov_home, docker_conn):
    """A preview runs through the governed twin: it reads, it audits, it does
    not mutate — the same invariant on the CLI as on MCP."""
    from container_host_aiops.cli import app

    result = CliRunner().invoke(app, ["manage", "restart", "abc123", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    docker_conn.docker_post.assert_not_called()
    assert _audit_tools(gov_home / "audit.db") == ["restart_container"]
