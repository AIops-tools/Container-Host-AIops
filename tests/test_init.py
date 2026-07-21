"""Tests for the ``container-host-aiops init`` onboarding wizard.

The wizard is driven end-to-end through Typer's CliRunner with every path
(config.yaml, secrets.enc) isolated under tmp_path. The master
password comes from CONTAINER_HOST_AIOPS_MASTER_PASSWORD (the non-interactive
path) and the hidden Portainer-token prompt is patched at the getpass boundary.
A Docker-socket target must complete without ever touching the secret store.
"""

from __future__ import annotations

import getpass as getpass_mod

import pytest
import yaml
from typer.testing import CliRunner

import container_host_aiops.cli.init as init_mod
import container_host_aiops.config as config_mod
import container_host_aiops.doctor as doctor_mod
import container_host_aiops.secretstore as ss

MASTER_PW = "init-master-pw"
API_TOKEN = "ptr_token_0123456789"

# Docker-socket answers: name, accept platform default (docker), accept
# unix-socket confirm default (True), accept default socket path, no second
# target, decline the trailing doctor run.
SOCKET_INPUT = "local\n\n\n\nn\nn\n"
# Portainer answers: name, platform, host, accept default port, accept default
# endpoint id, accept TLS-verify default (True), no second target, decline doctor.
PORTAINER_INPUT = "port1\nportainer\nportainer.example.com\n\n\n\nn\nn\n"


@pytest.fixture
def init_home(tmp_path, monkeypatch):
    """Isolate config + secret store + governance home under tmp_path."""
    config_file = tmp_path / "config.yaml"
    secrets_file = tmp_path / "secrets.enc"
    monkeypatch.setenv("CONTAINER_HOST_AIOPS_HOME", str(tmp_path))
    monkeypatch.setenv("CONTAINER_HOST_AIOPS_MASTER_PASSWORD", MASTER_PW)
    monkeypatch.setattr(init_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(init_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", secrets_file)
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    # The hidden Portainer-token prompt bypasses CliRunner stdin.
    monkeypatch.setattr(getpass_mod, "getpass", lambda prompt="": API_TOKEN)
    return tmp_path


def _run_init(input_text: str):
    from container_host_aiops.cli import app

    return CliRunner().invoke(app, ["init"], input=input_text)


@pytest.mark.unit
def test_init_docker_socket_target_needs_no_secret(init_home):
    result = _run_init(SOCKET_INPUT)
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"] == [
        {
            "name": "local",
            "platform": "docker",
            "socket_path": "/var/run/docker.sock",  # accepted default must land
        }
    ]
    # A socket target must not create (or need) the secret store at all.
    assert not (init_home / "secrets.enc").exists()


@pytest.mark.unit
def test_init_docker_tcp_target(init_home):
    # Decline the unix-socket confirm, give a TCP host, accept TLS default (False).
    result = _run_init("remote\n\nn\ndocker1.example.com\n\nn\nn\n")
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"] == [
        {
            "name": "remote",
            "platform": "docker",
            "host": "docker1.example.com",
            "verify_ssl": False,  # "Use TLS?" default is False for plain TCP
        }
    ]
    assert not (init_home / "secrets.enc").exists()


@pytest.mark.unit
def test_init_portainer_writes_config_with_entered_values(init_home):
    result = _run_init(PORTAINER_INPUT)
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"] == [
        {
            "name": "port1",
            "platform": "portainer",
            "host": "portainer.example.com",
            "port": 9443,
            "endpoint_id": "1",
            "verify_ssl": True,  # accepted TLS confirm default=True must land
        }
    ]


@pytest.mark.unit
def test_init_portainer_stores_token_encrypted_not_in_config(init_home):
    result = _run_init(PORTAINER_INPUT)
    assert result.exit_code == 0, result.output
    # Token is readable back through the secret store API...
    assert ss.SecretStore.unlock(MASTER_PW).get("port1") == API_TOKEN
    # ...and never lands in plaintext in config.yaml or secrets.enc.
    assert API_TOKEN not in (init_home / "config.yaml").read_text("utf-8")
    assert API_TOKEN not in (init_home / "secrets.enc").read_text("utf-8")


@pytest.mark.unit
def test_init_rejects_unknown_platform_then_reprompts(init_home):
    result = _run_init("x1\nlxd\nx1\n\n\n\nn\nn\n")
    assert result.exit_code == 0, result.output
    assert "Platform must be 'docker', 'portainer', or 'podman'." in result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert [t["name"] for t in raw["targets"]] == ["x1"]


@pytest.mark.unit
def test_init_writes_no_policy_rules(init_home):
    """The skill no longer authorizes, so init seeds no rules.yaml — a fresh
    install delivers full functionality and leaves permission to the account."""
    result = _run_init(SOCKET_INPUT)
    assert result.exit_code == 0, result.output
    assert not (init_home / "rules.yaml").exists()


@pytest.mark.unit
def test_init_accepting_doctor_confirm_runs_doctor(init_home, monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(doctor_mod, "run_doctor", lambda: calls.append(True) or 0)
    # Empty last answer accepts the confirm's default=True.
    result = _run_init("local\n\n\n\nn\n\n")
    assert result.exit_code == 0, result.output
    assert calls == [True]


@pytest.mark.unit
def test_init_overwrite_existing_target(init_home):
    result = _run_init(SOCKET_INPUT)
    assert result.exit_code == 0, result.output
    # Same name again: confirm overwrite, switch it to a custom socket path.
    result = _run_init("local\ny\n\n\n/run/user/1000/docker.sock\nn\nn\n")
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert [t["socket_path"] for t in raw["targets"]] == ["/run/user/1000/docker.sock"]
