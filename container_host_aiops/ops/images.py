"""Image-scoped reads over the Docker Engine API (read-only).

These reads answer "what images are on the host, what does one look like inspected
(and its build history/layers), which images are dangling (untagged, safe-ish to
prune), and how much disk are images using". All host text is sanitized.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops._util import _seg, clean, clean_list, human_bytes, short_id

_MAX_ROWS = 500


def _num(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def list_images(conn: Any, all_images: bool = False) -> dict:
    """[READ] List images with tags, size, and dangling status.

    ``all_images`` includes intermediate layers; by default only top-level images.
    """
    rows = clean_list(
        conn.docker_get("/images/json", params={"all": "true" if all_images else "false"})
    )
    compact: list[dict] = []
    total_size = 0
    for r in rows:
        size = _num(r.get("Size"))
        total_size += size
        tags = r.get("RepoTags") or []
        compact.append({
            "id": short_id(str(r.get("Id", "")).removeprefix("sha256:")),
            "repoTags": tags,
            "sizeBytes": size,
            "sizeHuman": human_bytes(size),
            "dangling": _is_dangling(tags),
            "containers": r.get("Containers"),
        })
    compact.sort(key=lambda i: i["sizeBytes"], reverse=True)
    return {
        "total": len(rows),
        "totalSizeBytes": total_size,
        "totalSizeHuman": human_bytes(total_size),
        "images": compact[:_MAX_ROWS],
    }


def inspect_image(conn: Any, image_id: str) -> dict:
    """[READ] Inspect an image plus its build history (layers, sizes, commands)."""
    info = clean(conn.docker_get(f"/images/{_seg(image_id)}/json"))
    try:
        history = clean_list(conn.docker_get(f"/images/{_seg(image_id)}/history"))
    except Exception:  # noqa: BLE001 — history is advisory
        history = []
    layers = [
        {
            "createdBy": h.get("CreatedBy"),
            "sizeBytes": _num(h.get("Size")),
            "sizeHuman": human_bytes(_num(h.get("Size"))),
        }
        for h in history
    ]
    return {
        "id": short_id(str(info.get("Id", "")).removeprefix("sha256:")),
        "repoTags": info.get("RepoTags"),
        "sizeBytes": _num(info.get("Size")),
        "sizeHuman": human_bytes(_num(info.get("Size"))),
        "architecture": info.get("Architecture"),
        "os": info.get("Os"),
        "layerCount": len(layers),
        "history": layers[:_MAX_ROWS],
    }


def dangling_images(conn: Any) -> dict:
    """[READ] Untagged (dangling) images — the low-risk prune candidates."""
    rows = clean_list(
        conn.docker_get(
            "/images/json", params={"filters": '{"dangling":["true"]}'}
        )
    )
    reclaimable = sum(_num(r.get("Size")) for r in rows)
    return {
        "danglingCount": len(rows),
        "reclaimableBytes": reclaimable,
        "reclaimableHuman": human_bytes(reclaimable),
        "images": [
            {
                "id": short_id(str(r.get("Id", "")).removeprefix("sha256:")),
                "sizeBytes": _num(r.get("Size")),
                "sizeHuman": human_bytes(_num(r.get("Size"))),
            }
            for r in rows
        ][:_MAX_ROWS],
    }


def image_disk_usage(conn: Any) -> dict:
    """[READ] Image disk usage from ``/system/df`` (total, active, reclaimable)."""
    df = clean(conn.docker_get("/system/df"))
    images = df.get("Images") or []
    total = sum(_num(i.get("Size")) for i in images)
    shared = sum(_num(i.get("SharedSize")) for i in images)
    active = sum(1 for i in images if _num(i.get("Containers")) > 0)
    return {
        "imageCount": len(images),
        "activeCount": active,
        "totalSizeBytes": total,
        "totalSizeHuman": human_bytes(total),
        "sharedSizeBytes": shared,
        "reclaimableBytes": max(0, total - shared),
        "reclaimableHuman": human_bytes(max(0, total - shared)),
    }


def _is_dangling(tags: Any) -> bool:
    return not tags or tags == ["<none>:<none>"]
