"""One-shot container-host overview (read-only).

A single call an agent can lead with before drilling into a specific container,
image, or volume: the host's identity + version, its container counts by state,
how many containers have restarts, and a disk-usage headline. Resilient — a
failing sub-call degrades to a partial summary with per-section error fields
rather than a raised traceback (a health probe must survive the thing it probes).
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops import containers as cont
from container_host_aiops.ops import system as sysops


def host_overview(conn: Any) -> dict:
    """[READ] Host summary: platform + version + container state rollup + disk."""
    result: dict[str, Any] = {
        "platform": getattr(getattr(conn, "target", None), "platform", "docker"),
        "target": getattr(getattr(conn, "target", None), "name", ""),
    }
    try:
        info = sysops.system_info(conn)
        result["serverVersion"] = info.get("serverVersion")
        result["operatingSystem"] = info.get("operatingSystem")
        result["containers"] = info.get("containers")
        result["containersRunning"] = info.get("containersRunning")
        result["containersStopped"] = info.get("containersStopped")
        result["images"] = info.get("images")
    except Exception as exc:  # noqa: BLE001 — partial summary, not a crash
        result["infoError"] = str(exc)[:200]
    try:
        summary = cont.restart_summary(conn, all_states=True)
        result["containersWithRestarts"] = summary.get("withRestarts")
    except Exception as exc:  # noqa: BLE001
        result["restartError"] = str(exc)[:200]
    try:
        df = sysops.system_df(conn)
        result["diskImagesHuman"] = (df.get("images") or {}).get("totalHuman")
        result["diskVolumesHuman"] = (df.get("volumes") or {}).get("totalHuman")
    except Exception as exc:  # noqa: BLE001
        result["dfError"] = str(exc)[:200]
    return result
