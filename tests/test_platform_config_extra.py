"""Extra platform + config coverage: the response normaliser, the podman-socket
autodetect OSError branch, and the config resolution / error paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from container_host_aiops import config as config_mod
from container_host_aiops import platform as plat
from container_host_aiops.config import AppConfig, TargetConfig, load_config
from container_host_aiops.secretstore import SecretStoreError

# ── platform.normalise (recursive sanitiser) ─────────────────────────────────


@pytest.mark.unit
def test_normalise_sanitizes_nested_dict_list_and_str():
    p = plat.get_platform(plat.DOCKER)
    out = p.normalise({"name": "svc", "items": ["a", 2, True], "count": 3})
    assert out["name"] == "svc"
    assert out["items"] == ["a", 2, True]
    assert out["count"] == 3


@pytest.mark.unit
def test_normalise_caps_pathological_nesting_depth():
    # Build a dict nested past the depth cap (8) — the deepest value folds to None.
    node: dict = {"leaf": "deep"}
    for _ in range(12):
        node = {"child": node}
    out = plat.get_platform(plat.DOCKER).normalise(node)
    # Walk down until we hit the None the depth cap inserts.
    cur = out
    depth = 0
    while isinstance(cur, dict) and "child" in cur:
        cur = cur["child"]
        depth += 1
    assert cur is None
    assert depth <= 9


@pytest.mark.unit
def test_default_podman_socket_skips_candidate_that_raises_oserror(monkeypatch):
    def _boom(self):
        raise OSError("permission denied probing socket")

    monkeypatch.setattr(plat.Path, "exists", _boom)
    # Every candidate raises OSError → the loop continues and falls back to rootful.
    assert plat.default_podman_socket() == plat.DEFAULT_PODMAN_ROOTFUL_SOCKET


# ── config: api_base override + lookup errors ────────────────────────────────


@pytest.mark.unit
def test_api_base_honours_explicit_base_url():
    t = TargetConfig(name="d", base_url="http://custom:9999")
    assert t.api_base == "http://custom:9999"


@pytest.mark.unit
def test_get_target_missing_raises_keyerror_with_available():
    cfg = AppConfig(targets=(TargetConfig(name="a"),))
    with pytest.raises(KeyError, match="a"):
        cfg.get_target("nope")


@pytest.mark.unit
def test_default_target_empty_raises():
    with pytest.raises(ValueError, match="No targets"):
        _ = AppConfig().default_target


@pytest.mark.unit
def test_load_config_missing_file_raises_with_init_hint():
    with pytest.raises(FileNotFoundError, match="init"):
        load_config(Path("/nonexistent/definitely-not-here.yaml"))


@pytest.mark.unit
def test_load_config_parses_targets(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "targets:\n"
        "  - name: local\n"
        "    platform: docker\n"
        "  - name: pc\n"
        "    platform: portainer\n"
        "    host: portainer.local\n"
        "    endpoint_id: 2\n"
    )
    cfg = load_config(cfg_file)
    assert [t.name for t in cfg.targets] == ["local", "pc"]
    assert cfg.get_target("pc").endpoint_id == "2"


# ── config: secret resolution (encrypted store → legacy env fallback) ────────


@pytest.mark.unit
def test_resolve_secret_falls_back_to_legacy_env_when_store_errors(monkeypatch):
    monkeypatch.setattr(config_mod, "has_store", lambda: True)

    def _raise(_name):
        raise SecretStoreError("locked")

    monkeypatch.setattr(config_mod, "get_secret", _raise)
    monkeypatch.setenv("CONTAINER_HOST_PC_TOKEN", "legacy-token")

    t = TargetConfig(name="pc", platform="portainer", host="h", endpoint_id="1")
    assert t.secret == "legacy-token"


@pytest.mark.unit
def test_resolve_secret_no_source_raises_actionable_error(monkeypatch):
    monkeypatch.setattr(config_mod, "has_store", lambda: False)
    monkeypatch.delenv("CONTAINER_HOST_PC2_TOKEN", raising=False)
    t = TargetConfig(name="pc2", platform="portainer", host="h", endpoint_id="1")
    with pytest.raises(OSError, match="secret set"):
        _ = t.secret
