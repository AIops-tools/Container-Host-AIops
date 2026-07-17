"""Podman pod reads over the libpod-native API (read-only, Podman-only).

A **pod** is a Podman-only object: a group of containers that share namespaces
(network, IPC, …), the same shape Kubernetes gives a Pod. Docker has no
equivalent, so this read hits the libpod-native endpoint (``/pods/json`` under
the platform's libpod prefix) rather than the Docker-compat layer, and it
teaching-errors on a Docker or Portainer target. All host text is sanitized at
the boundary.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.config import PODMAN
from container_host_aiops.ops._util import clean_list, short_id

_MAX_ROWS = 500


def _require_podman(conn: Any, tool: str) -> None:
    """Raise a teaching error unless ``conn``'s target is a Podman host."""
    target = getattr(conn, "target", None)
    platform = getattr(target, "platform", None)
    if platform is not None and platform != PODMAN:
        raise ValueError(
            f"'{tool}' requires a podman target, but '{getattr(target, 'name', '?')}' "
            f"is a {platform} target. Pods are a Podman-only feature (libpod) — "
            f"Docker and Portainer have no pod concept."
        )


def _pod_status_rollup(containers: list[dict]) -> dict[str, int]:
    """Count a pod's member containers by (lowercased) status."""
    rollup: dict[str, int] = {}
    for c in containers or []:
        status = str(c.get("Status") or c.get("State") or "unknown").lower()
        rollup[status] = rollup.get(status, 0) + 1
    return rollup


def list_pods(conn: Any) -> dict:
    """[READ] List Podman pods (Podman-only): id, name, status, member containers.

    Groups by pod status and returns compact rows, each with a per-pod rollup of
    its member containers by status. Requires a ``podman`` target — raises a
    teaching error on Docker / Portainer (which have no pod concept).
    """
    _require_podman(conn, "list_pods")
    rows = clean_list(conn.libpod_get("/pods/json"))
    by_status: dict[str, int] = {}
    compact: list[dict] = []
    for p in rows:
        status = str(p.get("Status") or "unknown").lower()
        by_status[status] = by_status.get(status, 0) + 1
        members = p.get("Containers") or []
        compact.append({
            "id": short_id(p.get("Id")),
            "name": p.get("Name"),
            "status": status,
            "created": p.get("Created"),
            "infraId": short_id(p.get("InfraId")),
            "numContainers": len(members),
            "containersByStatus": _pod_status_rollup(members),
        })
    return {
        "total": len(rows),
        "byStatus": dict(sorted(by_status.items(), key=lambda kv: kv[1], reverse=True)),
        "pods": compact[:_MAX_ROWS],
    }
