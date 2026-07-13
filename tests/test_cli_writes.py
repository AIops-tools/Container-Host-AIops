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
def test_cli_manage_stop_dry_run_makes_no_call_and_no_audit(gov_home, docker_conn):
    from container_host_aiops.cli import app

    result = CliRunner().invoke(app, ["manage", "stop", "abc123", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    docker_conn.docker_post.assert_not_called()
    assert not (gov_home / "audit.db").exists()


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
