"""Pure metric computations over Docker ``/stats`` and ``/inspect`` payloads.

Docker's ``/containers/{id}/stats?stream=false`` returns raw counters, not
percentages; the CPU and memory percentages every dashboard shows are computed
client-side from deltas. These helpers do exactly that, defensively (any missing
field degrades to 0.0 rather than raising), so the stats reads and the resource
pressure analysis share one transparent formula.
"""

from __future__ import annotations

from typing import Any


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def cpu_percent(stats: dict) -> float:
    """CPU usage percent from a Docker stats sample (Docker's own formula).

    ``(cpu_delta / system_delta) * online_cpus * 100`` where the deltas are
    between ``cpu_stats`` and ``precpu_stats``. Returns 0.0 when the sample is
    incomplete (first sample, or a missing counter).
    """
    cpu = stats.get("cpu_stats") or {}
    precpu = stats.get("precpu_stats") or {}
    cpu_usage = (cpu.get("cpu_usage") or {}).get("total_usage")
    precpu_usage = (precpu.get("cpu_usage") or {}).get("total_usage")
    cpu_delta = _num(cpu_usage) - _num(precpu_usage)
    system_delta = _num(cpu.get("system_cpu_usage")) - _num(precpu.get("system_cpu_usage"))
    online = cpu.get("online_cpus")
    if not online:
        percpu = (cpu.get("cpu_usage") or {}).get("percpu_usage") or []
        online = len(percpu) or 1
    if system_delta > 0 and cpu_delta > 0:
        return round((cpu_delta / system_delta) * float(online) * 100.0, 2)
    return 0.0


def mem_usage_and_limit(stats: dict) -> tuple[float, float]:
    """Return (used_bytes, limit_bytes) from a Docker stats sample.

    Subtracts the page cache (``stats.cache`` / ``inactive_file``) from raw usage
    the way ``docker stats`` does, so the number reflects real working set.
    """
    mem = stats.get("memory_stats") or {}
    usage = _num(mem.get("usage"))
    detail = mem.get("stats") or {}
    cache = detail.get("cache")
    if cache is None:
        cache = detail.get("inactive_file", 0)
    used = max(0.0, usage - _num(cache))
    limit = _num(mem.get("limit"))
    return used, limit


def mem_percent(stats: dict) -> float:
    """Memory usage percent of the container's limit (0.0 when no limit known)."""
    used, limit = mem_usage_and_limit(stats)
    if limit > 0:
        return round(used / limit * 100.0, 2)
    return 0.0


def host_mem_limit_bytes(inspect: dict) -> int:
    """The container's configured memory hard limit in bytes (0 = unlimited)."""
    host_config = inspect.get("HostConfig") or {}
    return int(_num(host_config.get("Memory")))


def host_cpu_limit(inspect: dict) -> dict:
    """The container's configured CPU limits (NanoCpus / quota+period / shares)."""
    host_config = inspect.get("HostConfig") or {}
    return {
        "NanoCpus": int(_num(host_config.get("NanoCpus"))),
        "CpuQuota": int(_num(host_config.get("CpuQuota"))),
        "CpuPeriod": int(_num(host_config.get("CpuPeriod"))),
        "CpuShares": int(_num(host_config.get("CpuShares"))),
    }
