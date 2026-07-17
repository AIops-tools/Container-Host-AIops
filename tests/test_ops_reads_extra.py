"""Extra read-path ops coverage (images / volumes / networks / overview) plus
the shared helpers (_util / _metrics). A fake connection returns canned JSON per
path; assertions pin the normalised shapes, the size/reclaimable math, and the
graceful-degradation branches.
"""

from __future__ import annotations

import pytest

from container_host_aiops.config import TargetConfig
from container_host_aiops.ops import _metrics, _util, images, networks, overview, volumes


class _Conn:
    def __init__(self, responses, errors=None, platform="docker", name="t"):
        self._responses = responses
        self._errors = errors or {}
        self.target = TargetConfig(name=name, platform=platform)

    def docker_get(self, path, params=None):
        if path in self._errors:
            raise self._errors[path]
        return self._responses[path]


# ── images ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_inspect_image_folds_history_into_layers():
    conn = _Conn({
        "/images/abc/json": {
            "Id": "sha256:abc", "RepoTags": ["app:1"], "Size": 1000,
            "Architecture": "amd64", "Os": "linux",
        },
        "/images/abc/history": [
            {"CreatedBy": "RUN a", "Size": 600},
            {"CreatedBy": "RUN b", "Size": 400},
        ],
    })
    out = images.inspect_image(conn, "abc")
    assert out["id"] == "abc"
    assert out["architecture"] == "amd64"
    assert out["layerCount"] == 2
    assert out["history"][0]["sizeBytes"] == 600


@pytest.mark.unit
def test_inspect_image_history_failure_is_advisory():
    conn = _Conn(
        {"/images/x/json": {"Id": "sha256:x", "Size": 5}},
        errors={"/images/x/history": RuntimeError("no history")},
    )
    out = images.inspect_image(conn, "x")
    assert out["layerCount"] == 0
    assert out["history"] == []


@pytest.mark.unit
def test_image_disk_usage_totals_and_reclaimable():
    conn = _Conn({
        "/system/df": {
            "Images": [
                {"Size": 1000, "SharedSize": 200, "Containers": 1},
                {"Size": 500, "SharedSize": 100, "Containers": 0},
            ]
        }
    })
    out = images.image_disk_usage(conn)
    assert out["imageCount"] == 2
    assert out["activeCount"] == 1  # one image is in use
    assert out["totalSizeBytes"] == 1500
    assert out["sharedSizeBytes"] == 300
    assert out["reclaimableBytes"] == 1200  # total - shared


@pytest.mark.unit
def test_image_num_coerces_bad_values_to_zero():
    conn = _Conn({"/images/json": [{"Id": "sha256:a", "Size": "not-a-number"}]})
    out = images.list_images(conn)
    assert out["images"][0]["sizeBytes"] == 0


# ── volumes ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_volumes_unwraps_volumes_key():
    conn = _Conn({
        "/volumes": {"Volumes": [
            {"Name": "v1", "Driver": "local", "Mountpoint": "/m", "Scope": "local"},
        ]}
    })
    out = volumes.list_volumes(conn)
    assert out["total"] == 1
    assert out["volumes"][0]["name"] == "v1"
    assert out["volumes"][0]["driver"] == "local"


@pytest.mark.unit
def test_inspect_volume_returns_cleaned_payload():
    conn = _Conn({"/volumes/v1": {"Name": "v1", "Driver": "local"}})
    out = volumes.inspect_volume(conn, "v1")
    assert out["Name"] == "v1"


@pytest.mark.unit
def test_dangling_volumes_only_zero_refcount_counts():
    conn = _Conn({
        "/system/df": {"Volumes": [
            {"Name": "used", "UsageData": {"RefCount": 3, "Size": 900}},
            {"Name": "orphan", "UsageData": {"RefCount": 0, "Size": 400}},
            {"Name": "nousage"},  # missing UsageData → refCount 0 → dangling, size 0
        ]}
    })
    out = volumes.dangling_volumes(conn)
    names = {v["name"] for v in out["volumes"]}
    assert names == {"orphan", "nousage"}
    assert out["danglingCount"] == 2
    assert out["reclaimableBytes"] == 400


# ── networks ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_inspect_network_summarises_ipam_and_attached():
    conn = _Conn({
        "/networks/n1": {
            "Id": "n1deadbeef0000", "Name": "bridge", "Driver": "bridge",
            "IPAM": {"Config": [{"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"}]},
            "Containers": {"c1": {}, "c2": {}},
        }
    })
    out = networks.inspect_network(conn, "n1")
    assert out["id"] == "n1deadbeef00"  # truncated to 12
    assert out["ipam"][0]["Subnet"] == "172.17.0.0/16"
    assert out["attachedCount"] == 2


@pytest.mark.unit
def test_inspect_network_handles_missing_ipam_and_containers():
    conn = _Conn({"/networks/host": {"Id": "hostid", "Name": "host", "Driver": "host"}})
    out = networks.inspect_network(conn, "host")
    assert out["ipam"] == []
    assert out["attachedCount"] == 0


# ── overview ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_host_overview_full_happy_path():
    conn = _Conn({
        "/info": {
            "ServerVersion": "25.0", "OperatingSystem": "Ubuntu",
            "Containers": 4, "ContainersRunning": 3, "ContainersStopped": 1, "Images": 9,
        },
        "/containers/json": [
            {"Id": "a"},
        ],
        "/containers/a/json": {"Id": "a", "Name": "/x",
                               "State": {"Status": "running", "RestartCount": 2}},
        "/system/df": {"Images": [{"Size": 10}], "Containers": [], "Volumes": [],
                       "BuildCache": []},
    })
    out = overview.host_overview(conn)
    assert out["serverVersion"] == "25.0"
    assert out["operatingSystem"] == "Ubuntu"
    assert out["containersRunning"] == 3
    assert out["containersWithRestarts"] == 1
    assert "diskImagesHuman" in out


@pytest.mark.unit
def test_host_overview_degrades_each_section_on_failure():
    conn = _Conn(
        {},
        errors={
            "/info": RuntimeError("info down"),
            "/containers/json": RuntimeError("list down"),
            "/system/df": RuntimeError("df down"),
        },
    )
    out = overview.host_overview(conn)
    # The probe survives every failing sub-call with per-section error fields.
    assert "infoError" in out
    assert "restartError" in out
    assert "dfError" in out
    assert out["platform"] == "docker"


# ── _util helpers ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_as_list_wraps_single_record_and_filters_non_dicts():
    assert _util.as_list({"Id": "a"}) == [{"Id": "a"}]
    assert _util.as_list({"Volumes": [{"Name": "v"}]}, "Volumes") == [{"Name": "v"}]
    assert _util.as_list([{"a": 1}, "junk", 5]) == [{"a": 1}]
    assert _util.as_list(None) == []


@pytest.mark.unit
def test_container_name_prefers_names_then_name_then_id():
    assert _util.container_name({"Names": ["/web"]}) == "web"
    assert _util.container_name({"Name": "/db"}) == "db"
    assert _util.container_name({"Id": "abcdef1234567890"}) == "abcdef123456"


@pytest.mark.unit
def test_human_bytes_scales_and_handles_bad_input():
    assert _util.human_bytes(0) == "0 B"
    assert _util.human_bytes(2048) == "2.0 KiB"
    assert _util.human_bytes(5 * 1024**4) == "5.0 TiB"
    assert _util.human_bytes(2 * 1024**5) == "2.0 PiB"
    assert _util.human_bytes("bad") == "0 B"


@pytest.mark.unit
def test_s_bounds_and_none_becomes_empty():
    assert _util.s(None) == ""
    assert _util.s(12345) == "12345"


# ── _metrics helpers ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_mem_percent_zero_without_limit():
    assert _metrics.mem_percent({"memory_stats": {"usage": 100}}) == 0.0


@pytest.mark.unit
def test_mem_usage_falls_back_to_inactive_file_when_no_cache():
    used, limit = _metrics.mem_usage_and_limit({
        "memory_stats": {"usage": 500, "limit": 1000, "stats": {"inactive_file": 100}},
    })
    assert used == 400.0
    assert limit == 1000.0


@pytest.mark.unit
def test_cpu_percent_uses_percpu_len_when_online_missing():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200, "percpu_usage": [1, 2, 3, 4]},
            "system_cpu_usage": 2000,
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
    }
    # cpu_delta=100, system_delta=1000, online=4 → 0.1 * 4 * 100 = 40.0
    assert _metrics.cpu_percent(stats) == 40.0
