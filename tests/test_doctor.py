"""Tests for ``run_doctor`` — environment and connectivity diagnostics.

Everything is redirected to a tmp dir (config, secret store) and the
connection layer is faked at the ``ConnectionManager`` boundary, so no test
ever touches a real Docker socket, Portainer server, or
``~/.container-host-aiops``.
"""

from __future__ import annotations

import pytest
import yaml
from rich.console import Console

import container_host_aiops.config as config_mod
import container_host_aiops.connection as connection_mod
import container_host_aiops.doctor as doctor_mod
import container_host_aiops.secretstore as ss
from container_host_aiops.doctor import run_doctor

MASTER_PW = "test-master-pw"


@pytest.fixture
def doctor_home(tmp_path, monkeypatch):
    """Isolate config + secret store paths under tmp_path."""
    config_file = tmp_path / "config.yaml"
    env_file = tmp_path / ".env"
    secrets_file = tmp_path / "secrets.enc"
    monkeypatch.setenv("CONTAINER_HOST_AIOPS_HOME", str(tmp_path))
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(config_mod, "ENV_FILE", env_file)
    monkeypatch.setattr(doctor_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(doctor_mod, "ENV_FILE", env_file)
    monkeypatch.setattr(doctor_mod, "SECRETS_FILE", secrets_file)
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", secrets_file)
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", env_file)
    monkeypatch.setattr(ss, "_cached", None)
    # Wide console so long messages don't wrap mid-assertion.
    monkeypatch.setattr(doctor_mod, "_console", Console(width=500))
    monkeypatch.delenv("CONTAINER_HOST_PORT1_TOKEN", raising=False)
    return tmp_path


def _write_config(tmp_path, targets: list[dict]) -> None:
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"targets": targets}), "utf-8")


def _seed_secret(monkeypatch, name: str = "port1", value: str = "ptr-token-1") -> None:
    monkeypatch.setenv("CONTAINER_HOST_AIOPS_MASTER_PASSWORD", MASTER_PW)
    ss.SecretStore.unlock(MASTER_PW).set(name, value)


_DOCKER_TARGET = {"name": "local", "platform": "docker", "socket_path": "/tmp/test-no.sock"}
_PORTAINER_TARGET = {
    "name": "port1",
    "platform": "portainer",
    "host": "portainer.example.com",
    "port": 9443,
    "endpoint_id": "1",
}


class _FakeConn:
    def __init__(self, target) -> None:
        self.target = target

    def get(self, path):  # Portainer management API
        assert path == "/api/endpoints"
        return [{"Id": 1}, {"Id": 2}]

    def docker_get(self, path):  # Docker Engine API
        assert path == "/version"
        return {"ApiVersion": "1.47"}


class _HealthyManager:
    """Stands in for ConnectionManager: every connect() succeeds."""

    def __init__(self, config) -> None:
        self._config = config

    def connect(self, name):
        return _FakeConn(self._config.get_target(name))


class _UnreachableManager:
    """Stands in for ConnectionManager: every connect() fails."""

    def __init__(self, config) -> None:
        self._config = config

    def connect(self, name):
        raise ConnectionError("No such file or directory: '/tmp/test-no.sock'")


@pytest.mark.unit
def test_doctor_missing_config_fails_with_init_hint(doctor_home, capsys):
    assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "Config file missing" in out
    assert "container-host-aiops init" in out


@pytest.mark.unit
def test_doctor_config_load_failure_reported_not_raised(doctor_home, capsys):
    (doctor_home / "config.yaml").write_text("targets: [unclosed", "utf-8")
    assert run_doctor() == 1
    assert "Config load failed" in capsys.readouterr().out


@pytest.mark.unit
def test_doctor_no_targets_configured(doctor_home, capsys):
    _write_config(doctor_home, [])
    assert run_doctor() == 1
    assert "No targets configured" in capsys.readouterr().out


@pytest.mark.unit
def test_doctor_mixed_fleet_all_healthy_exit_zero(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_DOCKER_TARGET, _PORTAINER_TARGET])
    _seed_secret(monkeypatch)
    monkeypatch.setattr(connection_mod, "ConnectionManager", _HealthyManager)
    assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "Config file present" in out
    assert "2 target(s) configured" in out
    assert "Encrypted secret store present" in out
    # Socket target needs no secret; Portainer target needs its API token.
    assert "'local' (docker) needs no secret (socket/TCP)" in out
    assert "API token present for 'port1' (portainer)" in out
    # Platform-specific connectivity checks.
    assert "Connected to 'local' (Docker Engine API) — Docker API 1.47" in out
    assert "Connected to 'port1' (Portainer API) — 2 endpoint(s) visible" in out


@pytest.mark.unit
def test_doctor_socket_only_fleet_needs_no_secret_store(doctor_home, capsys):
    """A pure Docker-socket fleet must pass without any secret store at all."""
    _write_config(doctor_home, [_DOCKER_TARGET])
    assert run_doctor(skip_auth=True) == 0
    out = capsys.readouterr().out
    assert "'local' (docker) needs no secret (socket/TCP)" in out
    # No secret-store nag for a fleet that needs no secrets.
    assert "secret store" not in out
    assert "No API token" not in out


@pytest.mark.unit
def test_doctor_portainer_without_secret_store_fails(doctor_home, capsys):
    _write_config(doctor_home, [_PORTAINER_TARGET])
    assert run_doctor(skip_auth=True) == 1
    out = capsys.readouterr().out
    assert "Portainer target(s) configured but no secret store yet" in out
    assert "No API token for target 'port1'" in out


@pytest.mark.unit
def test_doctor_skip_auth_skips_connectivity(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_DOCKER_TARGET])

    def _boom(config):  # doctor must not even construct a manager
        raise AssertionError("ConnectionManager should not be used with --skip-auth")

    monkeypatch.setattr(connection_mod, "ConnectionManager", _boom)
    assert run_doctor(skip_auth=True) == 0
    out = capsys.readouterr().out
    assert "Skipping connectivity check" in out
    assert "Connected" not in out


@pytest.mark.unit
def test_doctor_unreachable_socket_exit_one(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_DOCKER_TARGET])
    monkeypatch.setattr(connection_mod, "ConnectionManager", _UnreachableManager)
    assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "Connect to 'local' failed" in out
    assert "test-no.sock" in out


@pytest.mark.unit
def test_doctor_legacy_env_file_warns_migrate(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_PORTAINER_TARGET])
    (doctor_home / ".env").write_text("CONTAINER_HOST_PORT1_TOKEN=legacy\n", "utf-8")
    monkeypatch.setenv("CONTAINER_HOST_PORT1_TOKEN", "legacy")
    assert run_doctor(skip_auth=True) == 0
    out = capsys.readouterr().out
    assert "legacy plaintext .env" in out
    assert "secret migrate" in out


@pytest.mark.unit
def test_doctor_warns_on_loose_secret_permissions(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_PORTAINER_TARGET])
    _seed_secret(monkeypatch)
    (doctor_home / "secrets.enc").chmod(0o644)
    assert run_doctor(skip_auth=True) == 0
    assert "should be 600" in capsys.readouterr().out


@pytest.mark.unit
def test_cli_doctor_command_exits_with_doctor_code(doctor_home):
    from typer.testing import CliRunner

    from container_host_aiops.cli import app

    _write_config(doctor_home, [_DOCKER_TARGET])
    result = CliRunner().invoke(app, ["doctor", "--skip-auth"])
    assert result.exit_code == 0
    assert "Skipping connectivity check" in result.output
