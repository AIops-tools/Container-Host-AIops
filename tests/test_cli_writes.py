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
    """Same invariant on the high-risk twin: MAY read, MUST NOT write.

    remove_container is risk=high, so the secure-by-default approver gate now
    applies to the preview too, since it runs through the governed twin.
    """
    from container_host_aiops.cli import app

    monkeypatch.setenv("CONTAINER_HOST_AUDIT_APPROVED_BY", "tester")
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
def test_cli_high_risk_without_approver_teaches_instead_of_tracebacking(
    gov_home, docker_conn, monkeypatch
):
    """PolicyDenied must render as one teaching line, not a bare traceback.

    Its message names the exact env var to set — the most actionable error this
    tool produces — and it was being swallowed because PolicyDenied is not a
    ValueError.

    Exercised on the REAL write path: a preview deliberately does not demand an
    approver (you would need the approval to learn whether one is needed), so
    the denial only happens here.
    """
    from container_host_aiops.cli import app

    monkeypatch.delenv("CONTAINER_HOST_AUDIT_APPROVED_BY", raising=False)
    result = CliRunner().invoke(app, ["manage", "remove", "abc123"], input="y\ny\n")
    assert result.exit_code == 1
    assert "CONTAINER_HOST_AUDIT_APPROVED_BY" in result.output
    assert result.output.strip(), "a denial must never exit silently"
    docker_conn.docker_delete.assert_not_called()


@pytest.mark.unit
def test_cli_high_risk_dry_run_previews_without_an_approver(gov_home, docker_conn, monkeypatch):
    """The companion to the above: the preview goes through, so an operator can
    find out what a delete would do before going to fetch a named human."""
    from container_host_aiops.cli import app

    monkeypatch.delenv("CONTAINER_HOST_AUDIT_APPROVED_BY", raising=False)
    result = CliRunner().invoke(app, ["manage", "remove", "abc123", "--dry-run"])
    assert result.exit_code == 0
    docker_conn.docker_delete.assert_not_called()
