"""Read-path ops tests (containers / images / volumes / networks / system / stacks).

Uses a lightweight fake connection that returns canned JSON for each Docker path,
so normalisation, rollups, stats math, and the pure analyses are exercised
without a live Docker socket.
"""

import pytest

from container_host_aiops.config import TargetConfig
from container_host_aiops.ops import (
    _metrics,
    analyses,
    containers,
    images,
    networks,
    overview,
    pods,
    stacks,
    system,
    volumes,
)


class _Conn:
    """Fake connection: docker_get/get/libpod_get look up canned responses by path."""

    def __init__(self, responses, raw=None, platform="docker", name="t"):
        self._responses = responses
        self._raw = raw or {}
        self.target = TargetConfig(
            name=name,
            platform=platform,
            host="h" if platform == "portainer" else "",
            endpoint_id="1" if platform == "portainer" else "",
        )

    def docker_get(self, path, params=None):
        return self._responses[path]

    def docker_get_raw(self, path, params=None):
        return self._raw.get(path, b"")

    def libpod_get(self, path, params=None):
        # Mirror the real connection: a non-podman target cannot reach libpod.
        self.target.platform_obj.libpod_path(path)
        return self._responses[path]

    def get(self, path, **_kw):
        return self._responses[path]


# ── containers ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_containers_buckets_by_state():
    conn = _Conn({
        "/containers/json": [
            {"Id": "a1", "Names": ["/web"], "State": "running", "Image": "nginx"},
            {"Id": "b2", "Names": ["/db"], "State": "exited", "Image": "pg"},
            {"Id": "c3", "Names": ["/cache"], "State": "running", "Image": "redis"},
        ]
    })
    out = containers.list_containers(conn)
    assert out["total"] == 3
    assert out["byState"]["running"] == 2
    assert out["containers"][0]["name"] in {"web", "db", "cache"}


@pytest.mark.unit
def test_container_stats_computes_cpu_and_mem():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200}, "system_cpu_usage": 2000, "online_cpus": 2,
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
        "memory_stats": {"usage": 600, "limit": 1000, "stats": {"cache": 100}},
        "Name": "/svc",
    }
    conn = _Conn({"/containers/x/stats": stats})
    out = containers.container_stats(conn, "x")
    # cpu_delta=100, system_delta=1000 → 0.1 * 2 * 100 = 20.0
    assert out["cpuPercent"] == 20.0
    # used = 600-100=500, limit 1000 → 50%
    assert out["memPercent"] == 50.0
    assert out["memUsageBytes"] == 500


@pytest.mark.unit
def test_cpu_percent_first_sample_is_zero():
    assert _metrics.cpu_percent({}) == 0.0


@pytest.mark.unit
def test_restart_summary_ranks_by_restart_count():
    conn = _Conn({
        "/containers/json": [{"Id": "a"}, {"Id": "b"}],
        "/containers/a/json": {
            "Id": "a", "Name": "/loopy",
            "State": {"Status": "restarting", "RestartCount": 9, "ExitCode": 1},
        },
        "/containers/b/json": {
            "Id": "b", "Name": "/calm",
            "State": {"Status": "running", "RestartCount": 0, "ExitCode": 0},
        },
    })
    out = containers.restart_summary(conn)
    assert out["total"] == 2
    assert out["withRestarts"] == 1
    assert out["containers"][0]["name"] == "loopy"
    assert out["containers"][0]["restartCount"] == 9


@pytest.mark.unit
def test_container_logs_demux_framed_stream():
    # Two frames: stdout "hi\n" then stderr "err\n".
    frame1 = bytes([1, 0, 0, 0, 0, 0, 0, 3]) + b"hi\n"
    frame2 = bytes([2, 0, 0, 0, 0, 0, 0, 4]) + b"err\n"
    conn = _Conn({}, raw={"/containers/x/logs": frame1 + frame2})
    out = containers.container_logs(conn, "x")
    assert out["lines"] == ["hi", "err"]


# ── images / volumes / networks ──────────────────────────────────────────────


@pytest.mark.unit
def test_list_images_sorts_by_size_and_flags_dangling():
    conn = _Conn({
        "/images/json": [
            {"Id": "sha256:aaa", "RepoTags": ["app:1"], "Size": 100},
            {"Id": "sha256:bbb", "RepoTags": ["<none>:<none>"], "Size": 900},
        ]
    })
    out = images.list_images(conn)
    assert out["total"] == 2
    assert out["images"][0]["sizeBytes"] == 900
    assert out["images"][0]["dangling"] is True


@pytest.mark.unit
def test_dangling_images_totals_reclaimable():
    conn = _Conn({
        "/images/json": [
            {"Id": "sha256:x", "Size": 500},
            {"Id": "sha256:y", "Size": 250},
        ]
    })
    out = images.dangling_images(conn)
    assert out["danglingCount"] == 2
    assert out["reclaimableBytes"] == 750


@pytest.mark.unit
def test_dangling_volumes_from_df():
    conn = _Conn({
        "/system/df": {
            "Volumes": [
                {"Name": "v1", "UsageData": {"RefCount": 0, "Size": 400}},
                {"Name": "v2", "UsageData": {"RefCount": 2, "Size": 999}},
            ]
        }
    })
    out = volumes.dangling_volumes(conn)
    assert out["danglingCount"] == 1
    assert out["reclaimableBytes"] == 400


@pytest.mark.unit
def test_list_networks_buckets_by_driver():
    conn = _Conn({
        "/networks": [
            {"Id": "n1", "Name": "bridge", "Driver": "bridge"},
            {"Id": "n2", "Name": "host", "Driver": "host"},
            {"Id": "n3", "Name": "br2", "Driver": "bridge"},
        ]
    })
    out = networks.list_networks(conn)
    assert out["byDriver"]["bridge"] == 2


# ── system ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_system_df_breaks_down_usage():
    conn = _Conn({
        "/system/df": {
            "LayersSize": 1000,
            "Images": [{"Size": 800}, {"Size": 200}],
            "Containers": [{"SizeRw": 50}],
            "Volumes": [{"UsageData": {"Size": 300}}],
            "BuildCache": [{"Size": 60}],
        }
    })
    out = system.system_df(conn)
    assert out["images"]["totalBytes"] == 1000
    assert out["volumes"]["totalBytes"] == 300
    assert out["buildCache"]["totalBytes"] == 60


@pytest.mark.unit
def test_recent_events_parses_ndjson_rollup():
    body = (
        b'{"Type":"container","Action":"start","id":"abc","time":1}\n'
        b'{"Type":"container","Action":"die","id":"abc","time":2}\n'
        b'{"Type":"image","Action":"pull","time":3}\n'
    )
    conn = _Conn({}, raw={"/events": body})
    out = system.recent_events(conn, since=10)
    assert out["total"] == 3
    assert out["byTypeAction"]["container:start"] == 1


# ── stacks (portainer only) ──────────────────────────────────────────────────


@pytest.mark.unit
def test_list_stacks_requires_portainer_target():
    conn = _Conn({}, platform="docker")
    with pytest.raises(ValueError, match="portainer"):
        stacks.list_stacks(conn)


@pytest.mark.unit
def test_list_stacks_on_portainer_target():
    conn = _Conn(
        {"/api/stacks": [{"Id": 1, "Name": "web", "Type": 2, "EndpointId": 1}]},
        platform="portainer",
    )
    out = stacks.list_stacks(conn)
    assert out["total"] == 1
    assert out["stacks"][0]["name"] == "web"


# ── podman pods (libpod, podman-only) ─────────────────────────────────────────


def _pods_conn(platform="podman"):
    return _Conn(
        {
            "/pods/json": [
                {"Id": "pod-aaaa1111", "Name": "web-pod", "Status": "Running",
                 "InfraId": "inf-1", "Containers": [
                     {"Id": "c1", "Status": "running"}, {"Id": "c2", "Status": "exited"}]},
                {"Id": "pod-bbbb2222", "Name": "idle-pod", "Status": "Exited",
                 "Containers": []},
            ]
        },
        platform=platform,
    )


@pytest.mark.unit
def test_list_pods_on_podman_target():
    out = pods.list_pods(_pods_conn())
    assert out["total"] == 2
    assert out["byStatus"]["running"] == 1
    top = out["pods"][0]
    assert top["name"] == "web-pod"
    assert top["numContainers"] == 2
    assert top["containersByStatus"] == {"running": 1, "exited": 1}


@pytest.mark.unit
def test_list_pods_teaching_errors_on_docker():
    conn = _Conn({}, platform="docker")
    with pytest.raises(ValueError, match="podman"):
        pods.list_pods(conn)


@pytest.mark.unit
def test_list_pods_teaching_errors_on_portainer():
    conn = _Conn({}, platform="portainer")
    with pytest.raises(ValueError, match="podman"):
        pods.list_pods(conn)


# ── compose-stack awareness (docker AND podman) ───────────────────────────────


def _compose_rows():
    return [
        {"Id": "a1", "Names": ["/shop-web-1"], "State": "running",
         "Status": "Up 2h", "Labels": {
             "com.docker.compose.project": "shop", "com.docker.compose.service": "web"}},
        {"Id": "a2", "Names": ["/shop-db-1"], "State": "exited",
         "Status": "Exited (1)", "Labels": {
             "com.docker.compose.project": "shop", "com.docker.compose.service": "db"}},
        {"Id": "b1", "Names": ["/blog-web-1"], "State": "running",
         "Status": "Up 5m", "Labels": {
             "com.docker.compose.project": "blog", "com.docker.compose.service": "web"}},
        {"Id": "c1", "Names": ["/loose"], "State": "running", "Status": "Up",
         "Labels": {}},
    ]


@pytest.mark.unit
@pytest.mark.parametrize("platform", ["docker", "podman"])
def test_list_compose_stacks_groups_and_rolls_up_health(platform):
    conn = _Conn({"/containers/json": _compose_rows()}, platform=platform)
    out = stacks.list_compose_stacks(conn)
    assert out["totalStacks"] == 2
    assert out["ungroupedContainers"] == 1
    by_project = {s["project"]: s for s in out["stacks"]}
    # blog: single running container → healthy
    assert by_project["blog"]["health"] == "healthy"
    # shop: one running + one exited → degraded, two services
    assert by_project["shop"]["health"] == "degraded"
    assert by_project["shop"]["serviceCount"] == 2
    assert by_project["shop"]["services"] == ["db", "web"]


@pytest.mark.unit
def test_list_compose_stacks_down_when_none_running():
    rows = [
        {"Id": "x", "Names": ["/svc"], "State": "exited", "Status": "Exited (0)",
         "Labels": {"com.docker.compose.project": "dead",
                    "com.docker.compose.service": "svc"}},
    ]
    conn = _Conn({"/containers/json": rows}, platform="podman")
    out = stacks.list_compose_stacks(conn)
    assert out["stacks"][0]["health"] == "down"


# ── podman parity: Docker-compat reads behave identically on a podman target ──


@pytest.mark.unit
def test_list_containers_parity_on_podman_target():
    conn = _Conn({
        "/containers/json": [
            {"Id": "a1", "Names": ["/web"], "State": "running", "Image": "nginx"},
            {"Id": "b2", "Names": ["/db"], "State": "exited", "Image": "pg"},
        ]
    }, platform="podman")
    out = containers.list_containers(conn)
    assert out["total"] == 2
    assert out["byState"]["running"] == 1


@pytest.mark.unit
def test_restart_summary_parity_on_podman_target():
    conn = _Conn({
        "/containers/json": [{"Id": "a"}],
        "/containers/a/json": {
            "Id": "a", "Name": "/loopy",
            "State": {"Status": "restarting", "RestartCount": 5, "ExitCode": 1},
        },
    }, platform="podman")
    out = containers.restart_summary(conn)
    assert out["withRestarts"] == 1
    assert out["containers"][0]["restartCount"] == 5


@pytest.mark.unit
def test_restart_loop_rca_pull_parity_on_podman_target():
    """The flagship restart-loop RCA pulls live data through the compat layer on
    a podman target exactly as it does on docker."""
    conn = _Conn({
        "/containers/json": [{"Id": "a"}],
        "/containers/a/json": {
            "Id": "a", "Name": "/crash",
            "State": {"Status": "restarting", "RestartCount": 6, "ExitCode": 137,
                      "OOMKilled": True},
        },
    }, raw={"/containers/a/logs": b"boom\n"}, platform="podman")
    rows, logs = analyses.pull_restart_data(conn)
    out = analyses.restart_loop_rca(rows, logs)
    assert out["loopingCount"] == 1
    assert "memory" in out["looping"][0]["cause"].lower()


@pytest.mark.unit
def test_lifecycle_write_parity_on_podman_target():
    """A lifecycle write (stop) captures before-state and fires the compat POST
    on a podman target, identically to docker."""
    from unittest.mock import MagicMock

    from container_host_aiops.ops import writes

    conn = MagicMock(name="conn")
    conn.target = TargetConfig(name="pod1", platform="podman")
    conn.docker_get.return_value = {"Name": "/web", "State": {"Running": True}}
    conn.docker_post.return_value = {}
    out = writes.stop_container(conn, "web")
    assert out["action"] == "stop_container"
    assert out["name"] == "web"
    assert out["priorState"] == {"running": True}
    conn.docker_post.assert_called_once()
    assert conn.docker_post.call_args.args[0] == "/containers/web/stop"


# ── overview ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_host_overview_resilient_partial():
    conn = _Conn({
        "/info": {"ServerVersion": "25.0", "Containers": 3, "ContainersRunning": 2},
        "/containers/json": [],
        "/system/df": {"Images": [], "Containers": [], "Volumes": [], "BuildCache": []},
    })
    out = overview.host_overview(conn)
    assert out["platform"] == "docker"
    assert out["serverVersion"] == "25.0"
    assert out["containersRunning"] == 2


# ── flagship analyses (pure) ─────────────────────────────────────────────────


@pytest.mark.unit
def test_restart_loop_rca_flags_and_maps_cause():
    rows = [
        {"id": "a", "name": "loopy", "state": "restarting", "restartCount": 7,
         "exitCode": 137, "oomKilled": True},
        {"id": "b", "name": "ok", "state": "running", "restartCount": 0, "exitCode": 0},
    ]
    out = analyses.restart_loop_rca(rows, {"a": ["boom"]})
    assert out["loopingCount"] == 1
    top = out["looping"][0]
    assert top["name"] == "loopy"
    assert "memory" in top["cause"].lower()
    assert top["logsTail"] == ["boom"]


@pytest.mark.unit
def test_restart_loop_rca_exit_code_127_bad_entrypoint():
    rows = [{"id": "a", "name": "x", "state": "exited", "restartCount": 0, "exitCode": 127}]
    out = analyses.restart_loop_rca(rows)
    assert out["loopingCount"] == 1
    assert "not found" in out["looping"][0]["cause"].lower()


@pytest.mark.unit
def test_resource_pressure_analysis_ranks_and_recommends():
    samples = [
        {"id": "a", "name": "hot", "cpuPercent": 95.0, "memPercent": 30.0,
         "memUsageBytes": 3, "memLimitBytes": 10},
        {"id": "b", "name": "cool", "cpuPercent": 5.0, "memPercent": 5.0,
         "memUsageBytes": 1, "memLimitBytes": 10},
    ]
    out = analyses.resource_pressure_analysis(samples)
    assert out["overThresholdCount"] == 1
    assert out["ranked"][0]["name"] == "hot"
    assert out["ranked"][0]["over"] is True


@pytest.mark.unit
def test_resource_pressure_flags_missing_mem_limit():
    samples = [{"id": "a", "name": "leak", "cpuPercent": 10.0, "memPercent": 90.0,
                "memUsageBytes": 900, "memLimitBytes": 0}]
    out = analyses.resource_pressure_analysis(samples)
    row = out["ranked"][0]
    assert row["memLimited"] is False
    assert "no memory limit" in row["cause"].lower()


@pytest.mark.unit
def test_image_and_volume_bloat_totals_reclaimable():
    out = analyses.image_and_volume_bloat(
        {"danglingCount": 2, "reclaimableBytes": 500},
        {"danglingCount": 1, "reclaimableBytes": 300},
        {"buildCache": {"count": 3, "totalBytes": 200}},
    )
    assert out["totalReclaimableBytes"] == 1000
    assert out["candidates"][0]["reclaimableBytes"] == 500
